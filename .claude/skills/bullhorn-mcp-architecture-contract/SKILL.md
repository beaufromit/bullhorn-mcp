---
name: bullhorn-mcp-architecture-contract
description: Load this skill before changing any code in src/bullhorn_mcp/, adding or modifying an MCP tool, touching client.py request/write paths, pagination, dedup guards, error handling, or the enrichment startup path; also load it when you need the module map, the full 38-tool inventory, or to check whether a planned change violates one of the 15 load-bearing invariants (import-time safety, rest_url slash rule, isDeleted gate, guard-after-resolution, MCP-owned name, post-write GET, next_start arithmetic, notes-via-association, placements-vs-extensions, sub-keyed identity cache, additive enrichment, docstrings-as-interface, force escape hatches, hard-fail vs best-effort, uniform error surface). Provides each invariant with enforcing code location, failure mode, and historical evidence, plus the known weak points labeled as OPEN DEBT.
---

# Bullhorn MCP Architecture Contract

The load-bearing design of this repo: what every module does, the 15 invariants that past incidents burned into the code, the complete tool surface, and the known weak points. Violating any invariant here has already caused a real production incident at least once. All line numbers and counts verified as of 2026-07-03 (v0.0.46, 648 tests, 38 tools).

Jargon used below, defined once:

| Term | Meaning |
|---|---|
| MCP | Model Context Protocol; the tool-calling protocol this server speaks to AI clients |
| FastMCP | The Python framework (`fastmcp` package) providing `@mcp.tool()` registration and transports |
| CR | Change Request; a spec file `CRnn.md` in the repo root, the unit of change control |
| Lucene | Bullhorn's `/search/{entity}` query syntax (`isOpen:true`, booleans as `0/1`) |
| SQL WHERE | Bullhorn's `/query/{entity}` syntax (`isDeleted=false`, single-quoted strings) |
| BhRestToken | The Bullhorn session token returned by REST login, sent on every API call |
| Entra | Microsoft Entra ID (Azure AD); protects the HTTP transport via OIDC |
| picklist | A Bullhorn field with a fixed set of `{value, label}` options from `/meta` |
| enrichment | The startup pass that appends live `/meta` field summaries to tool docstrings |
| soft delete | Bullhorn marks records `isDeleted` instead of removing them; they stay in indexes |
| dedup | Duplicate detection before create, via fuzzy scoring in `fuzzy.py` |

## Module map

All files in `src/bullhorn_mcp/`, line counts via `wc -l` as of 2026-07-03 (v0.0.46):

| Module | Lines | Role |
|---|---|---|
| `server.py` | 3383 | FastMCP entry point. All 38 `@mcp.tool()` tools, the `/upload-cv` custom HTTP route, `main()`, lazy globals (`_client`, `_metadata`, `_shortlist_status_validated`, `_valid_note_actions` at lines 222-226), private helpers (`_strip_contact_title` :34, `_compute_person_name` :62, `_check_candidate_duplicates` :70, `_paginate_envelope` :269, `_strip_cc_telemetry`, `_truncate_against_meta`, `_iso_to_epoch_ms`), note and placement constants |
| `client.py` | 594 | `BullhornClient`: `_request` (401 auto-retry once), `search`/`query`/`get` plus `_with_meta` variants, `create`/`update`/`add_note` (all post-write GET), `get_association(_with_meta)`, `resolve_owner`, `get_meta`, multipart CV methods (`parse_resume_file`, `parse_resume_text`, `attach_file`), `_entity_has_isdeleted` gate, `DEFAULT_FIELDS`, `BullhornAPIError` |
| `auth.py` | 212 | `BullhornAuth`/`BullhornSession`: non-standard Bullhorn OAuth, regional 307 redirect handling, sync `session` property with 60-second-buffer auto-refresh |
| `config.py` | 49 | `BullhornConfig.from_env()`; validates the 4 required Bullhorn credentials |
| `metadata.py` | 140 | `BullhornMetadata`: per-entity `/meta` cache, `FIELD_ALIASES` (checked FIRST in `resolve_fields`), label-to-API-name resolution, picklist `options` retained |
| `descriptions.py` | 292 | Startup enrichment (`enrich_tool_descriptions`, async): `SUPPORTED_ENTITIES` (10 entities), `TOOL_ENTITY_MAP`, full vs compact section split (CR34) |
| `identity.py` | 95 | `resolve_caller` from the Entra JWT; `_caller_cache` keyed by the `sub` claim |
| `fuzzy.py` | 112 | Company/contact fuzzy match scoring; thresholds exact >= 0.95, likely >= 0.75, possible >= 0.50 |
| `bulk.py` | 360 | `BulkImporter`: batch company/contact import, dedup, halt after 3 consecutive errors |
| `candidate_config.py` | 57 | Env-driven per-tenant Candidate config (aliases/required/defaults/source stamp) |
| `joborder_config.py` | 48 | Same pattern for JobOrder (`create_job`) |
| `shortlist_config.py` | 13 | `DEFAULT_SHORTLIST_STATUS` and env override |
| `__init__.py` | 3 | Package marker |

