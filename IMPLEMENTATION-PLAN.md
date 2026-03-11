# Implementation Plan: Bullhorn MCP Record Management Expansion

## PRD Validation Notes

All 10 functional requirements (FR-1 through FR-10) are covered by user stories US-1 through US-21. No user stories were found that implement features outside the stated requirements.

**Minor gap noted:** NFR-4 requires field label resolution in all tools that accept field names (including create operations). US-15 explicitly covers this for `update_record`, but US-1 and US-2 (create operations) have no acceptance criterion for label resolution. This is handled as an implementation note within Sprint 4 and Sprint 5 tasks — label resolution via the metadata module will be applied consistently to create operations per NFR-4, without requiring a new user story.

---

## Current Status

| Sprint | Status | Summary |
|--------|--------|---------|
| Sprint 1 | **COMPLETE** | Convenience listing tools — 71 tests passing, tagged v0.0.1 |
| Sprint 2 | **COMPLETE** | Field Metadata and Label Resolution — 90 tests passing, tagged v0.0.2 |
| Sprint 3 | **NEXT** | Create ClientCorporation |
| Sprint 4 | PENDING | Create ClientContact with Owner Resolution |
| Sprint 5 | PENDING | Duplicate Detection |
| Sprint 6 | PENDING | Update Records and Add Notes |
| Sprint 7 | PENDING | Bulk Import |

---

## Architecture Overview

### New modules to be created
- `src/bullhorn_mcp/metadata.py` — Field metadata cache and label/API-name resolver (`BullhornMetadata`)
- `src/bullhorn_mcp/fuzzy.py` — Fuzzy string matching and confidence scoring for duplicate detection
- `src/bullhorn_mcp/bulk.py` — Bulk import orchestration logic

### Existing modules to be extended
- `src/bullhorn_mcp/client.py` — Add `create()`, `update()`, `add_note()`, `resolve_owner()` methods; extend `_request()` to support JSON request bodies
- `src/bullhorn_mcp/server.py` — Add 9 new MCP tool functions

### New test files to be created
- `tests/test_metadata.py`
- `tests/test_fuzzy.py`
- `tests/test_bulk.py`

### Existing test files to be extended
- `tests/test_client.py` — New client methods
- `tests/test_server.py` — New server tools

---

## Sprint 1: Convenience Listing Tools — COMPLETED

**User stories:** US-19, US-20, US-21

**What was delivered:** Extended `DEFAULT_FIELDS` for `ClientContact` (added `owner`, `status`, `title`, `dateAdded`, `clientCorporation`) and `ClientCorporation` (added `dateAdded`). Added `list_contacts` and `list_companies` MCP tools in `server.py`, mirroring the existing `list_candidates`/`list_jobs` pattern. Both tools support optional `query`, `status`, `limit`, and `fields` parameters. All 71 tests pass (63 pre-existing + 8 new). Tests are in `test_server.py` (TestListContacts: 3 tests, TestListCompanies: 2 tests, TestSprint1E2E: 1 test) and `test_client.py` (2 default-fields assertions).

---

## Sprint 2: Field Metadata and Label Resolution

**What was delivered:** Created `BullhornMetadata` class (`metadata.py`) with session-level caching, bidirectional label↔API-name resolution (`resolve_label_to_api`, `resolve_api_to_label`), and `resolve_fields()` for converting label-keyed dicts to API names. Added `get_entity_fields` MCP tool supporting full field listing and label/api_name lookup in either direction. Wired `_metadata` global and `get_metadata()` helper into `server.py`. Updated `reset_client` test fixture and `test_server_has_tools` assertion. 90 tests passing (71 pre-existing + 14 new metadata tests + 5 new server tests).

**User stories:** US-17, US-18
**Goal:** Create `BullhornMetadata` class with session-level caching. Add `get_entity_fields` MCP tool. Implement bidirectional label↔API-name resolution used internally by other tools.

### Tasks

