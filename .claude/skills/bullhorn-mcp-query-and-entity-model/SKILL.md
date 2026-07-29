---
name: bullhorn-mcp-query-and-entity-model
description: Load this skill whenever you write or review a Bullhorn query, or need domain context you do not have. For live triage of a current failure, load bullhorn-mcp-debugging-playbook FIRST; come here for query syntax and the entity model once the query itself is the confirmed suspect. Triggers: choosing between /search (Lucene), /query (SQL-ish WHERE), /entity GET, association endpoints, or /meta; constructing or correcting a query's syntax; you need to know which endpoint an entity supports (e.g. Note has no /query, ClientCorporation ID lookup fails in Lucene); you need the relationship map between Candidate, ClientContact, ClientCorporation, JobOrder, JobSubmission, Placement, PlacementChangeRequest, Note, Tearsheet, CorporateUser, UserMessage; you hit an unfamiliar recruitment term (tearsheet, shortlist, placement, extension, owner); or you need to understand picklists. Provides syntax reference tables, an endpoint support matrix, the entity relationship map, a recruitment glossary and workflow, and the picklist model, all grounded in this repo's code and tests.
---

# Bullhorn Query Languages and Entity Model

Bullhorn is a recruitment ATS/CRM (Applicant Tracking System / Customer Relationship Management: the database recruiters run their business in). This repo is an MCP (Model Context Protocol) server that wraps Bullhorn's REST API. This skill teaches the API's five access styles, their syntax, which entities support which style, how the entities relate, and the recruitment domain, assuming zero prior Bullhorn or recruitment knowledge.

All code references are to this repo. As of 2026-07-03 (v0.0.46, 648 tests): `src/bullhorn_mcp/client.py` is 594 lines, `src/bullhorn_mcp/server.py` is 3383 lines with 38 tools. Line numbers below are from that snapshot; treat them as volatile.

## Glossary (jargon used in this skill)

| Term | Meaning |
|---|---|
| Lucene | Query language of Bullhorn's `/search` endpoints: `field:value` pairs with `AND`/`OR`, backed by a search index |
| SQL-ish WHERE | Query language of Bullhorn's `/query` endpoints: `field='value'` clauses, like a SQL WHERE fragment (Bullhorn docs call it JPQL-like) |
| Entity | A Bullhorn record type (Candidate, JobOrder, ...). Each has its own ID sequence, so Candidate 123 and JobOrder 123 are unrelated records |
| Association | A to-many link between entities (e.g. a Candidate's notes, a Tearsheet's candidates), read/written via dedicated sub-endpoints |
| Field projection | The `fields=` parameter selecting which fields to return, including nested association fields like `owner(id,firstName)` |
| Picklist | A field whose values come from an admin-configured dropdown list (e.g. `status`); `/meta` reports the options as `{value, label}` dicts |
| Soft delete | Bullhorn flags records `isDeleted` instead of removing them; queries must filter them out (the client does this automatically) |
| BhRestToken | The session token header every REST call carries (see bullhorn-mcp-auth-and-identity) |
| Enrichment | This project's startup step that injects live `/meta` field inventories into tool descriptions (see bullhorn-mcp-docs-and-writing) |
| CR | Change Request, this project's unit of planned change, written as a `CRx.md` file (see bullhorn-mcp-change-control) |
| Tearsheet / hotlist | A named list of candidates a recruiter curates (defined fully in the workflow section below) |

## The five access styles

| # | Endpoint | Language | Key params | Response shape | Client method (client.py) |
|---|---|---|---|---|---|
| 1 | `GET /search/{entity}` | Lucene | `query`, `fields`, `count` (max 500), `start`, `sort` | `{data, total, start, count}` | `search()` / `search_with_meta()` |
| 2 | `GET /query/{entity}` | SQL-ish WHERE | `where`, `fields`, `count` (max 500), `start`, `orderBy` | `{data, total, start, count}` | `query()` / `query_with_meta()` |
| 3 | `GET /entity/{entity}/{id}` | none (direct ID) | `fields` | `{data: {...}}` (single record) | `get()` |
| 4 | `GET /entity/{entity}/{id}/{assoc}` | none | `fields`, `count` (max 500), `start`, `orderBy` | `{data, total, start, count}` | `get_association()` / `_with_meta`; `add_association()` (PUT), `remove_association()` (DELETE) |
| 5 | `GET /meta/{entity}` | none | `fields=*` | `{fields: [...]}` field inventory | `get_meta()` |

