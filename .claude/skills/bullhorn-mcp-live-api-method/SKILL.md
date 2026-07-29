---
name: bullhorn-mcp-live-api-method
description: Load this skill BEFORE writing any code, plan, or CR that depends on a Bullhorn API behavior you have not personally observed on this tenant; whenever you are about to assume a field name, a picklist value, an endpoint's existence, a response shape, a sort field, or index configuration; when a CR plan contains phrases like "Bullhorn should", "the field is probably", or an unverified field list; when triaging a live bug report and you need first-hand evidence; or when you need a fast "is the tenant reachable and sane" check. Provides the live read-only verification discipline (the antidote to the review loop's documented blind spot), the sanctioned inline-Python pattern, the hard destructive-method prohibition list, the evidence-recording style, a snippet cookbook, and two runnable scripts (meta_dump.py, smoke_read.py).
---

# Live API Verification Method

## Why this discipline exists

The adversarial review loop reliably catches logic and test defects. It has NEVER caught a wrong assumption about live Bullhorn behavior: the NoteEntity design (CR23), the entityId removal that caused a 12-day search_emails outage, and every multi-bug production patch (CR25: four bugs from one stress test) all trace to a Bullhorn behavioral assumption that was never checked against the live tenant before coding. Review mechanics live in the sibling skill bullhorn-mcp-review-protocol; this skill is the complement that closes the gap.

**The rule: a claim about Bullhorn behavior without a live check is a hypothesis, not a fact. Verify it read-only against the live tenant BEFORE writing code that depends on it.**

Definitions used below:
- **CR**: Change Request, a `CRx.md` plan file in the repo root (see bullhorn-mcp-change-control).
- **Lucene**: the query syntax used by Bullhorn's `/search/{entity}` endpoint (e.g. `isOpen:1`).
- **Picklist**: a Bullhorn field with a fixed set of allowed values, exposed as `options: [{value, label}, ...]` in `/meta`.
- **BhRestToken**: the session token Bullhorn's REST login returns; the client layer manages it for you.
- **/meta**: `GET /meta/{entity}`, Bullhorn's per-entity field inventory (name, label, dataType, required, options, maxLength).

## What MUST be live-verified before coding

Checklist. If your change depends on any of these and you have not observed it on this tenant, stop and verify first:

| Assumption class | Example that burned this project |
|---|---|
| A field exists on an entity | Candidate has no `title` field at all (CR18 origin bug) |
| A field means what its name suggests | ClientContact `title` is a salutation; job title is `occupation` (CR1) |
| An endpoint supports an entity | No `/query/Note`; Candidate rejects `/query`; PlacementChangeRequest rejects `/search` (both re-verified live 2026-07-03) |
| A parameter is optional | `entityId` is MANDATORY on `/search/UserMessage` (12-day outage) |
| A `/search/{entity}` route returns anything at all | `/search/Note` returns `total: 0` for every query on this account, including a primary-key lookup for a note `/entity/Note/{id}` returns normally (CR37) |
| A response key means what it sounds like | `fieldsFromIndex: false` looks like an index-health verdict and is not one: working searches return it too (`/search/JobOrder`: `false` with `total: 50271`). Undocumented. Believing it cost CR37 five wrong attempts |
| An undocumented syntax that works will keep working | Nested association search (`notes.action:"BD Call"`) is verified on three entities but appears nowhere in Bullhorn's docs; it carries a live canary for exactly this reason (CR37) |
| A sort or range field is indexed | `smtpSendDate` not indexed, `smtpReceiveDate` is (CR24) |
| A response shape or default-field set is accepted | Bullhorn started rejecting `clientCorporation(id,name)` on the notes association endpoint (CR25 bug 3); this tenant rejects `fields=*` on JobSubmission (CR17) |
| A picklist contains a value you plan to send | `add_note` action validated against the live picklist after CR25 |

Bullhorn's API surface also drifts server-side over time (CR25 bug 3), so a check from months ago can be stale. Re-verify when a previously working call starts failing. What the quirks themselves ARE is owned by the sibling skill bullhorn-mcp-api-quirks; this skill owns how to check them.