For the env var and constants tables, see the sibling skill bullhorn-mcp-config-and-flags.

## The 15 load-bearing invariants

Check every planned change against this list. Each entry: what it protects, where the code enforces it, what breaks if violated, and the historical evidence. When you must weaken one, say so explicitly in the CR and get it reviewed; never weaken one silently.

### 1. Importing server.py requires no Bullhorn credentials and no network

- Protects: the test suite (which imports `server.py` module-wide) and tool registration (FastMCP registers all 38 tools at import).
- Enforced: lazy globals; `get_client()` (server.py:229) constructs `BullhornClient` on first use, `get_metadata()` (server.py:239) likewise. Verified: `import bullhorn_mcp.server` succeeds with all `BULLHORN_*` vars unset.
- Exception, by design: transport env vars ARE read at import. `MCP_TRANSPORT` (server.py:160), `PORT` (server.py:161, `int()` so a non-numeric value crashes import), and in HTTP mode the four Entra vars via `_build_auth()` (server.py:166-195), called at `FastMCP(...)` construction (server.py:214). HTTP mode with any Entra var missing raises `ValueError` at import: fail-closed, intentional.
- Breaks if violated: every test file fails at collection; stdio startup requires credentials it should not need yet.
- Evidence: the Sprint 15/16 FastMCP regression cycle established the import-time transport reads; the lazy-client pattern dates to the original design.

### 2. `rest_url` never has a trailing slash

- Protects: every request URL.
- Enforced: `_request()` and `_request_multipart()` build `f"{session.rest_url}{endpoint}"` (client.py:83 and :125). Endpoints all start with `/`.
- Breaks if violated: double slashes in every URL; some Bullhorn tenants return `rest_url` WITH a trailing slash, so normalization matters. All test fixtures encode the no-slash rule; see bullhorn-mcp-testing-playbook for the fixture traps.
- Evidence: conftest comment and `test_bulk.py`'s private `_Session` class both carry the warning.

### 3. isDeleted auto-append, gated by metadata, failing safe

- Protects: reads from returning soft-deleted records (false-positive duplicates, ghost data).
- Enforced: `search_with_meta` appends `({query}) AND isDeleted:0` (client.py:245-246); `query_with_meta` appends `({where}) AND isDeleted=false` (client.py:320-321); both only when `exclude_deleted=True` (default) AND `_entity_has_isdeleted(entity)` (client.py:51-70). Gate order: `_ENTITIES_WITHOUT_ISDELETED` denylist (client.py:11, `{ClientCorporation, UserMessage}`) fast path, then `_isdeleted_cache`, then a live `/meta` scan; on `/meta` failure it returns True WITHOUT caching (client.py:66-69), so the clause is appended (safe default) and detection can retry later.
- Two sub-rules you must not break: (a) the parenthesization is unconditional, or `A OR B AND isDeleted:0` binds wrong and leaks deleted rows; (b) never cache the error-path result.
- Breaks if violated: entities lacking `isDeleted` get a 400 on every call; or deleted rows leak into dedup and lists.
- Evidence: this is the fourth iteration of the design (CR16 blanket append, CR24 per-call opt-out, CR25 static denylist, CR33 metadata gate). Per-entity quirk details live in bullhorn-mcp-api-quirks.

