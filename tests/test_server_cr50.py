"""Sprint 46 (CR50): file description cap and get_file_text (T46.1, T46.2), upload box always
offered and next_steps by hint and extension (T46.3, T46.4), attach reporting (T46.5), wording (T46.6),
box URI rename (T46.7), and the end-to-end flow across them (T46.8)."""

import asyncio
import copy
import json
import logging
from unittest.mock import Mock, PropertyMock, patch

import httpx
import pytest
import respx

from bullhorn_mcp import server
from bullhorn_mcp.auth import BullhornAuth
from bullhorn_mcp.client import BullhornClient

# Shared fixtures and helpers from earlier suites.
from tests.test_server import (  # noqa: F401
    _http_as,
    clean_upload_store,
    match_stub,
    mock_client,
    reset_client,
)
from tests.test_server_cr45 import (  # noqa: F401
    _FileBullhorn,
    _attach as _attach_file,
    fstack,
)
from tests.test_server_cr46 import (  # noqa: F401
    CID,
    PARSE,
    _Bullhorn,
    _attach as _attach_cv,
    _upload_with_parse,
    stack,
)



# ===== T46.1 cap and T46.2 get_file_text =====

REST = "https://rest99.bullhornstaffing.com/rest-services/abc123"
LONG = "x" * 1200


@pytest.fixture(autouse=True)
def _reset_client():
    server._client = None
    server._metadata = None
    yield
    server._client = None
    server._metadata = None


@pytest.fixture
def client(mock_session):
    auth = Mock(spec=BullhornAuth)
    type(auth).session = PropertyMock(return_value=mock_session)
    c = BullhornClient(auth)
    with patch.object(server, "get_client", return_value=c):
        yield c


def _file(i, description=LONG):
    return {"id": i, "name": f"f{i}.txt", "description": description}


def _capped(data):
    return json.loads(server.format_response(data))


# --- T46.1: the walker -------------------------------------------------------------


class TestCapWalker:
    def test_cap_envelope_fileattachments(self):
        data = {"id": 1, "fileAttachments": {"total": 2, "data": [_file(1), _file(2, "short")]}}

        out = server._cap_file_descriptions(data)

        rows = out["fileAttachments"]["data"]
        assert rows[0]["description"] == "x" * 500
        assert rows[0]["description_truncated"] is True
        assert rows[0]["description_length"] == 1200
        assert rows[1] == {"id": 2, "name": "f2.txt", "description": "short"}
        assert out["fileAttachments"]["total"] == 2

    def test_cap_plain_list_fileattachments(self):
        out = server._cap_file_descriptions({"fileAttachments": [_file(1)]})

        assert out["fileAttachments"][0]["description_length"] == 1200
        assert len(out["fileAttachments"][0]["description"]) == 500

    def test_cap_parsed_resume_file(self):
        out = server._cap_file_descriptions({"id": 5, "parsedResumeFile": _file(9)})

        assert out["parsedResumeFile"]["description_truncated"] is True
        assert len(out["parsedResumeFile"]["description"]) == 500

    def test_short_description_unchanged_no_flag(self):
        data = {"fileAttachments": {"total": 1, "data": [_file(1, "hello")]}}

        out = server._cap_file_descriptions(data)

        assert out == data
        assert out is data
        assert "description_truncated" not in out["fileAttachments"]["data"][0]

    def test_exactly_500_not_flagged(self):
        data = {"fileAttachments": [_file(1, "y" * 500)]}

        out = server._cap_file_descriptions(data)

        assert out["fileAttachments"][0]["description"] == "y" * 500
        assert "description_truncated" not in out["fileAttachments"][0]

    def test_501_flagged(self):
        out = server._cap_file_descriptions({"fileAttachments": [_file(1, "y" * 501)]})

        assert out["fileAttachments"][0]["description_length"] == 501

    def test_candidate_own_description_not_capped(self):
        data = {"id": 1, "description": LONG, "fileAttachments": [_file(1)]}

        out = server._cap_file_descriptions(data)

        assert out["description"] == LONG
        assert len(out["fileAttachments"][0]["description"]) == 500

    def test_nested_search_row_capped(self):
        data = {
            "data": [{"id": 1, "fileAttachments": {"total": 1, "data": [_file(1)]}}],
            "pagination": {"total": 1},
        }

        out = server._cap_file_descriptions(data)

        assert out["data"][0]["fileAttachments"]["data"][0]["description_length"] == 1200
        assert out["pagination"] == {"total": 1}

    def test_input_not_mutated(self):
        data = {
            "fileAttachments": {"total": 1, "data": [_file(1)]},
            "parsedResumeFile": _file(2),
        }
        snapshot = copy.deepcopy(data)

        server._cap_file_descriptions(data)
        server._cap_file_descriptions(data, file_rows=True)

        assert data == snapshot

    def test_file_rows_caps_top_level_rows_only_when_asked(self):
        env = {"data": [_file(1)], "pagination": {}}

        assert server._cap_file_descriptions(env)["data"][0]["description"] == LONG
        out = server._cap_file_descriptions(env, file_rows=True)
        assert len(out["data"][0]["description"]) == 500
        assert env["data"][0]["description"] == LONG

    def test_file_rows_plain_list(self):
        out = server._cap_file_descriptions([_file(1)], file_rows=True)

        assert out[0]["description_truncated"] is True

    def test_scalars_none_and_strings_pass_through(self):
        for value in (None, 3, "text", {"fileAttachments": None}, {"fileAttachments": "x"}):
            assert server._cap_file_descriptions(value) == value
            assert server._cap_file_descriptions(value, file_rows=True) == value

    def test_non_string_description_untouched(self):
        data = {"fileAttachments": [{"id": 1, "description": None}, {"id": 2, "description": 7}]}

        assert server._cap_file_descriptions(data) == data

    def test_format_response_applies_cap(self):
        out = _capped({"fileAttachments": [_file(1)]})

        assert out["fileAttachments"][0]["description_truncated"] is True


