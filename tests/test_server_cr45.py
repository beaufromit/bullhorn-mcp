"""CR45 Sprint 44 server tests: the CV tools refuse files that are not CVs (T44.6, P7).

A png, jpg or eml upload is a valid upload (attach_file takes it) but parse_cv,
create_candidate_from_cv and attach_cv are CV tools. They check the extension right
after reading the upload, before any parse, write or Bullhorn call, and leave the
upload received with no claim held, so attach_file can still use it.
"""

import json
from unittest.mock import patch

import pytest

from bullhorn_mcp import server
from bullhorn_mcp import uploads as server_uploads
from bullhorn_mcp.client import BullhornClient
# Autouse / shared fixtures and helpers live in test_server.py and test_server_cr46.py.
from tests.test_server import (  # noqa: F401
    _http_as,
    _seed_upload,
    clean_upload_store,
    match_stub,
    mock_client,
    reset_client,
)
from tests.test_server_cr46 import CID, PARSE, _Bullhorn, stack  # noqa: F401

PNG_BYTES = b"\x89PNG\r\n\x1a\n fake"
EML_BYTES = b"From: a@example.com\r\nSubject: hi\r\n\r\nbody"


def _png():
    return _seed_upload(filename="photo.png", data=PNG_BYTES)


class TestCvToolsRefuseNonCvFiles:
    def test_parse_cv_refuses_png(self, stack):
        upload_id = _png()

        data = stack(_Bullhorn(), server.parse_cv, upload_id=upload_id)

        assert data["error"] == "not_a_cv_file"
        assert ".png" in data["message"] and "photo.png" in data["message"]

    def test_create_candidate_from_cv_refuses_eml(self, stack):
        upload_id = _seed_upload(filename="note.eml", data=EML_BYTES)

        data = stack(_Bullhorn(), server.create_candidate_from_cv, upload_id=upload_id)

        assert data["error"] == "not_a_cv_file"
        assert ".eml" in data["message"]

    def test_attach_cv_refuses_jpg(self, stack):
        upload_id = _seed_upload(filename="scan.jpg", data=b"\xff\xd8\xff fake")

        data = stack(_Bullhorn(), server.attach_cv, candidate_id=CID, upload_id=upload_id)

        assert data["error"] == "not_a_cv_file"
        assert ".jpg" in data["message"]

    @pytest.mark.parametrize("tool, kwargs", [
        (server.parse_cv, {}),
        (server.create_candidate_from_cv, {}),
        (server.attach_cv, {"candidate_id": CID}),
    ])
    def test_cv_refusal_hint_names_attach_file(self, stack, tool, kwargs):
        upload_id = _png()

        data = stack(_Bullhorn(), tool, upload_id=upload_id, **kwargs)

        assert "attach_file(entity, entity_id, upload_id=" in data["hint"]
        assert upload_id in data["hint"]
        assert "without parsing" in data["hint"]

    @pytest.mark.parametrize("tool, kwargs", [
        (server.parse_cv, {}),
        (server.create_candidate_from_cv, {}),
        (server.attach_cv, {"candidate_id": CID}),
    ])
    def test_cv_refusal_before_claim_and_bullhorn(self, stack, tool, kwargs):
        """No Bullhorn call, no parse, no claim left: the upload is still received and claimable."""
        upload_id = _png()
        bh = _Bullhorn()

        with patch.object(BullhornClient, "parse_resume_file") as parse:
            data = stack(bh, tool, upload_id=upload_id, **kwargs)

        assert data["error"] == "not_a_cv_file"
        assert bh.requests == []
        parse.assert_not_called()
        assert server.upload_store.get(upload_id, "user-a")["status"] == "received"
        # A claim still held would make this raise upload_in_use.
        server.upload_store.claim(upload_id, "user-a")
        server.upload_store.release(upload_id)

    def test_create_candidate_from_cv_text_mode_unaffected(self, stack):
        """Text mode has no upload and no extension, so the CV check never applies."""
        with patch.object(BullhornClient, "parse_resume_text", return_value=json.loads(json.dumps(PARSE))):
            data = stack(_Bullhorn(), server.create_candidate_from_cv, content="Jane Doe CV")

        assert data.get("error") is None
        assert data["created"] is True
        assert data["candidate_id"] == CID

    def test_cv_files_still_pass_the_check(self, stack):
        """A real CV extension is not refused (guards against an over-broad check)."""
        upload_id = _seed_upload()
        with patch.object(BullhornClient, "parse_resume_file", return_value=json.loads(json.dumps(PARSE))):
            data = stack(_Bullhorn(), server.parse_cv, upload_id=upload_id)

        assert "error" not in data
        assert "parsed" in data