Note the param-name asymmetry: `/search` sorts with `sort`, while `/query` and association endpoints sort with `orderBy` (client.py lines 258-259, 333-334, 509-510). All accept a leading `-` for descending, e.g. `-dateAdded`.

Style 3's URL space also carries writes: `PUT /entity/{entity}` creates, `POST /entity/{entity}/{id}` updates (yes, that way round). The wrapper behavior of `create()`/`update()` and which tool wraps which endpoint are owned by bullhorn-mcp-architecture-contract.

### 1. /search: Lucene syntax

Exercised throughout server.py docstrings and query builders, and asserted in tests/test_client.py (`TestExcludeDeletedFilter`, from line 812 as of 2026-07-03).

| Construct | Example | Where exercised in this repo |
|---|---|---|
| Field match | `status:Approved` | server.py search_entities examples |
| Trailing wildcard | `name:Acme*`, `name:CFO*` | list_companies, list_tearsheets docstrings; `_company_broad_query` builds `name:{term}*` (server.py ~line 152) |
| Dotted association field | `owner.id:99`, `jobOrder.id:12345`, `sender.id:{person_id}` | list_tearsheets docstring, search_entities examples, search_emails clause builder (server.py ~line 1230) |
| Boolean as 0/1 | `isOpen:1`, `isDeleted:0` | list_jobs docstring; client.py appends `AND isDeleted:0` |
| Boolean as true/false | `isOpen:true` | CLAUDE.md live-API example only; both forms work, prefer `0`/`1` (the codebase convention) |
| AND / OR | `(sender.id:5 OR recipients.id:5)` | search_emails clause builder |
| Parenthesization | `(A OR B) AND isDeleted:0` | client.py line 246: `f"({query}) AND isDeleted:0"` |
| NOT | `NOT status:Archived` | standard Lucene, NOT exercised anywhere in this repo; verify live before relying on it |

Rules that have caused real bugs (history in bullhorn-mcp-failure-archaeology):

- **Always parenthesize a caller-supplied query before appending clauses.** `A OR B AND isDeleted:0` binds the AND tighter than the OR and leaks soft-deleted rows. The client wraps unconditionally: `(query) AND isDeleted:0`, and sends bare `isDeleted:0` when the query is empty (tests at test_client.py lines 817-847 as of 2026-07-03).
- Lucene booleans in this codebase are `0`/`1` (`isDeleted:0`), never `=false` (that is /query syntax).
- The Lucene index has per-tenant configuration hazards (deleted records included in the index, unindexed sort/date fields, Note/UserMessage index gaps): see bullhorn-mcp-api-quirks.

### 2. /query: SQL-ish WHERE syntax

Exercised in get_job_submissions, list_placements, `_shortlist_one`, and `resolve_owner` (client.py line 477-481).

| Construct | Example | Where exercised in this repo |
|---|---|---|
| Equality, single-quoted string | `status='Active'`, `name='{owner}'` | get_job_submissions (server.py ~line 1009), resolve_owner |
| Boolean | `isDeleted=false` | client.py line 321 auto-append |
| Numeric comparison | `salary > 100000`, `dateBegin >= {epoch_ms}` | query_entities docstring, list_placements clause builders |
| Dotted association field | `jobOrder.id={job_id}`, `candidate.id={id}` | get_job_submissions, `_shortlist_one` dedup check |
| AND | `candidate.id=5 AND jobOrder.id=9` | `_shortlist_one` |
| Match-all fallback | `id IS NOT NULL` | list_placements `_build_placement_where()` when no filters given |

Rules that have caused real bugs:

- **String literals take SINGLE quotes only.** Double quotes parse as a field name and 400. Fixed in commit 01cc962 ("use single quotes in get_job_submissions status WHERE clause"); verify with `git show 01cc962`.
- Booleans are `=false`/`=true` here, never `:0`/`:1` (that is Lucene syntax). The two languages are not interchangeable.
- Dates are epoch-milliseconds integers, compared numerically: list_placements converts ISO dates via `_iso_to_epoch_ms()` and builds `requestCustomDate1 >= {ms}`.
- OPEN DEBT: several call sites (get_job_submissions `status`, `resolve_owner` name, identity resolution) interpolate strings into WHERE clauses unescaped; only list_placements rejects embedded `'` (CR33 M2). Workaround: never pass untrusted strings containing `'`; validate like list_placements does (server.py ~line 625). Suggest a CR to centralize a quote guard. Details in bullhorn-mcp-architecture-contract.