# --- T46.1: tools ---------------------------------------------------------------


class TestCapEndToEnd:
    def test_get_company_fileattachments_capped_end_to_end(self, client):
        rows = [_file(i, LONG if i % 2 else "short") for i in range(23)]
        body = {"data": {"id": 10666, "fileAttachments": {"total": 23, "data": rows}}}
        with respx.mock:
            respx.get(f"{REST}/entity/ClientCorporation/10666").mock(
                return_value=httpx.Response(200, json=body)
            )
            out = json.loads(server.get_company(10666, fields="id,fileAttachments[50](id,name,description)"))

        files = out["fileAttachments"]["data"]
        assert len(files) == 23
        capped = [f for f in files if f.get("description_truncated")]
        assert len(capped) == 11
        assert all(len(f["description"]) == 500 for f in capped)
        assert all(f["description"] == "short" for f in files if not f.get("description_truncated"))

    def test_get_candidate_and_get_job_capped(self, client):
        cand = {"data": {"id": 1, "description": LONG, "fileAttachments": [_file(1)]}}
        job = {"data": {"id": 2, "fileAttachments": {"total": 1, "data": [_file(2)]}}}
        with respx.mock:
            respx.get(f"{REST}/entity/Candidate/1").mock(return_value=httpx.Response(200, json=cand))
            respx.get(f"{REST}/entity/JobOrder/2").mock(return_value=httpx.Response(200, json=job))
            c = json.loads(server.get_candidate(1, fields="id,description,fileAttachments"))
            j = json.loads(server.get_job(2, fields="id,fileAttachments"))

        assert c["description"] == LONG
        assert c["fileAttachments"][0]["description_length"] == 1200
        assert j["fileAttachments"]["data"][0]["description_length"] == 1200

    def test_query_entities_file_attachment_rows_capped(self, client):
        body = {"data": [_file(902), _file(901, "short")], "total": 2}
        with respx.mock:
            respx.get(f"{REST}/query/ClientCorporationFileAttachment").mock(
                return_value=httpx.Response(200, json=body)
            )
            out = json.loads(server.query_entities(
                entity="ClientCorporationFileAttachment", where="id>0", fields="id,description"
            ))

        assert out["data"][0]["description_truncated"] is True
        assert len(out["data"][0]["description"]) == 500
        assert out["data"][1]["description"] == "short"
        assert out["pagination"]["total"] == 2

    def test_query_entities_other_entity_rows_not_capped(self, client):
        body = {"data": [{"id": 1, "description": LONG}], "total": 1}
        with respx.mock:
            respx.get(f"{REST}/query/JobOrder").mock(return_value=httpx.Response(200, json=body))
            out = json.loads(server.query_entities(entity="JobOrder", where="id>0", fields="id,description"))

        assert out["data"][0]["description"] == LONG

    def test_search_entities_file_attachment_rows_capped(self, client):
        body = {"data": [_file(5)], "total": 1}
        with respx.mock:
            respx.get(f"{REST}/search/CandidateFileAttachment").mock(
                return_value=httpx.Response(200, json=body)
            )
            out = json.loads(server.search_entities(
                entity="CandidateFileAttachment", query="id:5", fields="id,description"
            ))

        assert out["data"][0]["description_length"] == 1200

    def test_search_entities_nested_row_capped(self, client):
        body = {"data": [{"id": 1, "fileAttachments": [_file(1)]}], "total": 1}
        with respx.mock:
            respx.get(f"{REST}/search/Candidate").mock(return_value=httpx.Response(200, json=body))
            out = json.loads(server.search_entities(
                entity="Candidate", query="id:1", fields="id,fileAttachments(id,description)"
            ))

        assert out["data"][0]["fileAttachments"][0]["description_truncated"] is True