#### T2.1 — Create `metadata.py` with `BullhornMetadata` class
**File:** `src/bullhorn_mcp/metadata.py` (new)
- `BullhornMetadata(client: BullhornClient)` stores a dict cache keyed by entity type.
- `get_fields(entity: str) -> list[dict]` — calls `client.get_meta(entity)`, parses `fields` array from response, caches result. Returns list of `{"name": str, "label": str, "type": str, "required": bool}`.
- `resolve_label_to_api(entity: str, label: str) -> str | None` — returns API field name for a given label (case-insensitive).
- `resolve_api_to_label(entity: str, api_name: str) -> str | None` — returns label for a given API field name.
- `resolve_fields(entity: str, fields: dict) -> dict` — given a dict of `{field_name_or_label: value}`, returns a new dict with all keys resolved to API field names. Keys that are already API names pass through unchanged.
- **Unit test:** `tests/test_metadata.py::test_get_fields_parses_response` — mock `/meta/ClientContact`, assert returns list with expected dicts.
- **Unit test:** `tests/test_metadata.py::test_get_fields_caches_result` — call `get_fields` twice, assert HTTP only called once.
- **Unit test:** `tests/test_metadata.py::test_resolve_label_to_api` — assert `"Consultant"` resolves to `"recruiterUserID"`.
- **Unit test:** `tests/test_metadata.py::test_resolve_api_to_label` — assert `"clientCorporation"` resolves to `"Company"`.
- **Unit test:** `tests/test_metadata.py::test_resolve_label_case_insensitive` — assert `"consultant"` resolves same as `"Consultant"`.
- **Unit test:** `tests/test_metadata.py::test_resolve_fields_mixed_keys` — dict with one label and one API name both resolve correctly.
- **Unit test:** `tests/test_metadata.py::test_resolve_fields_unknown_key_passes_through` — key not in metadata returns unchanged.

#### T2.2 — Add `get_entity_fields` MCP tool
**File:** `src/bullhorn_mcp/server.py`
- Parameters: `entity: str`, `label: str | None = None`, `api_name: str | None = None`.
- If neither `label` nor `api_name` provided: return full field list as JSON.
- If `label` provided: return `{"label": label, "api_name": resolved_or_null}`.
- If `api_name` provided: return `{"api_name": api_name, "label": resolved_or_null}`.
- **Unit test:** `tests/test_server.py::test_get_entity_fields_returns_list` — assert returns JSON list of field dicts.
- **Unit test:** `tests/test_server.py::test_get_entity_fields_resolve_label` — assert correct api_name returned.
- **Unit test:** `tests/test_server.py::test_get_entity_fields_resolve_api_name` — assert correct label returned.
- **Unit test:** `tests/test_server.py::test_get_entity_fields_unresolvable_label` — assert `null` api_name returned without error.

#### T2.3 — Wire `BullhornMetadata` into `get_client()`
**File:** `src/bullhorn_mcp/server.py`
- Instantiate a module-level `_metadata: BullhornMetadata | None = None`.
- Add `get_metadata() -> BullhornMetadata` helper that creates and returns `BullhornMetadata(get_client())`.
- **Test fixture update:** The existing `reset_client` fixture in `tests/test_server.py` resets `server._client = None`. Update it to also reset `server._metadata = None` to prevent metadata cache leaking between tests.
- **Test update:** The existing `test_server_has_tools` test only asserts the original 6 tools. Update it to also assert that `list_contacts` and `list_companies` are registered (these were added in Sprint 1 but the test was not updated to check for them).
- **MCP instructions update:** The `server.py` MCP instructions string currently reads `"Query Bullhorn CRM data - jobs, candidates, and placements"`. Update this to reflect the expanded capabilities (contacts, companies, field metadata) now that the server covers more than read-only job/candidate queries.

### Sprint 2 End-to-End Tests
- `tests/test_metadata.py::test_sprint2_e2e_full_resolution_cycle` — mock meta endpoint with realistic ClientContact field list; call `get_fields`, then `resolve_label_to_api("Consultant")`, then `resolve_api_to_label("recruiterUserID")`; assert round-trip is consistent.