### 3. /entity: direct GET by ID, and field projection

`get(entity, entity_id, fields)` hits `GET /entity/{entity}/{id}?fields=...` and returns the `data` dict (client.py lines 375-393).

Field projection syntax (works on `fields=` for ALL five styles):

| Form | Example | Verified in |
|---|---|---|
| Flat list | `id,title,status` | `DEFAULT_FIELDS` (client.py lines 14-39) |
| Association projection | `owner(id,firstName)`, `candidate(id,name)`, `jobOrder(id,title)` | `DEFAULT_FIELDS["Placement"]`, `DEFAULT_FIELDS["JobSubmission"]` |
| Nested (two levels) | `placement(id,status,candidate(id,name),jobOrder(id,title))` | `_PCR_DEFAULT_FIELDS` (server.py ~line 514) |
| All fields | `fields=*` | `get()` fallback when entity absent from `DEFAULT_FIELDS` |

`fields=*` is a tenant hazard (some tenants reject it per entity, which made successful writes look failed): see bullhorn-mcp-api-quirks.

### 4. Association endpoints

Read: `GET /entity/{Entity}/{id}/{association}` returns the same `{data, total, start, count}` envelope as search/query. This is THE way to read notes: `get_notes_for_entity` calls `get_association_with_meta(entity, entity_id, "notes", ...)` (server.py ~line 3091), and `get_tearsheet` reads `candidates` the same way (~line 856).

Write: to-many membership is edited by ID list in the URL, comma-joined:

```
PUT    /entity/Tearsheet/{id}/candidates/1,2,3   # add    (client.add_association)
DELETE /entity/Tearsheet/{id}/candidates/1,2,3   # remove (client.remove_association)
```

Verified at client.py lines 550-576; used by add_to_tearsheet / remove_from_tearsheet (server.py ~lines 932, 963); specified in PRD.md FR-21.

### 5. /meta: the field inventory and the project's source of truth

`get_meta(entity)` hits `GET /meta/{entity}?fields=*` (client.py lines 578-588). The response's `fields` list gives, per field: `name` (API name), `label` (UI display name), `type`, `required`, and for picklist fields `options` (list of `{value, label}`). `BullhornMetadata.get_fields()` (metadata.py) caches this per entity per process and projects exactly those keys.