# --- T46.2: get_file_text -------------------------------------------------------


def _entity_files(rows):
    return respx.get(f"{REST}/entityFiles/ClientCorporation/10666").mock(
        return_value=httpx.Response(200, json={"EntityFiles": rows})
    )


def _text(**kwargs):
    kwargs.setdefault("entity", "ClientCorporation")
    kwargs.setdefault("entity_id", 10666)
    kwargs.setdefault("file_id", 899)
    return json.loads(server.get_file_text(**kwargs))


class TestGetFileText:
    def test_full_text_under_page(self, client):
        row = {"id": 899, "name": "a.txt", "type": "Contract", "isDeleted": False, "description": "hello"}
        with respx.mock:
            _entity_files([row])
            out = _text()

        assert out == {
            "entity": "ClientCorporation", "entity_id": 10666, "file_id": 899,
            "name": "a.txt", "type": "Contract", "isDeleted": False,
            "length": 5, "offset": 0, "text": "hello", "next_offset": None,
        }

    def test_paging_next_offset_then_null(self, client):
        text = "a" * 20000 + "b" * 20000 + "c" * 5
        with respx.mock:
            _entity_files([{"id": 899, "name": "a.txt", "description": text}])
            first = _text()
            second = _text(offset=first["next_offset"])
            third = _text(offset=second["next_offset"])

        assert first["next_offset"] == 20000 and first["text"] == "a" * 20000
        assert second["next_offset"] == 40000 and second["text"] == "b" * 20000
        assert third["next_offset"] is None and third["text"] == "c" * 5
        assert first["length"] == 40005

    def test_exact_page_boundary_has_no_next(self, client):
        with respx.mock:
            _entity_files([{"id": 899, "name": "a.txt", "description": "a" * 20000}])
            out = _text()

        assert out["next_offset"] is None

    @pytest.mark.parametrize("offset", [-1, 5, 99, "3", 1.5, True])
    def test_invalid_offset(self, client, offset):
        with respx.mock:
            _entity_files([{"id": 899, "name": "a.txt", "description": "hello"}])
            out = _text(offset=offset)

        assert out["error"] == "invalid_offset"

    def test_file_not_found_lists_ids_and_names(self, client):
        with respx.mock:
            _entity_files([{"id": 1, "name": "one.txt"}, {"id": 2, "name": "two.txt"}])
            out = _text(file_id=999)

        assert out["error"] == "file_not_found"
        assert out["files"] == [{"id": 1, "name": "one.txt"}, {"id": 2, "name": "two.txt"}]

    def test_deleted_file_row_served_with_isdeleted(self, client):
        with respx.mock:
            _entity_files([{"id": 899, "name": "a.txt", "isDeleted": True, "description": "gone"}])
            out = _text()

        assert out["isDeleted"] is True and out["text"] == "gone"

    def test_entity_files_404_record_not_found(self, client):
        with respx.mock:
            respx.get(f"{REST}/entityFiles/ClientCorporation/10666").mock(
                return_value=httpx.Response(404, json={"errorMessage": "Entity not found."})
            )
            out = _text()

        assert out["error"] == "record_not_found"

    def test_non_404_with_404_in_body_is_uniform_error(self, client):
        with respx.mock:
            respx.get(f"{REST}/entityFiles/ClientCorporation/10666").mock(
                return_value=httpx.Response(500, json={"errorMessage": "id 404 broke"})
            )
            raw = server.get_file_text("ClientCorporation", 10666, 899)

        assert raw.startswith("ERROR: ")
        assert "record_not_found" not in raw

    def test_no_entity_get_call(self, client):
        with respx.mock(assert_all_called=False) as router:
            files = router.get(f"{REST}/entityFiles/ClientCorporation/10666").mock(
                return_value=httpx.Response(200, json={"EntityFiles": [{"id": 899, "description": "t"}]})
            )
            other = router.route(host="rest99.bullhornstaffing.com").mock(
                return_value=httpx.Response(500)
            )
            _text()

        assert files.call_count == 1
        assert other.call_count == 0

    def test_lead_refused(self, client):
        out = _text(entity="Lead")

        assert out["error"] == "unsupported_entity"
        assert "leads" in out["message"]

    def test_unknown_entity_refused(self, client):
        out = _text(entity="Note")

        assert out["error"] == "unsupported_entity"

    def test_empty_description_note(self, client):
        with respx.mock:
            _entity_files([{"id": 899, "name": "pic.png", "description": None}])
            out = _text()

        assert out["text"] == ""
        assert out["length"] == 0 and out["next_offset"] is None
        assert "no text" in out["note"]

    def test_bullhorn_error_uniform_surface(self, client):
        with respx.mock:
            respx.get(f"{REST}/entityFiles/ClientCorporation/10666").mock(
                return_value=httpx.Response(403, json={"errorMessage": "nope"})
            )
            raw = server.get_file_text("ClientCorporation", 10666, 899)

        assert raw.startswith("ERROR: ")

    def test_text_not_capped(self, client):
        with respx.mock:
            _entity_files([{"id": 899, "name": "a.txt", "description": LONG}])
            out = _text()

        assert out["text"] == LONG
        assert "description_truncated" not in out

    def test_not_in_tool_entity_map(self):
        from bullhorn_mcp.descriptions import TOOL_ENTITY_MAP

        assert "get_file_text" not in TOOL_ENTITY_MAP



