"""CR46 Sprint 43 server tests: writable-field filter, CV file attach, list skillSet, current company.

Every write is asserted on the RAW request (body or query string) that a real
BullhornClient and a real BullhornMetadata send over respx, never on a mock of our
own functions. /meta mocks use the raw Bullhorn shape so the test goes through
BullhornMetadata.get_fields.
"""

import copy
import json
from unittest.mock import Mock, PropertyMock, patch

import httpx
import pytest
import respx

from bullhorn_mcp import server
from bullhorn_mcp.auth import BullhornAuth
from bullhorn_mcp.client import BullhornClient
from bullhorn_mcp.metadata import BullhornMetadata
# Autouse / shared fixtures and helpers live in test_server.py.
from tests.test_server import (  # noqa: F401
    _CV_BYTES,
    _http_as,
    _seed_upload,
    clean_upload_store,
    match_stub,
    mock_client,
    reset_client,
)

CID = 900

META_FIELDS = [
    {"name": "firstName", "label": "First Name", "type": "SCALAR"},
    {"name": "lastName", "label": "Last Name", "type": "SCALAR"},
    {"name": "email", "label": "Email", "type": "SCALAR"},
    {"name": "mobile", "label": "Mobile", "type": "SCALAR"},
    {"name": "occupation", "label": "Job Title", "type": "SCALAR", "maxLength": 100},
    {"name": "companyName", "label": "Company", "type": "SCALAR"},
    {"name": "description", "label": "Description", "type": "SCALAR"},
    {"name": "address", "label": "Address", "type": "COMPOSITE", "dataSpecialization": "COMPOSITE"},
    {"name": "owner", "label": "Owner", "type": "TO_ONE"},
    {"name": "source", "label": "Source", "type": "SCALAR"},
    # readOnly but not SYSTEM: written in practice, must be kept
    {"name": "skillSet", "label": "Skills", "type": "SCALAR", "readOnly": True, "dataSpecialization": ""},
    {"name": "middleName", "label": "Middle Name", "type": "SCALAR", "readOnly": True},
    # readOnly SYSTEM: not Claude's to set
    {"name": "name", "label": "Name", "type": "SCALAR", "readOnly": True, "dataSpecialization": "SYSTEM"},
    {"name": "onboardingReceivedSent", "label": "Onboarding", "type": "COMPOSITE", "readOnly": True,
     "dataSpecialization": "SYSTEM"},
    {"name": "dateAdded", "label": "Date Added", "type": "SCALAR", "readOnly": True, "dataSpecialization": "SYSTEM"},
    # editHistoryValue is deliberately absent, as on the live tenant
]

PARSE = {
    "confidenceScore": 0.9,
    "candidate": {
        "name": "Jane Doe",
        "firstName": "Jane",
        "lastName": "Doe",
        "email": "jane@example.com",
        "mobile": "0851234567",
        "occupation": "Finance Manager",
        "address": {"city": "Dublin"},
        "description": "<p>CV</p>",
        "onboardingReceivedSent": {"x": 1},
        "editHistoryValue": {"y": 2},
    },
    "candidateWorkHistory": [],
    "candidateEducation": [],
    "skillList": [],
    "primarySkills": [],
}


class _Bullhorn:
    """A respx dispatcher that records every request and answers like Bullhorn."""

    def __init__(self, meta_fields=None, existing=None, existing_wh=None):
        self.meta_fields = META_FIELDS if meta_fields is None else meta_fields
        self.existing = existing or {}
        self.existing_wh = existing_wh or []
        self.requests: list[tuple[str, str, httpx.Request]] = []
        self.ids = iter(range(5000, 6000))

    def __call__(self, request):
        path = request.url.path.split("/rest-services/abc123", 1)[1]
        method = request.method
        self.requests.append((method, path, request))
        if path == "/meta/Candidate":
            if self.meta_fields is None:
                return httpx.Response(500, json={"errorMessage": "boom"})
            return httpx.Response(200, json={"entity": "Candidate", "fields": self.meta_fields})
        if path.startswith("/meta/"):
            return httpx.Response(200, json={"entity": path[6:], "fields": []})
        if method == "PUT" and path == "/entity/Candidate":
            return httpx.Response(200, json={"changedEntityId": CID, "changeType": "INSERT"})
        if method == "GET" and path == f"/entity/Candidate/{CID}":
            return httpx.Response(200, json={"data": {"id": CID, **self.existing}})
        if method == "POST" and path == f"/entity/Candidate/{CID}":
            return httpx.Response(200, json={"changedEntityId": CID, "changeType": "UPDATE"})
        if method == "PUT" and path.startswith("/entity/Candidate"):
            if path.endswith("/primarySkills/" + path.rsplit("/", 1)[-1]) and "/primarySkills/" in path:
                return httpx.Response(200, json={"changedEntityId": CID, "changeType": "ASSOCIATE"})
        if method == "PUT" and path in ("/entity/CandidateWorkHistory", "/entity/CandidateEducation"):
            return httpx.Response(200, json={"changedEntityId": next(self.ids), "changeType": "INSERT"})
        if method == "GET" and path == "/query/CandidateWorkHistory":
            return httpx.Response(200, json={"data": self.existing_wh, "total": len(self.existing_wh)})
        if method == "GET" and path == "/query/CandidateEducation":
            return httpx.Response(200, json={"data": [], "total": 0})
        if method == "GET" and path.endswith("/primarySkills"):
            return httpx.Response(200, json={"data": []})
        if method == "PUT" and path == f"/file/Candidate/{CID}/raw":
            return httpx.Response(200, json={"fileId": 77})
        return httpx.Response(404, json={"errorMessage": f"unmocked {method} {path}"})

    def find(self, method, path):
        return [r for m, p, r in self.requests if m == method and p == path]

    def body(self, method, path):
        reqs = self.find(method, path)
        assert len(reqs) == 1, f"expected one {method} {path}, got {len(reqs)}"
        return json.loads(reqs[0].content)