---

## Sprint 3: Create ClientCorporation

**User stories:** US-1 (partial — company creation only)
**Goal:** Add `create()` method to `BullhornClient`. Add `create_company` MCP tool. Lay the foundation for all create/update operations by extending `_request()` to support JSON bodies.

### Tasks

#### T3.1 — Extend `_request()` to support JSON request bodies
**File:** `src/bullhorn_mcp/client.py`
- Add optional `json: dict | None = None` parameter to `_request()`.
- Pass `json=json` to `httpx.Client.request()`.
- Handle 201 status code as success in addition to 200 (Bullhorn returns 200 for PUT creates).
- **Unit test:** `tests/test_client.py::test_request_with_json_body` — mock PUT endpoint, assert JSON body is sent correctly.

#### T3.2 — Add `create()` method to `BullhornClient`
**File:** `src/bullhorn_mcp/client.py`
- `create(entity: str, data: dict) -> dict` — PUT to `/entity/{entity}`, sends `data` as JSON body.
- Returns full response dict (includes `changedEntityId`, `changeType`).
- After create, call `get(entity, changedEntityId)` to return the created record alongside the response.
- Returns `{"changedEntityId": int, "changeType": "INSERT", "data": dict}`.
- **Unit test:** `tests/test_client.py::test_create_returns_insert_response` — mock PUT `/entity/ClientCorporation` returning `{"changedEntityId": 123, "changeType": "INSERT"}`, mock GET `/entity/ClientCorporation/123`, assert method returns combined dict.
- **Unit test:** `tests/test_client.py::test_create_raises_on_api_error` — mock 400 response, assert `BullhornAPIError` raised.

#### T3.3 — Add `create_company` MCP tool
**File:** `src/bullhorn_mcp/server.py`
- Parameters: `fields: dict` (all company fields as a dictionary).
- Calls `client.create("ClientCorporation", fields)`.
- Returns formatted JSON response.
- **Unit test:** `tests/test_server.py::test_create_company_success` — mock create flow, assert returns JSON with `changedEntityId`.
- **Unit test:** `tests/test_server.py::test_create_company_api_error` — assert `"ERROR:"` prefix returned.

### Sprint 3 End-to-End Tests
- `tests/test_server.py::test_sprint3_e2e_create_and_retrieve_company` — mock PUT create then GET retrieve; call `create_company({"name": "Acme", "status": "Prospect"})`; assert response contains `changedEntityId` and `data.name == "Acme"`.

---

## Sprint 4: Create ClientContact with Owner Resolution

**User stories:** US-2, US-4, US-5
**Goal:** Add `resolve_owner()` to client. Add `create_contact` MCP tool that requires owner, resolves consultant names to CorporateUser IDs, and handles disambiguation.

### Tasks

#### T4.1 — Add `resolve_owner()` method to `BullhornClient`
**File:** `src/bullhorn_mcp/client.py`
- `resolve_owner(owner: str | dict) -> dict | list` — if `owner` is already `{"id": int}`, return as-is. If string, search `CorporateUser` entity by name using `query(entity="CorporateUser", where=f"name='{owner}'", fields="id,firstName,lastName,email,department")`.
- If exactly one result: return `{"id": result["id"]}`.
- If multiple results: return the full list of matches (caller must disambiguate).
- If zero results: raise `ValueError(f"No CorporateUser found matching '{owner}'")`
- **Unit test:** `tests/test_client.py::test_resolve_owner_by_id_passthrough` — assert `{"id": 42}` returns unchanged.
- **Unit test:** `tests/test_client.py::test_resolve_owner_by_name_single_match` — mock CorporateUser query, assert returns `{"id": user_id}`.
- **Unit test:** `tests/test_client.py::test_resolve_owner_by_name_multiple_matches` — mock two results, assert returns list.
- **Unit test:** `tests/test_client.py::test_resolve_owner_by_name_no_match` — assert raises `ValueError`.