# ===== T46.3 box always offered, T46.4 next_steps, T46.6 hint, T46.7 URI =====


BASE = {"MCP_BASE_URL": "https://mcp.example.com"}
NEW_URI = "ui://bullhorn/upload-box.html"


@pytest.fixture(autouse=True)
def _reset_ui_log_set(clean_upload_store):
    server._UI_LOGGED_SESSIONS.clear()
    yield
    server._UI_LOGGED_SESSIONS.clear()


def _request(filename="Jane_Doe_CV.pdf", entity=None, entity_id=None, ui=False):
    """ui=None leaves _client_supports_ui unpatched (it then reads the faked context)."""
    with _http_as(), patch.dict("os.environ", BASE):
        if ui is None:
            return json.loads(server.request_file_upload(filename, entity, entity_id))
        with patch.object(server, "_client_supports_ui", return_value=ui):
            return json.loads(server.request_file_upload(filename, entity, entity_id))


def _fake_ctx(session_id, supports=True):
    ctx = Mock()
    ctx.session_id = session_id
    ctx.client_supports_extension.return_value = supports
    return ctx


def _ui_lines(caplog):
    return [r for r in caplog.records if r.getMessage().startswith("client advertises MCP Apps")]


class TestBoxAlwaysOffered:
    @pytest.mark.parametrize("ui", [True, False])
    def test_next_steps_offer_box_whatever_client_advertises(self, ui):
        data = _request(ui=ui)

        assert f"show_upload_box(upload_id='{data['upload_id']}')" in data["next_steps"][2]

    def test_stop_sentence_follows_box_sentence(self):
        text = _request()["next_steps"][2]

        assert text.index("show_upload_box(") < text.index("If no box appears")
        assert text.index("If no box appears") < text.index("stop")
        assert "do not curl the old one afterwards" in text
        assert "base64" in text

    def test_ui_support_logged_once_per_session(self, caplog):
        with caplog.at_level(logging.INFO, logger="bullhorn_mcp.server"), \
             patch.object(server, "get_context", return_value=_fake_ctx("s1", True)):
            _request(ui=None)
            _request(ui=None)
        assert [r.getMessage() for r in _ui_lines(caplog)] == ["client advertises MCP Apps: True"]

        caplog.clear()
        with caplog.at_level(logging.INFO, logger="bullhorn_mcp.server"), \
             patch.object(server, "get_context", return_value=_fake_ctx("s2", False)):
            _request(ui=None)
        assert [r.getMessage() for r in _ui_lines(caplog)] == ["client advertises MCP Apps: False"]

    def test_ui_support_without_context_keyed_no_session(self, caplog):
        with caplog.at_level(logging.INFO, logger="bullhorn_mcp.server"), \
             patch.object(server, "get_context", side_effect=RuntimeError("no ctx")):
            _request(ui=None)
            _request(ui=None)
        assert len(_ui_lines(caplog)) == 1
        assert server._UI_LOGGED_SESSIONS == {"no-session"}

    def test_ui_support_log_has_no_token_or_identity(self, caplog):
        with caplog.at_level(logging.INFO, logger="bullhorn_mcp.server"), \
             patch.object(server, "get_context", return_value=_fake_ctx("sess-secret-123")):
            data = _request(filename="Jane_Doe_CV.pdf", ui=None)
        token = data["upload_url"].rsplit("/", 1)[-1]
        lines = _ui_lines(caplog)
        assert len(lines) == 1
        text = lines[0].getMessage()
        for banned in (token, "sess-secret-123", "user-a", "Jane_Doe", data["upload_id"]):
            assert banned not in text

    def test_ui_support_log_set_bounded(self):
        for i in range(server._UI_LOGGED_MAX):
            server._UI_LOGGED_SESSIONS.add(f"s{i}")
        assert len(server._UI_LOGGED_SESSIONS) == server._UI_LOGGED_MAX
        with patch.object(server, "get_context", return_value=_fake_ctx("fresh")):
            server._log_ui_support_once()
        assert server._UI_LOGGED_SESSIONS == {"fresh"}

    def test_session_id_stable_across_calls_in_real_session(self):
        """FastMCP 3.2.x: get_context().session_id is the same on two calls in one client session."""
        import fastmcp
        from fastmcp.server.dependencies import get_context

        m = fastmcp.FastMCP("probe")

        @m.tool()
        def sid() -> str:
            return get_context().session_id

        async def run():
            async with fastmcp.Client(m) as c:
                a = (await c.call_tool("sid", {})).data
                b = (await c.call_tool("sid", {})).data
            return a, b

        a, b = asyncio.run(run())
        assert a == b