### 4. FIELD_ALIASES resolve first; guards fire AFTER label resolution

- Protects: write payload correctness and the no-company-reassignment rule (PRD hard exclusion).
- Enforced: `resolve_fields` checks the hardcoded `FIELD_ALIASES` entry before metadata label lookup (metadata.py:130-136). The company-reassignment guard in `update_record` checks `"clientCorporation" in resolved` AFTER `resolve_fields` runs (server.py:1589-1597), with an inline comment stating why.
- Breaks if violated: a caller sends the display label ("Company") instead of the API name and walks straight past the guard; or a known metadata gap ("job title" on ClientContact) maps to the wrong field.
- Evidence: known review failure pattern 6 (guard before resolution, Sprint 6, recurred in CR19) and pattern 8 (alias precedence, Sprint 8). See bullhorn-mcp-review-protocol for the pattern list.

### 5. `name` on person entities is MCP-owned

- Protects: record visibility. Bullhorn's REST API does NOT auto-compute `name` on Candidate/ClientContact (only the UI does); a null-name record is invisible in list views and unopenable in the Bullhorn UI.
- Enforced: `_strip_contact_title` (server.py:34) strips caller-supplied `title` and `name` on ClientContact/Candidate writes; `_compute_person_name` (server.py:62) injects `firstName + " " + lastName`; partial-name updates fetch the current record to fill the missing half (server.py:1600-1608). Call sites: create_contact (server.py:1368-1370), create_candidate (:2007-2009), create_candidate_from_cv (:2325, :2339), update_record (:1598-1608), attach_cv commit path (:2601-2608).
- Breaks if violated: silently invisible records; worse, a new write path that misses these helpers reintroduces the bug (this exact incomplete-fix-scope failure happened twice on attach_cv).
- Evidence: CR26, which reversed CR19's false belief that `name` was auto-computed; before CR26 the strip helper was actively removing caller names, guaranteeing nulls.

### 6. `create()`, `update()`, and `add_note()` return a post-write GET, never the raw POST/PUT response

- Protects: callers always receive the full fresh record with server-side defaults applied.
- Enforced: create does `PUT` then `self.get()` (client.py:214-227); update does `POST` then `self.get()` (client.py:395-407); add_note does `PUT /entity/Note` then `self.get("Note", ...)` (client.py:446-458).
- Breaks if violated (and its trap): the post-write GET uses `DEFAULT_FIELDS`, falling back to `fields=*` for entities not listed there. Some tenants reject `fields=*` per entity, so a SUCCESSFUL write then looks like a failure, and a retrying LLM creates duplicates or mislabels its own writes. When adding a write path for a new entity, add that entity to `DEFAULT_FIELDS` in client.py first.
- Evidence: CR17 (JobSubmission IDs 94607-94612 were created while the tool reported "created: 0").

### 7. Pagination envelope; `next_start` advances by the RAW page count