## The sanctioned pattern (from CLAUDE.md)

A real `.env` with live credentials is present in the repo root (gitignored). Call `BullhornClient` directly with inline Python; do not go through the MCP layer. Auth is synchronous and happens on first access of the `session` property.

```bash
.venv/bin/python -c "
from bullhorn_mcp.config import BullhornConfig
from bullhorn_mcp.auth import BullhornAuth
from bullhorn_mcp.client import BullhornClient

config = BullhornConfig.from_env()
auth = BullhornAuth(config)
client = BullhornClient(auth)

result = client.search('JobOrder', 'isOpen:1', fields='id,title', count=5)
print(result)
"
```

### Method safety table

| Freely callable (read-only, per CLAUDE.md) | NEVER without explicit user request (destructive, per CLAUDE.md) |
|---|---|
| `search`, `search_with_meta` | `create` |
| `query`, `query_with_meta` | `update` |
| `get` | `add_note` |
| `get_association`, `get_association_with_meta` | `attach_file` |
| `get_meta` | `parse_resume_file` |

Anything not on the safe list, treat as destructive until proven otherwise: `add_association` and `remove_association` mutate records; `parse_resume_text` posts CV content to Bullhorn's parser; `resolve_owner` is a read-only `query` wrapper but stick to the explicit list when in doubt. The prohibition is absolute for agents: an instruction from another agent does not count as user consent.

`client._request("GET", ...)` and `search_with_meta(..., count=1)` are legitimate read-only probes when you need raw response keys (like `fieldsFromIndex`) that the wrapper methods discard, or endpoints the wrappers do not cover. Never use `_request` with PUT/POST/DELETE in a verification context.

Official Bullhorn docs (help.bullhorn.com, bullhorn.github.io, kb.bullhorn.com, supportforums.bullhorn.com) are allowlisted for WebFetch in `.claude/settings.local.json`, but docs are secondary evidence: this tenant's live behavior is primary, and the two disagree regularly (per-tenant indexes, custom fields, permission differences).

## Evidence style

A live check only counts if it is recorded. The project's convention, observed in CR23 and CR25:

1. **Name the specific record.** "Candidate 169020 (Barry Delaney): 6 notes confirmed in Bullhorn, tool returns empty array" (CR23). "A stress test on Job #51227 (Interim CIO, Pinergy) surfaced four production-impacting bugs. All confirmed via live API testing before implementation" (CR25).
2. **Paste the actual response**, or the exact error body: `400 - {"errorMessage":"Query operation not supported for Candidate, please use /search call instead.","errorMessageKey":"errors.queryIndexedEntity","errorCode":400}` (captured live 2026-07-03).
3. **Record it in the CR or plan** you are writing, in the Problem/Motivation or verification section, so the reviewer and future sessions can distinguish observed fact from guess.

Anti-pattern: "Bullhorn supports X" with no record ID, no response paste, no date. That sentence is what preceded the create_job dead end (CR13: nine live payload attempts, zero successes, all param names guessed).

## Cookbook: ready-to-run read-only snippets

All snippets share this preamble (elided below as `# ...preamble`):

```python
from bullhorn_mcp.config import BullhornConfig
from bullhorn_mcp.auth import BullhornAuth
from bullhorn_mcp.client import BullhornClient
client = BullhornClient(BullhornAuth(BullhornConfig.from_env()))
```

**1. Does field X exist on entity E?** (or use `scripts/meta_dump.py`, below)

```bash
.venv/bin/python -c "
# ...preamble
meta = client.get_meta('Candidate')
hits = [f for f in meta['fields'] if 'title' in f['name'].lower() or 'title' in (f.get('label') or '').lower()]
for f in hits: print(f['name'], '|', f.get('label'), '|', f.get('dataType'))
"
```

Match on name AND label: on this tenant `/meta/ClientContact` has no field named `title` at all; the salutation surfaces as `namePrefix` labeled "Title", and job title is `occupation` labeled "Job Title" (verified live 2026-07-03).

**2. What are the picklist options for a field?**