# --- T44.5: attach_file ------------------------------------------------------------------

import httpx  # noqa: E402
import respx  # noqa: E402
from unittest.mock import Mock, PropertyMock  # noqa: E402

from bullhorn_mcp.auth import BullhornAuth  # noqa: E402
from bullhorn_mcp.metadata import BullhornMetadata  # noqa: E402
from tests.test_server import _CV_BYTES  # noqa: E402,F401
from tests.test_server_cr46 import _assert_original_cv_put  # noqa: E402,F401

SHARED_TYPES = ["Original CV", "Formatted CV", "Cover Letter", "References", "Signed Contract", "Proof of ID", "Visa"]
COMPANY_TYPES = ["Fee Agreement", "Directions", "Contract", "Credit Check"]
ATTACHABLE = ["Candidate", "ClientContact", "ClientCorporation", "JobOrder", "Placement", "Opportunity"]
_NO_ISDELETED = ("Placement",)


class _FileBullhorn:
    """respx dispatcher for attach_file: records every request and answers like Bullhorn."""

    def __init__(self, records=None, deleted=(), files=None, files_status=200, settings_status=200,
                 put_status=200, types=None, record_status=200, record_error="server error",
                 files_error="nope", meta_status=200):
        self.record_status = record_status  # non-200: the record read fails this way
        self.record_error = record_error
        self.files_error = files_error
        self.meta_status = meta_status
        self.records = records  # {(entity, id)} that exist; None = every id exists
        self.deleted = set(deleted)
        self.files = files or []
        self.files_status = files_status
        self.settings_status = settings_status
        self.put_status = put_status
        self.types = types
        self.requests: list[tuple[str, str, httpx.Request]] = []

    def __call__(self, request):
        path = request.url.path.split("/rest-services/abc123", 1)[1]
        method = request.method
        self.requests.append((method, path, request))
        parts = path.strip("/").split("/")
        if method == "GET" and parts[0] == "meta":
            if self.meta_status != 200:
                return httpx.Response(self.meta_status, json={"errorMessage": "meta down"})
            fields = [] if parts[1] in _NO_ISDELETED else [{"name": "isDeleted", "type": "SCALAR"}]
            return httpx.Response(200, json={"entity": parts[1], "fields": fields})
        if method == "GET" and parts[0] == "settings":
            if self.settings_status != 200:
                return httpx.Response(self.settings_status, json={"errorMessage": "boom"})
            return httpx.Response(200, json={
                "fileTypeList": SHARED_TYPES, "clientCorporationFileTypeList": COMPANY_TYPES,
            })
        if method == "GET" and parts[0] == "entity" and len(parts) == 3:
            entity, eid = parts[1], int(parts[2])
            if self.record_status != 200:
                return httpx.Response(self.record_status, json={"errorMessage": self.record_error})
            if self.records is not None and (entity, eid) not in self.records:
                return httpx.Response(404, json={"errorMessage": "Entity not found."})
            data = {"id": eid}
            if entity not in _NO_ISDELETED and "isDeleted" in (request.url.params.get("fields") or ""):
                data["isDeleted"] = (entity, eid) in self.deleted
            return httpx.Response(200, json={"data": data})
        if method == "GET" and parts[0] == "entityFiles":
            if self.files_status != 200:
                return httpx.Response(self.files_status, json={"errorMessage": self.files_error})
            return httpx.Response(200, json={"EntityFiles": self.files})
        if method == "PUT" and parts[0] == "file":
            if self.put_status != 200:
                return httpx.Response(self.put_status, json={"errorMessage": "write failed"})
            return httpx.Response(200, json={"fileId": 4321})
        return httpx.Response(404, json={"errorMessage": f"unmocked {method} {path}"})

    def find(self, method, prefix):
        return [r for m, p, r in self.requests if m == method and p.startswith(prefix)]

    def writes(self):
        return [(m, p) for m, p, _ in self.requests if m in ("PUT", "POST")]