@pytest.fixture
def stack(mock_session):
    """Real client + real metadata over respx; yields (bullhorn, run) where run executes a callable."""
    auth = Mock(spec=BullhornAuth)
    type(auth).session = PropertyMock(return_value=mock_session)
    client = BullhornClient(auth)
    metadata = BullhornMetadata(client)

    def run(bullhorn, fn, **kwargs):
        with respx.mock(assert_all_called=False) as router:
            router.route(host="rest99.bullhornstaffing.com").mock(side_effect=bullhorn)
            with _http_as(), \
                 patch.object(server, "get_client", return_value=client), \
                 patch.object(server, "get_metadata", return_value=metadata), \
                 patch.object(server, "resolve_caller", return_value={"id": 1}), \
                 patch.object(server, "get_candidate_required", return_value=[]), \
                 patch.object(server, "get_candidate_defaults", return_value={}), \
                 patch.object(server, "get_mcp_source", return_value="Claude"):
                return json.loads(fn(**kwargs))

    return run


def _upload_with_parse(parse, candidate_id=None):
    upload_id = _seed_upload(candidate_id=candidate_id)
    server.upload_store.set_parsed(upload_id, "user-a", copy.deepcopy(parse))
    return upload_id


def _create(stack, bh, parse=PARSE, **kwargs):
    return stack(bh, server.create_candidate_from_cv, upload_id=_upload_with_parse(parse), **kwargs)


def _attach(stack, bh, parse=PARSE, upload_id=None, **kwargs):
    upload_id = upload_id or _upload_with_parse(parse)
    kwargs.setdefault("candidate_id", CID)
    return stack(bh, server.attach_cv, upload_id=upload_id, **kwargs), upload_id


# --- T43.4: the CV file attaches like a consultant upload ---------------------------

def _assert_original_cv_put(bh):
    reqs = bh.find("PUT", f"/file/Candidate/{CID}/raw")
    assert len(reqs) == 1
    params = dict(reqs[0].url.params)
    assert params == {"externalID": "Portfolio", "type": "Original CV"}
    assert "fileType" not in reqs[0].url.query.decode()


class TestCvFileAttach:
    def test_create_from_cv_attaches_original_cv(self, stack, clean_upload_store):
        bh = _Bullhorn()
        upload_id = _upload_with_parse(PARSE)
        data = stack(bh, server.create_candidate_from_cv, upload_id=upload_id)
        _assert_original_cv_put(bh)
        assert data["written"]["file"] == {"file_id": 77, "name": "Jane_Doe_CV.pdf"}
        assert server.upload_store.get(upload_id, "user-a")["status"] == "attached"

    def test_attach_cv_attaches_original_cv(self, stack, clean_upload_store):
        bh = _Bullhorn(existing={"firstName": "Jane", "lastName": "Doe"})
        data, upload_id = _attach(stack, bh)
        _assert_original_cv_put(bh)
        assert data["written"]["file"] == {"file_id": 77, "name": "Jane_Doe_CV.pdf"}
        assert server.upload_store.get(upload_id, "user-a")["status"] == "attached"

    def test_attach_created_cv_file_attaches_original_cv(self, stack, clean_upload_store):
        bh = _Bullhorn()
        upload_id = _upload_with_parse(PARSE)
        server.upload_store.mark_created(upload_id, CID)
        data = stack(bh, server.attach_cv, candidate_id=CID, upload_id=upload_id)
        _assert_original_cv_put(bh)
        assert data["written"]["file"] == {"file_id": 77, "name": "Jane_Doe_CV.pdf"}
        assert server.upload_store.get(upload_id, "user-a")["status"] == "attached"