#### T4.2 — Add `create_contact` MCP tool
**File:** `src/bullhorn_mcp/server.py`
- Parameters: `fields: dict` (all contact fields as a dictionary; `owner` and `clientCorporation` are required).
- Validate `owner` key present in fields; return error if missing.
- Validate `clientCorporation` key present in fields; return error if missing.
- Call `client.resolve_owner(fields["owner"])`.
- If owner resolves to a list (multiple matches): return disambiguation response — do NOT create the record. Return JSON: `{"error": "owner_ambiguous", "matches": [...], "message": "Multiple users found. Specify owner by ID."}`.
- Replace `fields["owner"]` with `{"id": resolved_id}`.
- Apply field label resolution via `get_metadata().resolve_fields("ClientContact", fields)` (NFR-4).
- Call `client.create("ClientContact", resolved_fields)`.
- Returns formatted JSON response.
- **Unit test:** `tests/test_server.py::test_create_contact_success` — mock owner resolution and create flow, assert returns JSON with `changedEntityId`.
- **Unit test:** `tests/test_server.py::test_create_contact_missing_owner` — assert error returned without API calls.
- **Unit test:** `tests/test_server.py::test_create_contact_missing_corporation` — assert error returned without API calls.
- **Unit test:** `tests/test_server.py::test_create_contact_owner_ambiguous` — mock multiple CorporateUser results, assert disambiguation response returned, no create called.
- **Unit test:** `tests/test_server.py::test_create_contact_owner_not_found` — mock zero results, assert error returned.
- **Unit test:** `tests/test_server.py::test_create_contact_owner_by_id` — provide `owner: {"id": 99}`, assert passes through without CorporateUser query.

### Sprint 4 End-to-End Tests
- `tests/test_server.py::test_sprint4_e2e_create_contact_with_name_owner` — mock CorporateUser query (single match), mock ClientContact PUT, mock GET retrieve; call `create_contact({"firstName": "Jane", "lastName": "Doe", "clientCorporation": {"id": 1}, "owner": "Maryrose Lyons"})`; assert response has `changedEntityId` and `data.owner.id` matches resolved user.

---

## Sprint 5: Duplicate Detection

**User stories:** US-6, US-7, US-8 — satisfies NFR-5
**Goal:** Create `fuzzy.py` module with normalization and confidence scoring. Add `find_duplicate_companies` and `find_duplicate_contacts` MCP tools.

### Tasks

#### T5.1 — Create `fuzzy.py` with normalization helpers
**File:** `src/bullhorn_mcp/fuzzy.py` (new)
- `normalize(name: str) -> str` — lowercase, strip legal suffixes (`ltd`, `limited`, `inc`, `incorporated`, `plc`, `corp`, `corporation`, `llc`, `pty`, `co`), strip punctuation, collapse whitespace.
- No standalone `expand_abbreviations` function — acronym handling is done inline in `score_company_match` (see T5.2). A separate function returning a list of expansions would add untested complexity for a narrow case; the inline check is simpler and sufficient.
- **Unit test:** `tests/test_fuzzy.py::test_normalize_strips_ltd` — `"Acme Ltd"` → `"acme"`.
- **Unit test:** `tests/test_fuzzy.py::test_normalize_strips_incorporated` — `"Acme Incorporated"` → `"acme"`.
- **Unit test:** `tests/test_fuzzy.py::test_normalize_case_insensitive` — `"ACME CORP"` → `"acme"`.
- **Unit test:** `tests/test_fuzzy.py::test_normalize_strips_punctuation` — `"Acme, Inc."` → `"acme"`.