class TestNextStepsFollowHintAndExtension:
    def test_joborder_hint_docx_no_cv_text(self):
        data = _request("Spec.docx", "JobOrder", 51437)
        step = data["next_steps"][1]

        assert "parse_cv" not in step and "create_candidate_from_cv" not in step and "attach_cv" not in step
        assert f"attach_file(entity='JobOrder', entity_id=51437, upload_id='{data['upload_id']}', type?, description?)" in step
        assert f"get_file_upload(upload_id='{data['upload_id']}')" in step

    def test_png_no_hint_no_cv_text(self):
        step = _request("photo.png")["next_steps"][1]

        assert "parse_cv" not in step
        assert "attach_file(entity, entity_id, upload_id=" in step

    def test_docx_no_hint_keeps_cv_path(self):
        step = _request("Jane.docx")["next_steps"][1]

        assert "parse_cv(" in step and "create_candidate_from_cv(" in step and "attach_cv(" in step
        assert "attach_file(" in step

    def test_docx_candidate_hint_keeps_cv_path(self):
        step = _request("Jane.docx", "Candidate", 173063)["next_steps"][1]

        assert "parse_cv(" in step and "attach_cv(" in step

    def test_eml_candidate_hint_no_cv_text(self):
        step = _request("mail.eml", "Candidate", 173063)["next_steps"][1]

        assert "parse_cv" not in step
        assert "attach_file(entity='Candidate', entity_id=173063, upload_id=" in step

    @pytest.mark.parametrize(
        "filename,entity,entity_id,cv_text,named",
        [
            ("Spec.docx", "JobOrder", 51437, False, "entity='JobOrder', entity_id=51437"),
            ("photo.png", None, None, False, "attach_file(entity, entity_id,"),
            ("Jane.pdf", None, None, True, "attach_file(entity, entity_id,"),
            ("Jane.pdf", "Candidate", 5, True, "attach_file(entity, entity_id,"),
        ],
    )
    def test_show_upload_box_received_hint_same_rule(self, filename, entity, entity_id, cv_text, named):
        with _http_as(), patch.dict("os.environ", BASE):
            upload_id, token, _e = server.upload_store.create("user-a", filename, entity, entity_id)
            content = b"%PDF-1.4 x" if filename.endswith("pdf") else b"x"
            server.upload_store.redeem(token, filename, content)
            body = json.loads(server.show_upload_box(upload_id))

        assert body["error"] == "upload_already_received"
        assert ("parse_cv(" in body["hint"]) is cv_text
        assert named in body["hint"]
        # The upload is already received: no "check status is 'received'" step.
        assert "get_file_upload" not in body["hint"]