# --- T43.3: writable-field filter ---------------------------------------------------

def _real_metadata(meta_fields):
    client = Mock(spec=BullhornClient)
    client.get_meta.return_value = {"entity": "Candidate", "fields": meta_fields}
    return BullhornMetadata(client)


class TestWritableFields:
    def test_writable_fields_drops_unknown_and_system_readonly(self):
        kept, dropped = server._writable_candidate_fields(
            _real_metadata(META_FIELDS),
            {"firstName": "Jane", "editHistoryValue": {}, "onboardingReceivedSent": {}, "dateAdded": 1, "address": {"city": "X"}},
        )
        assert kept == {"firstName": "Jane", "address": {"city": "X"}}
        assert dropped == ["editHistoryValue", "onboardingReceivedSent", "dateAdded"]

    def test_writable_fields_keeps_non_system_readonly(self):
        kept, dropped = server._writable_candidate_fields(
            _real_metadata(META_FIELDS), {"skillSet": "Excel", "middleName": "Q"},
        )
        assert kept == {"skillSet": "Excel", "middleName": "Q"}
        assert dropped == []

    def test_writable_fields_meta_unavailable_drops_known_parser_keys(self):
        client = Mock(spec=BullhornClient)
        client.get_meta.side_effect = RuntimeError("meta down")
        kept, dropped = server._writable_candidate_fields(
            BullhornMetadata(client),
            {"firstName": "Jane", "editHistoryValue": {}, "onboardingReceivedSent": {}, "anything": 1},
        )
        assert kept == {"firstName": "Jane", "anything": 1}
        assert dropped == ["editHistoryValue", "onboardingReceivedSent"]

    def test_attach_cv_fetch_excludes_non_meta_parse_keys(self, stack, clean_upload_store):
        bh = _Bullhorn(existing={"firstName": "Jane", "lastName": "Doe"})
        _attach(stack, bh)
        fetch = bh.find("GET", f"/entity/Candidate/{CID}")
        # The first GET is the comparison fetch; the second is the post-write GET.
        assert len(fetch) == 2
        for req in fetch:
            asked = req.url.params["fields"].split(",")
            assert "editHistoryValue" not in asked
            assert "onboardingReceivedSent" not in asked
        assert "occupation" in fetch[0].url.params["fields"].split(",")

    def test_create_from_cv_payload_excludes_readonly_and_unknown(self, stack, clean_upload_store):
        bh = _Bullhorn()
        data = _create(stack, bh)
        body = bh.body("PUT", "/entity/Candidate")
        assert "editHistoryValue" not in body
        assert "onboardingReceivedSent" not in body
        assert body["address"] == {"city": "Dublin"}
        # The MCP computes the name itself; the parse's name is never a warning.
        assert body["name"] == "Jane Doe"
        assert not any("name" in w for w in data.get("warnings", []))

    def test_written_fields_match_sent_payload(self, stack, clean_upload_store):
        bh = _Bullhorn()
        data = _create(stack, bh)
        body = bh.body("PUT", "/entity/Candidate")
        assert set(data["written"]["fields"]) == set(body) - {"description"}
        attach_bh = _Bullhorn(existing={})
        attach, _ = _attach(stack, attach_bh)
        sent = attach_bh.body("POST", f"/entity/Candidate/{CID}")
        assert attach["written"]["fields"] == list(sent)
        assert "editHistoryValue" not in sent and "onboardingReceivedSent" not in sent

    def test_override_unknown_field_is_warned(self, stack, clean_upload_store):
        bh = _Bullhorn()
        data = _create(stack, bh, fields_override={"bogusField": "x", "onboardingReceivedSent": {}, "occupation": "CFO"})
        body = bh.body("PUT", "/entity/Candidate")
        assert "bogusField" not in body and "onboardingReceivedSent" not in body
        assert body["occupation"] == "CFO"
        assert any("bogusField" in w and "onboardingReceivedSent" in w for w in data["warnings"])

    def test_cv_path_parse_name_not_warned(self, stack, clean_upload_store):
        bh = _Bullhorn(existing={})
        create = _create(stack, bh)
        attach, _ = _attach(stack, _Bullhorn(existing={}))
        for data in (create, attach):
            assert not any("name" in w.lower() for w in data.get("warnings", []))

    def test_claude_name_warning_reworded(self, stack, clean_upload_store):
        bh = _Bullhorn()
        data = _create(stack, bh, fields_override={"name": "Someone Else"})
        body = bh.body("PUT", "/entity/Candidate")
        assert body["name"] == "Jane Doe"
        name_warnings = [w for w in data["warnings"] if "name" in w.lower()]
        assert len(name_warnings) == 1
        assert "replaced with the name computed from firstName and lastName" in name_warnings[0]
        assert "not writable" not in name_warnings[0]
        attach, _ = _attach(stack, _Bullhorn(existing={}), fields_override={"name": "Someone Else"})
        assert sum("replaced with the name computed" in w for w in attach["warnings"]) == 1
        assert not any("not writable" in w for w in attach["warnings"])

    def test_get_entity_fields_output_has_no_new_meta_keys(self, stack):
        bh = _Bullhorn()
        out = stack(bh, server.get_entity_fields, entity="Candidate")
        assert out
        for field in out:
            assert set(field) <= {"name", "label", "type", "required", "options"}