#### T5.2 — Implement `score_company_match()` confidence scoring
**File:** `src/bullhorn_mcp/fuzzy.py`
- `score_company_match(query: str, candidate: str) -> float` — returns 0.0–1.0.
- Strategy: normalize both; compute `difflib.SequenceMatcher` ratio on normalized strings. Inline acronym check: if the query is all-uppercase and its length matches the number of words in the candidate, compare query letters against candidate word initials and apply a score bonus if they match. Return clamped float.
- Thresholds: `>= 0.95` → exact, `0.75–0.95` → likely, `0.50–0.75` → possible, `< 0.50` → no match.
- `categorize_score(score: float) -> str` — returns `"exact"`, `"likely"`, `"possible"`, or `"none"`.
- **Unit test:** `tests/test_fuzzy.py::test_score_exact_match` — `"Acme Holdings Ltd"` vs `"Acme Holdings Ltd"` → `>= 0.95`.
- **Unit test:** `tests/test_fuzzy.py::test_score_acronym_match` — `"BNY"` vs `"Bank of New York Mellon"` → `0.75–0.95`.
- **Unit test:** `tests/test_fuzzy.py::test_score_suffix_variation` — `"Acme Ltd"` vs `"Acme Limited"` → `>= 0.95`.
- **Unit test:** `tests/test_fuzzy.py::test_score_unrelated` — `"Acme"` vs `"Globex"` → `< 0.50`.
- **Unit test:** `tests/test_fuzzy.py::test_score_possible_match` — `"Acme Holdings"` vs `"Acme Group"` → `0.50–0.75`.
- **Unit test:** `tests/test_fuzzy.py::test_categorize_score_thresholds` — verify all four categories at boundary values.

#### T5.3 — Implement `score_contact_match()` confidence scoring
**File:** `src/bullhorn_mcp/fuzzy.py`
- `score_contact_match(query_first: str, query_last: str, candidate: dict) -> float` — score against `firstName`/`lastName` fields. Exact name match → 1.0. Normalize and use SequenceMatcher on full name.
- Flag partial match when email differs (attach `"partial_match": true` in result dict upstream).
- **Unit test:** `tests/test_fuzzy.py::test_contact_exact_match` — same first and last → `>= 0.95`.
- **Unit test:** `tests/test_fuzzy.py::test_contact_partial_match` — same name different email → high score but caller flags partial.
- **Unit test:** `tests/test_fuzzy.py::test_contact_no_match` — different name → `< 0.50`.

#### T5.4 — Add `find_duplicate_companies` MCP tool
**File:** `src/bullhorn_mcp/server.py`
- Parameters: `name: str`, `website: str | None = None`, `phone: str | None = None`.
- Calls `client.search("ClientCorporation", query=f"name:{broad_terms}*", fields="id,name,status,phone", count=50)`.
- Applies `score_company_match` to each result.
- Filters results to score `>= 0.5`. Sorts descending by score.
- Returns `{"query": name, "matches": [...], "exact_match": bool}`.
- **Unit test:** `tests/test_server.py::test_find_duplicate_companies_exact` — mock search returning matching company, assert exact_match true.
- **Unit test:** `tests/test_server.py::test_find_duplicate_companies_likely` — mock search returning similar company, assert category "likely".
- **Unit test:** `tests/test_server.py::test_find_duplicate_companies_no_match` — mock empty search results, assert empty matches list.

#### T5.5 — Add `find_duplicate_contacts` MCP tool
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
- `tests/test_fuzzy.py::test_sprint5_e2e_company_duplicate_detection` — call `find_duplicate_companies("BNY")` with mocked search returning `"Bank of New York Mellon"`; assert response has category `"likely"`, confidence in `[0.75, 0.95]`, and `exact_match == false`.
- `tests/test_server.py::test_sprint5_e2e_contact_duplicate_flow` — call `find_duplicate_contacts("John", "Smith", 123)` with mocked search; assert JSON matches structure from PRD section 10.

---

## Sprint 6: Update Records and Add Notes

**User stories:** US-12, US-13, US-14, US-15, US-16
**Goal:** Add `update()` and `add_note()` methods to `BullhornClient`. Add `update_record` and `add_note` MCP tools. Enforce company reassignment guard. Integrate field label resolution.

### Tasks