@pytest.fixture
def fstack(mock_session):
    """Real client + metadata over respx; run(bh, fn, **kw) returns the tool's RAW string result."""
    auth = Mock(spec=BullhornAuth)
    type(auth).session = PropertyMock(return_value=mock_session)
    client = BullhornClient(auth)
    metadata = BullhornMetadata(client)

    def run(bh, fn, **kwargs):
        with respx.mock(assert_all_called=False) as router:
            router.route(host="rest99.bullhornstaffing.com").mock(side_effect=bh)
            with _http_as(), \
                 patch.object(server, "get_client", return_value=client), \
                 patch.object(server, "get_metadata", return_value=metadata):
                return fn(**kwargs)

    def run_json(bh, fn, **kwargs):
        return json.loads(run(bh, fn, **kwargs))

    run.json = run_json
    run.client = client
    return run


def _jd(filename="JD.docx"):
    return _seed_upload(filename=filename, data=b"PK\x03\x04 fake docx")


def _attach(fstack, bh, upload_id=None, entity="JobOrder", entity_id=51437, **kw):
    upload_id = upload_id or _jd()
    return fstack.json(bh, server.attach_file, entity=entity, entity_id=entity_id, upload_id=upload_id, **kw), upload_id


def _status(upload_id):
    return server.upload_store.get(upload_id, "user-a")["status"]