class TestUnsupportedTypeHint:
    def test_unsupported_file_type_hint_does_not_repeat_list(self):
        data = _request("notes.md")

        assert data["error"] == "unsupported_file_type"
        assert data["hint"] == (
            "Use one of the allowed types listed above, or convert the file (for example a .md file to .txt)."
        )
        assert "pdf" in data["message"]
        assert "pdf" not in data["hint"]


class TestBoxUriRenamed:
    def test_upload_box_uri_renamed(self):
        assert server._UPLOAD_BOX_URI == NEW_URI
        assert "cv-upload-box" not in server._UPLOAD_BOX_URI

    def test_tool_meta_and_result_meta_carry_new_uri(self):
        import fastmcp

        tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
        assert tools["show_upload_box"].meta == {"ui": {"resourceUri": NEW_URI}}

        with _http_as(), patch.dict("os.environ", BASE):
            upload_id, _t, _e = server.upload_store.create("user-a", "Jane.pdf", None)

            async def call():
                async with fastmcp.Client(server.mcp) as c:
                    return await c.call_tool("show_upload_box", {"upload_id": upload_id})

            result = asyncio.run(call())
        assert result.meta == {"ui": {"resourceUri": NEW_URI}}

    def test_resource_read_log_names_new_uri(self, caplog):
        with caplog.at_level(logging.INFO, logger="bullhorn_mcp.server"):
            asyncio.run(server.mcp.read_resource(NEW_URI))

        assert any(r.getMessage() == f"MCP App resource read: {NEW_URI}" for r in caplog.records)

    def test_upload_box_html_app_name(self):
        from importlib import resources

        html = resources.files("bullhorn_mcp").joinpath("upload_box.html").read_text(encoding="utf-8")
        assert 'name: "bullhorn-upload-box"' in html
        assert "bullhorn-cv-upload-box" not in html



# ===== T46.5 attach reporting and T46.6 same-name wording =====



@pytest.mark.usefixtures("clean_upload_store")
class TestAttachCvFileHasType:
    @pytest.mark.parametrize(
        "path",
        ["create", "attach_new", "attach_already_attached", "created_new", "created_already_attached"],
    )
    def test_attach_cv_file_has_type(self, stack, path):
        existing = {"firstName": "Jane", "lastName": "Doe"}
        if path == "create":
            upload_id = _upload_with_parse(PARSE)
            data = stack(_Bullhorn(), server.create_candidate_from_cv, upload_id=upload_id)
        elif path == "attach_new":
            data, _ = _attach_cv(stack, _Bullhorn(existing=existing))
        elif path == "attach_already_attached":
            upload_id = _upload_with_parse(PARSE)
            server.upload_store.mark_attached(upload_id, 77, "Candidate", CID)
            data, _ = _attach_cv(stack, _Bullhorn(existing=existing), upload_id=upload_id)
        else:
            upload_id = _upload_with_parse(PARSE)
            server.upload_store.mark_created(upload_id, CID)
            if path == "created_already_attached":
                server.upload_store.mark_attached(upload_id, 77, "Candidate", CID)
            data = stack(_Bullhorn(), server.attach_cv, candidate_id=CID, upload_id=upload_id)

        assert data["written"]["file"]["type"] == "Original CV"
        assert data["written"]["file"]["file_id"] == 77
        assert data["written"]["file"].get("already_attached", False) is path.endswith("already_attached")


