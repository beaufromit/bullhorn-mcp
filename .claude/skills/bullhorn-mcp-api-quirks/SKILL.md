---
name: bullhorn-mcp-api-quirks
description: Load this skill BEFORE writing or reviewing any code that touches the Bullhorn REST API, and whenever you need the underlying Bullhorn quirk behind a behavior (why a field name is rejected, why an entity has no isDeleted, why a write "failed" but the record persists, why a custom field maps the way it does) or a field name you are about to guess. For live triage of a current failure, load bullhorn-mcp-debugging-playbook FIRST; route back here for the quirk detail once a specific API behavior is the suspect. It is the consolidated Bullhorn API quirk reference for this project: field semantics per entity (title vs occupation vs salutation, name ownership, isDeleted coverage), endpoint-family hazards (/search, /query, /entity, associations, /meta, /resume), and this tenant's custom-field mappings. Every quirk is labeled UNIVERSAL or THIS TENANT.
---

# Bullhorn API Quirks Reference

The single home for every Bullhorn REST API behavior this project has learned the hard way. Consult it before assuming any Bullhorn field name, endpoint behavior, or error semantics. Never guess a field name; check this file, then `/meta`, then verify live (see bullhorn-mcp-live-api-method).

Labels used throughout:

- **UNIVERSAL**: Bullhorn REST platform behavior, expected on any tenant.
- **THIS TENANT**: verified only on this project's Bullhorn instance (custom fields, index configuration, permissions). Another customer's tenant may differ; re-verify before relying on it elsewhere.

Volatile facts in this file are current as of 2026-07-03 (v0.0.46, 648 tests, 38 MCP tools).

## Glossary (defined once, used throughout)

| Term | Meaning |
|---|---|
| CR | Change Request: a `CRx.md` spec file in the repo root; the unit of change control (see bullhorn-mcp-change-control) |
| Lucene | The query syntax used by `GET /search/{entity}` (e.g. `isOpen:true AND name:Acme*`) |
| SQL WHERE | The query syntax used by `GET /query/{entity}` (e.g. `status='Placed'`) |
| picklist | A Bullhorn field with an admin-configured list of allowed values, exposed via `/meta` as `options` |
| soft delete | Bullhorn marks records `isDeleted=true` instead of removing them; they stay in the database and the search index |
| association endpoint | `GET/PUT/DELETE /entity/{Entity}/{id}/{association}` for related-record collections (e.g. a record's notes, a tearsheet's candidates) |
| /meta | `GET /meta/{entity}`: the field inventory (name, label, type, required, maxLength, picklist options); this project's source of truth for field validity |
| tearsheet | A named candidate list (called Hotlist in some Bullhorn UI versions) that consultants build for client briefs |
| BhRestToken | The session token returned by Bullhorn's REST login, sent on every API call (owned by bullhorn-mcp-auth-and-identity) |
| epoch ms | Unix timestamp in milliseconds; Bullhorn's date wire format |
| FK | Foreign key: a to-one association field referencing another entity by id |
| enrichment | This project's startup step that appends live `/meta` field data to MCP tool descriptions (`src/bullhorn_mcp/descriptions.py`) |
| Textkernel | The third-party CV/resume parsing service behind Bullhorn's `/resume` endpoints |

## Cross-cutting behavioral hazards (read these first)