#### T6.1 — Add `update()` method to `BullhornClient`
**File:** `src/bullhorn_mcp/client.py`
- `update(entity: str, entity_id: int, data: dict) -> dict` — POST to `/entity/{entity}/{entity_id}` with JSON body.
- After update, call `get(entity, entity_id)` to return full record.
- Returns `{"changedEntityId": entity_id, "changeType": "UPDATE", "data": dict}`.
- **Unit test:** `tests/test_client.py::test_update_returns_update_response` — mock POST and GET, assert combined dict returned.
- **Unit test:** `tests/test_client.py::test_update_raises_on_api_error` — mock 400, assert `BullhornAPIError`.

#### T6.2 — Add `update_record` MCP tool
**File:** `src/bullhorn_mcp/server.py`
- Parameters: `entity: str`, `entity_id: int`, `fields: dict`.
- Guard: if `entity == "ClientContact"` and `"clientCorporation"` in `fields`, return error `"Company reassignment is not supported."` without calling API.
- Apply field label resolution: `get_metadata().resolve_fields(entity, fields)`.
- Call `client.update(entity, entity_id, resolved_fields)`.
- Returns formatted JSON.
- **Unit test:** `tests/test_server.py::test_update_record_success` — mock POST+GET, assert returns updated record.
- **Unit test:** `tests/test_server.py::test_update_record_company_reassignment_blocked` — assert error returned without API call.
- **Unit test:** `tests/test_server.py::test_update_record_label_resolution` — mock meta endpoint, provide label key, assert API called with resolved name.
- **Unit test:** `tests/test_server.py::test_update_record_api_error` — assert `"ERROR:"` prefix returned.

#### T6.3 — Add `add_note()` method to `BullhornClient`
**File:** `src/bullhorn_mcp/client.py`
- `add_note(entity: str, entity_id: int, action: str, comments: str) -> dict` — constructs Note payload.
- For `ClientContact`: sets `personReference: {"id": entity_id}` and `commentingPerson: {"id": entity_id}`.
- For `ClientCorporation`: sets `clientCorporation: {"id": entity_id}`.
- Sets `action` and `comments` fields.
- PUT to `/entity/Note`, returns `{"changedEntityId": int, "changeType": "INSERT", "data": dict}`.
- **Unit test:** `tests/test_client.py::test_add_note_to_contact` — mock PUT `/entity/Note`, assert `personReference` set correctly.
- **Unit test:** `tests/test_client.py::test_add_note_to_company` — assert `clientCorporation` set correctly.
- **Unit test:** `tests/test_client.py::test_add_note_raises_on_api_error` — mock 400, assert `BullhornAPIError`.

#### T6.4 — Add `add_note` MCP tool
**File:** `src/bullhorn_mcp/server.py`
- Parameters: `entity: str`, `entity_id: int`, `action: str`, `comments: str`.
- Validate `entity` is `"ClientContact"` or `"ClientCorporation"`; return error otherwise.
- Call `client.add_note(entity, entity_id, action, comments)`.
- Returns formatted JSON.
- **Unit test:** `tests/test_server.py::test_add_note_to_contact_success` — mock note creation, assert returns Note ID.
- **Unit test:** `tests/test_server.py::test_add_note_invalid_entity` — assert error for unsupported entity type.
- **Unit test:** `tests/test_server.py::test_add_note_api_error` — assert `"ERROR:"` prefix returned.

### Sprint 6 End-to-End Tests
- `tests/test_server.py::test_sprint6_e2e_update_then_note` — mock update POST/GET and note PUT; call `update_record("ClientContact", 54321, {"title": "CTO"})`; assert title updated; then call `add_note("ClientContact", 54321, "General Note", "Updated via test")`; assert Note ID returned.

---

## Sprint 7: Bulk Import

**User stories:** US-3, US-9, US-10, US-11
**Goal:** Implement `bulk_import` orchestration. Create `bulk.py` module. Add `bulk_import` MCP tool. Handle on-the-fly company creation, consecutive error halting, and summary generation.

### Tasks

