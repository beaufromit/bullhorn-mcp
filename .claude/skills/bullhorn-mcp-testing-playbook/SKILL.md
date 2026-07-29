---
name: bullhorn-mcp-testing-playbook
description: Load this skill BEFORE writing, modifying, or debugging any test in bullhorn-mcp-python. Triggers include adding tests for a new or changed MCP tool; a test that passes when it should fail (or fails mysteriously); choosing between respx and unittest.mock; a Mock's return_value being ignored; identity or client state leaking between tests; an isDeleted-clause assertion behaving oddly; async tests not running; or a review finding about test coverage or test validity. Provides the mocking architecture with a decision rule, the eight fixture and mock traps with locations, the payload-assertion law with worked skeletons, the anti-patterns reviews actually flagged, the per-file test inventory, and the new-tool test checklist.
---

# Bullhorn MCP Testing Playbook

How testing works in this repo and how to add tests that survive the adversarial review. All facts verified against the repo as of 2026-07-03 (v0.0.46, 648 tests passing, `648 passed in 41.15s`).

Jargon used throughout, defined once:

- **CR**: change request, a `CRnn.md` plan file in the repo root (see bullhorn-mcp-change-control).
- **respx**: a pytest library that mocks `httpx` at the HTTP-transport boundary; you register routes and it intercepts real client code's requests.
- **envelope**: the `{"data": [...], "pagination": {total, start, count, has_more, next_start}}` shape user-facing list tools return, built by `_paginate_envelope` (src/bullhorn_mcp/server.py:269 as of 2026-07-03).
- **autouse fixture**: a pytest fixture applied to every test in its scope without being named in the test signature.
- **dedup guard**: the pre-create duplicate check on create tools, bypassable with `force=True`.
- **enrichment**: the startup pass that appends live field metadata to tool docstrings (src/bullhorn_mcp/descriptions.py).
- **isDeleted clause**: the `AND isDeleted:0` (Lucene full-text syntax) or `AND isDeleted=false` (SQL-style) filter the client auto-appends to searches and queries.
- **picklist**: a Bullhorn field with a fixed set of `{value, label}` options served by `/meta`.

Run everything from the repo root. Full suite: `.venv/bin/pytest`. Install and pytest basics live in bullhorn-mcp-build-and-env.

## 1. Mocking architecture and the decision rule

The review protocol's standing consistency check (`.claude/commands/review.md`, lines 57-58 as of 2026-07-03) is: "respx for HTTP mocking, unittest.mock for server-layer DI". In practice there are three sanctioned patterns. Mock at the boundary directly below the code under test:

| Code under test | Pattern | Files that use it |
|---|---|---|
| `BullhornAuth`, `BullhornClient` request building | respx routes; real client object; assert on captured `route.calls[n].request` | tests/test_auth.py, tests/test_client.py |
| `BulkImporter`, `identity.resolve_caller` | real `BullhornClient` over respx (these modules' logic depends on real request behavior) | tests/test_bulk.py, tests/test_identity.py |
| `BullhornMetadata`, `descriptions.py` | plain `unittest.mock.Mock` client (no HTTP layer needed) | tests/test_metadata.py, tests/test_descriptions.py |
| Server tools (read paths, validation, guards) | `Mock` client injected via `with patch.object(server, "get_client", return_value=mock_client):` | tests/test_server.py (the bulk of it) |
| Server write paths end to end (payload assembly across label resolution) | hybrid: REAL `BullhornClient` + REAL `BullhornMetadata` over respx, injected via the same `get_client` patch | tests/test_server.py E2E classes (21 inline `import respx` sites as of 2026-07-03) |

Decision rule when adding a test:

1. Testing URL/body/header construction or retry behavior: respx, real client.
2. Testing a tool's branching, validation, guards, envelope math: `Mock` client + `patch.object(server, "get_client", ...)`.
3. Testing that a WRITE tool's outgoing payload is exactly right after aliasing, stripping, owner injection, or defaults: hybrid E2E (section 3).

Mixing these wrongly (for example respx-mocking Bullhorn while also Mock-patching the client, so no request ever fires) is itself a review finding under the test-validity check.

## 2. The eight traps (each has bitten a real sprint)

| # | Trap | Location (as of 2026-07-03) | Story in one line |
|---|---|---|---|
| 1 | `rest_url` must have NO trailing slash in every session fixture | tests/conftest.py:28 (`# No trailing slash` comment); tests/test_bulk.py:21-22 defines its OWN private `_Session`/`_Auth` with the same rule | `BullhornClient._request` concatenates `f"{session.rest_url}{endpoint}"`, so a trailing slash produces double-slash URLs that miss every respx route |
| 2 | `_wrap_with_meta` delegation in the `mock_client` fixture | tests/test_server.py:13-41 | `search_with_meta.side_effect` delegates to the bare `search` mock at call time; see rules below |
| 3 | Autouse state-reset fixtures | see table in 2.1 | forgetting them leaks lazy globals or cached identities across tests |
| 4 | Patch the USE site, not the definition site | all patches are `patch("bullhorn_mcp.identity.get_access_token", ...)` (tests/test_identity.py, tests/test_server.py:4103 etc.) | `identity.py` imports `get_access_token` at module level, so patching the fastmcp definition site does nothing (Sprint 16 review learning, recorded in IMPLEMENTATION-PLAN.md) |
| 5 | Token-mock claims must include `"sub"` | tests/test_identity.py:6-8 header comment | the identity cache is keyed by the Entra `sub` claim; a token without it raises `IdentityResolutionError` before your test's real subject runs (`test_resolve_caller_no_sub_claim` is the only intentional omission) |
| 6 | The CR33 `/meta` gotcha | tests/test_server.py:4909 `test_create_contact_dedup_excludes_deleted` | `_entity_has_isdeleted` fetches `/meta/{entity}`; with NO respx `/meta` route the fetch raises, the `except Exception: return True` fallback fires, and the clause is appended anyway, so your isDeleted assertion passes for the wrong reason. To genuinely test the metadata gate, register `/meta/{entity}` WITH (or without) an `isDeleted` field, as that test does |
| 7 | `MCP_TRANSPORT` pinning around module reloads | tests/test_server.py:3692-3694 | tests that `importlib.reload` the server after touching HTTP mode must restore under `patch.dict(os.environ, {"MCP_TRANSPORT": "stdio"})`, or a stale `MCP_TRANSPORT=http` in the env makes the reload demand Entra vars and crash (Sprint 16 review learning) |
| 8 | Async tests need explicit markers | markers on TestCVUploadEndpoint (9 tests) and one test in TestSprint15HttpTransport in tests/test_server.py; TestEnrichToolDescriptions (10 tests) in tests/test_descriptions.py | pyproject.toml sets no `asyncio_mode`, so pytest-asyncio (1.3.0 installed) runs in its default strict mode: an `async def` test without `@pytest.mark.asyncio` is silently skipped or errors, never quietly passes |

### 2.1 Autouse fixtures and what each resets

| Fixture | Scope | Location (as of 2026-07-03) | Resets |
|---|---|---|---|
| `reset_client` | every test in test_server.py (module-level autouse) | tests/test_server.py:44 | `server._client`, `server._metadata`, `server._shortlist_status_validated`, `server._valid_note_actions` (the lazy globals behind `get_client`/`get_metadata` and the one-shot validation flags) |
| `reset_cache` | every test in test_identity.py | tests/test_identity.py:22 | the per-`sub` identity cache via `identity._reset_caller_cache()` |
| `reset_identity_cache` | class-level autouse on the Sprint 17/18 owner-stamping classes | tests/test_server.py:3750, 3898, 3983, 4038 | same cache, for server-layer tests that exercise `resolve_caller` |
| `clear_candidate_required` | class-level autouse on `TestCreateCandidate` | tests/test_server.py:5042 | patches `bullhorn_mcp.server.get_candidate_required` to `[]` so the `BULLHORN_CANDIDATE_REQUIRED` default shipped uncommented in .env.example does not break tests that omit those fields |

If you add a test class that calls `resolve_caller` or reads candidate-required config, copy the relevant class-level fixture into it.

### 2.2 `_wrap_with_meta` rules (trap 2 in detail)

The shared `mock_client` fixture (tests/test_server.py:13-41) sets `side_effect` on `search_with_meta`, `query_with_meta`, and `get_association_with_meta` to a wrapper that, at call time, reads the bare mock (`client.search` etc.) and wraps its `return_value` in a `{data, total, start, count}` dict. Consequences:

- Setting `client.search.return_value = [...]` auto-propagates into the envelope. This is the normal way to stub list-tool data.
- Setting `client.search_with_meta.return_value = {...}` directly does NOTHING until you also set `client.search_with_meta.side_effect = None`, because Mock gives `side_effect` precedence. Existing examples with the in-code comment "Clear fixture side_effect so return_value takes precedence": tests/test_server.py:337, 368, 695, 6107, 6638.
- To simulate an API error in a list tool, set the exception on the BARE mock: `client.search.side_effect = BullhornAPIError("...")`. The wrapper re-raises `BaseException` side effects (tests/test_server.py:97 does exactly this).
- Callable side effects on the bare mock are invoked with the call args (`return se(*args, **kwargs)`). This was a review M2: the wrapper originally did `raise se` for callables, a TypeError bomb, fixed in commit a579c8e.
- `TestSearchEmails` carries its own copy of this wrapper (around tests/test_server.py:361); if you change the shared one, check for the duplicate.

## 3. THE PAYLOAD-ASSERTION LAW (the how)

Every write path gets a test that captures the EXACT outgoing payload. Method-argument assertions alone were proven insufficient in CR6: `title` was being injected somewhere in a 5-layer path and only the raw HTTP body revealed it. CR6.md (line 34) mandates: "a mock that captures the raw HTTP request body, not just the method arguments". Enforcement severity (untested write-path logic in server.py is CRITICAL) is owned by bullhorn-mcp-review-protocol; this section owns how to comply.

Three tiers, use the deepest one that covers the logic you added:

| Tier | When | Mechanism | Existing example |
|---|---|---|---|
| Client layer, raw HTTP body | you changed `client.py` request/body building | respx route, then `json.loads(route.calls[0].request.content)` | tests/test_client.py:337+ (`TestCreateEntity`), ten more `route.calls[0].request.content` sites |
| Server layer, exact call | you changed a tool's payload assembly and the client boundary is trusted | `mock_client.create.assert_called_once_with("Entity", {exact dict})`, never partial key checks | tests/test_server.py:1655 (`update.assert_called_once_with("JobOrder", 12345, {"title": "Senior Engineer"})`) |
| E2E raw body through real client + real metadata | payload assembly spans label resolution, aliases, env defaults, owner injection, or stripping | real `BullhornClient` and `BullhornMetadata` over respx, injected via `patch.object(server, "get_client", ...)`, capture the PUT body, assert `captured["body"] == {exact dict}` | tests/test_server.py:1757 `test_e2e_create_job_minimal` |

### Worked skeleton: E2E raw-body test for a new write tool

Adapt from `test_e2e_create_job_minimal`. This asserts the body is EXACTLY the expected keys, which is what catches injection:

```python
class TestMyNewToolE2E:
    @pytest.fixture
    def mock_auth(self, mock_session):
        from unittest.mock import Mock, PropertyMock
        from bullhorn_mcp.auth import BullhornAuth
        auth = Mock(spec=BullhornAuth)
        type(auth).session = PropertyMock(return_value=mock_session)
        return auth

    def test_e2e_payload_exact(self, mock_auth, mock_session):
        import httpx, respx
        from bullhorn_mcp.client import BullhornClient
        from bullhorn_mcp.metadata import BullhornMetadata

        captured = {}

        def capture_put(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"changedEntityId": 1, "changeType": "INSERT"})

        real_client = BullhornClient(mock_auth)
        real_metadata = BullhornMetadata(real_client)

        with respx.mock:
            respx.get(f"{mock_session.rest_url}/meta/MyEntity").mock(
                return_value=httpx.Response(200, json={"entity": "MyEntity", "fields": []})
            )
            respx.put(f"{mock_session.rest_url}/entity/MyEntity").mock(side_effect=capture_put)
            respx.get(f"{mock_session.rest_url}/entity/MyEntity/1").mock(
                return_value=httpx.Response(200, json={"data": {"id": 1}})
            )  # create() always does a follow-up GET; without this route the write "fails"

            with patch.object(server, "get_client", return_value=real_client), \
                 patch.object(server, "get_metadata", return_value=real_metadata), \
                 patch.object(server, "resolve_caller", return_value={"id": 42}):
                result = server.my_new_tool(...)

        assert captured["body"] == {"expectedKey": "expectedValue", "owner": {"id": 42}}
```

Notes: `mock_session` comes from tests/conftest.py (no trailing slash); the follow-up GET route is mandatory because `create()`/`update()` never return the POST response; equality (`==`) on the whole body, not `in` checks.

## 4. Test-quality anti-patterns reviews actually flagged

Every row is a real finding; do not repeat them.

| Anti-pattern | What it looks like | Real incident (verify command in section 7) |
|---|---|---|
| Vacuous assertion | `assert X or True`, or an assertion deleted instead of updated | Sprint 17 review: `test_create_contact_auto_owner_payload_no_leak` contained a vacuous `or True`; another test had both assertions dropped rather than updated (IMPLEMENTATION-PLAN.md, Sprint 17 review cycle note) |
| Masking mock / one-leg test | a mock's return value routes execution away from the leg the test claims to cover | commit 58684ff: `test_find_duplicate_contacts_company_search_excludes_deleted` mocked the company search to return nothing, so the ClientContact search leg it was named for never executed; fix was to return an exact-match company so both legs fire |
| Loose substring URL check | `assert "sender.id" in url` proves nothing about the value | Sprint 25 M1: tightened to `assert "sender.id%3A1" in url`; the identity tests use `parse_qs` on the parsed URL instead of full-URL substrings for the same reason |
| Untested write path | new payload-assembly logic with no payload assertion | commit d8c5903 C1: `create_candidate_from_cv` source stamping shipped untested; auto-CRITICAL under the review's standing checks |
| Mocking the thing under test | patching the very function whose behavior the test claims to verify | standing test-validity rule in `.claude/commands/review.md` lines 55-56: "A test that mocks the thing it is supposed to test is not a test" |
| Partial payload checks on writes | `assert "name" in body` instead of asserting the whole dict | the CR6 lesson; extra injected keys pass every `in` check |
| Asserting via the fallback | isDeleted-clause assertions that pass only because the `/meta` fetch failed | trap 6 above; register the `/meta` route or you are testing the exception handler |

## 5. Per-file test inventory

As of 2026-07-03 (v0.0.46), 648 tests collected, all passing. Verify with `.venv/bin/pytest --collect-only -q | tail -1`.

| File | Tests | Covers | Dominant mock style |
|---|---|---|---|
| tests/test_server.py | 377 (62 top-level classes) | all 38 MCP tools, guards, envelopes, transport, main() | Mock client via `get_client` patch; hybrid respx for E2E write paths |
| tests/test_client.py | 103 | request building, create/update/add_note, isDeleted gate, multipart, associations | respx |
| tests/test_descriptions.py | 36 | enrichment, TOOL_ENTITY_MAP consistency | Mock client, async (strict markers) |
| tests/test_metadata.py | 30 | label resolution, FIELD_ALIASES precedence, caching | Mock client |
| tests/test_fuzzy.py | 29 | normalization, scoring thresholds | pure functions, no mocks |
| tests/test_bulk.py | 18 | BulkImporter dedup and error halting | real client over respx (private `_Session`/`_Auth`) |
| tests/test_auth.py | 13 | OAuth flow, regional redirects, refresh | respx |
| tests/test_identity.py | 13 | resolve_caller, sub-keyed cache | real client over respx + `get_access_token` patch |
| tests/test_candidate_config.py | 10 | env-driven candidate config | monkeypatch env |
| tests/test_joborder_config.py | 10 | env-driven job config | monkeypatch env |
| tests/test_config.py | 6 | BullhornConfig.from_env | monkeypatch env |
| tests/test_shortlist_config.py | 3 | shortlist status env var | monkeypatch env |

pytest config (pyproject.toml `[tool.pytest.ini_options]`): `testpaths=["tests"]`, `pythonpath=["src"]`. Tests import from `src/` without an editable install.

## 6. Checklist: adding tests for a new tool

Do all that apply; the review will check each.

- [ ] **Registration**: add an `assert "my_tool" in tools` line to `TestMCPServerSetup.test_server_has_tools` (tests/test_server.py:2639 as of 2026-07-03). It uses `asyncio.run(server.mcp.list_tools())` because FastMCP 3.x removed `_tool_manager`.
- [ ] **Happy path** with the shared `mock_client` fixture and `patch.object(server, "get_client", return_value=mock_client)`.
- [ ] **Envelope assertions** for list-shaped tools: `json.loads(result)` then assert `data` plus the `pagination` keys (`total`, `start`, `count`, `has_more`, `next_start`), and that `start`/`count` are forwarded to the client (`call_args.kwargs["start"]`).
- [ ] **Query construction**: assert the exact Lucene query or SQL WHERE string via `call_args.kwargs`, e.g. `assert call_args.kwargs["where"] == "jobOrder.id=12345 AND status='Shortlisted'"`. Exact equality or exact-substring-with-value, never bare field-name substrings.
- [ ] **Error path**: set `BullhornAPIError` on the bare mock (`client.search.side_effect`, see section 2.2) and assert the result starts with `ERROR:`; validation failures assert the structured JSON `{"error": slug, ...}`.
- [ ] **Payload-assertion test** for any write path (section 3): exact `assert_called_once_with` at minimum, E2E raw body if payload assembly involves metadata, aliases, defaults, stripping, or owner injection.
- [ ] **Dedup and guard cases** where relevant: duplicate found blocks the write; `force=True` bypasses; guard-bypass attempt via a display label (the guard must fire AFTER label resolution) is rejected.
- [ ] **Injection guard**: if the tool interpolates a new parameter into a WHERE clause, add a single-quote rejection test (pattern: `test_invalid_status_returns_error`, added for CR33 M2).
- [ ] **isDeleted assertions**: if you assert clause presence/absence per entity, register the `/meta/{entity}` respx route explicitly (trap 6).
- [ ] **Docstring regression tests** where the docstring teaches field names: assert the bad example is absent and the good one present (pattern: tests/test_server.py:2987, the CR4 guards asserting `'"title": "CTO"' not in docstring`).
- [ ] **Enrichment mapping**: if the tool joins `TOOL_ENTITY_MAP`, the existing consistency test (tests/test_descriptions.py:355 area) asserts its entities are in `SUPPORTED_ENTITIES`; run test_descriptions.py after editing the map.
- [ ] **State fixtures**: copy `reset_identity_cache` into classes that hit `resolve_caller`; `clear_candidate_required` into candidate-create classes.
- [ ] **Full suite green**: `.venv/bin/pytest`. Record the new expected count per bullhorn-mcp-change-control.

## When NOT to use this skill

- Review severities, what counts as CRITICAL, the fix loop: bullhorn-mcp-review-protocol.
- Installing the venv, pytest invocation basics, dependency traps: bullhorn-mcp-build-and-env.
- What the invariants under test actually are (envelope math, guards, isDeleted gate): bullhorn-mcp-architecture-contract.
- Which incident originally produced a trap: bullhorn-mcp-failure-archaeology.
- Verifying real Bullhorn behavior before writing the test's expectations: bullhorn-mcp-live-api-method.
- Lucene/SQL syntax the assertions encode: bullhorn-mcp-query-and-entity-model.
- Triaging a live (non-test) failure: bullhorn-mcp-debugging-playbook.

## Provenance and maintenance

Re-verify each claim category before trusting it in a future session:

- Total and per-file test counts: `.venv/bin/pytest --collect-only -q | tail -1` and `.venv/bin/pytest --collect-only -q | grep -oP '^tests/test_\w+\.py' | sort | uniq -c`
- `_wrap_with_meta` wrapper and `mock_client` fixture: `grep -n "_wrap_with_meta" tests/test_server.py`
- `side_effect = None` override sites: `grep -n "side_effect = None" tests/test_server.py`
- Autouse fixture locations: `grep -n "autouse=True" tests/test_server.py tests/test_identity.py` and `grep -n "clear_candidate_required\|reset_identity_cache" tests/test_server.py`
- Trailing-slash rule: `grep -n "No trailing slash" tests/conftest.py` and `grep -n "rest_url" tests/test_bulk.py`
- Patch-the-use-site convention: `grep -rn "get_access_token" tests/ | grep patch`
- `"sub"` claim requirement: `sed -n '1,12p' tests/test_identity.py`
- CR33 /meta gotcha test: `grep -n "test_create_contact_dedup_excludes_deleted" tests/test_server.py`
- MCP_TRANSPORT pinning: `grep -n "MCP_TRANSPORT=stdio" -r tests/ IMPLEMENTATION-PLAN.md` and `sed -n '3690,3696p' tests/test_server.py`
- Async marker inventory: `awk '/^class /{cls=$2} /pytest.mark.asyncio/{print cls}' tests/test_server.py tests/test_descriptions.py | sort | uniq -c`; asyncio mode: `grep -n asyncio_mode pyproject.toml` (absent means strict default)
- Payload-assertion law origin: `grep -n "raw HTTP" CR6.md` and `grep -n "payload-assertion" .claude/commands/review.md`
- Raw-body assertion sites: `grep -n "request.content" tests/test_client.py tests/test_server.py`
- Anti-pattern incidents: `git show 58684ff --stat`, `git show a579c8e`, `git show d8c5903 --stat`, `grep -n "or True" IMPLEMENTATION-PLAN.md`, `grep -n "assertion too loose" IMPLEMENTATION-PLAN.md`
- Tool registration test: `grep -n "test_server_has_tools" tests/test_server.py`
- Helper locations (line numbers drift): `grep -n "_paginate_envelope\|def get_client" src/bullhorn_mcp/server.py`