| # | Quirk | Label | Consequence and rule |
|---|---|---|---|
| 1 | Bullhorn can PARTIALLY PERSIST a record and still return an error, with no indication in the response (CR5.md; real duplicate contacts 170841-170843) | UNIVERSAL | An LLM that retries a "failed" create silently creates duplicates. Rule: dedup-check before every create, always. |
| 2 | All dates are epoch-ms integers on the wire (`dateAdded`, `dateBegin`, `dateWebResponse`, `smtpReceiveDate`, ...) | UNIVERSAL | Convert ISO dates before filtering; `_iso_to_epoch_ms()` in `src/bullhorn_mcp/server.py` does this. |
| 3 | Entity IDs are per-type sequences: Candidate 123 and JobOrder 123 can both exist (CR21 review C1, "cross-entity ID leak", IMPLEMENTATION-PLAN.md Sprint 29 row) | UNIVERSAL | Never treat a bare ID as globally unique; always pair it with its entity type. |
| 4 | Some tenants reject `fields=*` per entity: this tenant returns 400 `errors.allFieldsNotAllowed` on JobSubmission (CR17.md) | THIS TENANT (the rejection); UNIVERSAL (that per-entity `fields=*` permissions exist) | Interacts badly with `create()`: `BullhornClient.create()` does the write (which succeeds), then a follow-up `get()` for the fresh record. If the entity is missing from `DEFAULT_FIELDS` (`src/bullhorn_mcp/client.py`), the get falls back to `fields=*`, the read 400s, and a SUCCESSFUL write looks failed. Rule: every writable entity must have a `DEFAULT_FIELDS` entry. |
| 5 | Bullhorn's server-side API surface DRIFTS: `clientCorporation(id,name)` was accepted on `/entity/{E}/{id}/notes` for weeks, then started returning 500 on every call (CR25.md fix 3) | UNIVERSAL (drift happens); THIS TENANT (this specific field regression) | A field that worked last month can break with no deploy on your side. When a previously green path 500s, suspect Bullhorn before suspecting the code. |
| 6 | ID lookups need `/entity`, not Lucene: `search_entities("ClientCorporation", "id:9493")` returns `[]` on this tenant (CR25.md fix 1) | THIS TENANT (verified here; likely index-dependent elsewhere) | Use `GET /entity/{entity}/{id}` (the `get_*` tools) for lookups by ID. |
| 7 | Bullhorn OAuth is non-standard (credentials as query params with `action=Login`, 307 redirects to regional auth hosts) | UNIVERSAL | Owned by bullhorn-mcp-auth-and-identity; listed here only so you do not "fix" the odd-looking flow in `src/bullhorn_mcp/auth.py`. |

## Endpoint families

### `GET /search/{entity}` (Lucene)

Full syntax teaching lives in bullhorn-mcp-query-and-entity-model. Quirks only:

| Quirk | Label |
|---|---|
| The Lucene index INCLUDES soft-deleted records; callers must filter explicitly (CR16.md) | UNIVERSAL |
| Lucene booleans are `0`/`1`: filter with `isDeleted:0`, never `isDeleted:false` | UNIVERSAL |
| Parenthesize the caller query BEFORE appending clauses: `A OR B AND isDeleted:0` binds as `A OR (B AND isDeleted:0)` and leaks deleted rows. `client.py` wraps unconditionally: `f"({query}) AND isDeleted:0"` (CR16.md "Why parentheses") | UNIVERSAL |
| `fieldsFromIndex` in a search response carries NO index-health information. Working searches return `false` too: `/search/JobOrder` returns `fieldsFromIndex: false` alongside `total: 50271`. The field is undocumented. To test whether a `/search/{entity}` route returns anything at all, use a match-all probe — `query=id:[0 TO 99999999]`, `total: 0` means the route returns nothing (CR37.md Part 6 belief A, which falsified the earlier CR23 claim) | UNIVERSAL |
| `/search/Note` returns `total: 0` for every query on this account, including a primary-key lookup for a note that `/entity/Note/{id}` returns normally. This is how note search behaves here, not a fault to escalate. Filter by note fields using the nested `notes.action` pattern on the parent entity, the `note_action` parameter on the list tools, or `get_notes_for_entity` (CR37.md) | THIS TENANT (state as of 2026-07-28) |
| Note fields ARE searchable as nested fields on the PARENT entity's healthy index: `notes.action`, `notes.comments`, `notes.dateAdded`, `notes.commentingPerson.id`, verified on Candidate / ClientContact / JobOrder. Results are parent records, deduplicated, never notes. Multi-word values MUST be double-quoted or they silently match nothing. `notes.isDeleted` does NOT work (returns 0 everywhere). UNDOCUMENTED by Bullhorn — verified, not contractually guaranteed; `smoke_read.py` carries a two-way canary (CR37.md) | THIS TENANT (verified); syntax undocumented |
| Sorting on an UNINDEXED field errors loudly ("Bad sort: unknown field smtpSendDate"), but RANGE-FILTERING on an unindexed field silently returns 0 rows. The error case is self-diagnosing; the silent case is not (CR24.md) | UNIVERSAL (mechanism); THIS TENANT (which fields are indexed) |
| A bare `*` query returns `Bad Query: {0}` (CR22.md bug 3) | UNIVERSAL |
| `/search/UserMessage` REQUIRES an `entityId` query parameter; omitting it fails every call with 400 "Missing parameter entityId" (commit c5cdfaa, confirmed live 2026-06-03) | UNIVERSAL |

