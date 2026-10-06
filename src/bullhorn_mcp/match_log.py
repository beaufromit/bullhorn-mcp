"""Minimal JSONL match log (CR44 D6, D12, P10, P11).

One line per match check and one per outcome, appended to a daily file.
Personal identifiers are SHA-256 hashed; no CV contents, no names in clear,
no breakdown reason text. Logging never raises into a tool.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_logger = logging.getLogger(__name__)

RETENTION_DAYS = 30
_FILE_PREFIX = "match-"
_FILE_SUFFIX = ".jsonl"

_lock = threading.Lock()
_last_pruned: date | None = None


def new_match_check_id() -> str:
    return "mc_" + uuid.uuid4().hex


def log_dir() -> Path:
    env = os.environ.get("BULLHORN_MATCH_LOG_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".local" / "state" / "bullhorn-mcp" / "match-log"


def _reset_for_tests() -> None:
    global _last_pruned
    _last_pruned = None


def _hash(value) -> str | None:
    if value is None or value == "":
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _hash_caller(caller):
    if caller is None:
        return None
    if isinstance(caller, int) and not isinstance(caller, bool):
        return caller
    return _hash(caller)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _prune(directory: Path, today: date) -> None:
    cutoff = today - timedelta(days=RETENTION_DAYS)
    for path in directory.glob(f"{_FILE_PREFIX}*{_FILE_SUFFIX}"):
        stem = path.name[len(_FILE_PREFIX):-len(_FILE_SUFFIX)]
        try:
            file_date = date.fromisoformat(stem)
        except ValueError:
            continue
        if file_date < cutoff:
            try:
                path.unlink()
            except OSError as exc:
                _logger.warning("match log: could not delete %s: %s", path.name, exc)


def _append(record: dict, now: datetime) -> None:
    global _last_pruned
    directory = log_dir()
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    today = now.date()
    with _lock:
        directory.mkdir(parents=True, exist_ok=True)
        if _last_pruned != today:
            _prune(directory, today)
            _last_pruned = today
        path = directory / f"{_FILE_PREFIX}{today.isoformat()}{_FILE_SUFFIX}"
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(line)


def _signals(profile, echo: dict) -> dict:
    work = list(profile.work_history or [])
    education = list(echo.get("education") or [])
    return {
        "emails": [_hash(e) for e in echo.get("emails") or []],
        "phones": [_hash(p) for p in echo.get("phones") or []],
        "linkedin": _hash(echo.get("linkedin")),
        "first_name": _hash(echo.get("first_name")),
        "last_name": _hash(echo.get("last_name")),
        "employers": list(echo.get("employers") or []),
        "schools": [e.get("school") for e in education if e.get("school")],
        "work_years": [[w.start_year, w.end_year] for w in work],
        "education_years": [e.get("year") for e in education],
        "work_count": len(work),
        "education_count": len(education),
    }


def log_check(match_check_id: str, *, caller, config_version: str, profile, result: dict) -> None:
    """Append one check line. Never raises."""
    try:
        now = _now()
        echo = result.get("profile") or profile.to_echo()
        candidates = []
        for m in result.get("matches") or []:
            candidates.append({
                "candidate_id": m.get("candidate_id"),
                "points": m.get("points"),
                "percentage": m.get("percentage"),
                "band": m.get("band"),
                "signals": [
                    {"signal": b.get("signal"), "points": b.get("points")}
                    for b in m.get("breakdown") or []
                ],
                "flags": list(m.get("flags") or []),
            })
        record = {
            "type": "check",
            "match_check_id": match_check_id,
            "ts": now.isoformat(),
            "caller": _hash_caller(caller),
            "config_version": config_version,
            "signals": _signals(profile, echo),
            "candidates": candidates,
            "flags": list(result.get("flags") or []),
            "deleted_candidate_ids": [d.get("candidate_id") for d in result.get("deleted_matches") or []],
        }
        _append(record, now)
    except Exception as exc:  # noqa: BLE001 - logging must never break a tool
        _logger.warning("match log: could not write check line: %s", exc)


def log_outcome(match_check_id: str, outcome: str, candidate_id: int | None = None, caller=None) -> None:
    """Append one outcome line under the check's id. Never raises."""
    try:
        now = _now()
        record = {
            "type": "outcome",
            "match_check_id": match_check_id,
            "ts": now.isoformat(),
            "outcome": outcome,
            "candidate_id": candidate_id,
            "caller": _hash_caller(caller),
        }
        _append(record, now)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("match log: could not write outcome line: %s", exc)