@pytest.mark.usefixtures("clean_upload_store")
class TestAttachFile:
    @pytest.mark.parametrize("entity", ATTACHABLE)
    def test_attach_per_entity(self, fstack, entity):
        bh = _FileBullhorn()
        data, upload_id = _attach(fstack, bh, entity=entity, entity_id=77)

        assert data == {
            "attached": True, "entity": entity, "entity_id": 77, "file_id": 4321,
            "filename": "JD.docx", "type": None, "description": None, "warnings": [],
        }
        assert len(bh.find("PUT", f"/file/{entity}/77/raw")) == 1
        assert _status(upload_id) == "attached"

    def test_lead_refused(self, fstack):
        bh = _FileBullhorn()
        data, upload_id = _attach(fstack, bh, entity="Lead", entity_id=5)

        assert data["error"] == "unsupported_entity"
        assert "leads" in data["message"] and "contact or candidate" in data["message"]
        assert bh.requests == []
        assert _status(upload_id) == "received"

    def test_unknown_entity_refused(self, fstack):
        bh = _FileBullhorn()
        data, _ = _attach(fstack, bh, entity="Placementx", entity_id=5)

        assert data["error"] == "unsupported_entity"
        for e in ATTACHABLE:
            assert e in data["message"]
        assert bh.requests == []

    def test_label_valid_written_in_list_spelling(self, fstack):
        bh = _FileBullhorn()
        data, _ = _attach(fstack, bh, entity="Candidate", entity_id=9, type="Cover Letter")

        assert data["type"] == "Cover Letter"
        assert dict(bh.find("PUT", "/file/")[0].url.params)["type"] == "Cover Letter"

    def test_label_case_insensitive_match(self, fstack):
        bh = _FileBullhorn()
        data, _ = _attach(fstack, bh, entity="Candidate", entity_id=9, type="  cover LETTER ")

        assert data["type"] == "Cover Letter"
        assert dict(bh.find("PUT", "/file/")[0].url.params)["type"] == "Cover Letter"

    def test_label_invalid_returns_allowed_list(self, fstack):
        bh = _FileBullhorn()
        data, upload_id = _attach(fstack, bh, entity="Candidate", entity_id=9, type="Job Description")

        assert data["error"] == "invalid_file_type_label"
        assert data["allowed"] == SHARED_TYPES
        assert "Candidate" in data["message"] and "Job Description" in data["message"]
        assert bh.writes() == []
        assert _status(upload_id) == "received"

    def test_company_label_from_company_list(self, fstack):
        bh = _FileBullhorn()
        refused, upload_id = _attach(fstack, bh, entity="ClientCorporation", entity_id=3, type="Cover Letter")
        assert refused["error"] == "invalid_file_type_label"
        assert refused["allowed"] == COMPANY_TYPES

        data, _ = _attach(fstack, bh, upload_id=upload_id, entity="ClientCorporation", entity_id=3, type="contract")
        assert data["type"] == "Contract"

    def test_no_label_attaches_with_no_type(self, fstack):
        bh = _FileBullhorn()
        data, _ = _attach(fstack, bh)

        assert data["type"] is None
        assert "type" not in dict(bh.find("PUT", "/file/")[0].url.params)
        assert bh.find("GET", "/settings") == []

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_label_is_none(self, fstack, blank):
        bh = _FileBullhorn()
        data, _ = _attach(fstack, bh, type=blank)

        assert data["type"] is None
        assert "type" not in dict(bh.find("PUT", "/file/")[0].url.params)

    def test_settings_unavailable_no_label_attaches(self, fstack):
        bh = _FileBullhorn(settings_status=500)
        data, _ = _attach(fstack, bh)

        assert data["attached"] is True

    def test_settings_unavailable_with_label_refused(self, fstack):
        bh = _FileBullhorn(settings_status=500)
        data, upload_id = _attach(fstack, bh, type="Cover Letter", entity="Candidate", entity_id=1)

        assert data["error"] == "file_types_unavailable"
        assert bh.writes() == []
        assert _status(upload_id) == "received"

    def test_record_not_found_404(self, fstack):
        bh = _FileBullhorn(records=set())
        data, upload_id = _attach(fstack, bh, entity_id=999)

        assert data["error"] == "record_not_found"
        assert "JobOrder 999" in data["message"]
        assert bh.writes() == []
        assert bh.find("GET", "/entityFiles") == []
        assert _status(upload_id) == "received"

    def test_soft_deleted_record_refused(self, fstack):
        bh = _FileBullhorn(deleted={("Candidate", 173779)})
        data, upload_id = _attach(fstack, bh, entity="Candidate", entity_id=173779)

        assert data["error"] == "record_not_found"
        assert bh.writes() == []
        assert _status(upload_id) == "received"

    def test_placement_no_isdeleted_field_requested(self, fstack):
        bh = _FileBullhorn()
        _attach(fstack, bh, entity="Placement", entity_id=11)
        _attach(fstack, bh, entity="Opportunity", entity_id=12)

        assert bh.find("GET", "/entity/Placement/11")[0].url.params["fields"] == "id"
        assert bh.find("GET", "/entity/Opportunity/12")[0].url.params["fields"] == "id,isDeleted"

    def test_placement_no_isdeleted_field_requested_when_meta_down(self, fstack):
        bh = _FileBullhorn(meta_status=500)
        data, _ = _attach(fstack, bh, entity="Placement", entity_id=11)

        assert data["attached"] is True
        assert bh.find("GET", "/entity/Placement/11")[0].url.params["fields"] == "id"

    @pytest.mark.parametrize("status", [400, 403, 500])
    def test_non_404_error_with_404_in_body_is_not_record_not_found(self, fstack, status):
        bh = _FileBullhorn(record_status=status, record_error="request 404-140455 failed")
        upload_id = _jd()
        raw = fstack(bh, server.attach_file, entity="JobOrder", entity_id=140455, upload_id=upload_id)

        assert raw.startswith("ERROR:") and str(status) in raw
        assert "record_not_found" not in raw
        assert bh.writes() == []
        assert _status(upload_id) == "received"

    def test_upload_not_found(self, fstack):
        bh = _FileBullhorn()
        data = fstack.json(bh, server.attach_file, entity="JobOrder", entity_id=1, upload_id="nope")

        assert data["error"] == "upload_not_found"
        assert bh.requests == []

    def test_upload_expired(self, fstack):
        bh = _FileBullhorn()
        upload_id = _jd()
        # Drive the store's own clock past the received file's lifetime.
        real_clock = server.upload_store._clock
        later = real_clock() + server_uploads.FILE_TTL_SECONDS + 1
        with patch.object(server.upload_store, "_clock", lambda: later):
            data, _ = _attach(fstack, bh, upload_id=upload_id)

        assert data["error"] == "upload_expired"
        assert bh.requests == []

    def test_upload_not_received(self, fstack):
        bh = _FileBullhorn()
        upload_id, _token, _ = server.upload_store.create("user-a", "JD.docx")
        data, _ = _attach(fstack, bh, upload_id=upload_id)

        assert data["error"] == "upload_pending"
        assert bh.requests == []
        server.upload_store.claim(upload_id, "user-a")  # claim was released

    def test_upload_already_attached(self, fstack):
        bh = _FileBullhorn()
        data, upload_id = _attach(fstack, bh)
        assert data["attached"] is True
        bh2 = _FileBullhorn()
        again, _ = _attach(fstack, bh2, upload_id=upload_id)

        assert again["error"] == "upload_already_attached"
        assert bh2.requests == []

    def test_upload_in_use_by_overlapping_call(self, fstack):
        bh = _FileBullhorn()
        upload_id = _jd()
        server.upload_store.claim(upload_id, "user-a")
        data, _ = _attach(fstack, bh, upload_id=upload_id)

        assert data["error"] == "upload_in_use"
        assert bh.requests == []
        # The other call's claim is untouched by the refused one.
        with pytest.raises(server.UploadError):
            server.upload_store.claim(upload_id, "user-a")

    def test_claim_released_on_bullhorn_error(self, fstack):
        bh = _FileBullhorn(put_status=500)
        upload_id = _jd()
        result = fstack(bh, server.attach_file, entity="JobOrder", entity_id=5, upload_id=upload_id)

        assert result.startswith("ERROR:")
        assert _status(upload_id) == "received"
        server.upload_store.claim(upload_id, "user-a")  # would raise if still held
        server.upload_store.release(upload_id)
        # And a retry now succeeds with the bytes still held.
        retry = fstack.json(_FileBullhorn(), server.attach_file, entity="JobOrder", entity_id=5, upload_id=upload_id)
        assert retry["attached"] is True

    @pytest.mark.parametrize("kwargs, error", [
        ({"entity": "Lead"}, "unsupported_entity"),
        ({"type": "Nope"}, "invalid_file_type_label"),
    ])
    def test_claim_released_on_validation_refusals(self, fstack, kwargs, error):
        upload_id = _jd()
        args = {"entity": "Candidate", "entity_id": 1, **kwargs}
        data = fstack.json(_FileBullhorn(), server.attach_file, upload_id=upload_id, **args)

        assert data["error"] == error
        server.upload_store.claim(upload_id, "user-a")
        server.upload_store.release(upload_id)

    def test_claim_released_on_record_not_found_and_record_error(self, fstack):
        upload_id = _jd()
        data = fstack.json(_FileBullhorn(records=set()), server.attach_file,
                           entity="JobOrder", entity_id=1, upload_id=upload_id)
        assert data["error"] == "record_not_found"
        server.upload_store.claim(upload_id, "user-a")
        server.upload_store.release(upload_id)

        # A non-404 record read error: no write, an error back, the claim released.
        bh = _FileBullhorn(record_status=500)
        upload_id = _jd()
        raw = fstack(bh, server.attach_file, entity="JobOrder", entity_id=1, upload_id=upload_id)
        assert raw.startswith("ERROR:") and "500" in raw
        assert bh.writes() == []
        assert _status(upload_id) == "received"
        server.upload_store.claim(upload_id, "user-a")
        server.upload_store.release(upload_id)

    def test_claim_released_on_file_types_unavailable(self, fstack):
        bh = _FileBullhorn(settings_status=500)
        data, upload_id = _attach(fstack, bh, type="Cover Letter", entity="Candidate", entity_id=1)
        assert data["error"] == "file_types_unavailable"
        server.upload_store.claim(upload_id, "user-a")
        server.upload_store.release(upload_id)

    def test_marked_attached_and_bytes_dropped(self, fstack):
        bh = _FileBullhorn()
        data, upload_id = _attach(fstack, bh, entity="ClientContact", entity_id=145635)

        rec = server.upload_store.get(upload_id, "user-a")
        assert rec["status"] == "attached" and rec["data"] is None
        with _http_as():
            shown = json.loads(server.get_file_upload(upload_id))
        assert shown["status"] == "attached"
        assert shown["file_id"] == 4321
        assert shown["attached_entity"] == "ClientContact"
        assert shown["attached_entity_id"] == 145635

    def test_same_name_warns_and_attaches(self, fstack):
        bh = _FileBullhorn(files=[
            {"id": 11, "name": "jd.DOCX", "isDeleted": False},
            {"id": 12, "name": " JD.docx ", "isDeleted": False},
            {"id": 13, "name": "other.docx", "isDeleted": False},
        ])
        data, upload_id = _attach(fstack, bh)

        assert data["attached"] is True
        assert len(data["warnings"]) == 1
        assert "11" in data["warnings"][0] and "12" in data["warnings"][0] and "13" not in data["warnings"][0]
        assert _status(upload_id) == "attached"

    def test_same_name_ignores_deleted_rows(self, fstack):
        bh = _FileBullhorn(files=[{"id": 11, "name": "JD.docx", "isDeleted": True}])
        data, _ = _attach(fstack, bh)

        assert data["warnings"] == []

    def test_entity_files_read_failure_still_attaches(self, fstack, caplog):
        bh = _FileBullhorn(files_status=500)
        with caplog.at_level("WARNING"):
            data, _ = _attach(fstack, bh)

        assert data["attached"] is True and data["warnings"] == []
        logged = " ".join(r.getMessage() for r in caplog.records)
        assert "could not read existing files" in logged
        assert "JD.docx" not in logged

    def test_entity_files_read_failure_log_leaves_out_bullhorn_body(self, fstack, caplog):
        bh = _FileBullhorn(files_status=500, files_error="Jane Doe 0871234567")
        with caplog.at_level("WARNING"):
            data, _ = _attach(fstack, bh)

        assert data["attached"] is True
        logged = " ".join(r.getMessage() for r in caplog.records)
        assert "could not read existing files of JobOrder 51437" in logged and "500" in logged
        assert "Jane" not in logged and "0871234567" not in logged

    def test_write_payload_exact(self, fstack):
        bh = _FileBullhorn()
        upload_id = _seed_upload(filename="Photo ID.png", data=PNG_BYTES)
        _attach(fstack, bh, upload_id=upload_id, entity="Candidate", entity_id=7,
                type="proof of id", description="Passport scan")

        puts = bh.find("PUT", "/file/")
        assert len(puts) == 1
        req = puts[0]
        assert req.url.path.endswith("/file/Candidate/7/raw")
        assert dict(req.url.params) == {
            "externalID": "Portfolio", "type": "Proof of ID", "description": "Passport scan",
        }
        body = req.content
        assert b'filename="Photo ID.png"' in body
        assert b"Content-Type: image/png" in body
        assert PNG_BYTES in body

    @pytest.mark.parametrize("description, sent", [
        ("  Passport scan  ", "Passport scan"),
        ("", None),
        ("   ", None),
    ])
    def test_description_stripped_and_blank_left_out(self, fstack, description, sent):
        bh = _FileBullhorn()
        _attach(fstack, bh, description=description)

        params = dict(bh.find("PUT", "/file/")[0].url.params)
        assert params.get("description") == sent
        if sent is None:
            assert "description" not in params

    def test_no_candidate_fields_written(self, fstack):
        bh = _FileBullhorn()
        _attach(fstack, bh, entity="Candidate", entity_id=7, type="Cover Letter")

        assert bh.writes() == [("PUT", "/file/Candidate/7/raw")]

    def test_attach_file_not_in_enrichment_map(self):
        from bullhorn_mcp.descriptions import TOOL_ENTITY_MAP
        assert "attach_file" not in TOOL_ENTITY_MAP

    def test_docstring_summary_reaches_agent(self):
        import asyncio
        tool = next(t for t in asyncio.run(server.mcp.list_tools()) if t.name == "attach_file")
        for needle in ("without parsing", "Lead", "JobOrder", "leave it blank", "parse_cv"):
            assert needle in tool.description