### `GET /query/{entity}` (SQL WHERE)

| Quirk | Label |
|---|---|
| String literals need SINGLE quotes: `status='Placed'`. Double quotes parse as a field name and 400 with "not a valid field name" (commit 01cc962, CR33 M2) | UNIVERSAL |
| SQL booleans are `true`/`false`: filter with `isDeleted=false` (contrast Lucene `isDeleted:0`) | UNIVERSAL |
| Parenthesize before appending, same precedence trap as Lucene; `client.py` wraps: `f"({where}) AND isDeleted=false"` | UNIVERSAL |
| There is NO `/query/Note`. `query_entities` hard-refuses `entity="Note"` (`src/bullhorn_mcp/server.py`, "Bullhorn does not expose /query/Note") | UNIVERSAL |
| Entities lacking `isDeleted` 400 on the auto-appended clause: "Where clause 'isDeleted' is not a valid field name" (CR24/CR25/CR33; see the isDeleted coverage table below) | UNIVERSAL |

### `GET/PUT/POST /entity/{entity}` (direct record access)

| Quirk | Label |
|---|---|
| CREATE is `PUT /entity/{entity}`; UPDATE is `POST /entity/{entity}/{id}`. Backwards from typical REST conventions (`src/bullhorn_mcp/client.py` `create()`/`update()`) | UNIVERSAL |
| Neither create nor update returns the record; this project always does a follow-up `get()`. See cross-cutting hazard 4 for the `fields=*` interaction | UNIVERSAL (thin write responses); project convention for the re-read |
| Field selection uses `fields=` with association syntax `owner(id,firstName)`; `fields=*` is a tenant-permission hazard (hazard 4) | UNIVERSAL |

### Association endpoints

| Quirk | Label |
|---|---|
| Notes are READ via `GET /entity/{Entity}/{id}/notes`, never via NoteEntity queries and never via `/query/Note`. This is the only reliable path (CR23.md, verified via Postman for Candidate and JobOrder) | UNIVERSAL |
| The notes association endpoint RETURNS soft-deleted notes; this project filters them in Python (`n.get("isDeleted")` checks in `server.py`). Pagination arithmetic over the filtered list is subtle and owned by bullhorn-mcp-architecture-contract | UNIVERSAL |
| TO_MANY association writes take comma-joined IDs in the URL path: `PUT /entity/Tearsheet/{id}/candidates/1,2,3`, `DELETE` likewise removes (CR32.md; `add_association`/`remove_association` in `client.py`) | UNIVERSAL |
| Association endpoints have their own field validation, separate from `/search` and `/entity` reads: `clientCorporation(id,name)` is rejected on `/entity/{E}/{id}/notes` (500) even though it was once accepted (CR25.md fix 3) | THIS TENANT (observed here); UNIVERSAL (separate validation surfaces) |

### `GET /meta/{entity}`

