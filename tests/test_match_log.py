"""Tests for the JSONL match log (CR44 T42B.5). Invented people only."""

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bullhorn_mcp import match_log
from bullhorn_mcp.duplicates import CandidateProfile, EducationEntry, WorkEntry


@pytest.fixture(autouse=True)
def log_env(tmp_path, monkeypatch):
    monkeypatch.setenv("BULLHORN_MATCH_LOG_DIR", str(tmp_path))
    match_log._reset_for_tests()
    yield tmp_path
    match_log._reset_for_tests()


def _profile():
    return CandidateProfile(
        first_name="Zelda",
        last_name="Quimby",
        emails=["Zelda.Quimby@example.invalid"],
        phones=["+353 87 555 0142"],
        linkedin_url="https://www.linkedin.com/in/zelda-quimby-test",
        work_history=[WorkEntry(company="Fictional Widgets Ltd", title="Controller", start_year=2015, end_year=2020)],
        education=[EducationEntry(school="Imaginary University", degree="BComm", year=2012)],
    )


def _result(profile):
    return {
        "config_version": "v1",
        "profile": profile.to_echo(),
        "matches": [{
            "candidate_id": 501,
            "name": "Zelda Quimby",
            "points": 12.5,
            "percentage": 91.0,
            "band": "high",
            "breakdown": [{"signal": "email", "points": 9.0, "reason": "Zelda Quimby shares an email at Fictional Widgets Ltd"}],
            "flags": ["shared_thing"],
        }],
        "flags": ["f1"],
        "deleted_matches": [{"candidate_id": 777, "name": "Deleted Dora"}],
    }


def _write_check(caller=42):
    p = _profile()
    cid = match_log.new_match_check_id()
    match_log.log_check(cid, caller=caller, config_version="v1", profile=p, result=_result(p))
    return cid


def _files(d):
    return sorted(Path(d).glob("match-*.jsonl"))


def _text(d):
    return "".join(f.read_text() for f in _files(d))


def _lines(d):
    return [json.loads(x) for x in _text(d).splitlines()]


def test_check_line_has_no_cv_contents(log_env):
    cid = _write_check()
    (line,) = _lines(log_env)
    assert line["type"] == "check"
    assert line["match_check_id"] == cid
    assert line["config_version"] == "v1"
    assert line["caller"] == 42
    assert set(line) == {"type", "match_check_id", "ts", "caller", "config_version",
                         "signals", "candidates", "flags", "deleted_candidate_ids"}
    assert line["candidates"] == [{
        "candidate_id": 501, "points": 12.5, "percentage": 91.0, "band": "high",
        "signals": [{"signal": "email", "points": 9.0}], "flags": ["shared_thing"],
    }]
    assert line["deleted_candidate_ids"] == [777]
    s = line["signals"]
    assert s["work_count"] == 1 and s["education_count"] == 1
    assert s["work_years"] == [[2015, 2020]]
    assert s["education_years"] == [2012]
    assert "Controller" not in _text(log_env)
    assert "BComm" not in _text(log_env)
    datetime.fromisoformat(line["ts"])


def test_identifiers_hashed(log_env):
    _write_check()
    text = _text(log_env).lower()
    for clear in ("zelda", "quimby", "example.invalid", "555 0142", "5550142", "353875550142",
                  "zelda-quimby-test"):
        assert clear not in text
    s = _lines(log_env)[0]["signals"]
    assert s["emails"] == [hashlib.sha256(b"zelda.quimby@example.invalid").hexdigest()]
    assert s["first_name"] == hashlib.sha256(b"zelda").hexdigest()
    assert len(s["phones"]) == 1 and len(s["phones"][0]) == 64
    assert len(s["linkedin"]) == 64


def test_no_reasons_or_names_in_log(log_env):
    _write_check()
    text = _text(log_env)
    assert "reason" not in text
    assert "shares an email" not in text
    assert "Zelda Quimby" not in text
    assert "Deleted Dora" not in text
    assert "Dora" not in text
    assert '"name"' not in text


def test_outcome_appended_under_same_id(log_env):
    cid = _write_check()
    match_log.log_outcome(cid, "attached_to", 501, caller=42)
    check, outcome = _lines(log_env)
    assert outcome["type"] == "outcome"
    assert outcome["match_check_id"] == check["match_check_id"] == cid
    assert outcome["outcome"] == "attached_to"
    assert outcome["candidate_id"] == 501
    assert outcome["caller"] == 42
    match_log.log_outcome(cid, "created_new")
    assert _lines(log_env)[2]["candidate_id"] is None
    assert _lines(log_env)[2]["caller"] is None


def test_daily_file_name(log_env):
    _write_check()
    today = datetime.now(timezone.utc).date().isoformat()
    assert [f.name for f in _files(log_env)] == [f"match-{today}.jsonl"]
    if os.name == "posix":
        assert (_files(log_env)[0].stat().st_mode & 0o777) == 0o600


def test_files_older_than_30_days_deleted(log_env):
    today = datetime.now(timezone.utc).date()
    old = log_env / f"match-{(today - timedelta(days=31)).isoformat()}.jsonl"
    edge = log_env / f"match-{(today - timedelta(days=30)).isoformat()}.jsonl"
    recent = log_env / f"match-{(today - timedelta(days=5)).isoformat()}.jsonl"
    other = log_env / "notes.txt"
    odd = log_env / "match-notadate.jsonl"
    for f in (old, edge, recent, other, odd):
        f.write_text("x\n")
    _write_check()
    assert not old.exists()
    assert edge.exists() and recent.exists() and other.exists() and odd.exists()


def test_prune_runs_once_per_day(log_env):
    _write_check()
    today = datetime.now(timezone.utc).date()
    old = log_env / f"match-{(today - timedelta(days=60)).isoformat()}.jsonl"
    old.write_text("x\n")
    _write_check()
    assert old.exists()


def test_log_failure_does_not_raise(tmp_path, monkeypatch, caplog):
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    monkeypatch.setenv("BULLHORN_MATCH_LOG_DIR", str(blocker / "sub"))
    with caplog.at_level(logging.WARNING, logger="bullhorn_mcp.match_log"):
        _write_check()
        match_log.log_outcome("mc_x", "created_new")
        match_log.log_check("mc_y", caller=None, config_version="v1", profile=None, result={})
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 3


def test_dir_from_env(tmp_path, monkeypatch):
    target = tmp_path / "custom" / "deeper"
    monkeypatch.setenv("BULLHORN_MATCH_LOG_DIR", str(target))
    assert match_log.log_dir() == target
    _write_check()
    assert len(_files(target)) == 1


def test_default_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("BULLHORN_MATCH_LOG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert match_log.log_dir() == tmp_path / ".local" / "state" / "bullhorn-mcp" / "match-log"


def test_caller_sub_hashed(log_env):
    cid = _write_check(caller="entra-sub-abc123")
    match_log.log_outcome(cid, "created_with_force", caller="entra-sub-abc123")
    assert "entra-sub-abc123" not in _text(log_env)
    expected = hashlib.sha256(b"entra-sub-abc123").hexdigest()
    assert [x["caller"] for x in _lines(log_env)] == [expected, expected]


def test_caller_none_allowed(log_env):
    _write_check(caller=None)
    assert _lines(log_env)[0]["caller"] is None


def test_new_match_check_id_unique():
    ids = {match_log.new_match_check_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(i.startswith("mc_") and len(i) == 35 for i in ids)