#### T7.1 — Create `bulk.py` with `BulkImporter` class
**File:** `src/bullhorn_mcp/bulk.py` (new)
- `BulkImporter(client: BullhornClient, metadata: BullhornMetadata)` constructor.
- Internal state: `_consecutive_errors: int = 0`.
- `process(companies: list[dict], contacts: list[dict]) -> dict` — top-level method returning full result dict.
- Returns structure: `{"halted": bool, "summary": {...}, "details": {"companies": [...], "contacts": [...]}}`.

#### T7.2 — Implement company processing phase
**File:** `src/bullhorn_mcp/bulk.py`
- `_process_companies(companies: list[dict]) -> dict[str, int]` — returns map of `input_name → bullhorn_id`.
- For each company:
  1. Call `find_duplicate_companies` logic (reuse `score_company_match` from fuzzy module against search results).
  2. If exact match (`>= 0.95`): record as `"existing"`, use existing ID.
  3. If likely/possible match: record as `"flagged"`, use existing ID (do not create), include match confidence.
  4. If no match: call `client.create("ClientCorporation", company_data)`, record as `"created"`.
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
  3. Check owner: call `client.resolve_owner(contact["owner"])`. If ambiguous: record as `"flagged"`.
  4. Run contact duplicate detection using `score_contact_match`.
  5. If exact match: record as `"existing"`.
  6. If no match: call `client.create("ClientContact", ...)`, record as `"created"`.
  7. On `BullhornAPIError`: increment `_consecutive_errors`. If `>= 3`: halt.
  8. On success: reset `_consecutive_errors = 0`.
- **Unit test:** `tests/test_bulk.py::test_process_contacts_resolves_company_from_map` — assert company ID from previous phase used, no extra search.
- **Unit test:** `tests/test_bulk.py::test_process_contacts_creates_company_on_the_fly` — mock company search (no results), mock company create, mock contact create; assert both created.
- **Unit test:** `tests/test_bulk.py::test_process_contacts_skips_existing` — mock contact duplicate detection with exact match; assert status "existing".
- **Unit test:** `tests/test_bulk.py::test_process_contacts_flags_ambiguous_owner` — mock multiple CorporateUser results; assert status "flagged".

#### T7.4 — Implement summary generation
**File:** `src/bullhorn_mcp/bulk.py`
- `_build_summary(company_details: list, contact_details: list) -> dict` — aggregates counts per status for both entity types.
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
- `tests/test_bulk.py::test_sprint7_e2e_full_batch_import` — mock: company search (no results), company create, contact owner resolution, contact search (no results), contact create ×2; call `BulkImporter.process(2 companies, 2 contacts)`; assert `summary.companies.created == 2`, `summary.contacts.created == 2`, `halted == False`, and `details` array has 4 entries.
- `tests/test_bulk.py::test_sprint7_e2e_halt_on_consecutive_errors` — mock 3 consecutive company creates to raise `BullhornAPIError`; assert `halted == True` and results up to failure are included.

---

## Full Regression Test Suite (All Sprints Complete)

After all sprints are implemented, run the complete test suite:

```bash
.venv/bin/pytest
```

Expected: all pre-existing tests pass unchanged (US-21 / FR-10) plus all new tests introduced in Sprints 1–7.

Key regression checks:
- `tests/test_server.py` — all existing `list_jobs`, `list_candidates`, `get_job`, `get_candidate`, `search_entities`, `query_entities` tests pass.
- `tests/test_client.py` — all existing `search`, `query`, `get` tests pass.
- `tests/test_auth.py` — all auth flow tests pass unchanged.
- `tests/test_config.py` — all config tests pass unchanged.

---

## Dependency Notes

- **No new third-party packages required** — fuzzy matching uses Python's built-in `difflib.SequenceMatcher`. All HTTP mocking continues with `respx`.
- Sprint 5 depends on Sprints 3 and 4 (duplicate detection is used internally by bulk import).
- Sprint 7 depends on all previous sprints (orchestrates create, duplicate detection, owner resolution, and metadata).
- Sprints 1 and 2 are independent and can be developed in any order.
- Sprints 3 and 4 must be done in order (contact create builds on `_request` extensions from Sprint 3).