| Quirk | Label |
|---|---|
| `/meta` is the source of truth for field validity; audit every write payload against it (CR2.md lesson) | project rule, UNIVERSAL data source |
| Picklist options come back as a list of `{value, label}` dicts under `options` (`src/bullhorn_mcp/metadata.py` `get_fields()`) | UNIVERSAL |
| `/meta` is how the code detects `isDeleted` support: `BullhornClient._entity_has_isdeleted()` scans the field list, caches per process, and falls back to True (append the clause) on any `/meta` error (CR33.md) | project mechanism |
| The `meta` query parameter accepts `off`, `basic`, or `full` and **defaults to `off`**. Without `meta=full`, Bullhorn omits `required`, `optional`, `readOnly`, `inputType`, `description`, `hint`, `multiValue`, `shouldAddCustomEntityLabel`, `sortOrder`, `systemRequired` from every field dict. `off`/`basic` gives only `[confidential, dataType, hideFromSearch, label, maxLength, name, options, type]`. `client.get_meta()` sends `meta=full` (it did not until CR37, so `required` read as False for every field for 10 sprints and the `[required]` marker never rendered) | UNIVERSAL, documented |
| Custom fields (`customText1` etc.) with `label == name` are unconfigured; a configured one has an admin-set label. **`label != name` is not sufficient**: Bullhorn auto-labels every unused slot by spacing out the field name ("Custom Float23" for `customFloat23`), so 76 of Candidate's 100 custom fields pass a naive check. Compare NORMALISED (whitespace stripped, lowercased) — `descriptions._is_auto_label()` (CR37 Part 5 bug C). Confirmed live: `customText41` "Candidate Source - This Placement" and `customDate1` "PitchMe Update Date" are real; `customDate10` "Custom Date 10" is a placeholder | UNIVERSAL heuristic, THIS TENANT examples |
| `hideFromSearch: false` does NOT predict that an association dot-path is searchable. No Candidate association has `hideFromSearch: true`, yet several dot paths return 0 while others filter correctly. Never auto-generate query guidance from `/meta` shape; test each path (CR37) | UNIVERSAL |

### `POST /resume/...` (CV parsing, Textkernel)

All from CR19.md; the multipart client methods use a 60s timeout (`client.py`).

