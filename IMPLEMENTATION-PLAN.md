# Implementation Plan: Bullhorn MCP Record Management Expansion

## PRD Validation Notes

All 10 functional requirements (FR-1 through FR-10) are covered by user stories US-1 through US-21. No user stories were found that implement features outside the stated requirements.

**Minor gap noted:** NFR-4 requires field label resolution in all tools that accept field names (including create operations). US-15 explicitly covers this for `update_record`, but US-1 and US-2 (create operations) have no acceptance criterion for label resolution. This is handled as an implementation note within Sprint 3, Sprint 4, and Sprint 6 tasks — label resolution via the metadata module will be applied consistently to create and update operations per NFR-4, without requiring a new user story.

**Sprint 14 completion note:** All 14 sprints (Sprints 1-7 original, Sprints 8-14 change requests) are complete. All FR-1 through FR-10, US-1 through US-21, and NFR-1 through NFR-7 are fully covered. One minor discrepancy: `find_duplicate_companies` accepts `website` and `phone` parameters (per FR-3's mention of "optionally other identifying fields") but these are not currently used in matching — results are based on name matching only. FR-3 does not mandate these parameters affect matching, so the behavior is acceptable.

**CR8 — new requirement:** CR8.md introduces HTTP transport for remote hosting, which has no equivalent in the original PRD. FR-11 (HTTP Transport Mode) and US-22 have been added to PRD.md to cover this requirement. Sprint 15 implements them.

---

## Current Status

| Sprint | Status | Summary |
|--------|--------|---------|
| Sprint 1 | **COMPLETE** | Convenience listing tools — 71 tests passing, tagged v0.0.1 |
| Sprint 2 | **COMPLETE** | Field Metadata and Label Resolution — 90 tests passing, tagged v0.0.2 |
| Sprint 3 | **COMPLETE** | Create ClientCorporation — 98 tests passing, tagged v0.0.3 |
| Sprint 4 | **COMPLETE** | Create ClientContact with Owner Resolution — 109 tests passing, tagged v0.0.4 |
| Sprint 5 | **COMPLETE** | Duplicate Detection — 149 tests passing, tagged v0.0.5 |
| Sprint 6 | **COMPLETE** | Update Records and Add Notes — 163 tests passing, tagged v0.0.6 |
| Sprint 7 | **COMPLETE** | Bulk Import — 177 tests passing, tagged v0.0.7 |
| Sprint 8 | **COMPLETE** | CR1: Fix title/occupation field mapping bug — 182 tests passing, tagged v0.0.8 |
| Sprint 9 | **COMPLETE** | CR2: Audit and fix auto-injected fields — 190 tests passing, tagged v0.0.9 |
| Sprint 10 | **COMPLETE** | CR3: Fix broken owner name resolution and department field leak — 195 tests passing, tagged v0.0.10 |
| Sprint 11 | **COMPLETE** | CR4: Fix incorrect title field in docstrings — 198 tests passing, tagged v0.0.11 |
| Sprint 12 | **COMPLETE** | CR6: Investigate and fix title field injection in update_record — 201 tests passing, tagged v0.0.12 |
| Sprint 13 | **COMPLETE** | CR7: Strip title from ClientContact write payloads with warning — 207 tests passing, tagged v0.0.13 |
| Sprint 14 | **COMPLETE** | CR5: Add duplicate check to create_contact before creation — 214 tests passing, tagged v0.0.14 |
| Sprint 15 | **COMPLETE** (4 tests regressed post-tag) | CR8: Add HTTP transport mode for remote hosting — tagged v0.0.15; 216/220 pass after post-sprint Entra OIDC commits |
| Sprint 16 | **COMPLETE** | Fix Sprint 15 test regressions + CR9: Identity resolution — 229 tests passing |
| Sprint 17 | **COMPLETE** | CR10: Owner stamping — auto-populate owner from authenticated user in create_contact / create_company — 244 tests passing |
| Sprint 18 | **COMPLETE** | CR11: Per-user identity cache — fix first-writer-wins bug for multi-user HTTP deployments — 248 tests passing |

### Sprint 15 post-tag regression note

After v0.0.15 was tagged, a series of "fixing OIDC scopes" commits changed how `_build_auth()` works: HTTP mode now validates Entra env vars at module import time and raises `ValueError` if they are absent. This broke 4 Sprint 15 tests:

| Failing test | Root cause |
|---|---|
| `test_server_has_tools` | FastMCP removed `_tool_manager._tools` — internal API changed |
| `test_main_http_transport` | `mcp.run()` now called with `host=` and `port=` kwargs; test expected only `transport=` |
| `test_fastmcp_port_configured_from_env` | FastMCP no longer exposes `mcp.settings.port` |
| `test_sprint15_e2e_http_mode_startup` | `importlib.reload` triggers `_build_auth()` which raises `ValueError` (Entra vars missing in test env) |

These are fixed as the first tasks in Sprint 16.

---

## Architecture Overview

### Existing modules (implemented)
- `src/bullhorn_mcp/config.py` — `BullhornConfig` dataclass with env loading
- `src/bullhorn_mcp/auth.py` — OAuth 2.0 flow with regional redirects, session refresh
- `src/bullhorn_mcp/client.py` — `BullhornClient` with `_request()` (params + json body, 200/201 success), `search()`, `query()`, `get()`, `get_meta()`, `create()`, `resolve_owner()`, `update()`, `add_note()`
- `src/bullhorn_mcp/metadata.py` — `BullhornMetadata` with `get_fields()`, `resolve_label_to_api()`, `resolve_api_to_label()`, `resolve_fields()`, session-level caching; `FIELD_ALIASES` constant for known metadata gaps (e.g. "job title" → `occupation` for ClientContact)
- `src/bullhorn_mcp/server.py` — MCP server with 16 tools: `list_jobs`, `list_candidates`, `list_contacts`, `list_companies`, `get_job`, `get_candidate`, `search_entities`, `query_entities`, `get_entity_fields`, `create_company`, `create_contact`, `find_duplicate_companies`, `find_duplicate_contacts`, `update_record`, `add_note`, `bulk_import`. Includes `get_client()` and `get_metadata()` helpers.
- `src/bullhorn_mcp/fuzzy.py` — Fuzzy string matching and confidence scoring

### New modules (implemented)
- `src/bullhorn_mcp/bulk.py` — BulkImporter with process(), _process_single_company(), _process_single_contact(), _resolve_or_create_company(), _build_summary()

### Existing modules extended
- `src/bullhorn_mcp/server.py` — Add `bulk_import` MCP tool (Sprint 7)

### Test files
- `tests/test_auth.py` — 13 tests (auth flow, regional servers)
- `tests/test_config.py` — 6 tests
- `tests/test_client.py` — 41 tests (search, query, get, pagination, create, update, add_note, resolve_owner, edge cases)
- `tests/test_metadata.py` — 21 tests (get_fields, label resolution, resolve_fields, FIELD_ALIASES, Sprint 8 alias, Sprint 9 payload audit, e2e)
- `tests/test_fuzzy.py` — 29 tests (normalize, score_company_match, score_contact_match, categorize_score, E2E)
- `tests/test_server.py` — 105 tests (all 16 tools + server setup + E2E tests Sprints 1–14)
- `tests/test_bulk.py` — 14 tests (company processing, contact processing, summary, E2E)
- **Total: 244 tests, all passing**

---

## Sprint 1: Convenience Listing Tools — COMPLETE

**User stories:** US-19, US-20, US-21
**Tag:** v0.0.1

**What was delivered:** Extended `DEFAULT_FIELDS` for `ClientContact` (added `owner`, `status`, `title`, `dateAdded`, `clientCorporation`) and `ClientCorporation` (added `dateAdded`). Added `list_contacts` and `list_companies` MCP tools in `server.py`, mirroring the existing `list_candidates`/`list_jobs` pattern. Both tools support optional `query`, `status`, `limit`, and `fields` parameters. All 71 tests pass (63 pre-existing + 8 new). Tests are in `test_server.py` (TestListContacts: 3 tests, TestListCompanies: 2 tests, TestSprint1E2E: 1 test) and `test_client.py` (2 default-fields assertions).

---

## Sprint 2: Field Metadata and Label Resolution — COMPLETE

**User stories:** US-17, US-18
**Tag:** v0.0.2

**What was delivered:** Created `BullhornMetadata` class (`metadata.py`) with session-level caching, bidirectional label/API-name resolution (`resolve_label_to_api`, `resolve_api_to_label`), and `resolve_fields()` for converting label-keyed dicts to API names. Added `get_entity_fields` MCP tool supporting full field listing and label/api_name lookup in either direction. Wired `_metadata` global and `get_metadata()` helper into `server.py`. Updated `reset_client` test fixture to also reset `_metadata`. Updated `test_server_has_tools` assertion to include all 9 tools (original 6 + `list_contacts`, `list_companies`, `get_entity_fields`). Updated MCP instructions string to reflect expanded capabilities. 90 tests passing (71 pre-existing + 14 new metadata tests + 5 new server tests).

### Tasks (completed)

#### T2.1 — Create `metadata.py` with `BullhornMetadata` class (DONE)
#### T2.2 — Add `get_entity_fields` MCP tool (DONE)
#### T2.3 — Wire `BullhornMetadata` into `get_client()` (DONE)
- Includes: `_metadata` global, `get_metadata()` helper, `reset_client` fixture update, `test_server_has_tools` assertion update, MCP instructions update.

### Sprint 2 End-to-End Tests (DONE)
- `tests/test_metadata.py::test_sprint2_e2e_full_resolution_cycle`

---

## Sprint 3: Create ClientCorporation

**Tag:** v0.0.3

**What was delivered:** Extended `_request()` with optional `json` parameter (forwarded on 401 retry) and now accepts both 200 and 201 as success codes. Added `create()` method to `BullhornClient` (PUT `/entity/{entity}`, then GET to return created record, returns `{changedEntityId, changeType, data}`). Added `create_company` MCP tool that resolves field labels via `get_metadata()` before calling `client.create("ClientCorporation", ...)`. Updated `test_server_has_tools` to assert `create_company` is registered. 98 tests passing (90 pre-existing + 4 new client tests + 4 new server tests).

**User stories:** US-1 (partial — company creation only)
**Goal:** Add `create()` method to `BullhornClient`. Add `create_company` MCP tool. Lay the foundation for all create/update operations by extending `_request()` to support JSON bodies.

### Tasks

#### T3.1 — Extend `_request()` to support JSON request bodies (DONE)
**File:** `src/bullhorn_mcp/client.py`

**Current state:** `_request()` signature is `(self, method, endpoint, params=None)`. It only passes `params` to `httpx.Client.request()` and only treats status 200 as success. It does not support sending a JSON body.

**Changes needed:**
- Add optional `json: dict | None = None` parameter to `_request()`.
- Pass `json=json` to `httpx.Client.request()` alongside existing `params`.
- Accept both 200 and 201 as success status codes. (Bullhorn typically returns 200 for PUT entity creates, but 201 should also be accepted for safety.)
- The 401 retry path must also forward the `json` parameter on retry.
- **Unit test:** `tests/test_client.py::test_request_with_json_body` — mock PUT endpoint, assert JSON body is sent correctly.
- **Unit test:** `tests/test_client.py::test_request_accepts_201_status` — mock endpoint returning 201, assert no error raised.

#### T3.2 — Add `create()` method to `BullhornClient` (DONE)
**File:** `src/bullhorn_mcp/client.py`
- `create(entity: str, data: dict) -> dict` — PUT to `/entity/{entity}`, sends `data` as JSON body.
- Returns full response dict (includes `changedEntityId`, `changeType`).
- After create, call `get(entity, changedEntityId)` to return the created record alongside the response.
- Returns `{"changedEntityId": int, "changeType": "INSERT", "data": dict}`.
- **Unit test:** `tests/test_client.py::test_create_returns_insert_response` — mock PUT `/entity/ClientCorporation` returning `{"changedEntityId": 123, "changeType": "INSERT"}`, mock GET `/entity/ClientCorporation/123`, assert method returns combined dict.
- **Unit test:** `tests/test_client.py::test_create_raises_on_api_error` — mock 400 response, assert `BullhornAPIError` raised.

#### T3.3 — Add `create_company` MCP tool (DONE)
**File:** `src/bullhorn_mcp/server.py`
- Parameters: `fields: dict` (all company fields as a dictionary).
- Apply field label resolution: `get_metadata().resolve_fields("ClientCorporation", fields)` (NFR-4 — labels must be accepted in create operations too).
- Calls `client.create("ClientCorporation", resolved_fields)`.
- Returns formatted JSON response.
- **Note:** `get_metadata()` already exists in `server.py` from Sprint 2, so no additional wiring is needed.
- **Unit test:** `tests/test_server.py::test_create_company_success` — mock create flow, assert returns JSON with `changedEntityId`.
- **Unit test:** `tests/test_server.py::test_create_company_api_error` — assert `"ERROR:"` prefix returned.
- **Unit test:** `tests/test_server.py::test_create_company_label_resolution` — mock meta endpoint, provide label key in fields, assert API called with resolved API name.

### Sprint 3 End-to-End Tests
- `tests/test_server.py::test_sprint3_e2e_create_and_retrieve_company` (DONE) — mock PUT create then GET retrieve; call `create_company({"name": "Acme", "status": "Prospect"})`; assert response contains `changedEntityId` and `data.name == "Acme"`.

---

## Sprint 4: Create ClientContact with Owner Resolution

**Tag:** v0.0.4

**What was delivered:** Added `resolve_owner()` to `BullhornClient` (passes `{"id": int}` through unchanged; queries `CorporateUser` by name, returning `{"id"}` for a single match, a list for multiple matches, raising `ValueError` for zero matches). Added `create_contact` MCP tool that validates `owner` and `clientCorporation` are present, resolves owner name to CorporateUser ID, returns disambiguation JSON if ambiguous, applies field label resolution via `get_metadata()`, then calls `client.create("ClientContact", ...)`. Updated `test_server_has_tools` to assert `create_contact` is registered. 109 tests passing (98 pre-existing + 4 new client tests + 7 new server tests).

**User stories:** US-2, US-4, US-5
**Goal:** Add `resolve_owner()` to client. Add `create_contact` MCP tool that requires owner, resolves consultant names to CorporateUser IDs, and handles disambiguation.

**Dependency:** Sprint 3 must be complete (requires `create()` method and `_request()` JSON body support).

### Tasks

#### T4.1 — Add `resolve_owner()` method to `BullhornClient` (DONE)
**File:** `src/bullhorn_mcp/client.py`
- `resolve_owner(owner: str | dict) -> dict | list` — if `owner` is already `{"id": int}`, return as-is. If string, search `CorporateUser` entity by name using `query(entity="CorporateUser", where=f"name='{owner}'", fields="id,firstName,lastName,email,department")`.
- If exactly one result: return `{"id": result["id"]}`.
- If multiple results: return the full list of matches (caller must disambiguate).
- If zero results: raise `ValueError(f"No CorporateUser found matching '{owner}'")`
- **Unit test:** `tests/test_client.py::test_resolve_owner_by_id_passthrough` — assert `{"id": 42}` returns unchanged.
- **Unit test:** `tests/test_client.py::test_resolve_owner_by_name_single_match` — mock CorporateUser query, assert returns `{"id": user_id}`.
- **Unit test:** `tests/test_client.py::test_resolve_owner_by_name_multiple_matches` — mock two results, assert returns list.
- **Unit test:** `tests/test_client.py::test_resolve_owner_by_name_no_match` — assert raises `ValueError`.

#### T4.2 — Add `create_contact` MCP tool (DONE)
**File:** `src/bullhorn_mcp/server.py`
- Parameters: `fields: dict` (all contact fields as a dictionary; `owner` and `clientCorporation` are required).
- Validate `owner` key present in fields; return error if missing.
- Validate `clientCorporation` key present in fields; return error if missing.
- Call `client.resolve_owner(fields["owner"])`.
- If owner resolves to a list (multiple matches): return disambiguation response — do NOT create the record. Return JSON: `{"error": "owner_ambiguous", "matches": [...], "message": "Multiple users found. Specify owner by ID."}`.
- Replace `fields["owner"]` with `{"id": resolved_id}`.
- Apply field label resolution via `get_metadata().resolve_fields("ClientContact", fields)` (NFR-4). **Note:** `get_metadata()` is already implemented in `server.py` from Sprint 2.
- Call `client.create("ClientContact", resolved_fields)`.
- Returns formatted JSON response.
- **Unit test:** `tests/test_server.py::test_create_contact_success` — mock owner resolution and create flow, assert returns JSON with `changedEntityId`.
- **Unit test:** `tests/test_server.py::test_create_contact_missing_owner` — assert error returned without API calls.
- **Unit test:** `tests/test_server.py::test_create_contact_missing_corporation` — assert error returned without API calls.
- **Unit test:** `tests/test_server.py::test_create_contact_owner_ambiguous` — mock multiple CorporateUser results, assert disambiguation response returned, no create called.
- **Unit test:** `tests/test_server.py::test_create_contact_owner_not_found` — mock zero results, assert error returned.
- **Unit test:** `tests/test_server.py::test_create_contact_owner_by_id` — provide `owner: {"id": 99}`, assert passes through without CorporateUser query.

### Sprint 4 End-to-End Tests
- `tests/test_server.py::test_sprint4_e2e_create_contact_with_name_owner` (DONE) — mock CorporateUser query (single match), mock ClientContact PUT, mock GET retrieve; call `create_contact({"firstName": "Jane", "lastName": "Doe", "clientCorporation": {"id": 1}, "owner": "Maryrose Lyons"})`; assert response has `changedEntityId` and `data.owner.id` matches resolved user.

---

## Sprint 5: Duplicate Detection

**Tag:** v0.0.5

**What was delivered:** Created `fuzzy.py` with `normalize()` (strips legal suffixes ltd/inc/plc/corp/llc/pty, punctuation, collapses whitespace), `score_company_match()` (SequenceMatcher on normalized strings + stop-word-aware acronym detection — BNY vs "Bank of New York Mellon" scores 0.82 "likely"), `categorize_score()` (exact ≥ 0.95 / likely 0.75–0.95 / possible 0.50–0.75 / none < 0.50), and `score_contact_match()` (SequenceMatcher on full name). Added `find_duplicate_companies` MCP tool (broad Lucene search, score all results, filter ≥ 0.50, sort by confidence). Added `find_duplicate_contacts` MCP tool (search by clientCorporation.id, score name pairs, flag records with email as `partial_match`). Updated `test_server_has_tools`. 149 tests passing (109 pre-existing + 29 new fuzzy tests + 11 new server tests).

**User stories:** US-6, US-7, US-8 — satisfies NFR-5
**Goal:** Create `fuzzy.py` module with normalization and confidence scoring. Add `find_duplicate_companies` and `find_duplicate_contacts` MCP tools.

**Dependency:** None on Sprints 3-4 directly, but Sprint 7 depends on this sprint. Can be developed in parallel with Sprint 4 if desired.

### Tasks

#### T5.1 — Create `fuzzy.py` with normalization helpers (DONE)
**File:** `src/bullhorn_mcp/fuzzy.py` (new)
- `normalize(name: str) -> str` — lowercase, strip legal suffixes (`ltd`, `limited`, `inc`, `incorporated`, `plc`, `corp`, `corporation`, `llc`, `pty`, `co`), strip punctuation, collapse whitespace.
- No standalone `expand_abbreviations` function — acronym handling is done inline in `score_company_match` (see T5.2). A separate function returning a list of expansions would add untested complexity for a narrow case; the inline check is simpler and sufficient.
- **Unit test:** `tests/test_fuzzy.py::test_normalize_strips_ltd` — `"Acme Ltd"` -> `"acme"`.
- **Unit test:** `tests/test_fuzzy.py::test_normalize_strips_incorporated` — `"Acme Incorporated"` -> `"acme"`.
- **Unit test:** `tests/test_fuzzy.py::test_normalize_case_insensitive` — `"ACME CORP"` -> `"acme"`.
- **Unit test:** `tests/test_fuzzy.py::test_normalize_strips_punctuation` — `"Acme, Inc."` -> `"acme"`.

#### T5.2 — Implement `score_company_match()` confidence scoring (DONE)
**File:** `src/bullhorn_mcp/fuzzy.py`
- `score_company_match(query: str, candidate: str) -> float` — returns 0.0-1.0.
- Strategy: normalize both; compute `difflib.SequenceMatcher` ratio on normalized strings. Inline acronym check: if the query is all-uppercase and its length matches the number of words in the candidate, compare query letters against candidate word initials and apply a score bonus if they match. Return clamped float.
- Thresholds: `>= 0.95` -> exact, `0.75-0.95` -> likely, `0.50-0.75` -> possible, `< 0.50` -> no match.
- `categorize_score(score: float) -> str` — returns `"exact"`, `"likely"`, `"possible"`, or `"none"`.
- **Unit test:** `tests/test_fuzzy.py::test_score_exact_match` — `"Acme Holdings Ltd"` vs `"Acme Holdings Ltd"` -> `>= 0.95`.
- **Unit test:** `tests/test_fuzzy.py::test_score_acronym_match` — `"BNY"` vs `"Bank of New York Mellon"` -> `0.75-0.95`.
- **Unit test:** `tests/test_fuzzy.py::test_score_suffix_variation` — `"Acme Ltd"` vs `"Acme Limited"` -> `>= 0.95`.
- **Unit test:** `tests/test_fuzzy.py::test_score_unrelated` — `"Acme"` vs `"Globex"` -> `< 0.50`.
- **Unit test:** `tests/test_fuzzy.py::test_score_possible_match` — `"Acme Holdings"` vs `"Acme Group"` -> `0.50-0.75`.
- **Unit test:** `tests/test_fuzzy.py::test_categorize_score_thresholds` — verify all four categories at boundary values.

#### T5.3 — Implement `score_contact_match()` confidence scoring (DONE)
**File:** `src/bullhorn_mcp/fuzzy.py`
- `score_contact_match(query_first: str, query_last: str, candidate: dict) -> float` — score against `firstName`/`lastName` fields. Exact name match -> 1.0. Normalize and use SequenceMatcher on full name.
- Flag partial match when email differs (attach `"partial_match": true` in result dict upstream).
- **Unit test:** `tests/test_fuzzy.py::test_contact_exact_match` — same first and last -> `>= 0.95`.
- **Unit test:** `tests/test_fuzzy.py::test_contact_partial_match` — same name different email -> high score but caller flags partial.
- **Unit test:** `tests/test_fuzzy.py::test_contact_no_match` — different name -> `< 0.50`.

#### T5.4 — Add `find_duplicate_companies` MCP tool (DONE)
**File:** `src/bullhorn_mcp/server.py`
- Parameters: `name: str`, `website: str | None = None`, `phone: str | None = None`.
- Calls `client.search("ClientCorporation", query=f"name:{broad_terms}*", fields="id,name,status,phone", count=50)`.
- Applies `score_company_match` to each result.
- Filters results to score `>= 0.5`. Sorts descending by score.
- Returns `{"query": name, "matches": [...], "exact_match": bool}`.
- **Unit test:** `tests/test_server.py::test_find_duplicate_companies_exact` — mock search returning matching company, assert exact_match true.
- **Unit test:** `tests/test_server.py::test_find_duplicate_companies_likely` — mock search returning similar company, assert category "likely".
- **Unit test:** `tests/test_server.py::test_find_duplicate_companies_no_match` — mock empty search results, assert empty matches list.

#### T5.5 — Add `find_duplicate_contacts` MCP tool (DONE)
**File:** `src/bullhorn_mcp/server.py`
- Parameters: `first_name: str`, `last_name: str`, `client_corporation_id: int`.
- Calls `client.search("ClientContact", query=f"clientCorporation.id:{client_corporation_id}", fields="id,firstName,lastName,email,phone,clientCorporation", count=100)`.
- Applies `score_contact_match` to each result.
- Flags results where email differs as `"partial_match": true`.
- Returns `{"query": {...}, "matches": [...], "exact_match": bool}`.
- **Unit test:** `tests/test_server.py::test_find_duplicate_contacts_exact` — mock search, assert exact match detected.
- **Unit test:** `tests/test_server.py::test_find_duplicate_contacts_partial` — same name different email flagged as partial.
- **Unit test:** `tests/test_server.py::test_find_duplicate_contacts_no_match` — assert empty results.

### Sprint 5 End-to-End Tests
- `tests/test_fuzzy.py::test_sprint5_e2e_company_duplicate_detection` (DONE) — call `find_duplicate_companies("BNY")` with mocked search returning `"Bank of New York Mellon"`; assert response has category `"likely"`, confidence in `[0.75, 0.95]`, and `exact_match == false`.
- `tests/test_server.py::test_sprint5_e2e_contact_duplicate_flow` (DONE) — call `find_duplicate_contacts("John", "Smith", 123)` with mocked search; assert JSON matches structure from PRD section 10.

---

## Sprint 6: Update Records and Add Notes

**Tag:** v0.0.6

**What was delivered:** Added `update()` to `BullhornClient` (POST `/entity/{entity}/{id}` with JSON body, then GET for full record, returns `{changedEntityId, changeType, data}`). Added `add_note()` to `BullhornClient` (constructs Note payload with `personReference`+`commentingPerson` for `ClientContact` or `clientCorporation` for `ClientCorporation`, PUT `/entity/Note`, returns created Note). Added `update_record` MCP tool with label resolution and company reassignment guard that fires AFTER label resolution (blocks bypass via label "Company"). Added `add_note` MCP tool with entity validation. Updated `test_server_has_tools`. 163 tests passing (149 pre-existing + 5 new client tests + 9 new server tests).

**User stories:** US-12, US-13, US-14, US-15, US-16
**Goal:** Add `update()` and `add_note()` methods to `BullhornClient`. Add `update_record` and `add_note` MCP tools. Enforce company reassignment guard. Integrate field label resolution.

**Dependency:** Sprint 3 must be complete (requires `_request()` JSON body support). Sprint 2's `get_metadata()` is already available.

### Tasks

#### T6.1 — Add `update()` method to `BullhornClient` (DONE)
**File:** `src/bullhorn_mcp/client.py`
- `update(entity: str, entity_id: int, data: dict) -> dict` — POST to `/entity/{entity}/{entity_id}` with JSON body.
- Uses `_request()` with `json=data` parameter (extended in T3.1).
- After update, call `get(entity, entity_id)` to return full record.
- Returns `{"changedEntityId": entity_id, "changeType": "UPDATE", "data": dict}`.
- **Unit test:** `tests/test_client.py::test_update_returns_update_response` — mock POST and GET, assert combined dict returned.
- **Unit test:** `tests/test_client.py::test_update_raises_on_api_error` — mock 400, assert `BullhornAPIError`.

#### T6.2 — Add `update_record` MCP tool (DONE)
**File:** `src/bullhorn_mcp/server.py`
- Parameters: `entity: str`, `entity_id: int`, `fields: dict`.
- Guard: if `entity == "ClientContact"` and `"clientCorporation"` in `fields`, return error `"Company reassignment is not supported."` without calling API.
- Apply field label resolution: `get_metadata().resolve_fields(entity, fields)`. **Note:** `get_metadata()` is already implemented from Sprint 2.
- **Important:** The company reassignment guard must check for `clientCorporation` in the resolved fields (after label resolution), not just the input fields. Otherwise a caller could bypass the guard by using the label "Company" instead of the API name `clientCorporation`.
- Call `client.update(entity, entity_id, resolved_fields)`.
- Returns formatted JSON.
- **Unit test:** `tests/test_server.py::test_update_record_success` — mock POST+GET, assert returns updated record.
- **Unit test:** `tests/test_server.py::test_update_record_company_reassignment_blocked` — assert error returned without API call.
- **Unit test:** `tests/test_server.py::test_update_record_label_resolution` — mock meta endpoint, provide label key, assert API called with resolved name.
- **Unit test:** `tests/test_server.py::test_update_record_api_error` — assert `"ERROR:"` prefix returned.
- **Unit test:** `tests/test_server.py::test_update_record_company_reassignment_blocked_via_label` — provide `"Company"` label instead of `clientCorporation`, assert guard still triggers after resolution.

#### T6.3 — Add `add_note()` method to `BullhornClient` (DONE)
**File:** `src/bullhorn_mcp/client.py`
- `add_note(entity: str, entity_id: int, action: str, comments: str) -> dict` — constructs Note payload.
- For `ClientContact`: sets `personReference: {"id": entity_id}` and `commentingPerson: {"id": entity_id}`.
- For `ClientCorporation`: sets `clientCorporation: {"id": entity_id}`.
- Sets `action` and `comments` fields.
- PUT to `/entity/Note` using `_request()` with `json=payload` (extended in T3.1).
- After create, call `get("Note", changedEntityId)` to return full Note record.
- Returns `{"changedEntityId": int, "changeType": "INSERT", "data": dict}`.
- **Design note on `commentingPerson`:** The PRD (FR-7) states "sets `commentingPerson` to automate the NoteEntity association." In Bullhorn, setting `commentingPerson` on a Note auto-creates a NoteEntity link, which is a known pattern for ensuring the note appears on the correct entity's Notes tab. Using the contact's own ID here is consistent with the PRD's intent. If a different behaviour is needed (e.g. setting `commentingPerson` to the authenticated CorporateUser), this should be revisited during implementation with a real Bullhorn instance.
- **Unit test:** `tests/test_client.py::test_add_note_to_contact` — mock PUT `/entity/Note`, assert `personReference` set correctly.
- **Unit test:** `tests/test_client.py::test_add_note_to_company` — assert `clientCorporation` set correctly.
- **Unit test:** `tests/test_client.py::test_add_note_raises_on_api_error` — mock 400, assert `BullhornAPIError`.

#### T6.4 — Add `add_note` MCP tool (DONE)
**File:** `src/bullhorn_mcp/server.py`
- Parameters: `entity: str`, `entity_id: int`, `action: str`, `comments: str`.
- Validate `entity` is `"ClientContact"` or `"ClientCorporation"`; return error otherwise.
- Call `client.add_note(entity, entity_id, action, comments)`.
- Returns formatted JSON.
- **Unit test:** `tests/test_server.py::test_add_note_to_contact_success` — mock note creation, assert returns Note ID.
- **Unit test:** `tests/test_server.py::test_add_note_invalid_entity` — assert error for unsupported entity type.
- **Unit test:** `tests/test_server.py::test_add_note_api_error` — assert `"ERROR:"` prefix returned.

### Sprint 6 End-to-End Tests
- `tests/test_server.py::test_sprint6_e2e_update_then_note` — mock update POST/GET and note PUT; call `update_record("ClientContact", 54321, {"title": "CTO"})`; assert title updated; then call `add_note("ClientContact", 54321, "General Note", "Updated via test")`; assert Note ID returned. (DONE)

---

## Sprint 7: Bulk Import

**User stories:** US-3, US-9, US-10, US-11
**Goal:** Implement `bulk_import` orchestration. Create `bulk.py` module. Add `bulk_import` MCP tool. Handle on-the-fly company creation, consecutive error halting, and summary generation.

**Dependency:** Requires all previous sprints. Uses `client.create()` (Sprint 3), `client.resolve_owner()` (Sprint 4), `score_company_match`/`score_contact_match` from `fuzzy.py` (Sprint 5), and `get_metadata()` (Sprint 2).

### Tasks

#### T7.1 — Create `bulk.py` with `BulkImporter` class
**File:** `src/bullhorn_mcp/bulk.py` (new)
- `BulkImporter(client: BullhornClient, metadata: BullhornMetadata)` constructor.
- Internal state: `_consecutive_errors: int = 0`.
- `process(companies: list[dict], contacts: list[dict]) -> dict` — top-level method returning full result dict.
- Returns structure: `{"halted": bool, "summary": {...}, "details": {"companies": [...], "contacts": [...]}}`.

#### T7.2 — Implement company processing phase
**File:** `src/bullhorn_mcp/bulk.py`
- `_process_companies(companies: list[dict]) -> dict[str, int]` — returns map of `input_name -> bullhorn_id`.
- For each company:
  1. Call `find_duplicate_companies` logic (reuse `score_company_match` from fuzzy module against search results).
  2. If exact match (`>= 0.95`): record as `"existing"`, use existing ID.
  3. If likely/possible match: record as `"flagged"`, use existing ID (do not create), include match confidence.
  4. If no match: apply field label resolution via `metadata.resolve_fields()` (NFR-4), then call `client.create("ClientCorporation", resolved_data)`, record as `"created"`.
  5. On `BullhornAPIError`: increment `_consecutive_errors`. If `>= 3`: set `halted=True`, stop.
  6. On success: reset `_consecutive_errors = 0`.
- **Unit test:** `tests/test_bulk.py::test_process_companies_creates_new` — mock search (no results), mock create; assert status "created".
- **Unit test:** `tests/test_bulk.py::test_process_companies_uses_existing` — mock search returning exact match; assert status "existing", no create called.
- **Unit test:** `tests/test_bulk.py::test_process_companies_flags_likely_match` — mock search with likely match; assert status "flagged".
- **Unit test:** `tests/test_bulk.py::test_process_companies_halts_on_consecutive_errors` — mock three consecutive create failures; assert `halted=True` after third.

#### T7.3 — Implement contact processing phase
**File:** `src/bullhorn_mcp/bulk.py`
- `_process_contacts(contacts: list[dict], company_id_map: dict) -> list[dict]` — each contact may have `company_name` (string reference) or `clientCorporation` (with id).
- For each contact:
  1. Resolve company: look up `company_name` in `company_id_map`. If not found, search Bullhorn. If still not found, create company on-the-fly (US-3) and add to map.
  2. Set `clientCorporation: {"id": resolved_id}` in contact fields.
  3. Check owner: call `client.resolve_owner(contact["owner"])`. If ambiguous (returns list): record as `"flagged"` with the match list for user review — do NOT error or halt. This is correct per PRD FR-5 ("flag it and include it in the results for user review"). If owner not found (raises `ValueError`): record as `"failed"`.
  4. Run contact duplicate detection using `score_contact_match`.
  5. If exact match: record as `"existing"`.
  6. If no match: apply field label resolution via `metadata.resolve_fields()` (NFR-4), then call `client.create("ClientContact", ...)`, record as `"created"`.
  7. On `BullhornAPIError`: increment `_consecutive_errors`. If `>= 3`: halt.
  8. On success: reset `_consecutive_errors = 0`.
- **Unit test:** `tests/test_bulk.py::test_process_contacts_resolves_company_from_map` — assert company ID from previous phase used, no extra search.
- **Unit test:** `tests/test_bulk.py::test_process_contacts_creates_company_on_the_fly` — mock company search (no results), mock company create, mock contact create; assert both created.
- **Unit test:** `tests/test_bulk.py::test_process_contacts_skips_existing` — mock contact duplicate detection with exact match; assert status "existing".
- **Unit test:** `tests/test_bulk.py::test_process_contacts_flags_ambiguous_owner` — mock multiple CorporateUser results; assert status "flagged", not "failed".
- **Unit test:** `tests/test_bulk.py::test_process_contacts_fails_on_owner_not_found` — mock zero CorporateUser results (ValueError); assert status "failed".

#### T7.4 — Implement summary generation
**File:** `src/bullhorn_mcp/bulk.py`
- `_build_summary(company_details: list, contact_details: list) -> dict` — aggregates counts per status for both entity types.
- Summary structure per entity type: `{"created": int, "existing": int, "flagged": int, "failed": int}`.
- **Unit test:** `tests/test_bulk.py::test_build_summary_correct_counts` — provide mixed status list, assert all count fields correct.

#### T7.5 — Add `bulk_import` MCP tool
**File:** `src/bullhorn_mcp/server.py`
- Parameters: `companies: list[dict]`, `contacts: list[dict]`.
- Instantiate `BulkImporter(get_client(), get_metadata())`.
- Call `importer.process(companies, contacts)`.
- Returns formatted JSON.
- **Unit test:** `tests/test_server.py::test_bulk_import_success` — mock all sub-operations, assert summary structure correct.
- **Unit test:** `tests/test_server.py::test_bulk_import_halts_on_errors` — mock consecutive failures, assert halted flag in response.

### Sprint 7 End-to-End Tests
- `tests/test_bulk.py::test_sprint7_e2e_full_batch_import` — mock: company search (no results), company create, contact owner resolution, contact search (no results), contact create x2; call `BulkImporter.process(2 companies, 2 contacts)`; assert `summary.companies.created == 2`, `summary.contacts.created == 2`, `halted == False`, and `details` array has 4 entries.
- `tests/test_bulk.py::test_sprint7_e2e_halt_on_consecutive_errors` — mock 3 consecutive company creates to raise `BullhornAPIError`; assert `halted == True` and results up to failure are included.

---

## Sprint 8: CR1 — Fix title/occupation Field Mapping Bug — COMPLETE

**Tag:** v0.0.8
**Change request:** CR1.md
**User stories affected:** US-2, US-4, US-9, US-15

**What was delivered:** Fixed misleading `create_contact` docstring example (`"title"` → `"occupation"`). Added `FIELD_ALIASES` module-level constant to `metadata.py` with initial entry `{"ClientContact": {"job title": "occupation"}}`. Applied alias lookup in `resolve_fields()` before the dynamic metadata lookup, so "job title" resolves to `occupation` without a metadata round-trip and without touching `resolve_label_to_api()`. Added 4 new metadata tests (alias resolution, case-insensitivity, title salutation passthrough, entity isolation) and 1 server E2E test confirming the PUT payload contains `occupation` and not `title`. 182 tests passing.

**Root cause:** The `create_contact` docstring example uses `"title": "VP Engineering"` as the key for job title. Calling agents (e.g. Claude) follow this example and send `title` as the field key. `resolve_fields` attempts to resolve "title" as a display label, but Bullhorn's metadata does not map any label named "title" to `occupation`. The key therefore passes through unchanged as the raw API field `title`, which in Bullhorn is the salutation/name prefix (Mr, Ms, Dr, etc.) — not the job title. This causes contact creation to fail or silently set the wrong field.

**Fix scope (minimal):**
1. Fix the misleading docstring example in `create_contact`.
2. Add a hardcoded alias in `metadata.py` so "job title" resolves to `occupation` for ClientContact (covers NFR-4 / US-15 label resolution for this known problematic case).
3. `"title"` as a raw key continues to pass through unchanged (correct for callers who genuinely want to set the salutation field).

**CR1 item 4 — field mapping review:** All field passing in `create_company`, `create_contact`, `update_record` is dynamic (caller-supplied dict → label resolver → Bullhorn API). No fields are hardcoded in server.py except the docstring example. `add_note` constructs a fixed payload (action, comments, personReference/clientCorporation) which is correct per the Bullhorn Note entity schema. No further field mapping issues were found.

### Tasks

#### T8.1 — Fix `create_contact` docstring example
**File:** `src/bullhorn_mcp/server.py`
- Change the docstring example field from `"title": "VP Engineering"` to `"occupation": "VP Engineering"`.
- No logic changes.
- **Unit test:** No new test needed — this is a documentation fix. Existing `test_create_contact_success` already exercises the creation path.

#### T8.2 — Add hardcoded alias "job title" → "occupation" for ClientContact in `BullhornMetadata`
**File:** `src/bullhorn_mcp/metadata.py`
- Add a module-level constant `FIELD_ALIASES: dict[str, dict[str, str]]` — a map of `{entity: {alias_lower: api_name}}` for known problematic label aliases that Bullhorn's metadata does not reliably resolve at runtime.
- Initial entry: `{"ClientContact": {"job title": "occupation"}}`.
- In `resolve_fields()`, before the dynamic label lookup, check `FIELD_ALIASES` for the entity and key (lowercased). If a match is found, use the hardcoded API name.
- The `resolve_label_to_api()` method is **not** changed — it remains a pure metadata lookup. The alias override only applies in `resolve_fields()`.
- **Unit test:** `tests/test_metadata.py::test_resolve_fields_job_title_alias` — call `resolve_fields("ClientContact", {"job title": "VP Engineering"})` with no mock needed (alias lookup is pre-metadata); assert result key is `"occupation"`.
- **Unit test:** `tests/test_metadata.py::test_resolve_fields_title_passes_through` — call `resolve_fields("ClientContact", {"title": "Mr"})` with a mock metadata response that has no label "title"; assert key remains `"title"` (salutation passthrough is preserved).

### Sprint 8 End-to-End Tests
- `tests/test_server.py::test_sprint8_e2e_create_contact_occupation` — mock owner resolution, metadata (no "title" label), and ClientContact PUT/GET; call `create_contact({"firstName": "Jane", "lastName": "Doe", "clientCorporation": {"id": 1}, "owner": {"id": 99}, "occupation": "VP of Engineering"})`; assert Bullhorn PUT payload contains `"occupation"` and does not contain `"title"`.

---

## Sprint 9: CR2 — Audit and Fix Auto-Injected Fields

**Tag:** v0.0.9
**Change request:** CR2.md
**User stories affected:** US-1, US-2, US-9, US-12

**Goal:** Audit `create_contact`, `create_company`, and `update_record` to confirm only caller-supplied fields reach the Bullhorn API. Remove any auto-injection found. Add payload-assertion tests that will catch this class of bug in future.

**Dependency:** All previous sprints complete.

**What was delivered:** Audit confirmed the current `fields: dict` pass-through pattern in `server.py`, `metadata.resolve_fields()`, and `client.create()`/`update()` is clean — no auto-injection exists in the code path. `DEFAULT_FIELDS` in `client.py` is used only by read operations (`search`, `query`, `get`) and does not affect write payloads. The only transformation in `create_contact` is normalising the `owner` string to `{"id": int}` (intentional). Added 8 new tests: `TestSprint9PayloadAudit` (4 tests asserting exact PUT/POST key sets for `create_contact`, `create_company`, `update_record`) and `TestSprint9E2E` (1 E2E test) in `test_server.py`; `TestSprint9FieldAudit` (3 tests covering `department` pass-through and no-key-injection guarantees for both entity types) in `test_metadata.py`. 190 tests passing.

**Audit findings:**
- `create_contact`: Only `owner` is transformed (string → `{"id": int}`). No other fields are added. Confirmed by `test_create_contact_payload_only_contains_caller_fields` and `test_create_contact_owner_normalised_not_injected`.
- `create_company`: Pure pass-through after label resolution. Confirmed by `test_create_company_payload_only_contains_caller_fields`.
- `update_record`: Pure pass-through after label resolution. Confirmed by `test_update_record_payload_only_contains_caller_fields`.
- `DEFAULT_FIELDS["ClientContact"]` contains `title` (salutation) for read responses only; never applied to write payloads.
- `department` field: No alias exists; passes through unchanged to Bullhorn which rejects it with a clear field error. This is correct behaviour — callers who mean `division` should use `division`. A `FIELD_ALIASES` entry was not added (no confirmed real-world evidence of systematic mislabelling).

### Background

CR2 reports that `create_contact` is sending fields the caller did not supply (e.g. `department`, which is not a valid ClientContact field — the correct field is `division`). CR1 resolved the `title`/`occupation` case; CR2 addresses the broader pattern.

Preliminary code review (Sprint 9 planning) shows the current `fields: dict` pass-through pattern in `server.py` and `metadata.resolve_fields()` appear clean. However, `DEFAULT_FIELDS["ClientContact"]` in `client.py` includes `title` (correct for reads), and subtle injection could occur if labels in `resolve_fields()` map a caller-supplied key to an unexpected API field. The tasks below verify this with tests and fix any issues found.

### Tasks

#### T9.1 — Audit `create_contact` payload construction
**Files:** `src/bullhorn_mcp/server.py`, `src/bullhorn_mcp/client.py`, `src/bullhorn_mcp/metadata.py`

Trace the complete path from `create_contact(fields)` to the Bullhorn PUT body:
1. `server.py`: validates `owner`/`clientCorporation` presence, normalises `owner` string → `{"id": int}`, calls `resolve_fields("ClientContact", contact_fields)`.
2. `metadata.py`: `resolve_fields()` iterates caller keys only — no new keys added.
3. `client.py`: `create()` sends `data` dict as JSON body unchanged.

Document every field in the PUT body relative to what the caller provided. Expected: only `owner` is transformed (string → `{"id": int}`); no other fields are added or removed.

If any injection is found (e.g. fields added from `DEFAULT_FIELDS`, from metadata iteration, or from tool parameter defaults), remove it so the PUT body equals exactly the caller-supplied fields after label resolution and `owner` normalisation.

**Note on `name` field:** Bullhorn recommends sending `name` alongside `firstName`/`lastName` for ClientContact. The tool does not auto-populate `name = f"{firstName} {lastName}"` — callers must supply it if desired. This is intentional (CR2 requires no auto-injection); document this explicitly.

- **Unit test:** `tests/test_server.py::test_create_contact_payload_only_contains_caller_fields` — call `create_contact({"firstName": "Jane", "lastName": "Doe", "clientCorporation": {"id": 1}, "owner": {"id": 99}})` with a mock that captures the PUT JSON body; assert body keys are exactly `{"firstName", "lastName", "clientCorporation", "owner"}` and nothing else.
- **Unit test:** `tests/test_server.py::test_create_contact_owner_normalised_not_injected` — provide `owner: "Maryrose Lyons"` (name string); mock CorporateUser query returning single user; assert PUT body contains `owner: {"id": <resolved_id>}` and no extra keys.

#### T9.2 — Audit `create_company` payload construction
**Files:** `src/bullhorn_mcp/server.py`

Trace `create_company(fields)` → `resolve_fields("ClientCorporation", fields)` → `client.create("ClientCorporation", resolved)`.

Expected: resolved dict equals caller's input with label keys replaced by API names. No fields added.

- **Unit test:** `tests/test_server.py::test_create_company_payload_only_contains_caller_fields` — call `create_company({"name": "Acme", "status": "Prospect"})` with a mock capturing the PUT body; assert body keys are exactly `{"name", "status"}`.

#### T9.3 — Audit `update_record` payload construction
**Files:** `src/bullhorn_mcp/server.py`

Trace `update_record(entity, entity_id, fields)` → `resolve_fields(entity, fields)` → `client.update(entity, entity_id, resolved)`.

Expected: resolved dict equals caller's input after label resolution. No fields added.

- **Unit test:** `tests/test_server.py::test_update_record_payload_only_contains_caller_fields` — call `update_record("ClientContact", 1, {"occupation": "CTO"})` with a mock capturing the POST body; assert body is exactly `{"occupation": "CTO"}`.

#### T9.4 — Verify `DEFAULT_FIELDS` does not affect write payloads
**File:** `src/bullhorn_mcp/client.py`

Confirm `DEFAULT_FIELDS` is referenced only in `search()`, `query()`, and `get()` (read path) — not in `create()` or `update()`. These latter two methods receive a `data: dict` argument and pass it directly to `_request()` as the JSON body without consulting `DEFAULT_FIELDS`.

This is a documentation/verification task — no code change expected. If any read of `DEFAULT_FIELDS` is found in write paths, remove it.

**Note:** `DEFAULT_FIELDS["ClientContact"]` includes `title` (salutation). This is correct for GET responses but must not appear in CREATE/UPDATE payloads unless the caller explicitly provides it. Tests T9.1–T9.3 will catch this if it occurs.

#### T9.5 — Fix any auto-injected fields found
**Files:** As applicable from T9.1–T9.4

If any audit step reveals fields being added to the payload beyond what the caller provided:
- Remove the injection.
- Document what was found and how it was resolved in the sprint's "What was delivered" section (to be filled in after completion, following the pattern of Sprint 8).

If no injection is found, document that conclusion explicitly.

#### T9.6 — Validate field names sent to Bullhorn against entity schema
**File:** `src/bullhorn_mcp/metadata.py`

The CR2 root cause may be that `metadata.resolve_fields()` is resolving a caller-supplied label (e.g. "Department") to an invalid ClientContact API field. Verify:
1. If a caller supplies `{"department": "Engineering"}`, `resolve_fields("ClientContact", ...)` checks if "department" is a known display label. If Bullhorn's metadata returns a field whose label is "Department" but whose API name is also not a valid ClientContact field (or maps to the wrong field), the label resolution could silently send a bad field name.
2. The fix is: `resolve_fields()` already passes through unknown keys unchanged. If "department" does not match any label in ClientContact metadata, it passes through as `"department"` — and Bullhorn will reject it with a field validation error. This is the correct behaviour; the tool should not silently drop unknown fields.
3. Add a `FIELD_ALIASES` entry for `ClientContact` mapping `"department"` → `"division"` if this is a known problematic alias (similar to `"job title"` → `"occupation"` in Sprint 8). Only add this alias if there is clear evidence from real usage that the mapping is needed — do not add it speculatively.

- **Unit test:** `tests/test_metadata.py::test_resolve_fields_unknown_key_passes_through` — call `resolve_fields("ClientContact", {"department": "Engineering"})` with a mock metadata response that has no "department" label; assert key passes through as `"department"` unchanged.

### Sprint 9 End-to-End Tests

- `tests/test_server.py::test_sprint9_e2e_minimal_create_contact_payload` — mock owner resolution (by ID, no CorporateUser query), mock ClientContact PUT (capture body), mock GET retrieve; call `create_contact({"firstName": "Jane", "lastName": "Doe", "clientCorporation": {"id": 1}, "owner": {"id": 99}})`; assert PUT body contains exactly `{"firstName": "Jane", "lastName": "Doe", "clientCorporation": {"id": 1}, "owner": {"id": 99}}` and response has `changedEntityId`.

---

## Sprint 10: CR3 — Fix Broken Owner Name Resolution and Department Field Leak

**Tag:** v0.0.10
**Change request:** CR3.md
**User stories affected:** US-2, US-3, US-4, US-5, US-9, US-10, US-11

**Goal:** Fix `resolve_owner()` so that providing a consultant name (e.g. "Beau Warren") reliably resolves to a CorporateUser ID. Ensure no CorporateUser data leaks into the ClientContact creation payload. Fix `bulk.py` to handle `BullhornAPIError` from owner resolution gracefully (per NFR-3).

**Dependency:** All previous sprints complete.

**What was delivered:** Removed `department` from the CorporateUser query fields in `resolve_owner()` (`client.py`) — changed `fields="id,firstName,lastName,email,department"` to `fields="id,firstName,lastName,email"`. This prevents `BullhornAPIError` on Bullhorn instances where `department` is not a valid queryable CorporateUser field, restoring owner name resolution. Extended `_process_single_contact()` in `bulk.py` to catch `BullhornAPIError` from `resolve_owner` (previously only `ValueError` was caught), marking the contact as `"failed"` and counting toward the consecutive-error halt threshold rather than aborting the entire batch. Added 5 new tests: `test_resolve_owner_query_does_not_include_department`, `test_resolve_owner_single_match_returns_id_only` (in `test_client.py`); `test_process_contact_owner_api_error_is_caught`, `test_process_contact_owner_api_error_counts_toward_halt` (in `test_bulk.py`); `test_sprint10_e2e_create_contact_owner_name_no_leak` (in `test_server.py`). 195 tests passing.

---

### Root Cause Analysis

**Issue 1 — Owner name not resolved:**
`resolve_owner()` in `client.py` queries CorporateUser with `fields="id,firstName,lastName,email,department"`. In some Bullhorn instances, `department` is not a valid queryable field on CorporateUser. When this is the case, the Bullhorn API returns a non-200 response, `_request()` raises `BullhornAPIError`, and `resolve_owner()` propagates it upward without catching it. In `create_contact` the error is caught and returned as `"ERROR: ..."` — the contact is never created. In `bulk.py`, `_process_single_contact` only catches `ValueError` from `resolve_owner`, so a `BullhornAPIError` propagates all the way to `bulk_import()` and aborts the entire batch rather than marking just that contact as failed.

**Issue 2 — `department` field in ClientContact payload:**
`resolve_owner()` correctly returns `{"id": results[0]["id"]}` for a single match and only the `owner` key is updated in `contact_fields`. The current code does not merge the full CorporateUser record into the payload. However, if `department` is a valid CorporateUser field in this Bullhorn instance and is present in query results, the risk of data leakage is inherent in including it in the query at all. Removing `department` from the query eliminates the possibility of it appearing anywhere in the resolution path. For the disambiguation (multiple-match) case, `email` alone is sufficient for disambiguation — `department` is not needed.

---

### Tasks

#### T10.1 — Remove `department` from `resolve_owner` CorporateUser query fields
**File:** `src/bullhorn_mcp/client.py`

Change the `fields` argument in the `resolve_owner` CorporateUser query from `"id,firstName,lastName,email,department"` to `"id,firstName,lastName,email"`.

**Rationale:** `department` is not reliably present as a queryable CorporateUser field across all Bullhorn instances. Removing it prevents query failures and eliminates any possibility of `department` data entering the resolution path. `email` is sufficient for disambiguation when multiple users match the same name.

- **Unit test:** `tests/test_client.py::test_resolve_owner_query_does_not_include_department` — mock the CorporateUser query endpoint; after calling `resolve_owner("Beau Warren")`, assert the `fields` query parameter sent to Bullhorn does not include `"department"`.
- **Unit test:** `tests/test_client.py::test_resolve_owner_single_match_returns_id_only` — mock CorporateUser query returning one user with multiple fields (id, firstName, lastName, email); assert `resolve_owner` returns exactly `{"id": <user_id>}` and nothing else.

#### T10.2 — Handle `BullhornAPIError` from `resolve_owner` in `bulk.py`
**File:** `src/bullhorn_mcp/bulk.py`

In `_process_single_contact`, extend the try/except around `client.resolve_owner()` to also catch `BullhornAPIError`. On `BullhornAPIError`, increment `_consecutive_errors`, return status `"failed"` with the error message, and check if `_consecutive_errors >= 3` to determine `halted`. This is consistent with how other `BullhornAPIError` cases are handled in the bulk importer, and satisfies NFR-3 (resilience to individual record failures).

Current code:
```python
try:
    owner_result = self.client.resolve_owner(owner_raw)
except ValueError as e:
    return (
        {"input_name": input_name, "status": "failed", "error": str(e), "company_id": company_id_value},
        False,
    )
```

Required change: also catch `BullhornAPIError` from `resolve_owner`, increment `_consecutive_errors`, and return `({"status": "failed", ...}, self._consecutive_errors >= 3)`.

- **Unit test:** `tests/test_bulk.py::test_process_contact_owner_api_error_is_caught` — mock `resolve_owner` to raise `BullhornAPIError`; assert `_process_single_contact` returns `status="failed"` and does not raise.
- **Unit test:** `tests/test_bulk.py::test_process_contact_owner_api_error_counts_toward_halt` — mock `resolve_owner` to raise `BullhornAPIError` three consecutive times; assert third call returns `halted=True`.

#### T10.3 — Add create_contact E2E test confirming no CorporateUser data in payload
**File:** `tests/test_server.py`

Add a test that calls `create_contact({"firstName": "Jane", "lastName": "Doe", "clientCorporation": {"id": 1}, "owner": "Beau Warren"})` with:
- A mocked CorporateUser query returning one user: `{"id": 42, "firstName": "Beau", "lastName": "Warren", "email": "beau@example.com"}` (no `department` field).
- A mocked ClientContact PUT endpoint capturing the JSON body.
- A mocked ClientContact GET for the created record.

Assert:
1. The ClientContact PUT body contains `"owner": {"id": 42}` — not the full CorporateUser record.
2. The PUT body does not contain `"department"`, `"firstName"` (from CorporateUser), `"lastName"` (from CorporateUser), or `"email"` (from CorporateUser).
3. The response contains `changedEntityId`.

- **Unit test:** `tests/test_server.py::test_sprint10_e2e_create_contact_owner_name_no_leak` — as described above.

### Sprint 10 End-to-End Tests

- `tests/test_server.py::test_sprint10_e2e_create_contact_owner_name_no_leak` — described in T10.3 above. Verifies the complete resolution path: name string → CorporateUser query (without `department`) → `{"id": int}` → ClientContact create payload with no CorporateUser data leakage.

---

## Sprint 11: CR4 — Fix Incorrect Title Field in Docstrings — COMPLETE

**Tag:** v0.0.11

**What was delivered:** Fixed two docstring errors where `title` was incorrectly used to mean job title for ClientContact:
- `update_record` docstring example changed from `{"title": "CTO"}` to `{"occupation": "CTO"}`.
- `list_contacts` docstring example changed from `title:Manager` to `occupation:Manager` in the Lucene query example.
Added `TestSprint11DocstringRegression` in `test_server.py` with 3 regression guards to prevent recurrence. 198 tests passing.

**User stories addressed:** US-12, US-15

---

## Sprint 12: CR6 — Investigate and Fix title Field Injection in update_record — COMPLETE

**Tag:** v0.0.12
**Change request:** CR6.md
**User stories affected:** US-12, US-13, US-15

**What was delivered:** Full execution-path audit of `update_record` found NO code-level injection. Specifically: `server.py` `update_record` passes `fields: dict` directly to `get_metadata().resolve_fields()` with no additions; `metadata.py` `resolve_fields()` iterates only over input keys, never adds new keys; `client.py` `update()` passes `data` directly to `_request("POST", ...)` without mutation; `client.py` `_request()` passes the `json` argument directly to httpx without mutation; `DEFAULT_FIELDS["ClientContact"]` (which contains `title`) is referenced only in read paths (`search()`, `query()`, `get()`), never in `update()` or `create()`. Root cause: the injection originates from the calling agent, not from MCP server code. Added `TestSprint12TitleInjectionRegression` in `test_server.py` with 3 regression tests that capture the raw HTTP POST body via `respx`. 201 tests passing.

---

## Sprint 13: CR7 — Strip title From ClientContact Write Payloads and Log Warning

**Tag:** v0.0.13
**Change request:** CR7.md
**User stories affected:** US-2, US-12, US-15

**Goal:** After Sprint 12 removes the active injection, add defense-in-depth: if `title` ever reaches a ClientContact write payload (from a calling agent that misunderstands the field), strip it silently with a logged warning and a `warnings` array in the response. This prevents Bullhorn from rejecting the operation while communicating the issue to the caller.

**Dependency:** Sprint 12 must be complete (removes the active injection; this sprint adds the guard).

**What was delivered:** Added `_logger = logging.getLogger(__name__)` and `_strip_contact_title(fields, entity)` helper to `server.py`. The helper strips `"title"` from ClientContact write payloads, logs a `WARNING`, and returns a `(cleaned_fields, warnings_list)` tuple. Applied the helper in `create_contact` (after `resolve_fields`, before `client.create()`) and in `update_record` (after the company-reassignment guard, before `client.update()`). When warnings are present, the JSON response includes a `"warnings"` array. Non-ClientContact entities and read paths are unaffected. Confirmed `DEFAULT_FIELDS["ClientContact"]` still includes `"title"` for read operations (no change needed). Added `TestSprint13TitleStripping` in `test_server.py` with 6 tests (create with title, create without title, update with title, update for non-ClientContact, update with occupation, E2E). 207 tests passing.

---

### Background

Even after the Sprint 12 fix removes the schema-level injection, callers may still send `title` meaning "job title" (a documented misunderstanding addressed in CR1/CR4). Rather than silently failing with a Bullhorn API error, the MCP should strip the field and warn. The chosen approach (Option C from CR7) avoids permanently hiding the real `title` (salutation) field behind an alias.

**Important:** This guard applies only to ClientContact write payloads. Other entities (e.g. JobOrder) have a valid writable `title` field.

---

### Tasks

#### T13.1 — Add `_strip_contact_title(fields: dict) -> tuple[dict, list[str]]` utility
**File:** `src/bullhorn_mcp/server.py` (or a shared helper)

A small function that:
- Takes `fields: dict` and `entity: str`.
- If `entity == "ClientContact"` and `"title"` is in `fields`: removes it, appends a warning string, logs a `logging.warning(...)`.
- Returns `(cleaned_fields, warnings_list)`.

Warning message: `"Field 'title' was stripped from the ClientContact payload. Use 'occupation' for job title or 'namePrefix' for salutation."`

This function is called in both `create_contact` and `update_record` **after** field label resolution (so that label-resolved keys are also checked).

#### T13.2 — Apply title stripping in `create_contact`
**File:** `src/bullhorn_mcp/server.py`

After `resolve_fields("ClientContact", fields)` and before calling `client.create()`:
- Call `_strip_contact_title(resolved_fields, "ClientContact")`.
- If `warnings` is non-empty, include `"warnings": warnings` in the response dict returned to the caller.

- **Unit test:** `tests/test_server.py::test_create_contact_title_stripped_with_warning` — call `create_contact({"firstName": "Jane", "lastName": "Doe", "clientCorporation": {"id": 1}, "owner": {"id": 99}, "title": "CTO"})` with a mock capturing the PUT body; assert PUT body does not contain `"title"`, and response contains `"warnings"` with the expected message.
- **Unit test:** `tests/test_server.py::test_create_contact_no_warning_without_title` — call without `title`; assert response does not contain `"warnings"` key.

#### T13.3 — Apply title stripping in `update_record`
**File:** `src/bullhorn_mcp/server.py`

After `resolve_fields(entity, fields)` and before calling `client.update()`:
- Call `_strip_contact_title(resolved_fields, entity)` — only strips if entity is ClientContact.
- If `warnings` is non-empty, include `"warnings": warnings` in the response dict.

- **Unit test:** `tests/test_server.py::test_update_record_title_stripped_with_warning` — call `update_record("ClientContact", 1, {"title": "VP"})` with a mock capturing the POST body; assert POST body does not contain `"title"`, and response contains `"warnings"`.
- **Unit test:** `tests/test_server.py::test_update_record_joborder_title_not_stripped` — call `update_record("JobOrder", 1, {"title": "Senior Engineer"})` with a mock; assert POST body contains `"title": "Senior Engineer"` (not stripped for non-ClientContact entities).
- **Unit test:** `tests/test_server.py::test_update_record_occupation_no_warning` — call `update_record("ClientContact", 1, {"occupation": "VP"})`; assert no `"warnings"` in response.

#### T13.4 — Confirm `DEFAULT_FIELDS` read paths are unaffected
**File:** `src/bullhorn_mcp/client.py`

Verify (read-only audit) that `DEFAULT_FIELDS["ClientContact"]` continues to include `title` for GET/search/query responses. `_strip_contact_title` only applies in write paths; read operations must not be modified.

No code change expected. Document the confirmation in the "What was delivered" section.

### Sprint 13 End-to-End Tests

- `tests/test_server.py::test_sprint13_e2e_create_contact_title_stripped` — mock owner resolution (by ID), metadata (resolves nothing new), ClientContact PUT (capture body), ClientContact GET; call `create_contact({"firstName": "Conor", "lastName": "Warren", "clientCorporation": {"id": 1}, "owner": {"id": 42}, "title": "CEO"})`; assert PUT body lacks `"title"`, response has `changedEntityId` and `warnings` array containing the expected message.

---

## Sprint 14: CR5 — Add Duplicate Check to create_contact Before Creation

**Tag:** v0.0.14
**Change request:** CR5.md
**User stories affected:** US-2, US-7

**Goal:** Add a pre-creation duplicate check to `create_contact` so that callers who retry after a (transient or bug-induced) error do not silently create duplicate contacts. Reuse the existing `score_contact_match` logic already used in `bulk_import`.

**Dependency:** Sprints 12 and 13 must be complete (the duplicates described in CR5 were caused by the title injection fixed in those sprints; this sprint adds a guard so retries are safe regardless of root cause).

---

### Background

During real usage, `create_contact` calls failed with `"Invalid field 'title'"` errors (the bug addressed in CR6/CR7). Bullhorn partially persisted the records before returning the error. When callers retried, they created additional duplicate contacts (IDs 170841, 170842, 170843). A pre-creation duplicate check would have caught the second and third attempts.

`bulk_import` already performs this check via `score_contact_match`. `create_contact` should do the same so individual creation is equally safe.

**Important:** `bulk_import` is **not** affected by this sprint. It calls `client.create()` directly (not `create_contact`) and manages its own duplicate detection.

---

### Tasks

#### T14.1 — Add duplicate detection before creation in `create_contact`
**File:** `src/bullhorn_mcp/server.py`

After resolving the owner and stripping `title` (Sprints 12–13), and before calling `client.create("ClientContact", ...)`:

1. Extract `clientCorporation.id` from the resolved fields.
2. Extract `firstName` and `lastName` from the resolved fields.
3. Call `client.search("ClientContact", query=f"clientCorporation.id:{corp_id}", fields="id,firstName,lastName,email,phone,clientCorporation", count=100)`.
4. Score each result with `score_contact_match(firstName, lastName, candidate)` from `fuzzy.py`.
5. Find the highest-scoring match.

Decision logic:
- **Score >= 0.95 (exact):** Return without creating. Response: `{"duplicate_found": True, "match": {"confidence": score, "category": "exact", "record": {...}}, "message": "A contact matching this name already exists at this company. Use update_record to modify the existing record, or set force=True to create regardless."}`.
- **Score 0.50–0.95 (likely/possible):** Return without creating. Response: same shape but `category` reflects the confidence band, with message asking caller to confirm.
- **No match:** Proceed with `client.create()` as normal.

- **Unit test:** `tests/test_server.py::test_create_contact_blocks_on_exact_duplicate` — mock contact search returning a contact with the same name at the same company; call `create_contact(...)` without `force=True`; assert response contains `duplicate_found: true`, no PUT call made.
- **Unit test:** `tests/test_server.py::test_create_contact_blocks_on_near_duplicate` — mock search returning a near-match (score 0.50–0.95); assert `duplicate_found: true` with appropriate category, no PUT call made.
- **Unit test:** `tests/test_server.py::test_create_contact_proceeds_when_no_duplicate` — mock search returning no matches; assert PUT called and `changedEntityId` in response.

#### T14.2 — Add `force: bool = False` parameter to `create_contact`
**File:** `src/bullhorn_mcp/server.py`

Add `force: bool = False` as an optional parameter to `create_contact`. When `force=True`, skip the duplicate check (step T14.1) entirely and proceed directly to `client.create()`.

Update the `create_contact` docstring to document the `force` parameter.

- **Unit test:** `tests/test_server.py::test_create_contact_force_bypasses_duplicate_check` — mock search (would return a duplicate if consulted), but pass `force=True`; assert no search call is made (or its result is ignored) and PUT is called.

#### T14.3 — Handle missing `clientCorporation` gracefully in duplicate check
**File:** `src/bullhorn_mcp/server.py`

If `clientCorporation` is absent from `fields` (already validated earlier in `create_contact`), the duplicate check cannot run. This should not happen in practice because `create_contact` already returns an error if `clientCorporation` is missing. Confirm the existing validation covers this before the duplicate check path is reached. No new validation needed.

### Sprint 14 End-to-End Tests

- `tests/test_server.py::test_sprint14_e2e_create_contact_duplicate_blocked` — mock: CorporateUser query (owner by name), ClientContact search (returns existing contact with same name/company), no PUT mock; call `create_contact({"firstName": "Conor", "lastName": "Warren", "clientCorporation": {"id": 10666}, "owner": "Beau Warren"})`; assert response has `duplicate_found: true`, `match.record.id` is the existing contact ID, no creation occurred.

- `tests/test_server.py::test_sprint14_e2e_create_contact_force_creates_despite_duplicate` — mock: CorporateUser query, ClientContact search (returns existing), ClientContact PUT, ClientContact GET; call `create_contact({..., "force": True})`; assert PUT is called and `changedEntityId` is in response.

### What was delivered

- `create_contact` in `src/bullhorn_mcp/server.py` gains a `force: bool = False` parameter.
- Before calling `client.create()`, the tool searches for existing ClientContact records at the same company and scores each with `score_contact_match`. If the best score is >= 0.50, it returns a `duplicate_found` response (with confidence, category, and the matching record) instead of creating. `force=True` bypasses this entirely.
- A search failure during the duplicate check is non-fatal — creation proceeds as normal.
- `bulk_import` is unaffected (it calls `client.create()` directly with its own dedup logic).
- Sprint 13 E2E test updated to mock the new search call (returning empty results) so it continues to pass.
- 7 new tests added in `TestSprint14DuplicateCheck`: exact duplicate blocked, near-duplicate blocked, no duplicate proceeds, force bypasses check, search failure is non-fatal, E2E duplicate blocked, E2E force creates despite duplicate.
- Total: 214 tests passing, tagged v0.0.14.

---

## Sprint 15: CR8 — Add HTTP Transport Mode for Remote Hosting — COMPLETE

**Tag:** v0.0.15
**Change request:** CR8.md
**User stories:** US-22 (new — see PRD.md FR-11)

**What was delivered:** Added `os` import to `server.py`. Four module-level variables (`_transport_mode`, `_port`, `_default_host`, `_host`) are read from env at import time and passed to `FastMCP(host=_host, port=_port, ...)`. `HOST` env var is read with `_default_host` as fallback (0.0.0.0 in http mode, 127.0.0.1 in stdio). `main()` uses `_transport_mode` (not re-reading env) to call `mcp.run(transport="streamable-http")` for HTTP or `mcp.run()` for stdio; any other value raises `ValueError`. Added `uvicorn>=0.30.0` to `pyproject.toml` dependencies. Updated `.env.example` with commented-out `MCP_TRANSPORT`, `PORT`, `HOST`. Added `## Hosted Deployment` section and extended the Environment Variables table in `README.md`. Added 6 tests in `TestSprint15HttpTransport` — dispatch tests use `patch.object(server, "_transport_mode", ...)` (not env patching) because `main()` reads the module-level var. Port/host tests use `importlib.reload`. 220 tests passing.

**Review cycle learnings:**
- `main()` must use module-level `_transport_mode` (not re-read `os.environ`) to stay consistent with the host/port already baked into `FastMCP()` at import time. Mixing import-time and runtime env reads creates silent misconfiguration.
- Tests for `main()` dispatch must patch `server._transport_mode` directly (via `patch.object`), not `os.environ`, since transport is resolved at import. Tests that need to verify import-time env reading (port, host) require `importlib.reload`.

**Dependency:** All previous sprints complete.

---

### Background

The server currently uses stdio transport exclusively. Claude.ai (web), ChatGPT, and any remotely-hosted AI client require an HTTP endpoint. Without this change the server cannot be deployed on infrastructure (Proxmox, Azure, etc.) and exposed via a Cloudflare tunnel for multi-user access.

`FastMCP` already supports `streamable-http` transport natively via `mcp.run(transport="streamable-http")`. Port and host are configured at `FastMCP` construction time via `port=` and `host=` kwargs. The implementation therefore requires reading env vars during server initialisation and passing them to `FastMCP(...)`.

`uvicorn` is required by the SDK's HTTP transport but is absent from `pyproject.toml`.

---

### Tasks

#### T15.1 — Add `uvicorn` to `pyproject.toml` (DONE)
**File:** `pyproject.toml`

Add `"uvicorn>=0.30.0"` to the main `dependencies` list alongside `mcp`, `httpx`, and `python-dotenv`.

No new tests — uvicorn availability is implicitly validated when the HTTP-mode server tests exercise `mcp.run(transport="streamable-http")`.

#### T15.2 — Read transport env vars and pass to `FastMCP` constructor in `server.py` (DONE)
**File:** `src/bullhorn_mcp/server.py`

Read the following environment variables at module load time, before the `mcp = FastMCP(...)` call:

- `MCP_TRANSPORT` — `"stdio"` (default) or `"http"`. Any other value should raise a `ValueError` at startup with a clear message listing valid options.
- `PORT` — integer, default `8000`. Cast with `int(os.environ.get("PORT", 8000))`.
- `HOST` — default `"0.0.0.0"` when `MCP_TRANSPORT=http`, `"127.0.0.1"` when stdio (stdio host is irrelevant but should match current FastMCP default to avoid side-effects). Since the FastMCP default is `"127.0.0.1"`, only override host to `"0.0.0.0"` in HTTP mode.

Pass `port=port` and `host=host` to `FastMCP(...)` so that `run_streamable_http_async` picks them up from `mcp.settings`.

Update `main()`:

```python
def main():
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        _logger.info("Starting Bullhorn MCP server in HTTP mode on %s:%s", _host, _port)
        mcp.run(transport="streamable-http")
    elif transport == "stdio":
        mcp.run()
    else:
        raise ValueError(f"Unknown MCP_TRANSPORT '{transport}'. Valid values: stdio, http")
```

Add `import os` to the server module imports.

Log the active transport and port on startup (INFO level) so it is immediately clear which mode is running.

Unit tests:
- `tests/test_server.py::test_main_stdio_default` — patch `os.environ` with no `MCP_TRANSPORT`; mock `mcp.run`; call `main()`; assert `mcp.run` called with no `transport` kwarg (or `transport="stdio"` — verify which path is taken).
- `tests/test_server.py::test_main_http_transport` — patch `os.environ` with `MCP_TRANSPORT=http`; mock `mcp.run`; call `main()`; assert `mcp.run` called with `transport="streamable-http"`.
- `tests/test_server.py::test_main_invalid_transport` — patch `os.environ` with `MCP_TRANSPORT=grpc`; call `main()`; assert `ValueError` raised with message including `"grpc"`.
- `tests/test_server.py::test_fastmcp_port_configured_from_env` — patch `os.environ` with `PORT=9999`; re-import (or use importlib.reload) so module-level env reading runs; assert `mcp.settings.port == 9999`.

**Note on module-level env reading:** The `mcp = FastMCP(...)` call at module level means `PORT`/`HOST` are read once at import time. Tests that need to vary these values should either mock at module level before import or use `importlib.reload`. The test for `PORT` configuration should use the latter pattern — document this in the test comment.

#### T15.3 — Update `.env.example` (DONE)
**File:** `.env.example`

Append the following block after the existing optional URL overrides:

```
# Transport mode (stdio for local Claude Desktop/Code, http for hosted deployment)
# MCP_TRANSPORT=stdio

# HTTP mode settings (only used when MCP_TRANSPORT=http)
# PORT=8000
# HOST=0.0.0.0
```

No tests — this is a documentation file.

#### T15.4 — Update `README.md` with Hosted Deployment section (DONE)
**File:** `README.md`

Add a new top-level section `## Hosted Deployment` after the existing local client configuration sections. The section should cover:

1. **Prerequisites:** `MCP_TRANSPORT=http` and `PORT` env vars; ensure `uvicorn` is installed (it is if installed from `pyproject.toml`).
2. **Running the server:** command to start in HTTP mode, confirming it binds on the configured port.
3. **Reverse proxy / tunnel:** note that a reverse proxy or Cloudflare Tunnel should expose the port over HTTPS.
4. **Connecting clients:** Claude.ai and ChatGPT connect via the public HTTPS URL (e.g. `https://bullhorn-mcp.example.com/mcp`) in their connector/tool settings.

No tests — this is documentation.

---

### Sprint 15 End-to-End Tests

- `tests/test_server.py::test_sprint15_e2e_http_mode_startup` — patch `MCP_TRANSPORT=http` and `PORT=8001` in env; mock `mcp.run`; call `main()`; assert `mcp.run` was called with `transport="streamable-http"` and that `mcp.settings.port` equals `8001` (verifying the port env var propagated to FastMCP at construction time).

---

## Full Regression Test Suite (All Sprints Complete)

After all sprints are implemented, run the complete test suite:

```bash
.venv/bin/pytest
```

Expected: all pre-existing tests pass unchanged (US-21 / FR-10) plus all new tests introduced in Sprints 1-15.

Key regression checks:
- `tests/test_server.py` — all existing `list_jobs`, `list_candidates`, `get_job`, `get_candidate`, `search_entities`, `query_entities` tests pass.
- `tests/test_client.py` — all existing `search`, `query`, `get` tests pass.
- `tests/test_auth.py` — all auth flow tests pass unchanged.
- `tests/test_config.py` — all config tests pass unchanged.

---

## Dependency Notes

- **Sprint 15 introduces one new third-party dependency:** `uvicorn>=0.30.0`, required by the MCP SDK's `streamable-http` transport. All other sprints (1-14) have no new third-party packages — fuzzy matching uses Python's built-in `difflib.SequenceMatcher` and HTTP mocking uses `respx`.
- Sprints 1 and 2 are independent and complete.
- Sprint 3 is the foundation for all write operations (extends `_request()`, adds `create()`).
- Sprint 4 depends on Sprint 3 (`create()` method, `_request()` JSON body support).
- Sprint 5 has no direct dependency on Sprints 3-4 (fuzzy module is standalone), but the MCP tools use `client.search()` which already exists. Can be developed in parallel with Sprint 4.
- Sprint 6 depends on Sprint 3 (`_request()` JSON body support for `update()` and `add_note()`).
- Sprint 7 depends on all previous sprints (orchestrates create, duplicate detection, owner resolution, metadata, and field label resolution).
- Sprint 8 is a standalone bug fix; it depends on Sprint 2 (metadata module) and Sprint 4 (create_contact tool) but does not block or depend on Sprint 7.
- Sprint 16 depends on Sprint 15 (fixes its regressions) and introduces CR9 infrastructure used by Sprint 17.
- Sprint 17 depends on Sprint 16 (CR9's `identity.py` and `IdentityResolutionError`).
- Sprint 18 depends on Sprint 17 (replaces the single-slot cache introduced in Sprint 16; all Sprint 17 callers of `resolve_caller()` are unaffected — signature unchanged).

---

## Sprint 16: Fix Sprint 15 Test Regressions + CR9 Identity Resolution — COMPLETE

**Tag:** v0.0.16
**Change requests:** CR9.md (new); fixes Sprint 15 regressions
**User stories:** None directly (CR9 is infrastructure; no user stories are modified in this sprint)
**Dependency:** Sprint 15 complete

**What was delivered:**
- Fixed 4 Sprint 15 test regressions caused by FastMCP 3.x API changes + post-tag Entra OIDC commits:
  - `test_server_has_tools` — switched from removed `_tool_manager._tools` to `asyncio.run(mcp.list_tools())`.
  - `test_main_http_transport` — updated assertion to include `host=ANY, port=ANY` kwargs.
  - `test_fastmcp_port_configured_from_env` — assert `_port` module-level var instead of removed `mcp.settings.port`.
  - `test_sprint15_e2e_http_mode_startup` — mock `OIDCProxy` to prevent real HTTP calls during reload; assert `_port` var; include host/port in `mcp.run` assertion; wrap restore reload in `patch.dict(MCP_TRANSPORT=stdio)` to guard against stale env.
- Created `src/bullhorn_mcp/identity.py` with `IdentityResolutionError` and `resolve_caller(client)`. `get_access_token` is a module-level import so tests patch `bullhorn_mcp.identity.get_access_token` (use site). Resolves authenticated user's email from Entra JWT claims → Bullhorn CorporateUser query. Module-level cache (single-user process assumption). `_reset_caller_cache()` helper for test isolation.
- Created `tests/test_identity.py` with 9 tests covering all acceptance criteria from CR9. The `fields` query-param assertion uses `parse_qs` on the parsed URL, not a full-URL substring check.
- 229 tests passing (220 pre-existing fixed + 9 new identity tests).
- Review learnings: always patch at the use site (`bullhorn_mcp.identity.get_access_token`), not the definition site; restore reloads that touch HTTP mode must pin `MCP_TRANSPORT=stdio` explicitly.

### Background

Two independent work items are bundled here because both are small and the regression fixes are prerequisites for a clean baseline before adding new capability.

**Regression fixes** — Four Sprint 15 tests broke after post-tag Entra OIDC commits (see regression note in Current Status). The tests must be fixed so they accurately reflect the current server behaviour before new code is added.

**CR9** — The server authenticates users via Microsoft Entra but does not use the authenticated identity anywhere. CR9 adds a new module (`identity.py`) with `resolve_caller()` which extracts the user's email from the Entra ID token and resolves it to a Bullhorn CorporateUser record. The resolved identity is cached per server process. This is infrastructure only — no existing tools are changed in this sprint.

### Tasks

#### T16.1 — Fix `test_server_has_tools` (Sprint 15 regression)
**File:** `tests/test_server.py`

FastMCP removed the `_tool_manager._tools` internal attribute. Update the test to use the current FastMCP public API for listing registered tools.

First, inspect the FastMCP object at runtime (e.g. `dir(server.mcp)`) to find the correct public attribute or method. Likely candidates: `mcp.list_tools()` (async) or a tools dict accessible via a public attribute. Confirm by reading the installed FastMCP source.

Update `test_server_has_tools` to assert the same set of 16 tool names using the correct API.

- **Unit test:** `tests/test_server.py::TestMCPServerSetup::test_server_has_tools` — must pass after fix; still asserts all 16 registered tool names.

#### T16.2 — Fix `test_main_http_transport` (Sprint 15 regression)
**File:** `tests/test_server.py`

The `main()` implementation was updated: `mcp.run()` is now called with `host=` and `port=` kwargs in addition to `transport=`. The test asserted `mock_run.assert_called_once_with(transport="streamable-http")` which no longer matches.

Update the assertion to use `assert_called_once_with(transport="streamable-http", host=mock.ANY, port=mock.ANY)` (or pin the exact host/port values if they are deterministic in the test environment). The goal is to assert the transport argument without brittlely asserting the specific host/port, since those come from env vars already tested elsewhere.

- **Unit test:** `tests/test_server.py::TestSprint15HttpTransport::test_main_http_transport` — must pass; asserts `transport="streamable-http"` is forwarded.

#### T16.3 — Fix `test_fastmcp_port_configured_from_env` (Sprint 15 regression)
**File:** `tests/test_server.py`

FastMCP no longer exposes `mcp.settings.port`. Find the correct attribute by inspecting the installed FastMCP version. Options: `mcp._port`, `mcp.port`, or the attribute may be on a different object. If FastMCP offers no public attribute for the configured port, assert indirectly — e.g. that the `_port` module-level variable in `server.py` equals `9999` after reload with `PORT=9999`.

Update the assertion accordingly.

- **Unit test:** `tests/test_server.py::TestSprint15HttpTransport::test_fastmcp_port_configured_from_env` — must pass; asserts `PORT=9999` env var propagated correctly at module load.

#### T16.4 — Fix `test_sprint15_e2e_http_mode_startup` (Sprint 15 regression)
**File:** `tests/test_server.py`

`importlib.reload(server_module)` now triggers `_build_auth()` which raises `ValueError` when Entra env vars are absent. The test must set the required Entra env vars in the patched environment before reloading, so `_build_auth()` can construct an `OIDCProxy` without error (or mock `_build_auth` to return `None`).

The simpler approach: patch `_build_auth` to return `None` during the reload (using `patch` as a context manager before the reload call), then assert `mcp.run` was called with `transport="streamable-http"`.

Alternatively, set dummy Entra env vars (`ENTRA_TENANT_ID=test`, `ENTRA_CLIENT_ID=test`, `ENTRA_CLIENT_SECRET=test`, `MCP_BASE_URL=https://test`) in the `monkeypatch` env before reload — this avoids needing to mock `OIDCProxy` construction. Confirm which approach is less fragile.

- **Unit test:** `tests/test_server.py::TestSprint15HttpTransport::test_sprint15_e2e_http_mode_startup` — must pass; asserts HTTP mode env triggers HTTP transport at startup.

#### T16.5 — Create `src/bullhorn_mcp/identity.py` with `resolve_caller()`
**File:** `src/bullhorn_mcp/identity.py` (new)

**`IdentityResolutionError`**
- Custom exception extending `Exception`.
- Defined in `identity.py` (no shared exceptions module needed at this stage).

**`resolve_caller(client: BullhornClient) -> dict`**
- Imports `get_access_token` from `fastmcp.server.dependencies`.
- If `get_access_token()` returns `None`, raises `IdentityResolutionError("No authentication token available")`.
- Extracts `email` from `token.claims`. Falls back to `preferred_username` if `email` is absent. If neither is present, raises `IdentityResolutionError("No email claim found in token")`.
- Queries Bullhorn: `client.query(entity="CorporateUser", where=f"email='{email}'", fields="id,firstName,lastName,email")`.
  - **Important:** Do NOT include `department` in the fields list (per CR9 AC-5 and the lesson from Sprint 10 / CR3).
- Exactly one result → return `{"id": int, "firstName": str, "lastName": str, "email": str}`.
- Zero results → raises `IdentityResolutionError(f"No Bullhorn CorporateUser found for email '{email}'")`
- Multiple results → raises `IdentityResolutionError(f"Multiple Bullhorn CorporateUsers found for email '{email}' — expected exactly one")`

**Caching**
- Module-level cache: `_resolved_caller: dict | None = None`.
- On first successful call, store result in `_resolved_caller`. Subsequent calls return the cached dict without querying Bullhorn.
- The cache is per server process — acceptable because the server runs as a single-user systemd service behind Cloudflare Tunnel.
- For test isolation, expose `_reset_caller_cache()` (or allow direct module-level reset via `identity._resolved_caller = None`) so tests can clear the cache between runs.

**No changes to existing tools** — `resolve_caller()` is importable but not called by any tool in this sprint.

#### T16.6 — Tests for `identity.py`
**File:** `tests/test_identity.py` (new)

All tests use `respx` for httpx mocking (consistent with existing test files) and `unittest.mock.patch` for `get_access_token`.

- `test_resolve_caller_success` — mock `get_access_token()` returning a token with `email` claim; mock CorporateUser query returning one result; assert returned dict is `{"id": 1, "firstName": "Beau", "lastName": "Warren", "email": "beau@thepanel.com"}`.
- `test_resolve_caller_no_token` — mock `get_access_token()` returning `None`; assert `IdentityResolutionError` raised with "No authentication token available".
- `test_resolve_caller_no_email_claim` — mock token with no `email` and no `preferred_username`; assert `IdentityResolutionError` raised with "No email claim found".
- `test_resolve_caller_fallback_to_preferred_username` — mock token with no `email` but `preferred_username` = "beau@thepanel.com"; mock CorporateUser query; assert query uses "beau@thepanel.com".
- `test_resolve_caller_no_match` — mock CorporateUser query returning empty list; assert `IdentityResolutionError` raised with "No Bullhorn CorporateUser found".
- `test_resolve_caller_multiple_matches` — mock CorporateUser query returning two results; assert `IdentityResolutionError` raised with "Multiple Bullhorn CorporateUsers found".
- `test_resolve_caller_cached` — call `resolve_caller()` twice; assert CorporateUser query endpoint called exactly once (cache hit on second call).
- `test_resolve_caller_query_fields_no_department` — mock CorporateUser query; call `resolve_caller()`; assert the `fields` query parameter sent to Bullhorn does not contain `"department"`.

### Sprint 16 End-to-End Test

- `tests/test_identity.py::test_resolve_caller_e2e_full_flow` — mock `get_access_token()` returning a token with `email = "beau@thepanel.com"`, mock CorporateUser query returning one result, reset cache before test; assert `resolve_caller()` returns the expected dict; call again and assert the HTTP endpoint was only called once (cache works).

### Expected test count after Sprint 16

Current passing: 216. Regression fixes change 4 failing tests to passing (no new tests). New `test_identity.py` adds 9 tests. **Expected: 229 tests passing, 0 failing.**

---

## Sprint 17: CR10 — Owner Stamping from Authenticated User

**Change request:** CR10.md
**User stories affected:** US-1 (create company), US-2 (create contact), US-4 (owner required → optional)
**Dependency:** Sprint 16 complete (requires `resolve_caller` and `IdentityResolutionError` from `identity.py`)

### Background

Currently `create_contact` validates that `owner` is present and returns an error if absent. `create_company` does not require owner. CR10 changes both tools: if the caller does not provide `owner`, the server automatically sets it to the authenticated user's Bullhorn CorporateUser (resolved via `resolve_caller()` from Sprint 16). If the caller explicitly provides `owner`, that value is honoured without override.

This removes friction for both consultants (who are already authenticated) and automated agents (who must otherwise be configured with owner IDs).

`bulk_import` and `update_record` are **not affected** — bulk import has its own owner logic, and update is a deliberate field change.

### Tasks

#### T17.1 — Make `owner` optional in `create_contact`; auto-populate from authenticated user
**File:** `src/bullhorn_mcp/server.py`

Current behaviour: if `"owner"` not in `fields`, returns `{"error": "owner is required"}`.

New behaviour:
```python
# Import at top of server.py:
from .identity import resolve_caller, IdentityResolutionError

# In create_contact, replace the "owner is required" guard:
if "owner" not in fields:
    try:
        caller = resolve_caller(get_client())
        fields = dict(fields)  # don't mutate input
        fields["owner"] = {"id": caller["id"]}
    except IdentityResolutionError as e:
        return format_response({
            "error": "identity_resolution_failed",
            "message": str(e),
            "hint": "Provide an explicit 'owner' field or check that your email matches a Bullhorn CorporateUser."
        })
```

The auto-populated `owner` (`{"id": caller["id"]}`) is set before the `clientCorporation` validation and before `client.resolve_owner()`, so it flows through the existing `resolve_owner()` passthrough path (`{"id": int}` → returned unchanged) and then through duplicate detection and `client.create()` unchanged.

If `owner` IS present, the existing `resolve_owner()` path handles it (string name, `{"id": int}`, ambiguous results) exactly as before. The auto-populated path and the explicit-owner path both converge at `client.resolve_owner()` — no special-casing is needed.

Update the `create_contact` docstring to document that `owner` is optional and describe the auto-population behaviour.

- **Unit test:** `tests/test_server.py::test_create_contact_owner_auto_populated` — mock `resolve_caller()` returning `{"id": 42, ...}`; call `create_contact({..., no owner})` with mocked duplicate search (no results) and mocked PUT/GET; assert PUT payload contains `"owner": {"id": 42}`.
- **Unit test:** `tests/test_server.py::test_create_contact_explicit_owner_dict_wins` — provide `owner: {"id": 99}` in fields; assert `resolve_caller()` is NOT called (patch and assert no calls); assert PUT payload contains `"owner": {"id": 99}`.
- **Unit test:** `tests/test_server.py::test_create_contact_explicit_owner_name_wins` — provide `owner: "Maryrose Lyons"` in fields; assert `resolve_owner()` is called, `resolve_caller()` is NOT called; existing disambiguation behaviour preserved.
- **Unit test:** `tests/test_server.py::test_create_contact_identity_resolution_fails` — mock `resolve_caller()` raising `IdentityResolutionError("No authentication token available")`; call without `owner`; assert response contains `"error": "identity_resolution_failed"` and the hint.
- **Unit test:** `tests/test_server.py::test_create_contact_no_owner_required_error_gone` — call without `owner` with successful identity resolution; assert response does NOT contain `"owner is required"`.
- **Payload audit test:** `tests/test_server.py::test_create_contact_auto_owner_payload_no_leak` — when owner is auto-populated, assert PUT body contains only `"owner": {"id": int}` from the resolved identity — no `firstName`, `lastName`, or `email` from the CorporateUser record.

#### T17.2 — Make `owner` optional in `create_company`; auto-populate from authenticated user
**File:** `src/bullhorn_mcp/server.py`

Apply the same pattern as T17.1 to `create_company`. If `owner` is absent from `fields`, call `resolve_caller(get_client())` and inject `{"id": caller["id"]}` only — not the full caller dict. If present, use it as-is (no name resolution — `create_company` does not currently use `resolve_owner()`; maintain this behaviour).

`create_company` currently does NOT validate `owner` — it passes all fields straight to `client.create()` after label resolution. The change is additive: prepend the auto-population block before `resolved = get_metadata().resolve_fields(...)`.

Update the `create_company` docstring to document that `owner` is optional.

- **Unit test:** `tests/test_server.py::test_create_company_owner_auto_populated` — mock `resolve_caller()` returning `{"id": 42, "firstName": "Beau", "lastName": "Warren", "email": "beau@thepanel.com"}`; call `create_company({"name": "Acme"})` with mocked PUT/GET; assert PUT payload contains `"owner": {"id": 42}`.
- **Payload audit test:** `tests/test_server.py::test_create_company_auto_owner_payload_no_leak` — same setup; assert PUT body key `"owner"` equals exactly `{"id": 42}` with no additional CorporateUser fields (`firstName`, `lastName`, `email`). This is the Sprint 9 pattern (known failure pattern #4) applied to create_company.
- **Unit test:** `tests/test_server.py::test_create_company_explicit_owner_wins` — provide `owner: {"id": 99}`; assert `resolve_caller()` is NOT called; PUT payload has `"owner": {"id": 99}`.
- **Unit test:** `tests/test_server.py::test_create_company_identity_resolution_fails` — mock `resolve_caller()` raising `IdentityResolutionError`; assert `"error": "identity_resolution_failed"` response.

#### T17.3 — Confirm `bulk_import` and `update_record` are unaffected
**File:** `src/bullhorn_mcp/server.py`, `src/bullhorn_mcp/bulk.py`

Code review only. Confirm:
- `bulk_import` calls `BulkImporter` which calls `client.resolve_owner()` directly — `resolve_caller()` is never called in this path.
- `update_record` does not auto-populate `owner` — updating owner is a deliberate caller action.

Add a comment to `bulk_import` and `update_record` in `server.py` noting that CR10 owner stamping intentionally does not apply.

No new logic changes. Add one regression test for each:
- **Unit test:** `tests/test_server.py::test_bulk_import_does_not_call_resolve_caller` — call `bulk_import` with an `owner` in the contacts list; assert `resolve_caller()` is never invoked.
- **Unit test:** `tests/test_server.py::test_update_record_does_not_auto_populate_owner` — call `update_record` without an `owner` field; assert `resolve_caller()` is never invoked, and the POST body does not contain `owner`.

### Sprint 17 End-to-End Tests

- `tests/test_server.py::test_e2e_create_contact_no_owner_auto_populated` — mock: `get_access_token()` returning token with `email = "beau@thepanel.com"`, CorporateUser query returning `{"id": 7}`, ClientContact search (no duplicates), ClientContact PUT (capture body), ClientContact GET; call `create_contact({"firstName": "Jane", "lastName": "Doe", "clientCorporation": {"id": 1}})` without owner; assert PUT body has `owner: {"id": 7}` and response has `changedEntityId`.
- `tests/test_server.py::test_e2e_create_contact_explicit_owner_overrides` — same mocks except token/CorporateUser query not set up; call with `owner: {"id": 99}`; assert PUT body has `owner: {"id": 99}`, `resolve_caller()` never called.
- `tests/test_server.py::test_e2e_create_company_no_owner_auto_populated` — same pattern for company creation; assert PUT body contains `owner: {"id": 7}`.

### Expected test count after Sprint 17

Previous: 229 tests. New tests in T17.1 (6), T17.2 (4), T17.3 (2), E2E (3) = 15 new tests. **Expected: 244 tests passing, 0 failing.**

(T17.2 count increased from 3 → 4 to add the missing `test_create_company_auto_owner_payload_no_leak` payload audit test, per the Sprint 9 pattern for owner data leakage.)

### Sprint 17 completion note

All 15 new tests added plus updates to 5 existing tests that previously assumed owner was absent would error. 244 tests passing. Key changes:
- `create_contact` no longer requires `owner` — auto-populated from `resolve_caller()` if absent
- `create_company` auto-populates `owner` from `resolve_caller()` if absent
- `bulk_import` and `update_record` explicitly commented as unaffected by CR10
- `test_create_contact_missing_owner` updated: now tests `IdentityResolutionError` path (identity_resolution_failed error code)
- Existing `TestCreateCompany` tests patched to provide `resolve_caller` mock since owner is now auto-stamped

**Sprint 17 review cycle note:** During the review/iterate cycle, three test issues were identified and fixed:
1. `test_create_company_label_resolution` had both assertions dropped instead of updated to include the auto-injected `owner` key — restored with correct expected values
2. `test_create_company_success` was missing `mock_client.create.assert_called_once_with(...)` — restored with `owner: {"id": 1}` included
3. `test_create_contact_auto_owner_payload_no_leak` contained a vacuous `or True` assertion — removed

Pattern: when adding auto-injection before `resolve_fields`, the `resolve_fields.assert_called_once_with` arguments must include the injected key.

---

## Sprint 18: CR11 — Per-user Identity Cache (Fix First-Writer-Wins Bug)

**Change request:** CR11.md
**User stories affected:** None directly — correctness fix to infrastructure introduced in Sprint 16/CR9. Ensures FR-11 (HTTP multi-user deployment) and NFR-3 (resilience) are correctly satisfied.
**Dependency:** Sprint 17 complete (Sprint 16 created `identity.py` with the single-slot cache that this sprint replaces)

### Background

`identity.py` stores the resolved Bullhorn CorporateUser in a single module-level slot (`_resolved_caller: dict | None = None`). This was intentional when CR9 was written under the assumption that the server runs as a single-user process. However, Sprint 15 added HTTP transport (`MCP_TRANSPORT=http`), which allows multiple consultants to share a single server process. Once any user resolves their identity, every subsequent caller — regardless of their own Entra token — receives the cached identity of the first user.

**Concrete failure mode:** Paul McArdle resolves his identity first. Fergal Keys connects and calls `create_contact`. The cache hits on Paul's entry. Fergal's new contact is created with Paul as owner. No error or warning is surfaced.

The fix keys the cache by the authenticated user's Entra `sub` claim (a stable, unique, per-user identifier already confirmed present in the token). `sub` is extracted before `email` — its absence is itself an error (a token without `sub` cannot be reliably cached).

### File affected

`src/bullhorn_mcp/identity.py` — targeted change; no other files require modification.

### Tasks

#### T18.1 — Replace single-slot cache with per-user dict keyed by `sub`
**File:** `src/bullhorn_mcp/identity.py`

**Before:**
```python
_resolved_caller: dict | None = None

def resolve_caller(client):
    global _resolved_caller
    if _resolved_caller is not None:
        return _resolved_caller
    ...
    _resolved_caller = results[0]
    return _resolved_caller
```

**After:**
```python
_caller_cache: dict[str, dict] = {}  # keyed by token claims["sub"]

def resolve_caller(client):
    token = get_access_token()
    if token is None:
        raise IdentityResolutionError("No authentication token available")

    claims = getattr(token, "claims", {}) or {}
    sub = claims.get("sub")
    if not sub:
        raise IdentityResolutionError("No 'sub' claim found in token — cannot key identity cache")

    if sub in _caller_cache:
        return _caller_cache[sub]

    email = claims.get("email") or claims.get("preferred_username")
    if not email:
        raise IdentityResolutionError("No email claim found in token")

    results = client.query(
        entity="CorporateUser",
        where=f"email='{email}'",
        fields="id,firstName,lastName,email",
    )

    if len(results) == 0:
        raise IdentityResolutionError(f"No Bullhorn CorporateUser found for email '{email}'")
    if len(results) > 1:
        raise IdentityResolutionError(
            f"Multiple Bullhorn CorporateUsers found for email '{email}' — expected exactly one"
        )

    _caller_cache[sub] = results[0]
    return _caller_cache[sub]
```

Key changes from current code:
- `sub` is extracted first (before `email`); its absence raises `IdentityResolutionError` immediately.
- Cache lookup uses `sub in _caller_cache` (dict key presence) rather than `_resolved_caller is not None`.
- `email` extraction and the Bullhorn query happen only on a cache miss.
- The `_resolved_caller` global variable is removed; `_caller_cache` replaces it.

Update the module-level comment to remove the "single-user service" caveat and document that the cache is safe for multi-user HTTP deployments.

- **Unit test:** `tests/test_identity.py::test_resolve_caller_no_sub_claim` — mock token with no `sub` claim (but `email` present); assert `IdentityResolutionError` raised with message referencing `sub`.
- **Unit test:** `tests/test_identity.py::test_resolve_caller_multi_user_isolation` — mock two tokens with distinct `sub` values and distinct emails; call `resolve_caller()` for each (reset cache between calls is NOT required — they should use different cache slots); assert each returns its own CorporateUser dict and Bullhorn is queried exactly twice.
- **Unit test:** `tests/test_identity.py::test_resolve_caller_multi_user_cache_hit` — call `resolve_caller()` twice with the same `sub` value; assert Bullhorn CorporateUser query endpoint called exactly once.
- **Unit test:** `tests/test_identity.py::test_reset_caller_cache_clears_all` — populate `_caller_cache` with two entries (two distinct `sub` values); call `_reset_caller_cache()`; assert both entries are gone (cache is empty).

#### T18.2 — Update `_reset_caller_cache()` to clear the dict
**File:** `src/bullhorn_mcp/identity.py`

```python
def _reset_caller_cache() -> None:
    """Clear the per-user identity cache. Used in tests for isolation."""
    global _caller_cache
    _caller_cache.clear()
```

The signature is unchanged. Callers in `tests/test_identity.py` that currently call `_reset_caller_cache()` continue to work without modification — clearing a dict vs setting a var to `None` is transparent to callers.

#### T18.3 — Verify existing tests pass unchanged
**File:** `tests/test_identity.py`

The 9 existing tests were written for single-user behaviour, which is a subset of the new multi-user behaviour. All should pass without modification because:
- `test_resolve_caller_success` — provides `email` in claims; `sub` must now also be present. Update the mock token fixture to include `sub` if it doesn't already. (Inspect existing test setup to confirm.)
- `test_resolve_caller_cached` — calls twice with the same token; the `sub`-keyed cache still hits on the second call. Passes unchanged if the mock token includes `sub`.
- `test_resolve_caller_no_token` — `get_access_token()` returns `None`; first thing checked is still the token. Passes unchanged.
- `test_resolve_caller_no_email_claim` — token is present but has no `email`/`preferred_username`. Now the code also checks `sub` first — this test must also include `sub` in the mock token or it will hit the new `sub` guard first. Update the mock to include `sub` so the test still exercises the no-email path.
- All others — confirm no changes needed to the mock token structure.

If any existing test's mock token lacks `sub`, add `"sub": "test-sub-value"` to that token's claims dict. This is a test-fixture update only, not a behaviour change.

### Sprint 18 End-to-End Tests

- `tests/test_identity.py::test_resolve_caller_multi_user_isolation` — described in T18.1. This doubles as the E2E test for the multi-user scenario: two distinct users, two distinct CorporateUser lookups, two correct cached results.

### What was delivered

- `src/bullhorn_mcp/identity.py`: replaced `_resolved_caller: dict | None = None` with `_caller_cache: dict[str, dict] = {}` keyed by Entra `sub` claim. `sub` is now extracted before `email` — its absence raises `IdentityResolutionError` immediately. `_reset_caller_cache()` now calls `.clear()`. Module comment updated to remove the "single-user service" assumption.
- `tests/test_identity.py`: added `"sub"` claim to all existing mock token fixtures (required by the new `sub`-first extraction order). Added 4 new tests: `test_resolve_caller_no_sub_claim`, `test_resolve_caller_multi_user_isolation`, `test_resolve_caller_multi_user_cache_hit`, `test_reset_caller_cache_clears_all`.
- `tests/test_server.py`: updated Sprint 17 E2E token fixtures for `test_e2e_create_contact_no_owner_auto_populated` and `test_e2e_create_company_no_owner_auto_populated` to include `"sub": "sub-beau"` — these tests mock `get_access_token` directly and call the real `identity.py`, so they also needed the `sub` claim.
- **248 tests passing, 0 failing.**