Treat `/meta` as ground truth for field validity: this project uses it for label-to-API-name resolution, the `isDeleted` auto-clause gate (`_entity_has_isdeleted`), value truncation against `maxLength`, Note-action validation, and startup description enrichment. When unsure whether a field exists on an entity, check `/meta` first; never guess API names (guessing produced the project's biggest dead end, see bullhorn-mcp-failure-archaeology).

## Endpoint support matrix

Not every entity supports every style. Verified exceptions:

| Entity | /search (Lucene) | /query (WHERE) | Notes |
|---|---|---|---|
| Note | comments text only; record-scoped filters unreliable | **NO /query/Note exists**; `query_entities` hard-refuses `entity="Note"` (server.py ~line 1122) | Read notes via the association endpoint. `/search/Note` needs a per-tenant index (bullhorn-mcp-api-quirks) |
| ClientCorporation | **ID lookups return `[]`**: `search_entities("ClientCorporation", "id:9493")` finds nothing (documented in CR25.md item 1); name searches work | works (no `isDeleted` field, clause auto-skipped) | Fetch by ID via `/entity` (`get_company` tool exists for exactly this reason) |
| UserMessage | works but `entityId` param is mandatory and index is partial | n/a in this repo | Details in bullhorn-mcp-api-quirks |
| Everything else used here | works | works | `isDeleted` clause auto-appended when `/meta` shows the field |

When a search returns empty and you expected rows, route through bullhorn-mcp-debugging-playbook before concluding the data is absent.

## Entity relationship map

Grounded in `DEFAULT_FIELDS` (client.py lines 14-39), write payloads in server.py, and `_ENTITY_FIELD` in `client.add_note` (client.py lines 435-443).

```
ClientCorporation (a client company)
  |-- ClientContact.clientCorporation      (contact works at company)
  |-- JobOrder.clientCorporation           (job belongs to company)
  |-- Placement.clientCorporation          (denormalized onto placement)

JobOrder (a vacancy)                        fields: clientCorporation, clientContact, owner
  |-- JobSubmission.jobOrder                (candidate submitted to job)
  |-- Placement.jobOrder                    (candidate placed in job)

Candidate (a job seeker)                    NO clientCorporation FK; current employer is
  |                                         free-text companyName (server.py ~line 1918)
  |-- JobSubmission.candidate
  |-- Placement.candidate
  |-- Tearsheet <-> candidates              (to-many association, both directions)

JobSubmission = {candidate, jobOrder, status, dateWebResponse, sendingUser}
Placement     = {candidate, jobOrder, clientCorporation, status, dateBegin, dateEnd}
PlacementChangeRequest.placement            (child of one Placement; requestType,
                                             requestStatus, requestCustomDate1)

Note: one subject-reference field per target entity type:
  personReference -> Candidate | ClientContact     clientCorporation -> ClientCorporation
  jobOrder -> JobOrder                             placements/leads/opportunities -> lists
  commentingPerson -> CorporateUser (author)

CorporateUser (a recruiter/consultant): referenced as owner (Candidate, ClientContact,
  JobOrder, Tearsheet), sendingUser (JobSubmission), commentingPerson (Note),
  sender/toRecipients/ccRecipients (UserMessage)

UserMessage (a synced email): sender, toRecipients, ccRecipients, messageFiles, threadID
Tearsheet (hotlist): owner + candidates association
Lead / Opportunity: valid note targets in this repo (_NOTE_TARGET_ENTITIES), otherwise untouched
```

Two structural facts that trip newcomers:

- **Candidate is internally a subtype of User** in Bullhorn's data model. Verified statement in CR23.md: join-table rows for Candidate notes carry `targetEntityName='User'`, not `'Candidate'`. This is why the NoteEntity join table is unreliable and notes are read via associations (full incident: bullhorn-mcp-failure-archaeology; quirk detail: bullhorn-mcp-api-quirks).
- **Entity IDs are per-type sequences.** A Candidate and a JobOrder can share ID 123. Never treat a bare ID as globally unique; always pair it with its entity type.

Per-entity field semantics (title vs occupation, name computation, source vs candidateSource, customText mappings) are owned by bullhorn-mcp-api-quirks.

## Recruitment domain: glossary and workflow

The commercial pipeline this data model represents, in order:

| Step | Entity | What happens |
|---|---|---|
| 1. Win a client | ClientCorporation | A company that pays the consultancy to fill roles |
| 2. Know the buyer | ClientContact | The person at that company who hires (a job title, an email) |
| 3. Take a job | JobOrder | A vacancy the client wants filled: title, salary, openings, owner |
| 4. Source people | Candidate | Job seekers, often created from a parsed CV |
| 5. Shortlist | JobSubmission | Links one Candidate to one JobOrder with a status (e.g. "Shortlisted", "Interviewing", "Offered", "Placed"). This IS the pipeline: `get_job_submissions` reads it, the shortlist tools write it |
| 6. Place | Placement | The candidate got the job. Revenue event: status, dateBegin, dateEnd, fee data |
| 7. Extend | PlacementChangeRequest | A contract placement gets extended. In this tenant an extension is NEVER a new Placement row: it is a PlacementChangeRequest with `requestType='Contract Extension'` whose `requestCustomDate1` ("Extension Start Date") steps forward, while `Placement.dateBegin` stays pinned to the original start (CR33.md; enforced by `list_placements`, which never merges the two record types) |

Supporting concepts:

- **Tearsheet (hotlist):** a named candidate list a consultant curates for a client brief or a passive talent pool (PRD.md FR-21). Not tied to one job; it is a working set.
- **Owner attribution:** every contact/company/candidate carries an `owner` (CorporateUser). Commercially this drives whose relationship it is, activity reporting, and downstream automation; PRD.md requires "correct ownership" on every created record and the whole identity-resolution machinery exists to stamp it (mechanics: bullhorn-mcp-auth-and-identity).
- **Duplicate prevention:** duplicate contacts/candidates pollute outreach (double emails to the same person), corrupt ownership, and break automation keyed on records. PRD FR-3/FR-4 mandate fuzzy dedup before create; it matters doubly here because Bullhorn can partially persist a record while returning an error, and a retrying LLM then creates duplicates (quirk detail: bullhorn-mcp-api-quirks).
- **Note:** a timestamped activity log entry (call, meeting, general note) attached to a record via one subject field per entity type, with an `action` picklist.
- **UserMessage:** an email synced into Bullhorn, searchable per person mailbox.

## Picklists

A picklist field's legal values are configured per Bullhorn instance by an admin, not fixed by the API. `/meta` reports them under the field's `options` key as a list of `{value, label}` dicts (metadata.py `get_fields()` docstring; descriptions.py inlines `o.get("value")` as "Valid values: ..." for the fields in `PICKLIST_FIELDS_TO_EXPAND`: status, employmentType, category, type, source).

Two distinct questions, two distinct answers:

1. **WHAT values exist** is metadata: read `/meta` (e.g. `add_note` validates `action` against the live Note picklist and returns the valid list on mismatch, server.py ~line 1718).
2. **WHICH value means what for this team** is deployment policy, not discoverable from metadata. Example: nothing in `/meta` says which JobSubmission status means "shortlisted" for this consultancy; that lives in the `BULLHORN_SHORTLIST_STATUS` env var (default "Shortlisted", validated warn-only at first use). This is why per-tenant meaning goes into env config, never hardcoded. The full env var catalog and the config philosophy are owned by bullhorn-mcp-config-and-flags.

## When NOT to use this skill

| You need | Go to |
|---|---|
| Per-entity behavioral quirks, tenant hazards, field semantics (title/occupation, fields=*, entityId, partial persistence, index gaps) | bullhorn-mcp-api-quirks |
| Which MCP tool wraps which endpoint; wrapper invariants (isDeleted gate internals, pagination envelope, create/update behavior) | bullhorn-mcp-architecture-contract |
| History of how a query design failed before (notes saga, isDeleted arc, create_job dead end) | bullhorn-mcp-failure-archaeology |
| A query is misbehaving right now and you want triage | bullhorn-mcp-debugging-playbook |
| Verifying a syntax assumption against the live tenant before coding | bullhorn-mcp-live-api-method |
| OAuth, BhRestToken, identity resolution, owner stamping mechanics | bullhorn-mcp-auth-and-identity |
| Env vars that configure picklist policy and per-tenant aliases | bullhorn-mcp-config-and-flags |
| Writing/mocking tests for queries | bullhorn-mcp-testing-playbook |

## Provenance and maintenance

Every claim category here can drift. Re-verify before trusting:

| Claim | Re-verification command |
|---|---|
| Five access styles, param names, count cap, response envelopes | `grep -n "def search_with_meta\|def query_with_meta\|def get\b\|def get_association\|def get_meta\|orderBy\|\"sort\"\|min(count, 500)" src/bullhorn_mcp/client.py` |
| Lucene isDeleted wrap and 0/1 booleans | `grep -n "isDeleted:0" src/bullhorn_mcp/client.py tests/test_client.py` |
| SQL single-quote rule and its fix | `git show 01cc962 --stat` and `grep -n "status='" src/bullhorn_mcp/server.py` |
| No /query/Note refusal | `grep -n "entity_not_queryable" src/bullhorn_mcp/server.py` |
| ClientCorporation Lucene ID-lookup failure | `grep -n "id:9493" CR25.md` |
| Tearsheet association PUT/DELETE comma-join | `grep -n "add_association\|remove_association" src/bullhorn_mcp/client.py src/bullhorn_mcp/server.py` |
| /meta projection keys and picklist `{value, label}` shape | `grep -n "options" src/bullhorn_mcp/metadata.py src/bullhorn_mcp/descriptions.py` |
| Entity relationship fields | `sed -n '14,39p' src/bullhorn_mcp/client.py` and `grep -n "_ENTITY_FIELD" src/bullhorn_mcp/client.py` |
| Candidate-is-a-User | `grep -n "subtype of the .User. entity" CR23.md` |
| Placement vs PlacementChangeRequest model | `grep -n "requestCustomDate1\|Contract Extension" src/bullhorn_mcp/server.py CR33.md` |
| Candidate has no clientCorporation FK (free-text companyName) | `grep -n "NOT clientCorporation" src/bullhorn_mcp/server.py` |
| Shortlist status env policy | `grep -n "BULLHORN_SHORTLIST_STATUS\|DEFAULT_SHORTLIST_STATUS" src/bullhorn_mcp/shortlist_config.py` |
| Tool count / test count / line counts | `grep -c "@mcp.tool()" src/bullhorn_mcp/server.py`; `.venv/bin/pytest -q`; `wc -l src/bullhorn_mcp/server.py src/bullhorn_mcp/client.py` |
| WHERE-interpolation OPEN DEBT still open | `grep -n "in status" src/bullhorn_mcp/server.py` (only list_placements guards) and `grep -n "where=f" src/bullhorn_mcp/server.py src/bullhorn_mcp/client.py` |
