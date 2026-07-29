---
name: bullhorn-mcp-debugging-playbook
description: "Load this skill FIRST when triaging any live misbehavior of the Bullhorn MCP server: a 400 'invalid field' on a write, empty results that should not be empty, a write that reported failure but the record exists in Bullhorn, an agent stuck in a pagination loop, records created with the wrong owner, a 500 from the notes tools, a 400 from email search, an auth failure, the server dying at import/startup, or tool descriptions missing their field reference. Provides a symptom-to-suspects routing table with ranked suspects and a discriminating experiment (copy-pasteable, read-only) for each, plus the named CR6 5-layer injection checklist and the check-/meta-first reflex. Route here BEFORE guessing at causes; every entry echoes a real past incident."
---

# Bullhorn MCP Debugging Playbook

Symptom-first triage for live problems in this repo. Each routing entry lists suspects in ranked order (most likely first, based on what actually happened in this project's history), a discriminating experiment that tells suspects apart, and the past incident it echoes. Full incident narratives live in the sibling skill bullhorn-mcp-failure-archaeology; this skill is the routing layer.

Volatile facts in this file are as of 2026-07-03 (tag v0.0.46, 648 tests passing, verified by running `.venv/bin/pytest` this session). Line numbers cited are from that revision and will drift; the Provenance section gives re-verification commands.

## Jargon, defined once

| Term | Meaning |
|---|---|
| CR | Change Request: a `CRx.md` plan file in the repo root; the unit of change control (see bullhorn-mcp-change-control) |
| Lucene | The query syntax of Bullhorn's `/search/{entity}` endpoint (`isOpen:true`, booleans as `0/1`) |
| SQL-ish WHERE | The syntax of Bullhorn's `/query/{entity}` endpoint (`isDeleted=false`, single-quoted strings) |
| BhRestToken | The session token Bullhorn's REST login returns; sent as a header on every API call |
| picklist | A Bullhorn field with a fixed set of allowed `{value, label}` options, served by `/meta` |
| /meta | `GET /meta/{entity}`: Bullhorn's per-entity field inventory (name, label, type, required, picklist options); this project's source of truth for field validity |
| enrichment | The startup step where `enrich_tool_descriptions()` appends live `/meta` field references to tool docstrings |
| isDeleted auto-append | `BullhornClient.search()`/`query()` silently append `AND isDeleted:0` (Lucene) or `AND isDeleted=false` (SQL) unless the entity lacks the field or `exclude_deleted=False` is passed |
| Entra | Microsoft Entra ID (Azure AD): the OIDC provider protecting the hosted HTTP transport |
| tearsheet | A Bullhorn hotlist: a named saved list of candidates/records |
| targetEntityName | A column on Bullhorn's NoteEntity join table; unreliable (stores 'User' for Candidate rows) and no longer used by this codebase |

## The two reflexes (do these before anything else)

1. Check /meta first. Any theory involving a field name is testable in seconds, read-only:

```bash
.venv/bin/python .claude/skills/bullhorn-mcp-live-api-method/scripts/meta_dump.py ClientContact title
```

Substitute entity and optional substring filter. If the field is absent from `/meta`, the field name is wrong, full stop. The live-check cookbook and script docs are in bullhorn-mcp-live-api-method.

2. Reproduce read-only before touching anything. Read-only client methods (`search`, `query`, `get`, `get_association`, `get_meta`) are freely callable against the live tenant per CLAUDE.md. Destructive methods (`create`, `update`, `add_note`, `attach_file`, `parse_resume_file`) require explicit user permission; never call them to "test a fix".

Any fix you land still goes through the CR, review, tag cycle (bullhorn-mcp-change-control). Debugging routes you to the cause; it does not authorize hotfixes around change control.

## Routing table

### Symptom 1: 400 "invalid field" on a write (create/update)

| Rank | Suspect | Discriminating experiment |
|---|---|---|
| 1 | title/occupation semantics: caller sent `title` meaning job title. On ClientContact `title` is the salutation; on Candidate `title` does not exist at all; job title is `occupation` on both | Check the error text for the field name, then `meta_dump.py <Entity> <field>`. If absent from /meta the caller's field name is the bug. Note: `_strip_contact_title()` in src/bullhorn_mcp/server.py already strips `title` and `name` on Candidate/ClientContact writes, so if the 400 names `title` on those entities, a code path BYPASSED the strip helper: find it |
| 2 | Field injected somewhere in the 5-layer path (the field in the error is not in the caller's payload) | Run the CR6 5-layer injection checklist below |
| 3 | Stale agent tool schema: the calling agent sends `fieldname: null` for every parameter its cached schema lists | Ask for (or log) the exact JSON the agent sent to the MCP tool. Null-valued keys the user never typed = stale schema; fix is docstring/schema level, not code |
| 4 | Alias mismatch: caller used a display label that FIELD_ALIASES or /meta remaps to something unexpected (or fails to remap) | Run the resolution inline, read-only: see Layer 2 command in the checklist below |

Echoes: the CR1-CR7 ClientContact field-injection saga and the CR18 Candidate-title origin bug (bullhorn-mcp-failure-archaeology). Recurrence of this class is auto-CRITICAL in review (bullhorn-mcp-review-protocol).

### Named procedure: the CR6 5-layer injection checklist

Use when a write fails on a field the caller swears they never sent. CR6 established that a field can enter the payload at five distinct layers; check ALL five, in order, even after the first hit (CR6 found multiple contributors).

| Layer | What can inject | How to inspect |
|---|---|---|
| 1. Caller payload | The calling agent itself adds the field (learned it from a docstring example, or a stale tool schema makes it send `field: null` on every call) | Capture the exact tool-call JSON from the agent transcript. Also check the docstring: `grep -n '"title"' src/bullhorn_mcp/server.py` (CR4's bug was a docstring example teaching agents the wrong field) |
| 2. Label remapping | `BullhornMetadata.resolve_fields()` remaps a caller key whose lowercase matches a FIELD_ALIASES entry, or whose text matches a /meta display label | Read-only inline check: run the snippet below with the real payload and diff input vs output keys |
| 3. Server helpers | Tool-body dict mutations in src/bullhorn_mcp/server.py between resolution and the client call: defaults merges, `_compute_person_name`, owner stamping, source stamping; also DEFAULT_FIELDS (a READ-side constant) leaking into a write path | Read the tool function top to bottom; list every statement that adds or renames a dict key. Then `grep -n "DEFAULT_FIELDS" src/bullhorn_mcp/server.py src/bullhorn_mcp/client.py` and confirm no write path references it |
| 4. Client body mutation | `client.create()`/`update()`/`_request()` altering the `json=` body | `sed -n '73,101p' src/bullhorn_mcp/client.py` and read `create`/`update`: as of 2026-07-03 the body passes through untouched; verify that is still true |
| 5. Raw HTTP body | The only ground truth. Everything above can look clean while the wire bytes differ | Write a respx test that captures `request.content` and asserts the exact JSON body (the CR6 law: payload-assertion tests must capture the RAW POST body, not method args; see bullhorn-mcp-testing-playbook) |

Layer 2 inline check (read-only, uses live /meta):

```bash
.venv/bin/python -c "
from bullhorn_mcp.config import BullhornConfig
from bullhorn_mcp.auth import BullhornAuth
from bullhorn_mcp.client import BullhornClient
from bullhorn_mcp.metadata import BullhornMetadata
md = BullhornMetadata(BullhornClient(BullhornAuth(BullhornConfig.from_env())))
payload = {'firstName': 'Test', 'job title': 'CTO'}  # substitute the real payload
print(md.resolve_fields('ClientContact', payload))
"
```

### Symptom 2: empty results that should not be empty

| Rank | Suspect | Discriminating experiment |
|---|---|---|
| 1 | isDeleted auto-append: the caller's query was complete, but the client appended `AND isDeleted:0` / `AND isDeleted=false` and the target records are soft-deleted | Re-run the same query with `exclude_deleted=False` via inline Python (read-only `client.search(...)` / `client.query(...)`). Results appear = deleted records were the answer |
| 2 | The `/search/{entity}` route itself returns nothing, whatever the query. On this account `/search/Note` returns `total: 0` for every query, including a primary-key lookup for a note `/entity/Note/{id}` returns normally. Do NOT use `fieldsFromIndex` to test this — working searches return `false` too (`/search/JobOrder`: `false` with `total: 50271`), a false signal that sent the CR37 investigation down the wrong path for five attempts | Match-all probe, read-only: `client._request('GET','/search/Note',{'query':'id:[0 TO 99999999]','fields':'id','count':1})`. `total: 0` = the route returns nothing, so the caller's empty result says nothing about their data. `search_notes` runs exactly this probe and attaches a `warnings` key. Route the caller to the nested `notes.action` pattern, `note_action` on the list tools, or `get_notes_for_entity` |
| 3 | ID lookup attempted via Lucene: `search_entities("ClientCorporation", "id:9493")` returns `[]` on this tenant; ID lookups need `/entity` | Compare read-only: `client.get('ClientCorporation', 9493)` succeeds while `client.search('ClientCorporation', 'id:9493')` returns nothing = wrong endpoint, use `get_company`/`get()` |
| 4 | Unindexed date-range silently matching nothing: a Lucene range on an unindexed field (e.g. `smtpSendDate:[...]` on UserMessage) errors on sort but silently returns 0 on filter. OPEN DEBT: `search_emails` `since`/`until` still builds `smtpSendDate:[lo TO hi]` (src/bullhorn_mcp/server.py near line 1236 as of 2026-07-03); workaround: drop since/until and filter client-side, or range on `smtpReceiveDate`; suggest a CR to switch the filter field | Re-run the identical query WITHOUT the date clause. Results appear = the range clause is the killer, not the data |
| 5 | targetEntityName filtering (legacy): any code path filtering notes by NoteEntity `targetEntityName` drops rows because Bullhorn stores 'User' for Candidate notes and mixes 'JobOrder'/'User' for jobs | `grep -rn "targetEntityName" src/` should return nothing; if it returns anything, that code is the bug. Correct read path is `GET /entity/{Entity}/{id}/notes` (client `get_association`) |

Echoes: CR16 soft-delete false positives, the CR21-CR23 notes saga, CR24 email sort, CR25 Pinergy ID lookup (bullhorn-mcp-failure-archaeology). Quirk details per entity: bullhorn-mcp-api-quirks.

### Symptom 3: write "fails" but the record EXISTS in Bullhorn

Do NOT retry first. Bullhorn can partially persist a record and still return an error, and a retry creates a duplicate (CR5, real duplicate IDs 170841-170843). Verify existence read-only before anything else:

```bash
.venv/bin/python -c "
from bullhorn_mcp.config import BullhornConfig
from bullhorn_mcp.auth import BullhornAuth
from bullhorn_mcp.client import BullhornClient
client = BullhornClient(BullhornAuth(BullhornConfig.from_env()))
print(client.search('ClientContact', 'lastName:Smith', fields=['id','firstName','lastName','dateAdded'], count=5))
"
```

| Rank | Suspect | Discriminating experiment |
|---|---|---|
| 1 | Post-write GET failed, not the write: `create()`/`update()` in src/bullhorn_mcp/client.py never return the POST/PUT response; they call `get()` afterwards. If that read 400s, a successful write looks failed | Does the error text mention fields or authorization rather than the write? Check whether the entity is in `DEFAULT_FIELDS` (src/bullhorn_mcp/client.py lines 14-39 as of 2026-07-03): a missing entity falls back to `fields=*` on `get()` |
| 2 | `fields=*` permission: this tenant rejects `fields=*` on some entities (JobSubmission: 400 "not authorized to request all fields") | `client.get('JobSubmission', <id>)` inline: if it 400s with an all-fields message while `client.get('JobSubmission', <id>, fields=['id','status'])` works, add the entity to `DEFAULT_FIELDS` (that was the CR17 fix) |
| 3 | Genuine partial persistence: Bullhorn wrote part of the record then errored | The record exists but has missing/null fields vs the payload. Compare the read-only `get()` result against what was sent |

Echoes: CR17 (shortlist reported 0 created while JobSubmissions 94607-94612 were written), CR5 duplicates (bullhorn-mcp-failure-archaeology).

### Symptom 4: infinite or stuck pagination

| Rank | Suspect | Discriminating experiment |
|---|---|---|
| 1 | next_start arithmetic broken by client-side filtering: `get_notes_for_entity` filters soft-deleted notes in Python AFTER fetching, so `next_start` must advance by the RAW page count (`raw_page_count`), never by the filtered `count`. If a page is all-deleted and next_start does not advance, the agent loops forever | Read the tool's pagination block (`grep -n "raw_page_count" src/bullhorn_mcp/server.py`) and confirm `next_start = start + raw_page_count`. Then reproduce read-only with `client.get_association_with_meta(...)` on a record known to have deleted notes and hand-check the arithmetic |
| 2 | Consumer computing its own offset: the envelope contract is "always use `next_start`, never `start + count`". An agent or script doing `start + count` under-advances whenever filtering dropped rows | Inspect the consumer's calls: are the `start` values it sends equal to the `next_start` values it received? |
| 3 | `_paginate_envelope` misuse on a new tool: the shared helper (src/bullhorn_mcp/server.py, `def _paginate_envelope`) assumes NO client-side filtering between fetch and envelope. A new tool that filters rows then calls it will report wrong `count`/`next_start` | `grep -n "_paginate_envelope" src/bullhorn_mcp/server.py` and check each call site for filtering between the `*_with_meta` call and the envelope |

Echo: the CR28 pagination triple-cycle, where a review-prescribed fix was itself flagged as an infinite loop the next cycle (bullhorn-mcp-failure-archaeology).

### Symptom 5: wrong owner on created records

| Rank | Suspect | Discriminating experiment |
|---|---|---|
| 1 | Identity cache keying: the cache in src/bullhorn_mcp/identity.py must be a dict keyed by the Entra `sub` claim. Any regression to a single slot or email keying gives user B records owned by user A in shared HTTP deployments | `grep -n "_caller_cache" src/bullhorn_mcp/identity.py`: confirm `dict[str, dict]` keyed by `claims["sub"]`. Then check: are ALL wrong-owner records owned by the FIRST user active after a restart? That signature = cache keying |
| 2 | Dict-merge precedence: a `payload.update(...)` AFTER owner resolution lets caller data silently override the resolved owner | In the affected tool in src/bullhorn_mcp/server.py, find the `resolve_owner` call and read every mutation after it; any later merge that can write the `owner` key is the bug. `grep -n "resolve_owner" src/bullhorn_mcp/server.py` lists the call sites |
| 3 | resolve_owner leakage: `resolve_owner` must contribute only `{"id": int}` to payloads; and CorporateUser queries must never include `department` (invalid on some tenants, kills resolution silently) | `grep -n "department" src/bullhorn_mcp/identity.py src/bullhorn_mcp/client.py` should hit only the warning comments |

Echoes: CR11 first-writer-wins cache, CR3 owner leakage, the Sprint 21 merge-precedence finding (bullhorn-mcp-failure-archaeology). Auth/identity design detail: bullhorn-mcp-auth-and-identity.

### Symptom 6: 500 from the notes tools

| Rank | Suspect | Discriminating experiment |
|---|---|---|
| 1 | Default-fields drift: Bullhorn started rejecting a field in `_NOTE_DEFAULT_FIELDS` server-side. This has happened: `clientCorporation(id,name)` worked, then began 500ing on the association endpoint (CR25 fix 3). Bullhorn's API surface drifts under you | Bisect the field list read-only: call `client.get_association('Candidate', <id>, 'notes', fields='id')` (works?) then add fields back one at a time until it 500s |
| 2 | The two note-field constants diverged: `_NOTE_DEFAULT_FIELDS` and `_NOTE_SEARCH_DEFAULT_FIELDS` in src/bullhorn_mcp/server.py are intentionally byte-identical with a keep-in-sync comment; they diverged once (CR22). OPEN DEBT: they remain duplicates; suggest folding into one constant in a future CR | `grep -n "_NOTE_DEFAULT_FIELDS\|_NOTE_SEARCH_DEFAULT_FIELDS" src/bullhorn_mcp/server.py` and diff the two string bodies by eye |
| 3 | Caller-supplied `fields` includes a rejected field (e.g. `clientCorporation`) | Re-run with `fields=None` (defaults). Works = the caller's field list is the bug |

Echoes: the notes saga, three breakages of one feature (bullhorn-mcp-failure-archaeology); which fields each note endpoint rejects: bullhorn-mcp-api-quirks.

### Symptom 7: 400 from /search/UserMessage (search_emails)

| Rank | Suspect | Discriminating experiment |
|---|---|---|
| 1 | Missing mandatory `entityId`: Bullhorn REQUIRES the `entityId` query parameter on `GET /search/UserMessage`. Removing it caused a 12-day production outage; the restore is `extra_params={"entityId": person_id}` in `search_emails` (src/bullhorn_mcp/server.py near line 1253 as of 2026-07-03). Never remove it, whatever the semantic argument | Error text says "Missing parameter entityId"? Then `grep -n "entityId" src/bullhorn_mcp/server.py` and confirm the extra_params line is present |
| 2 | Unindexed sort field: `smtpReceiveDate` (server timestamp) is indexed on this tenant; `smtpSendDate` (client timestamp) is not; sorting by it errors "Bad sort: unknown field" | Read-only inline: `client.search('UserMessage', 'sender.id:<id>', sort='-smtpReceiveDate', extra_params={'entityId': <id>})` works while the same with `-smtpSendDate` errors |

Echoes: the entityId regression (12-day outage) and CR24 (bullhorn-mcp-failure-archaeology).

### Symptom 8: auth failures

First discriminate WHICH auth system failed. There are two: Bullhorn's non-standard OAuth (server to Bullhorn) and Entra OIDC (client to server, HTTP mode only).

| Signature | Layer | First suspects |
|---|---|---|
| `AuthenticationError` in tool output or logs, with text "Failed to get auth code" / "Token exchange failed" / "REST login failed" / "OAuth error" (raised in src/bullhorn_mcp/auth.py) | Bullhorn side | Bad credentials in `.env`; regional redirect handling (some accounts 307 to auth-apac/auth-emea; `_regional_auth_url` must be tracked); expired session not refreshing |
| ValueError at import: "HTTP transport requires Entra OAuth" style, before the server even starts | Entra config | Missing one of the four Entra vars in HTTP mode; this is fail-closed BY DESIGN, see Symptom 9 |
| HTTP 401 from the MCP endpoint itself, tools never run | Entra side | Token/scope/audience issues; users re-prompted to sign in = refresh-token (`offline_access`) issues |
| Tools run but return `identity_resolution_failed` JSON | Identity layer | Token lacks `sub`/`email` claims, or no matching CorporateUser |

Fastest whole-stack Bullhorn-side check (read-only):

```bash
.venv/bin/python .claude/skills/bullhorn-mcp-live-api-method/scripts/smoke_read.py
```

Succeeds = Bullhorn auth and REST are fine; the problem is Entra-side or identity-side. Full auth flow anatomy, Entra configuration, and the deeper triage table are owned by bullhorn-mcp-auth-and-identity; this table only routes you to the right layer.

### Symptom 9: server fails at import or startup

| Rank | Suspect | Discriminating experiment |
|---|---|---|
| 1 | `ModuleNotFoundError: No module named 'fastmcp'` on a fresh install. OPEN DEBT: server.py imports `fastmcp` but pyproject.toml declares only `mcp>=1.0.0`; workaround `uv pip install fastmcp`; suggest a CR to declare it | `grep -n "fastmcp\|mcp>" pyproject.toml` shows the gap. Install details: bullhorn-mcp-build-and-env |
| 2 | HTTP mode with missing Entra vars: `_build_auth()` raises ValueError at IMPORT time when `MCP_TRANSPORT=http` and any of ENTRA_TENANT_ID / ENTRA_CLIENT_ID / ENTRA_CLIENT_SECRET / MCP_BASE_URL is unset. Deliberate fail-closed design, not a bug | Error names the missing vars. `MCP_TRANSPORT=stdio .venv/bin/python -c "import bullhorn_mcp.server"` imports clean = confirmed transport-conditional |
| 3 | Non-numeric PORT: `int(os.environ.get("PORT", 8000))` runs at module import (src/bullhorn_mcp/server.py near line 161 as of 2026-07-03), so `PORT=abc` crashes import with ValueError even in stdio mode | Unset PORT and re-import |
| 4 | Unknown MCP_TRANSPORT value: `main()` raises "Unknown MCP_TRANSPORT" for anything but stdio/http | Read the error text; it names the valid values |

Env var semantics (what is read when) are owned by bullhorn-mcp-config-and-flags.

### Symptom 10: enrichment silently absent (tools lack their "Field reference" sections)

This is a DESIGNED degradation, not a crash: the whole enrichment call in `main()` is wrapped in try/except, so a dead Bullhorn at startup leaves static docstrings in place and the server runs.

| Rank | Suspect | Discriminating experiment |
|---|---|---|
| 1 | Enrichment threw and was swallowed: look for `"Could not enrich tool descriptions at startup"` (warning logged in `main()`, src/bullhorn_mcp/server.py) | Check server startup logs/stderr for that exact string. Present = enrichment failed wholesale; the exception text follows it |
| 2 | Per-entity /meta failure: `descriptions.py` logs `"Could not load metadata for <entity>"` per entity and `"No entity metadata loaded"` when all fail | `grep -n "Could not load metadata\|No entity metadata" src/bullhorn_mcp/descriptions.py` confirms the strings; then search the logs for them |
| 3 | The tool is intentionally compact: since CR34, the generic discovery tools (search_entities, query_entities, update_record, get_entity_fields) get a compact name-only field section plus a pointer to get_entity_fields, NOT the full detail. Not a bug | `grep -n "GENERIC_DISCOVERY_TOOLS" src/bullhorn_mcp/descriptions.py` lists which tools are compact by design |
| 4 | Server launched without `main()`: enrichment runs only inside `main()`; importing the module (as tests do) never enriches | How was the process started? Anything but `python -m bullhorn_mcp.server` / the `bullhorn-mcp` script skips enrichment |

Enrichment architecture and its additive-and-optional invariant are owned by bullhorn-mcp-architecture-contract; token-cost operations by bullhorn-mcp-run-and-operate.

## Cross-cutting OPEN DEBT to keep on the suspect list

| Item | Debug relevance | Workaround / next step |
|---|---|---|
| Unescaped WHERE interpolation in `get_job_submissions` (status), `resolve_owner`, and `identity.resolve_caller` (src/bullhorn_mcp/server.py near line 1009 and identity/client query builders, as of 2026-07-03) | A status or name containing `'` produces a confusing Bullhorn "bad query" 400 that looks like an API quirk | Strip/refuse quotes at the call site for now; suggest a CR extending the list_placements quote guard pattern to all interpolated params |
| `search_emails` date filter on unindexed `smtpSendDate` | since/until silently returns 0 rows | See Symptom 2 rank 4 |
| Undeclared fastmcp dependency | Fresh installs die at import | See Symptom 9 rank 1 |
| Duplicate `_NOTE_*_DEFAULT_FIELDS` constants | Divergence breaks one notes path while the other works, a very confusing split symptom | See Symptom 6 rank 2 |

## When NOT to use this skill

| Situation | Use instead |
|---|---|
| You need the full story behind an incident echoed above | bullhorn-mcp-failure-archaeology |
| You need the per-entity/per-endpoint quirk reference (which fields exist, which endpoints reject what) | bullhorn-mcp-api-quirks |
| You need the live read-only verification cookbook, script docs, or evidence-recording style | bullhorn-mcp-live-api-method |
| You are writing or fixing a Bullhorn query, not debugging one that already misbehaved | bullhorn-mcp-query-and-entity-model |
| Auth/identity deep dive (flow anatomy, Entra config, token lifetimes) | bullhorn-mcp-auth-and-identity |
| A test is failing (mocking traps, fixtures, payload-assertion law) | bullhorn-mcp-testing-playbook |
| Install/venv/dependency problems beyond the fastmcp routing entry | bullhorn-mcp-build-and-env |
| Env var and constant semantics | bullhorn-mcp-config-and-flags |
| Which invariant a proposed fix might violate | bullhorn-mcp-architecture-contract |
| Turning a diagnosis into a shipped fix | bullhorn-mcp-change-control, then bullhorn-mcp-review-protocol |

## Provenance and maintenance

Every claim category below can drift. Re-verify before trusting a stale copy of this file.

| Claim | Re-verification command |
|---|---|
| Test count and suite health (648 as of 2026-07-03) | `.venv/bin/pytest -q` |
| Current tag (v0.0.46) | `git describe --tags` |
| title/name strip helper behavior | `grep -n "_strip_contact_title" -A 25 src/bullhorn_mcp/server.py \| head -40` |
| FIELD_ALIASES contents and aliases-first order | `sed -n '20,45p' src/bullhorn_mcp/metadata.py && grep -n "entity_aliases" src/bullhorn_mcp/metadata.py` |
| isDeleted auto-append and metadata gate | `grep -n "_entity_has_isdeleted\|isDeleted:0\|isDeleted=false" src/bullhorn_mcp/client.py` |
| create/update post-write GET | `grep -n -A 4 "def create\|def update" src/bullhorn_mcp/client.py \| grep -n "self.get"` |
| DEFAULT_FIELDS entity list and `*` fallback | `sed -n '14,40p' src/bullhorn_mcp/client.py && grep -n 'DEFAULT_FIELDS.get(entity, "\*")' src/bullhorn_mcp/client.py` |
| Raw-count pagination in get_notes_for_entity | `grep -n "raw_page_count" src/bullhorn_mcp/server.py` |
| Identity cache keyed by sub | `grep -n "_caller_cache\|claims.get(\"sub\")" src/bullhorn_mcp/identity.py` |
| entityId extra_params and -smtpReceiveDate sort in search_emails | `grep -n "entityId\|smtpReceiveDate\|smtpSendDate" src/bullhorn_mcp/server.py` |
| Note field constants (duplication, no clientCorporation) | `grep -n -A 10 "_NOTE_DEFAULT_FIELDS = " src/bullhorn_mcp/server.py` |
| Import-time env reads (MCP_TRANSPORT, PORT, Entra) | `sed -n '155,215p' src/bullhorn_mcp/server.py` |
| fastmcp still undeclared | `grep -n "fastmcp" pyproject.toml src/bullhorn_mcp/server.py` |
| Enrichment try/except and warning strings | `grep -n "Could not enrich" src/bullhorn_mcp/server.py && grep -n "Could not load metadata" src/bullhorn_mcp/descriptions.py` |
| query_entities Note refusal | `grep -n "entity_not_queryable" src/bullhorn_mcp/server.py` |
| list_placements quote guard vs get_job_submissions gap | `grep -n "must not contain single quotes" src/bullhorn_mcp/server.py && grep -n "AND status='" src/bullhorn_mcp/server.py` |
| CR6 five-layer origin | `sed -n '11,30p' CR6.md` |
| Auth error strings and regional redirect handling | `grep -n "AuthenticationError\|_regional_auth_url\|307" src/bullhorn_mcp/auth.py` |
| Live-check scripts still exist | `ls .claude/skills/bullhorn-mcp-live-api-method/scripts/` |