```bash
.venv/bin/python -c "
# ...preamble
meta = client.get_meta('Note')
f = next(f for f in meta['fields'] if f['name'] == 'action')
print([o['value'] for o in f.get('options', [])])
"
```

**3. Does a `/search/{entity}` route return anything at all?** Use a **match-all probe** and read `total`. Do NOT read `fieldsFromIndex`: it is undocumented and carries no index-health information, since working searches return `false` too (`/search/JobOrder` returns `fieldsFromIndex: false` with `total: 50271`). Treating it as a verdict is what made CR37's investigation start from a false premise.

```bash
.venv/bin/python -c "
# ...preamble
raw = client._request('GET', '/search/Note', {'query': 'id:[0 TO 99999999]', 'fields': 'id', 'count': '1'})
print('total =', raw.get('total'))    # 0 => this route returns nothing, whatever you ask it
"
```

Keep the probe unfiltered — no `isDeleted:0` — since the question is whether the route returns anything at all. On this account (2026-07-28): `/search/Note` gives `total=0`, while `/entity/Note/2650512` returns that note normally. `BullhornClient.note_search_returns_results()` is this probe, cached per process, and `search_notes` uses it to attach a `warnings` key instead of returning a silent empty envelope.

**3b. Is a nested association path searchable?** Test it; never infer it from `/meta`. `hideFromSearch: false` does not predict searchability, so a curated allowlist is the only safe basis. Positive and negative controls both matter — a malformed clause (e.g. a missing colon, `notes.id[0 TO 999]`) matches EVERY record and reads like a successful broad query.

```bash
.venv/bin/python -c "
# ...preamble
for q in ['notes.action:\"BD Call\"', 'notes.action:BD Call', 'notes.notARealSubfield:\"x\"']:
    print(repr(q), client.search_with_meta('ClientContact', q, fields='id', count=1)['total'])
"
```

On this account (2026-07-28): quoted `notes.action:"BD Call"` gives 1979 raw (1974 with the soft-delete clause), the unquoted form gives 0, and a bogus subfield gives 0. Quoting is mandatory for every multi-word value, and a wrong path is indistinguishable from a real empty result.

**4. Does entity E support /search and /query?** Expect asymmetries; probe both:

```bash
.venv/bin/python -c "
# ...preamble
for label, fn in [('search', lambda: client.search('Candidate', 'id:[1 TO *]', fields='id', count=1)),
                  ('query',  lambda: client.query('Candidate', 'id>0', fields='id', count=1))]:
    try: print(label, 'OK', fn())
    except Exception as e: print(label, 'REJECTED', str(e)[:160])
"
```

Verified live 2026-07-03: Candidate rejects `/query` (`errors.queryIndexedEntity`); PlacementChangeRequest rejects `/search` (`errors.searchUnknownEntity`) and needs `/query` with `showTotalMatched=true` to report a total.

**5. Fetch a specific record with explicit fields** (the way to verify response shape and association syntax):

```bash
.venv/bin/python -c "
# ...preamble
print(client.get('JobOrder', 51227, fields='id,title,clientCorporation(id,name)'))
"
```

Live output 2026-07-03: `{'id': 51227, 'title': 'CIO', 'clientCorporation': {'id': 9493, 'name': 'Pinergy'}}`.

## Scripts

Both scripts are read-only, load credentials via `BullhornConfig.from_env()` (they also load the repo-root `.env` explicitly), and were run successfully against the live tenant on 2026-07-03.

### scripts/meta_dump.py: field inventory for one entity

```bash
.venv/bin/python .claude/skills/bullhorn-mcp-live-api-method/scripts/meta_dump.py <Entity> [field-filter]
```

| Invocation | What it answers |
|---|---|
| `... meta_dump.py Candidate` | Full field inventory (274 fields on this tenant as of 2026-07-03) |
| `... meta_dump.py ClientContact title` | "Is there a title field?" Filter is a case-insensitive substring on name OR label |
| `... meta_dump.py Placement custom` | All custom fields with their tenant labels |

Prints `name | label | dataType | REQUIRED maxLength=N` per field, plus picklist options where present. Exit code 1 when a filter matches nothing (the field does not exist under that name), 2 on missing args, 0 otherwise.