@pytest.mark.usefixtures("clean_upload_store")
class TestAttachFileReporting:
    def test_attach_file_echoes_description(self, fstack):
        data, _ = _attach_file(fstack, _FileBullhorn(), description="  Signed copy  ")

        assert data["description"] == "Signed copy"

    @pytest.mark.parametrize("kwargs", [{"description": "   "}, {}])
    def test_attach_file_blank_description_echoed_null(self, fstack, kwargs):
        data, _ = _attach_file(fstack, _FileBullhorn(), **kwargs)

        assert data["attached"] is True
        assert "description" in data and data["description"] is None

    def test_same_name_warning_one_id_singular(self, fstack):
        bh = _FileBullhorn(files=[{"id": 11, "name": "JD.docx", "isDeleted": False}])
        data, _ = _attach_file(fstack, bh)

        assert "(file id 11)" in data["warnings"][0]
        assert "file ids" not in data["warnings"][0]

    def test_same_name_warning_two_ids_plural(self, fstack):
        bh = _FileBullhorn(files=[
            {"id": 11, "name": "JD.docx", "isDeleted": False},
            {"id": 12, "name": "jd.docx", "isDeleted": False},
        ])
        data, _ = _attach_file(fstack, bh)

        assert "(file ids 11, 12)" in data["warnings"][0]


# ===== T46.8 end to end across T46.1 to T46.7 =====

JD_TEXT = "".join(f"Line {i:05d} of the Finance Manager job description. " for i in range(600))  # ~31k chars


class _StatefulFileBullhorn(_FileBullhorn):
    """_FileBullhorn that remembers the PUT file, returns it under the JobOrder's fileAttachments, and
    serves it from /entityFiles with Bullhorn's extracted text as its description (CR50 F2 source)."""

    def __call__(self, request):
        path = request.url.path.split("/rest-services/abc123", 1)[1]
        parts = path.strip("/").split("/")
        if request.method == "PUT" and parts[0] == "file":
            self.files = [{"id": 4321, "name": "Finance Manager JD.docx", "type": "Job Description",
                           "description": JD_TEXT}]
        if (request.method == "GET" and parts[0] == "entity" and len(parts) == 3
                and "fileAttachments" in (request.url.params.get("fields") or "")):
            self.requests.append((request.method, path, request))
            return httpx.Response(200, json={"data": {
                "id": int(parts[2]), "title": "Finance Manager",
                "fileAttachments": {"total": len(self.files), "data": [dict(f) for f in self.files]},
            }})
        return super().__call__(request)


@pytest.mark.usefixtures("clean_upload_store")
class TestCr50EndToEnd:
    @pytest.fixture
    def http(self):
        from starlette.testclient import TestClient
        return TestClient(server.mcp.http_app())

    def test_docx_jd_on_job_upload_attach_read_capped_then_full_text(self, fstack, http):
        bh = _StatefulFileBullhorn()

        # F3 + F1: a JobOrder-hinted docx gets no CV text, and the box step is always offered.
        with patch.dict("os.environ", {"MCP_BASE_URL": "https://mcp.example.com"}):
            ticket = fstack.json(bh, server.request_file_upload, filename="Finance Manager JD.docx",
                                 entity="JobOrder", entity_id=51437)
        steps = " ".join(ticket["next_steps"])
        assert "parse_cv" not in steps and "attach_cv" not in steps
        assert "attach_file(entity='JobOrder', entity_id=51437" in steps
        assert "show_upload_box" in steps

        token = ticket["upload_url"].rsplit("/upload/", 1)[1]
        resp = http.post(f"/upload/{token}", files={"file": ("x-Finance Manager JD.docx", b"PK\x03\x04 jd")})
        assert resp.status_code == 200

        # F5: attach_file echoes the description it sent.
        attached = fstack.json(bh, server.attach_file, entity="JobOrder", entity_id=51437,
                               upload_id=ticket["upload_id"], description="  Signed JD  ")
        assert attached["attached"] is True and attached["description"] == "Signed JD"

        # F2: a read returns the file with a 500-character preview, flagged, with its full length.
        job = fstack.json(bh, server.get_job, job_id=51437, fields="id,title,fileAttachments(id,name,description)")
        row = job["fileAttachments"]["data"][0]
        assert len(row["description"]) == 500 and row["description"] == JD_TEXT[:500]
        assert row["description_truncated"] is True and row["description_length"] == len(JD_TEXT)

        # F2: get_file_text returns the whole text in two pages.
        page1 = fstack.json(bh, server.get_file_text, entity="JobOrder", entity_id=51437, file_id=4321)
        assert page1["length"] == len(JD_TEXT) and page1["next_offset"] == 20000
        page2 = fstack.json(bh, server.get_file_text, entity="JobOrder", entity_id=51437, file_id=4321,
                            offset=page1["next_offset"])
        assert page2["next_offset"] is None
        assert page1["text"] + page2["text"] == JD_TEXT