- Protects: LLM pagination loops terminating.
- Enforced: user-facing list/search tools return `{"data": [...], "pagination": {total, start, count, has_more, next_start}}` via `_paginate_envelope` (server.py:269-288). `get_notes_for_entity` computes its own envelope (server.py:3101-3121): `raw_page_count = len(raw_notes)` drives `next_start = start + raw_page_count`, while `count` reflects rows AFTER the soft-delete filter. Contract for consumers: use `next_start`, never `start + count`.
- Breaks if violated: a page consisting entirely of soft-deleted notes makes `next_start == start` with `has_more=True`, and the calling LLM loops forever.
- Evidence: commit 1289e16 (review C1, the CR28 pagination triple-cycle; a prior review's "fix" introduced the loop).

### 8. Notes are read via the association endpoint, never NoteEntity, never `/query/Note`

- Protects: note reads returning anything at all.
- Enforced: `get_notes_for_entity` and the entity-filtered path of `search_notes` call `GET /entity/{Entity}/{id}/notes` via `get_association_with_meta` (client.py:489; call sites server.py:3091, :3209). `query_entities` hard-refuses `entity="Note"` with a structured error (server.py:1122-1130).
- Breaks if violated: NoteEntity's `targetEntityName` column is unreliable (stores `'User'` for Candidate rows, mixes `'JobOrder'`/`'User'` for jobs), so any filter on it silently drops notes; `/query/Note` does not exist in Bullhorn.
- Evidence: the notes saga (CR21 through CR23, feature rewritten twice in one day, commit 710e756 carries both tags v0.0.33 and v0.0.34). Endpoint details in bullhorn-mcp-api-quirks.

### 9. Placements and extensions are never merged

- Protects: correct reporting of contract extensions. In this tenant an extension is NEVER a new Placement row; it is a `PlacementChangeRequest` with `requestType='Contract Extension'` whose date field is `requestCustomDate1`; `Placement.dateBegin` stays pinned to the original start.
- Enforced: `list_placements` (server.py:522) takes `record_type` of "new" / "extensions" / "both"; "extensions" always includes the `requestType='Contract Extension'` clause (see `_build_pcr_where`, server.py:646-653); "both" returns two SEPARATE envelopes with rows tagged `record_type: "new"` / `"extension"`.
- Breaks if violated: merged or dateBegin-based extension reporting is simply wrong for this tenant.
- Evidence: CR33, including the recorded dead end that `customInt3` is null everywhere and is NOT the extension signal.

### 10. The identity cache is keyed by the Entra `sub` claim

- Protects: multi-user HTTP deployments from cross-user owner attribution.
- Enforced: `_caller_cache: dict[str, dict]` keyed by `claims["sub"]` (identity.py:26-30, :64-71); a missing `sub` raises `IdentityResolutionError` immediately (identity.py:65-68). Related hard rule: CorporateUser identity queries must NEVER include `department` (invalid on some tenants; comment at identity.py:81).
- Breaks if violated: a single-slot or email-keyed cache gives first-writer-wins; user B's records get created with user A as owner, with no error.
- Evidence: CR11 (commit 37fde9c) for the cache; CR3 (commit bb4c7f9) for `department`. Flow details in bullhorn-mcp-auth-and-identity.

### 11. Enrichment is strictly additive and optional; the server starts even if Bullhorn is down

- Protects: startup availability.
- Enforced: `main()` wraps `asyncio.run(enrich_tool_descriptions(mcp, get_client()))` in try/except, logging a warning and continuing (server.py:3363-3366); inside enrichment, per-entity and per-tool failures are individually caught (descriptions.py:254-261, :286-290) so one bad entity never blocks the rest. The returned `BullhornMetadata` is stored as the server's `_metadata` cache to avoid re-fetching `/meta`.
- Breaks if violated: an enrichment exception at startup would take down both stdio and HTTP modes; static docstrings are the designed fallback.
- Evidence: CR18 (design), CR34 (full vs compact section split, roughly 80% token reduction).

### 12. Docstrings are the LLM's interface and de facto access control

- Protects: correct agent behavior. Agents learn field names and capabilities exclusively from tool docstrings; a docstring that omits an entity effectively disables the capability, and a wrong example teaches every agent the same bug.
- Enforced: socially, not structurally; plus one regression test asserting the `update_record` docstring does not contain the known-bad example `{"title": "CTO"}`.
- Breaks if violated: CR4 (a single bad docstring example broke every update issued by agents); conversely CR31 unlocked Candidate updates with a docstring-only, zero-code change.
- Evidence: CR1/CR4/CR31. Docstring authoring rules and token budgets live in bullhorn-mcp-docs-and-writing.

### 13. Dedup guards on every create path, with `force` escape hatches (and known places force does NOT exist)

- Protects: CRM hygiene. Motivation: Bullhorn can PARTIALLY PERSIST a record while returning an error, and LLMs retry, so unguarded creates mint duplicates.
- Enforced, inventory:

| Path | Guard | Escape hatch |
|---|---|---|
| `create_contact` | fuzzy match vs same-company contacts; blocks at score >= 0.50 (server.py:1399) | `force=True` |
| `create_candidate` | `_check_candidate_duplicates`; exact email match short-circuits to score 1.0 (server.py:105-107) | `force=True` |
| `create_candidate_from_cv` | same candidate dedup (server.py:2286) | `force=True` |
| `shortlist_candidate` / `shortlist_candidates` | pre-check for an existing (candidate, job) JobSubmission; returns the existing record with `duplicate=true` | NO force parameter, by design (Bullhorn has no server-side JobSubmission duplicate prevention) |
| `bulk_import` (`BulkImporter`) | exact match reuses the existing record; likely/possible matches are flagged | NO force |
| dedup search failure | non-fatal; create proceeds (server.py:1388) | n/a |

- Breaks if violated: silent duplicates (CR5 created real duplicate contacts, IDs 170841-170843).
- Evidence: CR5, CR15, CR19.

### 14. Failure handling splits by tool class: hard-fail vs graceful degradation

- Protects: predictable behavior when identity resolution fails (stdio mode has no JWT).
- Enforced: owner-requiring creates hard-fail with structured `{"error": "identity_resolution_failed", ...}` JSON and do not write (6 sites: server.py:901, :1292, :1347, :1495, :1958, :2311). `add_note` degrades gracefully: it catches `IdentityResolutionError` and writes the note without `commentingPerson` (server.py:1725-1730). Best-effort with warnings (never blocking the primary write): enrichment, dedup search failures, CV child records/skills/file attach in `create_candidate_from_cv`, `_truncate_against_meta`, picklist loads.
- Breaks if violated: creates without owners pollute attribution and activity reports; or notes fail entirely in stdio mode.
- Evidence: CR10 (owner fallback design), CR19 (best-effort CV child records).

### 15. Uniform error surface: exceptions never reach the MCP layer

- Protects: the MCP client from raw tracebacks and the agent from unparseable failures.
- Enforced: every tool body wraps its work in try/except catching `(AuthenticationError, BullhornAPIError)` and returning the string `f"ERROR: {e}"` (38 occurrences in server.py, one per tool); input-validation failures return structured JSON `{"error": "<slug>", "message": "..."}` via `format_response`; some tools additionally catch `ValueError` (e.g. `search_emails` maps resolve_owner misses to `{"error": "user_not_found"}`, server.py:1258-1260).
- Breaks if violated: an uncaught exception propagates through FastMCP as a protocol-level error the agent cannot act on.
- Evidence: consistent convention across all 38 tools; the `/upload-cv` route additionally maps tool-level `"error"` JSON to HTTP 500 (review C1, commit f684bfc).

## Complete tool inventory (38 tools, verified 2026-07-03)

Verify the count: `grep -c "@mcp.tool()" src/bullhorn_mcp/server.py` returns 38.

### Paginated reads (11)

| Tool | Purpose | Notable guards |
|---|---|---|
| `list_jobs` | List/search JobOrders (Lucene) | pagination envelope |
| `list_candidates` | List/search Candidates (Lucene) | pagination envelope |
| `list_contacts` | List/search ClientContacts (Lucene) | pagination envelope |
| `list_companies` | List/search ClientCorporations (Lucene) | pagination envelope; no isDeleted clause (denylist) |
| `list_placements` | Placements and/or contract extensions (`record_type` new/extensions/both) | single-quote rejection on `status` (server.py:625); never merges the two record types |
| `get_job_submissions` | Pipeline for a job, optional status filter | OPEN DEBT: status interpolated unescaped (see below) |
| `search_entities` | Generic Lucene search, any supported entity | pagination envelope |
| `query_entities` | Generic SQL WHERE query | hard-refuses `entity="Note"` (server.py:1122) |
| `search_emails` | UserMessage search for a person | mandatory `entityId` extra param (server.py:1253); sorts by `smtpReceiveDate` |
| `get_notes_for_entity` | All notes on a record via association endpoint | raw-count `next_start`; cc-telemetry stripped into `call_metadata` |
| `search_notes` | Note full-text (Lucene) or entity-filtered (association + local filter) | the Lucene path returns nothing on this account; a cached match-all probe detects that and attaches a `warnings` key rather than returning a silent empty envelope (CR37) |

### Single-record reads (4)

`get_job`, `get_candidate`, `get_company`, `get_contact`: direct `/entity/{E}/{id}` GET with default field sets. `get_company` exists because Lucene ID lookups on ClientCorporation return nothing (CR25).

### Tearsheets (5)

`list_tearsheets`, `get_tearsheet`, `create_tearsheet` (owner-stamped, hard-fail identity), `add_to_tearsheet`, `remove_from_tearsheet` (association PUT/DELETE with comma-joined IDs). A tearsheet is a Bullhorn hotlist: a named, shareable collection of records.

### Creates (4)

| Tool | Notable guards |
|---|---|
| `create_company` | owner hard-fail; label resolution |
| `create_contact` | requires `clientCorporation`; dedup >= 0.50 with `force`; title/name strip and recompute; owner hard-fail |
| `create_job` | requires `clientCorporation` dict with id; env-driven aliases/required/defaults (joborder_config.py); everything else in a `fields` dict (the CR14 rewrite after the CR13 dead end) |
| `create_candidate` | dedup with email short-circuit and `force`; env required fields; `source` stamped from `BULLHORN_MCP_SOURCE`; title/name rules |

### Updates (2)

`update_job` (JobOrder convenience wrapper), `update_record` (generic; company-reassignment guard AFTER resolution; name recompute on person entities; supports ClientContact, ClientCorporation, Candidate per docstring).

### Notes (1)

`add_note`: action validated against the live Note.action picklist at first call; `commentingPerson` stamped when identity resolves, gracefully omitted otherwise.

### Duplicate finders (3)

`find_duplicate_companies`, `find_duplicate_contacts`, `find_duplicate_candidates`: read-only fuzzy scoring, no writes.

### CV pipeline (4)

| Tool | Notable guards |
|---|---|
| `parse_cv` | multipart to Textkernel parser, 60s timeout, no writes |
| `parse_cv_text` | text variant, no writes |
| `create_candidate_from_cv` | parse + dedup + create; child records (work history, education, skills, file attach) are best-effort with warnings |
| `attach_cv` | stateless two-call protocol: call 1 previews a per-field diff (nothing written), call 2 commits via `fields_to_update` or `force_all=True`; re-parses on call 2 |

### Batch and shortlist (3)

`bulk_import` (companies + contacts via `BulkImporter`, halts after 3 consecutive errors), `shortlist_candidate`, `shortlist_candidates` (JobSubmission creates with duplicate pre-check, no force).

### Discovery (1)

`get_entity_fields`: live `/meta` field inventory for any supported entity; the escape hatch the compact CR34 descriptions point to.

## Known weak points (all OPEN DEBT, per the project owner's explicit policy)

These are open backlog, not accepted design. Never present them as intentional. Never oversell a candidate fix as decided.

| # | OPEN DEBT | Detail (verified) | Workaround now | Suggested CR |
|---|---|---|---|---|
| 1 | SQL-injection asymmetry | `list_placements` rejects `'` in `status` (server.py:625-629), but `get_job_submissions` interpolates `status` into WHERE unescaped (server.py:1008-1009), `BullhornClient.resolve_owner` interpolates the owner name (client.py:475-479), and `identity.resolve_caller` interpolates the email claim (identity.py:77-79) | Treat these params as trusted-ish (agent-supplied), but reject any value containing `'` at the call boundary when you touch these paths | A CR extending the CR33 M2 quote guard to every interpolated WHERE param, each with a validation test |
| 2 | Duplicated note constants and one unused | `_NOTE_DEFAULT_FIELDS` (server.py:1650) and `_NOTE_SEARCH_DEFAULT_FIELDS` (server.py:1663) are byte-identical with a keep-in-sync comment (they diverged once, CR22); `_NOTE_ENTITY_SUBJECT_FIELD` (server.py:1640) is defined but referenced by no tool body (it mirrors `_ENTITY_FIELD` inside `client.add_note`, client.py:434); the `get_notes_for_entity` docstring (server.py:3056) still lists `clientCorporation` though CR25 dropped it from the constant | Edit both constants together, always; ignore the unused dict | Fold into the planned CR35 consolidation: single constant, delete the unused dict, fix the docstring |
| 3 | Undeclared `fastmcp` dependency | server.py:14-15 imports `fastmcp` (installed ad hoc, 3.2.4) but pyproject.toml declares only `mcp>=1.0.0`; a truly fresh install fails at server import | `uv pip install fastmcp` after the editable install; see bullhorn-mcp-build-and-env for the full procedure | A CR declaring `fastmcp` with a version bound (mind the FastMCP 3.x breaking-change history) |
| 4 | No CI | No `.github/` directory exists; the adversarial review loop is the only quality gate | Run `.venv/bin/pytest` locally before every commit, per the change-control loop | A CR adding a minimal GitHub Actions pytest job |
| 5 | `search_emails` can miss emails scoped under another primary entity | `entityId` scopes `/search/UserMessage` to one primary entity, so combined with the Lucene sender/recipient clause it can drop emails synced under a different primary entity. (The mandatory-parameter fact itself is NOT debt: it is an accepted API constraint, recorded in the tool inventory row for `search_emails` above; removing `entityId` caused the 12-day outage db78771 to c5cdfaa, so never remove it.) | Query with the other party's `entityId` too and merge the results | A multi-entity sweep for `search_emails`; needs live-API proof first (see bullhorn-mcp-live-api-method); none exists yet |

## When NOT to use this skill

| You need | Go to |
|---|---|
| Env var / constant tables, per-tenant config philosophy | bullhorn-mcp-config-and-flags |
| Bullhorn API quirk details per entity/endpoint | bullhorn-mcp-api-quirks |
| Lucene vs SQL syntax, entity relationships, recruitment workflow | bullhorn-mcp-query-and-entity-model |
| OAuth/Entra flow internals, owner stamping detail | bullhorn-mcp-auth-and-identity |
| How tests enforce these invariants, fixture traps | bullhorn-mcp-testing-playbook |
| The incident chronology behind each invariant | bullhorn-mcp-failure-archaeology |
| CR lifecycle, commit/tag discipline | bullhorn-mcp-change-control |
| Review severities and the 8 failure patterns | bullhorn-mcp-review-protocol |
| Install and dependency procedure | bullhorn-mcp-build-and-env |
| Startup, transports, production topology | bullhorn-mcp-run-and-operate |
| Docstring authoring and doc drift | bullhorn-mcp-docs-and-writing |
| Symptom-driven triage | bullhorn-mcp-debugging-playbook |
| Live-API verification before coding | bullhorn-mcp-live-api-method |
| CR35 consolidation and productization plan | bullhorn-mcp-productization-campaign |

## Provenance and maintenance

Every fact above was verified against the repo on 2026-07-03 at v0.0.46. Re-verify before trusting:

| Claim | Re-verification command |
|---|---|
| Module line counts | `wc -l src/bullhorn_mcp/*.py` |
| Tool count is 38 | `grep -c "@mcp.tool()" src/bullhorn_mcp/server.py` |
| Import needs no Bullhorn creds | `env -u BULLHORN_CLIENT_ID -u BULLHORN_CLIENT_SECRET -u BULLHORN_USERNAME -u BULLHORN_PASSWORD .venv/bin/python -c "import bullhorn_mcp.server"` (run outside repo root so `.env` is not loaded) |
| Import-time env reads and Entra fail-closed | `grep -n "MCP_TRANSPORT\|_build_auth\|ENTRA_" src/bullhorn_mcp/server.py \| head -20` |
| rest_url concatenation | `grep -n 'session.rest_url}{endpoint' src/bullhorn_mcp/client.py` |
| isDeleted gate and fail-safe fallback | `sed -n '51,75p' src/bullhorn_mcp/client.py` and `grep -n "isDeleted:0\|isDeleted=false" src/bullhorn_mcp/client.py` |
| Alias-first resolution | `sed -n '116,140p' src/bullhorn_mcp/metadata.py` |
| Guard after resolution | `grep -n "check after resolution" src/bullhorn_mcp/server.py` |
| Name ownership call sites | `grep -n "_strip_contact_title\|_compute_person_name" src/bullhorn_mcp/server.py` |
| Post-write GET in create/update/add_note | `grep -n "self.get(" src/bullhorn_mcp/client.py` |
| Raw-count next_start in notes | `grep -n "raw_page_count" src/bullhorn_mcp/server.py` |
| Note refusal in query_entities | `grep -n 'entity == "Note"' src/bullhorn_mcp/server.py` |
| Extension clause | `grep -n "Contract Extension" src/bullhorn_mcp/server.py` |
| sub-keyed identity cache | `grep -n "_caller_cache\|sub" src/bullhorn_mcp/identity.py` |
| Enrichment try/except in main | `sed -n '3360,3370p' src/bullhorn_mcp/server.py` |
| Force params and their absence | `grep -n "force: bool" src/bullhorn_mcp/server.py` and `grep -n "def shortlist_candidate" -A 6 src/bullhorn_mcp/server.py` |
| Hard-fail sites | `grep -n "identity_resolution_failed" src/bullhorn_mcp/server.py` |
| Uniform error surface | `grep -c 'f"ERROR: {e}"' src/bullhorn_mcp/server.py` (expect 38) |
| OPEN DEBT 1 (interpolation) | `grep -n "status='{status}'" src/bullhorn_mcp/server.py; grep -n "name='{owner}'" src/bullhorn_mcp/client.py; grep -n "email='{email}'" src/bullhorn_mcp/identity.py` |
| OPEN DEBT 2 (note constants) | `grep -n "_NOTE_DEFAULT_FIELDS\|_NOTE_SEARCH_DEFAULT_FIELDS\|_NOTE_ENTITY_SUBJECT_FIELD" src/bullhorn_mcp/server.py` |
| OPEN DEBT 3 (fastmcp gap) | `grep -n "fastmcp" pyproject.toml src/bullhorn_mcp/server.py` |
| OPEN DEBT 4 (no CI) | `ls .github 2>&1` |
| OPEN DEBT 5 (entityId) | `grep -n "entityId" src/bullhorn_mcp/server.py; git log --oneline --all \| grep -E "db78771\|c5cdfaa"` |
| Historical commits cited | `git log --oneline --all \| grep -E "1289e16\|37fde9c\|710e756\|bb4c7f9\|ed7adcb\|f684bfc"` |
| Test count | `.venv/bin/pytest -q 2>&1 \| tail -1` (expect 648 passed as of v0.0.46) |
| Current tag | `git tag \| sort -V \| tail -1` |