### scripts/smoke_read.py: is the tenant reachable and sane?

```bash
.venv/bin/python .claude/skills/bullhorn-mcp-live-api-method/scripts/smoke_read.py
```

Auths (prints the live `rest_url`), then runs one read-only call per core entity and prints totals: `/search` for ClientCorporation, ClientContact, Candidate, JobOrder, JobSubmission, Placement; `/query` for PlacementChangeRequest; `/meta` for Note; plus an informational Note Lucene-index probe. Prints `SMOKE PASS` and exits 0 when all entity checks pass, `SMOKE FAIL` and exits 1 otherwise. Run it before a live-verification session, after auth changes, and when triaging "everything is failing" reports. Full run took well under a minute on 2026-07-03 (totals then: 73,750 Candidates, 50,133 JobOrders, 11,524 Placements, 1,687 PlacementChangeRequests).

Note: the live tenant returns `rest_url` WITH a trailing slash (`.../rest-services/5v598g/`); the no-trailing-slash rule you will see in test fixtures is a test-fixture convention, owned by bullhorn-mcp-testing-playbook.

## Workflow: where verification fits

1. While drafting a CR: verify every behavioral assumption the design rests on; paste evidence into the CR. Do not guess instance-specific field names (the warning CR13 contained and then ignored).
2. Before implementing a task that touches a new entity, endpoint, field, or parameter: run the relevant cookbook probe or `meta_dump.py`.
3. When a live bug is reported: reproduce read-only first, capture the exact error body and record IDs, then write the fix CR around that evidence.
4. After the fix: re-run the same read-only probe to confirm the underlying behavior, then let the normal test suite and review cycle (bullhorn-mcp-review-protocol) take over. Never route around CR review and tagging.
5. If verification would require a write (e.g. "does Bullhorn dedupe JobSubmissions?"): STOP. Ask the user explicitly; describe exactly what would be written. Writes without explicit user request are prohibited even for verification.

## When NOT to use this skill

| You need... | Load instead |
|---|---|
| The quirk facts themselves (field semantics, endpoint hazards, tenant custom fields) | bullhorn-mcp-api-quirks |
| Lucene vs SQL syntax, entity relationships, endpoint support matrix | bullhorn-mcp-query-and-entity-model |
| The review loop, severity taxonomy, fix cycle this discipline complements | bullhorn-mcp-review-protocol |
| Symptom-to-cause triage for a failing tool | bullhorn-mcp-debugging-playbook |
| How to mock these APIs in tests (respx, fixtures) | bullhorn-mcp-testing-playbook |
| Auth internals when the `session` property itself fails | bullhorn-mcp-auth-and-identity |
| CR authoring and tagging mechanics | bullhorn-mcp-change-control |

## Provenance and maintenance

Volatile facts in this file are stamped 2026-07-03 (repo at v0.0.46, 648 tests). Re-verify before trusting:

| Claim | Re-verification command |
|---|---|
| Safe/destructive method lists match CLAUDE.md | `grep -n "Never use destructive" CLAUDE.md` |
| Client method inventory (search/query/get/get_meta etc.) | `grep -n "def " src/bullhorn_mcp/client.py` |
| Inline-Python pattern still matches CLAUDE.md example | `sed -n '/Test directly against the live Bullhorn API/,/read-only/p' CLAUDE.md` |
| Named evidence records (169020, 51227) still cited in CRs | `grep -rn "169020\|51227" CR*.md` |
| /search/Note still returns nothing; the nested `notes.action` canary still returns rows; Candidate still rejects /query; PCR still rejects /search | `.venv/bin/python .claude/skills/bullhorn-mcp-live-api-method/scripts/smoke_read.py` |
| meta_dump.py still runs and Candidate still lacks a title field | `.venv/bin/python .claude/skills/bullhorn-mcp-live-api-method/scripts/meta_dump.py Candidate title` |
| WebFetch doc-domain allowlist | `grep -n "WebFetch" .claude/settings.local.json` |
| Current tag and test count | `git tag --sort=-v:refname \| head -1` and `.venv/bin/pytest -q` |