| Quirk | Label |
|---|---|
| `POST /resume/parseToCandidate` (multipart binary) officially supports `html|text` only, but pdf/doc/docx usually work; validate against the target tenant | UNIVERSAL (docs vs reality gap) |
| Parsing is synchronous and slow: use a 60s timeout, not the default | UNIVERSAL |
| Parsed values can EXCEED the `/meta` `maxLength` of their target field; truncate before writing or the write 400s | UNIVERSAL |
| CVs without an email address can fail to parse (Bullhorn sdk-rest issue #146, cited in CR19.md) | UNIVERSAL |
| Skills that do not match Bullhorn's skill list have no `id`; route unmatched skills into the `skillSet` free-text field | UNIVERSAL |
| `POST /resume/parseToCandidateViaJson` is the JSON-body variant for pasted text/HTML | UNIVERSAL |

## Field semantics: title, occupation, salutation, name

The founding bug cluster of this project (CR1 through CR7). Memorize this table.

| Entity | `title` means | Job title field | Salutation field |
|---|---|---|---|
| ClientContact | Salutation (Mr/Ms/Dr) | `occupation` | `title` (write via `namePrefix`; writes of `title` are stripped with a warning, CR7.md) |
| Candidate | NOTHING: `title` is not a valid field at all (CR18.md; live `/meta` confirmed 2026-07-03) | `occupation` | n/a |
| JobOrder | The job's title (valid, do not strip) | `title` | n/a |

**`name` is MCP-owned on person entities (UNIVERSAL, CR26.md).** Bullhorn REST does NOT auto-compute `name` from firstName + lastName; only the UI does. A record created via REST without an explicit `name` has `name=null` and is invisible in Bullhorn list views and unopenable in the UI. This project strips caller-supplied `name` and always recomputes it as `firstName + " " + lastName` (`_strip_contact_title` and `_compute_person_name` in `src/bullhorn_mcp/server.py`); partial-name updates fetch the current record to fill the missing half.

## isDeleted coverage

Which entities have the `isDeleted` field (live `/meta` verified 2026-07-03; mechanism in `_entity_has_isdeleted`, CR33.md). Entities WITHOUT it 400 on the auto-appended soft-delete clause.

| Entity | Has isDeleted | Notes |
|---|---|---|
| Candidate, ClientContact, JobOrder, JobSubmission, Note, Tearsheet, CorporateUser | yes | clause safe |
| ClientCorporation | NO | uses `status` for lifecycle instead (CR25.md); in the static denylist `_ENTITIES_WITHOUT_ISDELETED` |
| UserMessage | NO | CR24.md; in the static denylist |
| Placement | NO | CR33.md; caught by the `/meta` gate |
| PlacementChangeRequest | NO | CR33.md; caught by the `/meta` gate |

Label: UNIVERSAL that isDeleted coverage varies per entity; the exact per-entity facts above are verified on THIS TENANT (Bullhorn docs suggest they are platform-wide, but only this tenant is confirmed).

## Per-entity quirk reference

### Candidate

| Quirk | Label |
|---|---|
| NO `title` field at all; job title is `occupation` (CR18.md; live `/meta` 2026-07-03) | UNIVERSAL |
| NO `clientCorporation` FK; current employer is the free-text `companyName` (CR19.md; live `/meta` 2026-07-03). `create_candidate`/`update_record` reject `clientCorporation` with a pointer to `companyName` | UNIVERSAL |
| `source` (free text) is NOT `candidateSource` (an association); they are different fields (CR19.md) | UNIVERSAL |
| Candidate is internally a subtype of the `User` entity; this is why NoteEntity rows for candidates carry `targetEntityName='User'` (CR23.md) | UNIVERSAL |
| `name` must be sent explicitly (see field semantics above) | UNIVERSAL |

### ClientContact

| Quirk | Label |
|---|---|
| `title` = salutation, `occupation` = job title; `FIELD_ALIASES["ClientContact"]["job title"] = "occupation"` (CR1.md, `src/bullhorn_mcp/metadata.py`) | UNIVERSAL |
| NO `department` field; the equivalent is `division` (CR2.md) | UNIVERSAL |
| Writes of `title` are stripped with a warning rather than remapped (`namePrefix` is the writable salutation; a global title-to-occupation alias would make the real salutation inaccessible, CR7.md) | project policy |
| `name` must be sent explicitly (CR26.md) | UNIVERSAL |

### ClientCorporation

| Quirk | Label |
|---|---|
| No `isDeleted`; uses `status` (CR25.md) | THIS TENANT verified, likely UNIVERSAL |
| Lucene ID lookup `id:9493` returns `[]`; use `GET /entity/ClientCorporation/{id}` (CR25.md; `get_company` tool exists for this) | THIS TENANT |

### CorporateUser

| Quirk | Label |
|---|---|
| NEVER include `department` in CorporateUser queries: it is not reliably queryable and silently kills identity resolution on some tenants (CR3.md; enforced by a comment in `src/bullhorn_mcp/identity.py`). This is known failure pattern 5 in the review protocol | UNIVERSAL (defensive rule); THIS TENANT (observed breakage) |

### JobOrder

| Quirk | Label |
|---|---|
| `title` is a real, valid field (the job's title); do not apply the ClientContact strip here (CR7.md) | UNIVERSAL |
| Custom-field mappings, all THIS TENANT (from CR13.md/CR14.md and `.env.example`): sector = `customText1`; salary range = `customText10`; location = `customText11`; "publish on website" = `customText12` (0 = not published, the shipped default); grade = `correlatedCustomText2`; fee = `feeArrangement`; published job description = `publicDescription` | THIS TENANT (except `publicDescription` and `feeArrangement`, which are standard field names configured for these purposes here) |
| These mappings live in env config (`BULLHORN_JOBORDER_ALIASES` etc., see bullhorn-mcp-config-and-flags), a direct lesson of the CR13 dead end: never hardcode instance-specific field names | project rule |

### JobSubmission

| Quirk | Label |
|---|---|
| Create is `PUT /entity/JobSubmission`; required body fields: `candidate`, `jobOrder`, `status`, `dateWebResponse` (epoch ms) (CR15.md) | UNIVERSAL |
| `sendingUser` is the "Added By" attribution; if omitted it defaults to the API service account, so stamp it explicitly for correct attribution (CR15.md) | UNIVERSAL |
| Bullhorn does NOT prevent duplicate JobSubmissions for the same (candidate, jobOrder) pair; dedup is entirely the caller's job (CR15.md) | UNIVERSAL |
| This tenant rejects `fields=*` on JobSubmission (400 `errors.allFieldsNotAllowed`); combined with the post-write get(), this made successful writes look failed until JobSubmission was added to `DEFAULT_FIELDS` (CR17.md) | THIS TENANT |

### Note and NoteEntity

| Quirk | Label |
|---|---|
| Note is dual-identity: WRITE via `PUT /entity/Note`, READ via the association endpoint `GET /entity/{Entity}/{id}/notes` (CR23.md; `add_note` in `client.py`) | UNIVERSAL |
| NoteEntity `targetEntityName` is UNRELIABLE: Candidate rows store `'User'` (Candidate is a User subtype), and a single JobOrder's rows MIX `'JobOrder'` and `'User'`. Any targetEntityName filter silently drops notes. NoteEntity was abandoned entirely (CR23.md) | UNIVERSAL |
| There is no `/query/Note` | UNIVERSAL |
| `/search/Note` returns `total: 0` for every query on this account. Use the nested `notes.*` pattern on the parent entity, the `note_action` parameter on the list tools, or `get_notes_for_entity`. `search_notes` probes this at runtime and attaches a `warnings` key rather than returning a silent empty envelope (CR37.md) | THIS TENANT (state as of 2026-07-28) |
| `clientCorporation(id,name)` is rejected on the notes association endpoint (500) and on `/search/Note`; it is excluded from both note field constants in `server.py` (CR22.md, CR25.md) | THIS TENANT observed; treat as UNIVERSAL defensively |
| Note writes link to their target via per-entity fields: `personReference` for Candidate/ClientContact, `jobOrder` for JobOrder, `clientCorporation` for ClientCorporation, and LIST-valued `placements`/`leads`/`opportunities` for those types (`_ENTITY_FIELD` in `client.py` `add_note`) | UNIVERSAL |
| Note `comments` can embed click-to-call telemetry tags like `[cc:<uuid>,<num>,<num>,inbound|outbound]`; this project strips them into `call_metadata` (`_CC_TAG_RE` in `server.py`, CR21) | THIS TENANT (telephony integration artifact) |
| Note `action` must be a valid picklist value; this project validates against the live picklist at first `add_note` call (CR25.md) | UNIVERSAL (picklist enforcement) |

### Placement

| Quirk | Label |
|---|---|
| No `isDeleted` field (CR33.md; live `/meta` 2026-07-03) | THIS TENANT verified |
| `customText41` = "Candidate Source - This Placement" (live `/meta` label confirmed 2026-07-03; IMPLEMENTATION-PLAN.md CR34 section) | THIS TENANT |
| `dateBegin` NEVER moves after the original start, even across dozens of contract extensions; only `dateEnd` moves (CR33.md; example Placement 10982, dateBegin Jun 2023 with 34 extensions) | THIS TENANT data model |
| `customInt3` is null everywhere and is NOT the extension signal (CR33 investigation dead end; dropped from default fields) | THIS TENANT |

### PlacementChangeRequest

| Quirk | Label |
|---|---|
| A contract extension is NEVER a new Placement row; it is a PlacementChangeRequest with `requestType='Contract Extension'` linked to the one original placement (CR33.md) | THIS TENANT data model |
| `requestCustomDate1` = "Extension Start Date" (live `/meta` label confirmed 2026-07-03); it steps forward per extension and is the correct "start date" for extension events | THIS TENANT |
| No `isDeleted` field (CR33.md) | THIS TENANT verified |
| Never merge new-placement rows and extension rows into one list; `list_placements` returns them under separate keys by design | project rule backed by the data model |

### Tearsheet

| Quirk | Label |
|---|---|
| Called "Hotlist" in some Bullhorn UI versions; the API entity is `Tearsheet` (CR32.md) | UNIVERSAL |
| Candidates are managed via TO_MANY association writes with comma-joined IDs: `PUT/DELETE /entity/Tearsheet/{id}/candidates/1,2,3`; both return HTTP 200 with a JSON body (CR32.md) | UNIVERSAL |
| Has `isDeleted`; normal soft-delete filtering applies (CR32.md assumption 1, unchallenged since) | THIS TENANT verified via the gate |

### UserMessage (emails)

| Quirk | Label |
|---|---|
| `entityId` is a MANDATORY query parameter on `GET /search/UserMessage`; omitting it 400s every call (commit c5cdfaa). The mandatory requirement is an accepted API constraint, never remove it. Separate from that: `entityId` scopes results to one primary entity, so emails synced under a different entity can be missed when combined with sender/recipient clauses. OPEN DEBT (the residual scoping limitation, not the mandatory param): workaround is to also query with the other party's entityId and merge; no CR exists for a multi-entity sweep, suggest one if it bites | UNIVERSAL (mandatory param); OPEN DEBT (scoping limitation) |
| `smtpReceiveDate` (server timestamp) is indexed and sortable on this tenant; `smtpSendDate` (client timestamp) is NOT indexed, so sorting on it errors (CR24.md) | THIS TENANT |
| OPEN DEBT: `since`/`until` range filters on `smtpSendDate` silently return 0 rows because the field is unindexed (CR24.md explicitly deferred this). Workaround: sort by `-smtpReceiveDate` and filter client-side, or drop the date bounds. Suggest a CR to move the range filter to `smtpReceiveDate` | THIS TENANT |
| No `isDeleted` field (CR24.md; live `/meta` 2026-07-03) | THIS TENANT verified |

## Pre-write checklist (run before any new write path)

1. Field names verified against `/meta/{entity}` (not guessed, not copied from another entity). Never invent instance-specific names: the CR13 create_job dead end shipped a tool that was uncallable under ANY input.
2. Dedup check before create (hazard 1: partial persistence).
3. Entity present in `DEFAULT_FIELDS` in `src/bullhorn_mcp/client.py` (hazard 4: post-write get vs `fields=*`).
4. Dates converted to epoch ms.
5. String values in any `/query` WHERE use single quotes, and user input is guarded against embedded single quotes (CR33 M2). OPEN DEBT: `get_job_submissions`, `resolve_owner`, and `identity.resolve_caller` still interpolate unescaped; do not copy that pattern; a hardening CR is the suggested fix (details owned by bullhorn-mcp-architecture-contract).
6. If the payload touches ClientContact or Candidate: no `title` in the payload, `name` recomputed, no `department` (ClientContact) or `clientCorporation` (Candidate).
7. Instance-specific field mappings go in env config, never hardcoded (CR14 lesson; see bullhorn-mcp-config-and-flags).

## When NOT to use this skill

| Topic | Go to |
|---|---|
| HOW to write Lucene/SQL queries, entity relationship map, recruitment workflow | bullhorn-mcp-query-and-entity-model |
| The incident stories behind these quirks (notes saga, create_job dead end, entityId outage) | bullhorn-mcp-failure-archaeology |
| Bullhorn OAuth flow, BhRestToken lifecycle, Entra identity, owner stamping rules | bullhorn-mcp-auth-and-identity |
| Symptom-to-cause triage when something is failing right now | bullhorn-mcp-debugging-playbook |
| Verifying a quirk against the live tenant before coding | bullhorn-mcp-live-api-method |
| Env vars that carry the tenant mappings (BULLHORN_JOBORDER_ALIASES etc.) | bullhorn-mcp-config-and-flags |
| Module invariants, pagination arithmetic, error-surface conventions | bullhorn-mcp-architecture-contract |
| Writing tests that mock these behaviors | bullhorn-mcp-testing-playbook |

## Provenance and maintenance

Each claim category with a one-line re-verification command (run from the repo root):

| Claim | Re-verify with |
|---|---|
| Tool/test/tag counts (38 tools, 648 tests, v0.0.46) | `grep -c "@mcp.tool" src/bullhorn_mcp/server.py && .venv/bin/pytest -q 2>&1 \| tail -1 && git tag \| sort -V \| tail -1` |
| isDeleted denylist and /meta gate | `grep -n "_ENTITIES_WITHOUT_ISDELETED\|_entity_has_isdeleted" src/bullhorn_mcp/client.py` |
| Per-entity isDeleted coverage and tenant labels (customText41, requestCustomDate1) | live read-only `get_meta` per bullhorn-mcp-live-api-method (last run 2026-07-03) |
| title/occupation aliases and label resolution order | `grep -n -A 16 "FIELD_ALIASES" src/bullhorn_mcp/metadata.py` |
| name recompute and title strip | `grep -n "_compute_person_name\|_strip_contact_title" src/bullhorn_mcp/server.py` |
| Lucene/SQL clause wrapping and boolean forms | `grep -n "isDeleted:0\|isDeleted=false" src/bullhorn_mcp/client.py` |
| Parenthesization rationale | `grep -n "parenthes\|Why parentheses" CR16.md` |
| Partial persistence | `grep -n "partially" CR5.md` |
| fields=* JobSubmission rejection | `grep -n "allFieldsNotAllowed" CR17.md` |
| Notes: association rule, targetEntityName, no /query/Note | `grep -n "targetEntityName\|association endpoint" CR23.md && grep -n "/query/Note" src/bullhorn_mcp/server.py` |
| clientCorporation-on-notes 500 (API drift) | `grep -n "clientCorporation" CR25.md` |
| entityId mandatory + smtp field indexing | `git show c5cdfaa --stat && grep -n "smtpReceiveDate\|fieldsFromIndex" CR24.md` |
| Single-quote rule | `git show 01cc962 --stat` |
| JobSubmission create mechanics and no dup prevention | `grep -n "PUT\|dateWebResponse\|does not prevent" CR15.md` |
| JobOrder tenant mappings | `grep -n "customText1\|feeArrangement" .env.example CR14.md` |
| Placement/extension model, customInt3 dead end | `grep -n "Contract Extension\|dateBegin\|customText41" CR33.md` |
| CV parser hazards | `grep -n "maxLength\|skillSet\|email" CR19.md && grep -n "timeout" src/bullhorn_mcp/client.py` |
| cc telemetry regex | `grep -n -A 3 "_CC_TAG_RE = " src/bullhorn_mcp/server.py` |
| Picklist {value,label} shape | `grep -n "options" src/bullhorn_mcp/metadata.py` |
| add_note per-entity link fields | `grep -n -A 10 "_ENTITY_FIELD" src/bullhorn_mcp/client.py` |
| Tearsheet association mechanics | `grep -n "candidates/1,2,3" src/bullhorn_mcp/client.py CR32.md` |
| OPEN DEBT items (smtpSendDate ranges, unescaped WHERE interpolation, entityId tension) | `grep -n "separate problem" CR24.md && grep -n "status must not contain single quotes" src/bullhorn_mcp/server.py` |