# --- T43.6: skillSet returned as a list ---------------------------------------------

class TestListSkillSet:
    def test_skill_set_names_accepts_list(self):
        assert server._skill_set_names(["Excel", " IFRS ", "", 3]) == {"excel", "ifrs"}
        assert server._skill_set_names("Excel, IFRS") == {"excel", "ifrs"}
        assert server._skill_set_names(None) == set()

    def test_merge_skill_set_list_existing_keeps_names(self):
        combined, added = server._merge_skill_set(["Excel", "IFRS"], ["ifrs", "Budgeting"])
        assert combined == "Excel, IFRS, Budgeting"
        assert added == ["Budgeting"]

    def test_attach_cv_keeps_existing_list_skillset(self, stack, clean_upload_store):
        bh = _Bullhorn(existing={"firstName": "Jane", "lastName": "Doe", "skillSet": ["Excel", "IFRS"]})
        parse = {**PARSE, "skillList": ["IFRS", "Budgeting"]}
        data, _ = _attach(stack, bh, parse=parse)
        skill_posts = [json.loads(r.content) for r in bh.find("POST", f"/entity/Candidate/{CID}")
                       if "skillSet" in json.loads(r.content)]
        assert len(skill_posts) == 1
        names = [n.strip() for n in skill_posts[0]["skillSet"].split(",")]
        assert sorted(names) == ["Budgeting", "Excel", "IFRS"]
        assert data["written"]["skill_set"] == ["Budgeting"]

    @pytest.mark.parametrize("skills", [None, ["Budgeting"]])
    def test_create_candidate_list_skillset_joined(self, stack, clean_upload_store, skills):
        bh = _Bullhorn()
        kwargs = {"fields": {"firstName": "Jane", "lastName": "Doe", "skillSet": ["Excel", "IFRS"]}, "force": True}
        if skills:
            kwargs["skills"] = skills
        stack(bh, server.create_candidate, **kwargs)
        body = bh.body("PUT", "/entity/Candidate")
        assert body["skillSet"] == ("Excel, IFRS, Budgeting" if skills else "Excel, IFRS")


# --- T43.7: current company from the CV ---------------------------------------------

WH_CURRENT = {"companyName": "Acme Ltd", "title": "FC", "startDate": 1700000000000, "endDate": 1790000000000}
WH_OLD = {"companyName": "Old Co", "title": "Acct", "startDate": 1500000000000, "endDate": 1690000000000}


class TestCurrentCompany:
    def test_current_entry_is_latest_start_date_ignoring_end_date(self):
        # The OLD entry carries the later endDate; the latest startDate still wins.
        old_with_late_end = {**WH_OLD, "endDate": 1999999999999}
        assert server._current_company_name([old_with_late_end, WH_CURRENT]) == "Acme Ltd"
        assert server._current_company_name([WH_CURRENT, old_with_late_end]) == "Acme Ltd"

    def test_no_company_proposed_when_current_entry_has_none(self):
        no_company = {"title": "FC", "startDate": 1800000000000}
        assert server._current_company_name([WH_OLD, no_company]) is None
        assert server._current_company_name([]) is None
        assert server._current_company_name([{"companyName": "X"}]) is None

    def test_attach_cv_company_from_current_work_history(self, stack, clean_upload_store):
        bh = _Bullhorn(existing={"firstName": "Jane", "lastName": "Doe", "companyName": ""})
        parse = {**PARSE, "candidateWorkHistory": [WH_OLD, WH_CURRENT]}
        data, _ = _attach(stack, bh, parse=parse)
        assert bh.body("POST", f"/entity/Candidate/{CID}")["companyName"] == "Acme Ltd"
        assert "pending_overwrites" not in data

    def test_attach_cv_company_change_is_pending_overwrite(self, stack, clean_upload_store):
        bh = _Bullhorn(existing={"firstName": "Jane", "lastName": "Doe", "companyName": "Previous Plc"})
        parse = {**PARSE, "candidateWorkHistory": [WH_OLD, WH_CURRENT]}
        upload_id = _upload_with_parse(parse)
        first, _ = _attach(stack, bh, upload_id=upload_id)
        assert {"field": "companyName", "current": "Previous Plc", "proposed": "Acme Ltd"} in first["pending_overwrites"]
        assert all("companyName" not in json.loads(r.content) for r in bh.find("POST", f"/entity/Candidate/{CID}"))

        bh2 = _Bullhorn(existing={"firstName": "Jane", "lastName": "Doe", "companyName": "Previous Plc"})
        second, _ = _attach(stack, bh2, upload_id=upload_id, overwrite=["companyName"])
        assert bh2.body("POST", f"/entity/Candidate/{CID}")["companyName"] == "Acme Ltd"
        assert "companyName" in second["overwritten"]

    def test_create_from_cv_company_from_corrected_work_history(self, stack, clean_upload_store):
        bh = _Bullhorn()
        parse = {**PARSE, "candidateWorkHistory": [WH_OLD]}
        corrected = [{"companyName": "Corrected Co", "title": "CFO", "startDate": 1750000000000}, WH_OLD]
        _create(stack, bh, parse=parse, work_history=corrected)
        assert bh.body("PUT", "/entity/Candidate")["companyName"] == "Corrected Co"

    def test_create_from_cv_company_from_parse_when_not_corrected(self, stack, clean_upload_store):
        bh = _Bullhorn()
        parse = {**PARSE, "candidateWorkHistory": [WH_OLD, WH_CURRENT]}
        _create(stack, bh, parse=parse)
        assert bh.body("PUT", "/entity/Candidate")["companyName"] == "Acme Ltd"


