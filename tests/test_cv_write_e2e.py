"""CR46 T43.12: end-to-end CV write path at the HTTP boundary with the REAL parse fixture.

A real BullhornClient and BullhornMetadata run over respx (harness from
test_server_cr46.py); every assertion is on the raw requests sent, plus the match log
written by the real log module. No mock of our own functions sits between the tool and
the wire (the retrieval stub only answers the duplicate search).
"""

import copy
import json
from pathlib import Path

import pytest

from bullhorn_mcp import server
from tests.test_server_cr46 import (  # noqa: F401
    CID,
    _assert_original_cv_put,
    _attach,
    _Bullhorn,
    _fresh_check,
    _no_points,
    _outcomes,
    _upload_with_parse,
    clean_upload_store,
    match_stub,
    real_log,
    reset_client,
    stack,
)

FIXTURE = Path(__file__).parent / "fixtures" / "cv_parse_sample.json"


class _E2EBullhorn(_Bullhorn):
    """The base harness, which also answers the child read-back GET."""


@pytest.fixture
def real_parse():
    return json.loads(FIXTURE.read_text())


def _corrected_history(parse):
    """Claude's correction: employer split out of the merged title, current employer filled."""
    old, current = copy.deepcopy(parse["candidateWorkHistory"])
    assert old["startDate"] < current["startDate"] or current["startDate"] < old["startDate"]
    entries = copy.deepcopy(parse["candidateWorkHistory"])
    latest = max(entries, key=lambda e: e["startDate"])
    for e in entries:
        if e is latest:
            e["companyName"] = "Example Widgets Ltd"
        else:
            e["companyName"] = "Sample Gadgets Ireland"
            e["title"] = "Financial Accountant"
    return entries, latest


def _fields_of(request):
    return request.url.params.get("fields")