# --- T44.14: end to end at the HTTP boundary -------------------------------------------

@pytest.mark.usefixtures("clean_upload_store")
class TestAttachFileEndToEnd:
    @pytest.fixture
    def http(self):
        from starlette.testclient import TestClient
        return TestClient(server.mcp.http_app())

    def _request(self, fstack, bh, filename, **kw):
        with patch.dict("os.environ", {"MCP_BASE_URL": "https://mcp.example.com"}):
            ticket = fstack.json(bh, server.request_file_upload, filename=filename, **kw)
        assert "error" not in ticket
        return ticket["upload_id"], ticket["upload_url"].rsplit("/upload/", 1)[1]

    def test_docx_jd_on_joborder(self, fstack, http):
        bh = _FileBullhorn()
        upload_id, token = self._request(fstack, bh, "Finance Manager JD.docx", entity="JobOrder", entity_id=51437)
        resp = http.post(f"/upload/{token}", files={"file": ("abc-Finance Manager JD.docx", b"PK\x03\x04 jd")})
        assert resp.status_code == 200

        data = fstack.json(bh, server.attach_file, entity="JobOrder", entity_id=51437, upload_id=upload_id)
        assert data["attached"] is True and data["filename"] == "Finance Manager JD.docx"
        put = bh.find("PUT", "/file/JobOrder/51437/raw")[0]
        assert dict(put.url.params) == {"externalID": "Portfolio"}
        assert b"wordprocessingml.document" in put.content

        shown = fstack.json(bh, server.get_file_upload, upload_id=upload_id)
        assert shown["status"] == "attached" and shown["attached_entity"] == "JobOrder"
        assert shown["attached_entity_id"] == 51437

    def test_png_on_client_contact(self, fstack, http):
        bh = _FileBullhorn()
        upload_id, token = self._request(fstack, bh, "card.png")
        assert http.post(f"/upload/{token}", files={"file": ("x-card.png", PNG_BYTES)}).status_code == 200

        data = fstack.json(bh, server.attach_file, entity="ClientContact", entity_id=145635,
                           upload_id=upload_id, description="Business card")
        assert data["attached"] is True
        put = bh.find("PUT", "/file/ClientContact/145635/raw")[0]
        assert dict(put.url.params) == {"externalID": "Portfolio", "description": "Business card"}
        assert b"image/png" in put.content
        shown = fstack.json(bh, server.get_file_upload, upload_id=upload_id)
        assert shown["attached_entity"] == "ClientContact"

    def test_png_refused_by_parse_cv_and_stays_received(self, fstack, http):
        bh = _FileBullhorn()
        upload_id, token = self._request(fstack, bh, "card.png")
        http.post(f"/upload/{token}", files={"file": ("x-card.png", PNG_BYTES)})

        data = fstack.json(bh, server.parse_cv, upload_id=upload_id)

        assert data["error"] == "not_a_cv_file"
        assert bh.requests == []
        assert _status(upload_id) == "received"

    def test_cv_through_renamed_tools_keeps_original_cv_type(self, stack, http, match_stub):
        bh = _Bullhorn(existing={"firstName": "Jane", "lastName": "Doe"})
        with patch.dict("os.environ", {"MCP_BASE_URL": "https://mcp.example.com"}):
            ticket = stack(bh, server.request_file_upload, filename="Jane_Doe_CV.pdf")
        token = ticket["upload_url"].rsplit("/upload/", 1)[1]
        assert http.post(f"/upload/{token}", files={"file": ("x-Jane_Doe_CV.pdf", _CV_BYTES)}).status_code == 200
        upload_id = ticket["upload_id"]
        assert stack(bh, server.get_file_upload, upload_id=upload_id)["status"] == "received"

        with patch.object(BullhornClient, "parse_resume_file", return_value=json.loads(json.dumps(PARSE))):
            parsed = stack(bh, server.parse_cv, upload_id=upload_id)
        assert "error" not in parsed
        data = stack(bh, server.attach_cv, candidate_id=CID, upload_id=upload_id)

        assert "error" not in data
        _assert_original_cv_put(bh)