# --- T43.8 / T43.9: outcome under the passed id, no points in responses ------------------

from bullhorn_mcp import match_log  # noqa: E402
from tests.test_server import _match, _match_result  # noqa: E402

# Captured at import, before the autouse match_stub replaces log_outcome with a mock.
_REAL_LOG_OUTCOME = match_log.log_outcome

CREATE_FIELDS = {"firstName": "Jane", "lastName": "Doe", "email": "jane@example.com"}


@pytest.fixture
def real_log(tmp_path, monkeypatch):
    """The real match log writing to tmp_path; yields a reader of every JSONL line written."""
    monkeypatch.setenv("BULLHORN_MATCH_LOG_DIR", str(tmp_path))
    match_log._reset_for_tests()

    def lines():
        out = []
        for f in sorted(tmp_path.glob("match-*.jsonl")):
            out += [json.loads(x) for x in f.read_text().splitlines()]
        return out

    with patch.object(server.match_log, "log_outcome", _REAL_LOG_OUTCOME):
        yield lines


def _outcomes(lines):
    return [(x["match_check_id"], x["outcome"], x["candidate_id"]) for x in lines() if x["type"] == "outcome"]


def _no_points(node, path="$"):
    """Recursively assert no key named ``points`` appears anywhere in a parsed JSON response."""
    if isinstance(node, dict):
        assert "points" not in node, f"points at {path}"
        for k, v in node.items():
            _no_points(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _no_points(v, f"{path}[{i}]")


def _fresh_check(match_stub, check_id="mc_fresh", matches=None):
    match_stub.match.return_value = _match_result(matches or [], check_id=check_id)


def _create_candidate(stack, bh, **kwargs):
    return stack(bh, server.create_candidate, fields=dict(CREATE_FIELDS), **kwargs)


class TestOutcomeUnderPassedId:
    def test_create_from_cv_logs_outcome_under_passed_id(self, stack, match_stub, real_log):
        """The fresh check still runs; the outcome is logged under its id and the passed id."""
        _fresh_check(match_stub)
        data = _create(stack, _Bullhorn(), match_check_id="mc_passed")

        assert match_stub.match.call_count == 1
        assert _outcomes(real_log) == [
            ("mc_fresh", "created_new", CID), ("mc_passed", "created_new", CID),
        ]
        assert data["duplicate_check"]["match_check_id"] == "mc_fresh"
        assert data["match_check_id"] == "mc_passed"

    def test_create_candidate_logs_outcome_under_passed_id(self, stack, match_stub, real_log):
        _fresh_check(match_stub)
        data = _create_candidate(stack, _Bullhorn(), match_check_id="mc_passed")

        assert match_stub.match.call_count == 1
        assert _outcomes(real_log) == [
            ("mc_fresh", "created_new", CID), ("mc_passed", "created_new", CID),
        ]
        assert data["duplicate_check"]["match_check_id"] == "mc_fresh"
        assert data["match_check_id"] == "mc_passed"

    def test_same_passed_and_fresh_id_logged_once(self, stack, match_stub, real_log):
        _fresh_check(match_stub, check_id="mc_same")
        _create_candidate(stack, _Bullhorn(), match_check_id="mc_same")

        assert _outcomes(real_log) == [("mc_same", "created_new", CID)]

    def test_create_from_cv_logs_outcome_under_passed_id_with_force(self, stack, match_stub, real_log):
        """force skips the check (A1) and logs created_with_force under the passed id only."""
        data = _create(stack, _Bullhorn(), force=True, match_check_id="mc_passed")

        match_stub.match.assert_not_called()
        assert _outcomes(real_log) == [("mc_passed", "created_with_force", CID)]
        assert data["duplicate_check"] is None
        assert data["match_check_id"] == "mc_passed"

    def test_create_candidate_logs_outcome_under_passed_id_with_force(self, stack, match_stub, real_log):
        data = _create_candidate(stack, _Bullhorn(), force=True, match_check_id="mc_passed")

        match_stub.match.assert_not_called()
        assert _outcomes(real_log) == [("mc_passed", "created_with_force", CID)]
        assert data["duplicate_check"] is None
        assert data["match_check_id"] == "mc_passed"

    def test_create_candidate_returns_duplicate_check(self, stack, match_stub):
        """create_candidate reports the check on every create, as the CV path does (P2)."""
        _fresh_check(match_stub)
        data = _create_candidate(stack, _Bullhorn())

        assert data["duplicate_check"]["match_check_id"] == "mc_fresh"
        assert "match_check_id" not in data  # only echoed when one was passed

    def test_create_candidate_force_duplicate_check_null(self, stack, match_stub):
        data = _create_candidate(stack, _Bullhorn(), force=True)

        assert "duplicate_check" in data and data["duplicate_check"] is None


class TestNoPointsInResponses:
    STRONG = [_match(flags=["guaranteed_match:email"])]
    WEAK = [_match(candidate_id=51, percentage=60, band="uncertain")]

    def _with_deleted(self, match_stub, matches):
        match_stub.match.return_value = _match_result(matches, deleted_matches=[_match(candidate_id=77)])

    def test_find_duplicates_response_has_no_points(self, match_stub, mock_client):
        self._with_deleted(match_stub, self.STRONG)
        with patch.object(server, "get_client", return_value=mock_client):
            data = json.loads(server.find_duplicate_candidates("Jane", "Doe", email="jane@example.com"))

        assert data["matches"] and data["deleted_matches"]
        _no_points(data)

    def test_parse_cv_duplicate_check_has_no_points(self, stack, match_stub):
        self._with_deleted(match_stub, self.STRONG)
        upload_id = _upload_with_parse(PARSE)
        with patch.object(server, "_parse_upload", return_value=copy.deepcopy(PARSE)), \
             patch.object(BullhornClient, "parse_resume_text", return_value=copy.deepcopy(PARSE)):
            data = stack(_Bullhorn(), server.parse_cv, upload_id=upload_id)
            text = stack(_Bullhorn(), server.parse_cv_text, content="Jane Doe CV")

        assert data["duplicate_check"]["matches"] and text["duplicate_check"]["matches"]
        _no_points(data)
        _no_points(text)

    def test_stop_response_has_no_points(self, stack, match_stub):
        """Both create tools' stop responses (duplicate_found and possible_duplicates)."""
        for matches, kind in ((self.STRONG, "duplicate_found"), (self.WEAK, "possible_duplicates")):
            self._with_deleted(match_stub, matches)
            cv = _create(stack, _Bullhorn())
            plain = _create_candidate(stack, _Bullhorn())
            for data in (cv, plain):
                assert data[kind] is True and data["matches"]
                _no_points(data)

    def test_create_success_duplicate_check_has_no_points(self, stack, match_stub):
        """A check with only a low match does not stop; its duplicate_check still carries no points."""
        match_stub.match.return_value = _match_result(
            [_match(candidate_id=52, percentage=10, band="low")], deleted_matches=[_match(candidate_id=77)])
        cv = _create(stack, _Bullhorn())
        plain = _create_candidate(stack, _Bullhorn())

        for data in (cv, plain):
            assert data["duplicate_check"]["matches"]
            _no_points(data)

    def test_match_log_keeps_points(self, stack, match_stub, real_log):
        """Logging reads points from the original result: the check line and the create still work."""
        result = _match_result([_match(candidate_id=52, percentage=10, band="low")])

        def check(client, profile, caller=None):
            match_log.log_check("mc_fresh", caller=caller, config_version="2", profile=profile, result=result)
            return result

        match_stub.match.side_effect = check
        data = _create_candidate(stack, _Bullhorn(), match_check_id="mc_passed")

        _no_points(data)
        assert result["matches"][0]["points"] == 12.5  # the original is never mutated
        lines = real_log()
        check_line = next(x for x in lines if x["type"] == "check")
        assert check_line["candidates"][0]["points"] == 12.5
        assert check_line["candidates"][0]["signals"][0]["points"] == 6.0
        assert [x["outcome"] for x in lines if x["type"] == "outcome"] == ["created_new", "created_new"]


# --- T43.11: the upload box result carries ui.resourceUri, expiry in seconds ----------------

BOX_URI = "ui://bullhorn/cv-upload-box.html"


class TestUploadBoxResult:
    def test_show_upload_box_result_has_resource_uri(self):
        """Through a real in-process MCP client call: the CallToolResult _meta names the resource."""
        import asyncio
        import fastmcp
        upload_id = _seed_pending_upload()

        async def call():
            async with fastmcp.Client(server.mcp) as c:
                return await c.call_tool("show_cv_upload_box", {"upload_id": upload_id})

        with _http_as(), patch.dict("os.environ", {"MCP_BASE_URL": "https://mcp.example.com"}):
            result = asyncio.run(call())

        assert result.meta == {"ui": {"resourceUri": BOX_URI}}
        body = json.loads(result.content[0].text)
        assert body["upload_id"] == upload_id
        assert body["upload_url"].startswith("https://mcp.example.com/upload/")

    def test_upload_responses_have_expires_in_seconds(self):
        with _http_as(), patch.dict("os.environ", {"MCP_BASE_URL": "https://mcp.example.com"}), \
             patch.object(server, "_client_supports_ui", return_value=True):
            first = json.loads(server.request_cv_upload("Jane_Doe_CV.pdf"))
            shown = server.show_cv_upload_box(first["upload_id"])
        shown = json.loads(shown.content[0].text)

        for data in (first, shown):
            assert isinstance(data["expires_in_seconds"], int)
            assert 0 < data["expires_in_seconds"] <= 3600
        assert "do not curl" in first["next_steps"][2]
        assert "replaces" in shown["message"] and "do not curl" in shown["message"]

    def test_upload_box_resource_read_logged(self, caplog):
        import asyncio
        import logging
        with caplog.at_level(logging.INFO, logger="bullhorn_mcp.server"):
            asyncio.run(server.mcp.read_resource(BOX_URI))

        assert any(BOX_URI in r.getMessage() and r.levelno == logging.INFO for r in caplog.records)


def _seed_pending_upload():
    upload_id, _token, _ = server.upload_store.create("user-a", "Jane_Doe_CV.pdf", None)
    return upload_id


# --- B10 (found by T43.13 live): work history matched without endDate ----------------


class TestWorkHistoryMatchIgnoresEndDate:
    """The parser fills the current role's endDate inconsistently (the parse date on
    one run, null on the next), so an endDate difference must not make the same role
    look new. T43.13 live (2026-11-13) duplicated row 473104 on 173063 this way."""

    def test_same_role_different_end_date_is_already_present(self):
        existing = [{"id": 473104, "companyName": None, "title": "Senior Financial Accountant",
                     "startDate": 1609520400000, "endDate": 1788278400000}]
        parsed = [{"companyName": None, "title": "Senior Financial Accountant",
                   "startDate": 1609520400000, "endDate": None}]
        new_wh, _ = server._new_cv_children(existing, [], parsed, [])
        assert new_wh == []

    def test_different_start_date_is_still_new(self):
        existing = [{"id": 1, "companyName": "Acme", "title": "FC", "startDate": 1500000000000, "endDate": None}]
        parsed = [{"companyName": "Acme", "title": "FC", "startDate": 1700000000000, "endDate": None}]
        new_wh, _ = server._new_cv_children(existing, [], parsed, [])
        assert new_wh == parsed


# --- CR48 / T43.16: the consultant chooses each overwrite --------------------------------

OVERWRITE_PARSE = {**PARSE, "candidateWorkHistory": [WH_CURRENT], "skillList": ["Excel"]}
OVERWRITE_EXISTING = {
    "firstName": "Jane", "lastName": "Doe", "email": "jane@example.com", "mobile": "0851234567",
    "occupation": "Old Title", "companyName": "Previous Plc", "description": "<p>an older description</p>",
    "skillSet": "Excel",
}


def _candidate_posts(bh):
    return [json.loads(r.content) for r in bh.find("POST", f"/entity/Candidate/{CID}")]


def _merged_post(bh):
    return {k: v for p in _candidate_posts(bh) for k, v in p.items()}


class TestOverwriteChoice:
    def _first(self, stack):
        """The additions call: returns (response, upload_id). Writes nothing over an existing value."""
        bh = _Bullhorn(existing=OVERWRITE_EXISTING)
        data, upload_id = _attach(stack, bh, parse=OVERWRITE_PARSE)
        return data, upload_id

    def _again(self, stack, upload_id, existing_wh=None, **kwargs):
        bh = _Bullhorn(existing=OVERWRITE_EXISTING, existing_wh=existing_wh)
        data, _ = _attach(stack, bh, upload_id=upload_id, **kwargs)
        return data, bh

    def test_attach_cv_overwrite_list_writes_only_chosen(self, stack, clean_upload_store):
        _, upload_id = self._first(stack)
        data, bh = self._again(stack, upload_id, overwrite=["occupation"])
        body = _merged_post(bh)
        assert body["occupation"] == "Finance Manager"
        assert "companyName" not in body
        assert data["overwritten"] == ["occupation"]
        kept = {k["field"]: k for k in data["kept"]}
        assert kept["companyName"] == {"field": "companyName", "current": "Previous Plc"}
        assert "pending_overwrites" not in data

    def test_attach_cv_overwrite_all_writes_every_pending(self, stack, clean_upload_store):
        first, upload_id = self._first(stack)
        pending = [c["field"] for c in first["pending_overwrites"]]
        assert set(pending) == {"occupation", "companyName", "description"}
        for spelling in (["all"], ["ALL"], [" All "]):
            data, bh = self._again(stack, upload_id, overwrite=spelling)
            body = _merged_post(bh)
            assert body["occupation"] == "Finance Manager"
            assert body["companyName"] == "Acme Ltd"
            assert body["description"] == "<p>CV</p>"
            assert set(data["overwritten"]) == set(pending)
            assert "kept" not in data

    def test_attach_cv_no_overwrite_writes_none(self, stack, clean_upload_store):
        first, upload_id = self._first(stack)
        for omitted in ({}, {"overwrite": None}, {"overwrite": []}):
            data, bh = self._again(stack, upload_id, **omitted)
            body = _merged_post(bh)
            assert not {"occupation", "companyName", "description"} & set(body)
            assert "overwritten" not in data and "kept" not in data
            assert {c["field"] for c in data["pending_overwrites"]} == {"occupation", "companyName", "description"}
        assert first["pending_overwrites"]

    def test_attach_cv_overwrite_by_label(self, stack, clean_upload_store):
        _, upload_id = self._first(stack)
        data, bh = self._again(stack, upload_id, overwrite=["Job Title"])
        body = _merged_post(bh)
        assert body["occupation"] == "Finance Manager"
        assert "companyName" not in body
        assert data["overwritten"] == ["occupation"]
        assert not [w for w in data.get("warnings", []) if "overwrite" in w]

    def test_attach_cv_overwrite_unknown_field_warned(self, stack, clean_upload_store):
        _, upload_id = self._first(stack)
        data, bh = self._again(stack, upload_id, overwrite=["occupation", "email", "nonsense"])
        body = _merged_post(bh)
        assert body["occupation"] == "Finance Manager"
        # email equals the record's value, nonsense is nothing: neither is a pending overwrite
        assert "email" not in body and "nonsense" not in body
        assert data["overwritten"] == ["occupation"]
        warning = " ".join(w for w in data["warnings"] if "overwrite" in w)
        assert "email" in warning and "nonsense" in warning and "occupation" not in warning

    def test_attach_cv_overwrite_description_chosen(self, stack, clean_upload_store):
        _, upload_id = self._first(stack)
        data, bh = self._again(stack, upload_id, overwrite=["occupation"])
        assert "description" not in _merged_post(bh)
        kept = {k["field"]: k for k in data["kept"]}
        assert kept["description"] == {"field": "description", "current_length": len("<p>an older description</p>")}

        data, bh = self._again(stack, upload_id, overwrite=["description"])
        body = _merged_post(bh)
        assert body["description"] == "<p>CV</p>"
        assert "occupation" not in body and "companyName" not in body
        assert data["overwritten"] == ["description"]

    def test_attach_cv_overwrite_call_adds_nothing_twice(self, stack, clean_upload_store):
        first, upload_id = self._first(stack)
        assert first["written"]["file"]["file_id"] == 77
        written_wh = [{"id": 1, **WH_CURRENT}]
        bh = _Bullhorn(existing=OVERWRITE_EXISTING, existing_wh=written_wh)
        data, _ = _attach(stack, bh, upload_id=upload_id, overwrite=["occupation"])
        assert bh.find("PUT", "/entity/CandidateWorkHistory") == []
        assert bh.find("PUT", "/entity/CandidateEducation") == []
        assert bh.find("PUT", f"/file/Candidate/{CID}/raw") == []
        assert all("skillSet" not in p for p in _candidate_posts(bh))
        assert not [r for m, p, r in bh.requests if m == "PUT" and "/primarySkills/" in p]
        assert data["written"]["work_history"] == [] and data["written"]["skill_set"] == []
        assert data["written"]["file"]["already_attached"] is True
        assert _merged_post(bh) == {"occupation": "Finance Manager"}

    def test_attach_cv_hint_asks_per_field(self, stack, clean_upload_store):
        first, _ = self._first(stack)
        hint = first["hint"]
        assert "overwrite=[" in hint and "EACH" in hint and "confirm" not in hint
        assert "current vs proposed" in hint