class TestCvWriteE2E:
    def test_e2e_create_from_cv_real_parse(self, stack, match_stub, real_log, real_parse, clean_upload_store):
        _fresh_check(match_stub, check_id="mc_fresh")
        history, latest = _corrected_history(real_parse)
        bh = _E2EBullhorn()
        upload_id = _upload_with_parse(real_parse)
        data = stack(bh, server.create_candidate_from_cv, upload_id=upload_id,
                     work_history=history, match_check_id="mc_passed")

        # Candidate PUT body
        body = bh.body("PUT", "/entity/Candidate")
        for banned in ("editHistoryValue", "onboardingReceivedSent", "dateAdded"):
            assert banned not in body
        assert body["name"] == "Testcase Cr-Fortyone"  # MCP-computed from first/last, not the parse key
        assert body["address"] == real_parse["candidate"]["address"]
        assert body["companyName"] == "Example Widgets Ltd"
        assert body["firstName"] == "Testcase" and body["lastName"] == "Cr-Fortyone"
        assert body["occupation"] == "Senior Financial Accountant"
        assert isinstance(body["skillSet"], str)
        assert [n.strip() for n in body["skillSet"].split(",")] == real_parse["skillList"]

        # Child creates and their read-backs carry explicit fields
        wh_puts = bh.find("PUT", "/entity/CandidateWorkHistory")
        assert len(wh_puts) == 2
        wh_bodies = [json.loads(r.content) for r in wh_puts]
        assert {b["companyName"] for b in wh_bodies} == {"Example Widgets Ltd", "Sample Gadgets Ireland"}
        assert all(b["candidate"] == {"id": CID} for b in wh_bodies)
        edu_bodies = [json.loads(r.content) for r in bh.find("PUT", "/entity/CandidateEducation")]
        assert len(edu_bodies) == len(real_parse["candidateEducation"]) == 2
        assert all(b["candidate"] == {"id": CID} for b in edu_bodies)
        assert {b.get("school") for b in edu_bodies} == {"Example University", None}
        readbacks = [(m, p, r) for m, p, r in bh.requests
                     if m == "GET" and p.startswith(("/entity/CandidateWorkHistory/", "/entity/CandidateEducation/",
                                                      f"/entity/Candidate/{CID}"))]
        assert len(readbacks) >= 5
        for _, p, r in readbacks:
            f = _fields_of(r)
            assert f and f != "*" and "*" not in f.split(","), p
            if p == f"/entity/Candidate/{CID}":
                assert "editHistoryValue" not in f

        # File
        _assert_original_cv_put(bh)

        # written matches what was sent
        written = data["written"]
        assert written["file"] == {"file_id": 77, "name": "Jane_Doe_CV.pdf"}
        assert [w["companyName"] for w in written["work_history"]] == [b["companyName"] for b in wh_bodies]
        assert len(written["education"]) == 2
        assert set(written["fields"]) == set(body) - {"description"}
        assert written["description_length"] == len(body["description"])
        assert written["skill_set"] == real_parse["skillList"]
        assert written["primary_skills"] == [1000334, 1000125, 1000562]
        assert any(m == "PUT" and p.startswith(f"/entity/Candidate/{CID}/primarySkills/") for m, p, _ in bh.requests)

        # match log: under both the fresh and the passed id
        ids = {cid for cid, outcome, cand in _outcomes(real_log) if cand == CID}
        assert ids == {"mc_fresh", "mc_passed"}
        _no_points(data)

    def test_e2e_attach_cv_real_parse_additions_then_overwrite_choice(self, stack, real_parse, clean_upload_store):
        history, _ = _corrected_history(real_parse)
        existing = {"firstName": "Testcase", "lastName": "Cr-Fortyone", "email": "testcase.cr41@example.com",
                    "occupation": "Accounts Assistant", "companyName": "Old Employer Plc",
                    "skillSet": ["Excel", "IFRS"]}
        upload_id = _upload_with_parse(real_parse)

        bh = _E2EBullhorn(existing=existing)
        first, _ = _attach(stack, bh, upload_id=upload_id, work_history=history)

        # The Candidate GET never asks for the parser-only key
        get = bh.find("GET", f"/entity/Candidate/{CID}")[0]
        assert "editHistoryValue" not in _fields_of(get)
        assert "*" not in _fields_of(get).split(",")

        posts = [json.loads(r.content) for r in bh.find("POST", f"/entity/Candidate/{CID}")]
        for post in posts:
            assert "occupation" not in post and "companyName" not in post
            assert "editHistoryValue" not in post and "onboardingReceivedSent" not in post
        sk = [p["skillSet"] for p in posts if "skillSet" in p]
        assert len(sk) == 1
        names = [n.strip() for n in sk[0].split(",")]
        assert names[:2] == ["Excel", "IFRS"]
        assert len({n.lower() for n in names}) == len(names)
        assert {n.lower() for n in names} == {n.lower() for n in ["Excel", "IFRS", *real_parse["skillList"]]}
        pending = {p["field"]: p for p in first["pending_overwrites"]}
        assert set(pending) >= {"occupation", "companyName"}
        assert pending["occupation"]["current"] == "Accounts Assistant"
        assert pending["occupation"]["proposed"] == "Senior Financial Accountant"
        assert pending["companyName"]["current"] == "Old Employer Plc"
        assert pending["companyName"]["proposed"] == "Example Widgets Ltd"
        _assert_original_cv_put(bh)
        _no_points(first)

        # Second call, same arguments plus overwrite=["occupation"]: only that one
        bh2 = _E2EBullhorn(existing=existing)
        second, _ = _attach(stack, bh2, upload_id=upload_id, work_history=history, overwrite=["occupation"])
        posts2 = [json.loads(r.content) for r in bh2.find("POST", f"/entity/Candidate/{CID}")]
        merged = {k: v for p in posts2 for k, v in p.items()}
        assert merged["occupation"] == "Senior Financial Accountant"
        assert "companyName" not in merged
        assert all("companyName" not in p for p in posts2)
        assert second["overwritten"] == ["occupation"]
        kept = {k["field"]: k for k in second["kept"]}
        assert kept["companyName"]["current"] == "Old Employer Plc"
        assert "pending_overwrites" not in second
        # the file was attached once, in the first call, and is not repeated
        assert bh2.find("PUT", f"/file/Candidate/{CID}/raw") == []
        _no_points(second)

    def test_e2e_attach_cv_file_only_path(self, stack, real_parse, clean_upload_store):
        upload_id = _upload_with_parse(real_parse)
        server.upload_store.mark_created(upload_id, CID)
        bh = _E2EBullhorn()
        data = stack(bh, server.attach_cv, candidate_id=CID, upload_id=upload_id)

        _assert_original_cv_put(bh)
        assert data["written"]["file"] == {"file_id": 77, "name": "Jane_Doe_CV.pdf"}
        writes = [(m, p) for m, p, _ in bh.requests if m in ("POST", "PUT", "DELETE")]
        assert writes == [("PUT", f"/file/Candidate/{CID}/raw")]
        assert server.upload_store.get(upload_id, "user-a")["status"] == "attached"
