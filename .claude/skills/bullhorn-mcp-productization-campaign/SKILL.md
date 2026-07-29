---
name: bullhorn-mcp-productization-campaign
description: >-
  Load this skill when the task is to make the one-tenant Bullhorn MCP server
  product-grade: de-instancing tenant-specific knowledge into config,
  consolidating or trimming the 38-tool surface (the forward-referenced but
  unspecced CR35), or hardening the server against Bullhorn server-side drift.
  Triggers include "productize", "multi-tenant", "de-instance", "reduce tool
  count", "consolidate tools", "CR35", "merge the getters", "make this reusable
  for another Bullhorn customer", "harden against API drift", "token budget is
  too high and we should cut tools". Provides a decision-gated, measurable,
  three-phase campaign where every change routes through the CR then review
  then tag loop, with real inventory numbers, a ranked consolidation menu,
  metadata-gating recipes, numeric exit gates, and fenced-off wrong paths.
---

# Bullhorn MCP Productization Campaign

## What this skill is

This is the executable, decision-gated campaign for the project's hardest
standing problem: this server encodes one Bullhorn tenant's reality (custom
field mappings, picklist values, index configuration) in code, ships a large
38-tool surface, and repeatedly breaks when Bullhorn changes behavior
server-side. The campaign turns "make it product-grade" into three phases with
copy-pasteable inventory commands, classification rubrics, and numeric exit
gates. Nothing here is judged by eye.

Terms defined once:
- **CR (Change Request)**: a `CRx.md` plan file in the repo root that governs a
  unit of work. See bullhorn-mcp-change-control.
- **de-instance**: move a fact that is true only for this one tenant out of
  code and into environment configuration, so the default reproduces this
  tenant exactly while another tenant can override.
- **picklist**: a Bullhorn field whose valid values are a fixed enumerated list
  (for example JobSubmission.status).
- **enrichment**: the startup process (`descriptions.py`) that appends live
  `/meta` field summaries to each tool's description.
- **metadata-gating**: replacing a hardcoded behavioral assumption with a
  runtime `/meta` lookup that falls back safely, following the
  `_entity_has_isdeleted` precedent in `client.py`.
- **/meta**: the Bullhorn field-inventory endpoint `/meta/{entity}`, the
  project's source of truth for field validity and picklists.

**The iron rule of this campaign: every change routes through CR then review
then tag.** Do not hand-merge tools, edit constants, or move config axes
outside a CR. The CRx.md lifecycle, commit/push/tag discipline, and
IMPLEMENTATION-PLAN.md bookkeeping are owned by bullhorn-mcp-change-control; the
adversarial review loop, the 8 known failure patterns, and the 5-cycle safety
valve are owned by bullhorn-mcp-review-protocol. This skill never authorizes
routing around them.

---

## Phase 0: Preflight (run before touching anything)

Every phase begins clean. Run these and confirm the expected values before
opening any CR.

| Check | Command | Expected (as of 2026-07-03) |
|---|---|---|
| Clean main | `git status --porcelain` | empty (ignore untracked `.claude/skills/`) |
| Current tag | `git tag \| sort -V \| tail -1` | `v0.0.46` |
| Full suite green | `.venv/bin/pytest -q` | `648 passed` |
| Tool count | `grep -c "@mcp.tool()" src/bullhorn_mcp/server.py` | `38` |

If the tag or test count differs, this skill is stale: re-derive the baseline
before proceeding and update the date-stamped numbers below. If the suite is
red, STOP; a productization change on a red baseline cannot be gated. If
`fastmcp` import fails on a fresh clone, that is the known undeclared-dependency
OPEN DEBT (see bullhorn-mcp-build-and-env); install it and note it, do not let
it block.

---

## Phase 1: De-instance tenant knowledge into config

**Goal.** Every fact that is true only for this tenant lives in an env var with
a default that reproduces current behavior exactly. Another Bullhorn customer
can deploy by editing `.env` only, never code. This tenant sees zero change.

### Step 1.1: Run the inventory (exact commands)

```bash
grep -rn "customText"        src/
grep -rn "correlatedCustom"  src/
grep -rn "requestCustomDate1" src/
grep -rn "requestType"       src/
grep -rn "Contract Extension" src/
grep -rn "Shortlisted"       src/
grep -rn "customInt"         src/
```

### Step 1.2: Compare against the known baseline (the gate expectation)

As of 2026-07-03 (HEAD `8b5f377`, v0.0.46) the inventory is small and
concentrated. These are the exact hits. **If you see hits in files not listed
here, branch: the surface has grown, extend the inventory before classifying.**

| Grep | Count | Locations | Classification |
|---|---|---|---|
| `customText` | 3 | `metadata.py:34`; `client.py:19`; `descriptions.py:18` | see below |
| `correlatedCustom` | 0 | none | dossier's `correlatedCustomText2` grade mapping is NOT in code, it is a documented quirk only; nothing to move |
| `requestCustomDate1` | 8 | all in `server.py` (`list_placements`, lines ~515, 542, 547, 556, 573, 649, 651, 672) | see below |
| `requestType` | 2 | `server.py:515` (default fields), `server.py:647` (`requestType='Contract Extension'`) | see below |
| `Contract Extension` | 4 | `server.py` 546/555/588 (docstring), 647 (code literal) | see below |
| `Shortlisted` | 5 | `shortlist_config.py:5` (default const); `server.py` docstrings 985/1001/2875/2948 | already env-backed via `BULLHORN_SHORTLIST_STATUS`; keep |
| `customInt` | 1 | `descriptions.py:19` (regex comment) | universal, keep |

### Step 1.3: Classify every hit (the rubric)

Sort each hit into exactly one bucket:

| Bucket | Test | Action |
|---|---|---|
| **Move-to-env-config** | The value would be different on another tenant AND changing it changes behavior. | Add or extend an env axis; default reproduces current value. |
| **Universal-keep** | True for every Bullhorn tenant (a regex for custom-field naming; a Bullhorn-defined enum literal). | Leave in code. |
| **Docstring-only** | Appears only in a docstring as an example. | Leave, unless misleading; docstring edits still route through review (see bullhorn-mcp-docs-and-writing). |

Applying the rubric to the current baseline:

- `metadata.py:34` `"publish on website": "customText12"` in `FIELD_ALIASES["JobOrder"]`: **move-to-env-config.** A config axis already exists (`BULLHORN_JOBORDER_ALIASES` merges into this dict, env wins on conflict). The cleanest move is to relocate this one hardcoded alias into the shipped `.env.example` `BULLHORN_JOBORDER_ALIASES` so the code default is tenant-neutral. Note the two `publicDescription` aliases on the same lines are UNIVERSAL Bullhorn field names, keep them.
- `client.py:19` Placement `DEFAULT_FIELDS` includes `customText41` ("Candidate Source - This Placement" on this tenant): **move-to-env-config, and there is NO existing axis.** This is the one genuinely undefended tenant field in `DEFAULT_FIELDS`. Adding a config axis for it is a coherent CR (see Step 1.5). Until then it is a latent risk: a tenant without `customText41` gets a 400 on Placement `get`/search when defaults apply.
- `descriptions.py:18-19` custom-field regex comment: **universal-keep.**
- `server.py` `requestType='Contract Extension'` and `requestCustomDate1`: **move-to-env-config candidate, but gated.** The extension data model itself is not tenant-specific in shape, but the `requestType` literal and the `requestCustomDate1` field name are this tenant's contract-extension encoding. If de-instancing, add env axes (for example `BULLHORN_EXTENSION_REQUEST_TYPE`, `BULLHORN_EXTENSION_DATE_FIELD`) with the current literals as defaults. Do NOT change the placement-vs-extension logic while doing so (see fences).
- `shortlist_config.py` / `Shortlisted`: **already done.** `BULLHORN_SHORTLIST_STATUS` exists. No work.

The template to copy for any new axis is `joborder_config.py`: a module with
`_load_json_env()` (warn-and-continue on bad JSON so the server always starts),
one getter per axis (aliases / required / defaults), env value merged into the
code dict with env winning on conflict, alias targets NOT validated at load
(misconfig surfaces as a Bullhorn error at write time, by design). The env var
table and per-tenant config philosophy are owned by bullhorn-mcp-config-and-flags;
consult it before adding an axis so you match the naming and read-time
conventions.

### Step 1.4: Verify the quirk before you move it

Before moving any custom-field mapping, confirm the field name and its meaning
on the live tenant read-only (`/meta`, `search`, `get`). Never guess a Bullhorn
instance field name: that is exactly the CR13 `create_job` dead end (see
fences). The read-only live verification discipline and runnable scripts are
owned by bullhorn-mcp-live-api-method; the authoritative quirk truth is owned by
bullhorn-mcp-api-quirks. Use them; do not re-derive quirks here.

### Step 1.5: One CR per coherent batch

Group by config module, not by file. Reasonable batches:
- CR-A: JobOrder alias de-instance (move `publish on website` to `.env.example`).
- CR-B: Placement `customText41` config axis (new `BULLHORN_PLACEMENT_*` module modeled on `joborder_config.py`).
- CR-C: extension requestType/date-field axes (only if the owner wants full de-instance; higher risk, touches `list_placements`).

Each CR maps to a PRD requirement; if none exists, amend the PRD first (this is
the change-control rule, not optional).

### Step 1.6: Phase 1 exit gate (all must hold)

- [ ] `.venv/bin/pytest -q` still green, test count monotonically non-decreasing (>= 648).
- [ ] `.env.example` updated with every new axis, commented with the current tenant's value.
- [ ] **Defaults reproduce current behavior EXACTLY.** With no env overrides set, a diff of tool outputs against the pre-CR baseline is empty. This is the gate: this tenant must see zero change.
- [ ] A new payload-assertion or resolution test proves the env override path works (env value wins over the code default). Tests migrate, never get deleted.
- [ ] Clean review cycle, then tag (owned by change-control / review-protocol).

---

## Phase 2: Consolidate the 38-tool surface (CR35)

CR35 is forward-referenced in MEMORY.md and the dossier but **has no spec file
as of 2026-07-03** (verified: no `CR35*.md` in repo root). Writing that spec is
Phase 2's first deliverable. Consolidation is worth doing because tool
descriptions cost context tokens in every conversation with the connector
enabled (the CR34 lesson: the surface was ~111k tokens before the ~80%
enrichment trim). Fewer, well-chosen tools cut that further, but only if no
capability is lost.

### Step 2.0: Measure first, always

Do not consolidate on intuition about token cost. Run the token-cost
measurement script (owned by bullhorn-mcp-run-and-operate) to get the current
per-tool and total description size. Record it as the CR35 baseline. Every merge
in this phase is judged against a measured before/after, never by eye.

### Step 2.1: The ranked consolidation menu

Derived from the real 38-tool inventory and `TOOL_ENTITY_MAP` in
`descriptions.py`. Ranked best-first by (token saving) minus (capability-loss
risk). Token-saving estimate method: for each merge, `saving ≈ (removed tool
count) × (per-tool description size from Step 2.0)`, minus the size of any
enrichment the merged tool must now carry.

| # | Merge candidate | Tools | Token saving | Capability-loss risk | Verdict |
|---|---|---|---|---|---|
| 1 | **Unify by-ID getters** into `get_record(entity, id, fields)` | `get_job`, `get_candidate`, `get_company`, `get_contact` | High (4 near-identical thin wrappers over `client.get()` collapse to 1) | Low: bodies are identical except the entity string | Strong candidate. Obligations below. |
| 2 | **Fold `update_job` into `update_record`** | `update_job` | Medium | Low-Medium: `update_job` is a JobOrder-typed convenience over `update_record`; check it adds no guard `update_record` lacks | Candidate; verify no unique guard first. |
| 3 | **Merge `shortlist_candidate` into `shortlist_candidates`** | `shortlist_candidate` (singular) | Medium | Low: singular is `shortlist_candidates([id])` | Candidate; keep the batch dedup guard. |
| 4 | **Merge `parse_cv` + `parse_cv_text`** into one with a mode | `parse_cv_text` | Medium | Low-Medium: file vs raw-text input paths differ | Candidate; both multipart/timeout behaviors must survive. |
| 5 | **Unify duplicate-finders** into `find_duplicates(entity, ...)` | `find_duplicate_companies`, `find_duplicate_contacts`, `find_duplicate_candidates` | Medium-High | **Medium-High**: each uses a different fuzzy scorer (`score_company_match` vs `score_contact_match`) and different match fields | Only if the merged tool dispatches to the correct scorer per entity; do not flatten scoring. |
| 6 | **Fold curated `list_*` into `search_entities`** | `list_jobs`, `list_candidates`, `list_contacts`, `list_companies` | High | **High**: each carries a curated default sort (`-dateAdded`) and default field set that teach the LLM the right shape | Weak candidate; the curated docstrings are a teaching surface. If merged, the curation must move into enrichment, or capability degrades. |
| 7 | Merge notes tools | `get_notes_for_entity`, `search_notes` | Medium | **HIGH** | **DO NOT.** They use different endpoints (association GET vs Lucene `/search/Note`); collapsing them risks resurrecting NoteEntity (CR23 fence). |
| 8 | Merge `list_placements` into anything | `list_placements` | n/a | **HIGH** | **DO NOT.** Placement-vs-extension model (CR33 fence). |
| 9 | Collapse tearsheet CRUD | 5 tearsheet tools | Low | Medium | Weak; distinct verbs (list/get/create/add/remove), low token payoff. |

**`list_placements` and the notes tools are STOP-listed, not ranked.** They are
here so a future session does not "discover" them as easy wins.

### Step 2.2: Per-merge obligations checklist

For every merge you ship, ALL of these, or do not ship it:

- [ ] **Capability transfer in docstrings.** Removing a capability from a
  docstring disables it for the LLM (the CR31 lesson: a docstring that omits an
  entity effectively disables that entity). Every field example, every
  entity-specific pointer (for example each getter's "use get_notes_for_entity"
  note) migrates into the merged tool's docstring or its enrichment section.
- [ ] **`TOOL_ENTITY_MAP` updated.** Removed tool names deleted; the merged tool
  added with the union of entities. If the merged tool spans many entities
  (like the unified getter), add it to `GENERIC_DISCOVERY_TOOLS` so it gets the
  compact name-only enrichment plus a pointer to `get_entity_fields`, not a
  bloated full section per entity. CR34 and CR35 both edit `TOOL_ENTITY_MAP`:
  sequence CR35 after CR34 is tagged (it is: v0.0.46 shipped CR34).
- [ ] **Enrichment still runs.** After the edit, confirm
  `enrich_tool_descriptions` produces a section for the merged tool. Enrichment
  is strictly additive and optional; do not let a merge break the startup path.
- [ ] **Payload-assertion tests migrate, never delete.** The removed tools' tests
  move to the merged tool and still assert the raw request payload / exact
  `create`/`get` call. This is the Sprint 9 payload-assertion law (owned by
  bullhorn-mcp-testing-playbook). Deleting a write-path test is a review CRITICAL.
- [ ] **Pagination envelope preserved.** Any user-facing list/search behavior in
  the merged tool still returns `{"data": [...], "pagination": {...}}` via
  `_paginate_envelope`, and any notes-style raw-offset `next_start` arithmetic is
  preserved verbatim (getting it wrong caused an infinite-loop C1).
- [ ] **Guards preserved.** Dedup guards, the company-reassignment guard, the
  `_strip_contact_title` / name-recompute logic, and the note-action validation
  all survive the merge unchanged. Never remove a review-pattern guard during a
  refactor (see fences).

### Step 2.3: The capability scenario list (the named regression suite)

Before merging, write down the concrete capabilities that must still be
expressible after Phase 2. These are the STOP-rule oracle. Minimum list:

1. Fetch one JobOrder, one Candidate, one ClientCorporation, one ClientContact
   by ID with custom `fields`.
2. Update a single arbitrary field on a Candidate and on a JobOrder.
3. Shortlist one candidate and shortlist a batch, each with dedup.
4. Parse a CV from an uploaded file and from raw text.
5. Find likely-duplicate companies, contacts, and candidates, each with the
   correct scorer.
6. List recent jobs / candidates / contacts / companies newest-first.
7. Fetch notes for a record (association) and full-text search notes (Lucene).
8. List placements (new) and extensions separately, never merged.

**STOP rule.** If a merged tool cannot express any capability on this list, do
not ship the merge; split it back. Example: if `get_record` cannot carry the
per-entity notes pointer, either add it to the docstring or keep the getters.

### Step 2.4: Phase 2 exit gate (numeric)

- [ ] Measured total description tokens strictly below the Step 2.0 baseline; record the target and the achieved number in the CR.
- [ ] Test count monotonically non-decreasing (>= the count at Phase 2 start; migrated tests keep their assertions).
- [ ] Every capability on the Step 2.3 scenario list demonstrably still passes.
- [ ] Tool count decreased by exactly the number of tools the CR says it removes (verify with `grep -c "@mcp.tool()"`).
- [ ] Clean review cycle, then tag.

---

## Phase 3: Harden against Bullhorn server-side drift

**Goal.** Replace remaining hardcoded behavioral assumptions with runtime
`/meta` lookups that fail safe, so a Bullhorn-side change (a dropped field, an
unindexed sort field) degrades instead of 400/500ing every call. Bullhorn's API
surface demonstrably drifts: it started rejecting `clientCorporation` on the
notes association endpoint (CR25 fix 3) after it had worked.

### The pattern template: `_entity_has_isdeleted` (client.py)

Copy this shape for every gate:

1. **Denylist fast path.** A static frozenset of known-answers checked first
   (`_ENTITIES_WITHOUT_ISDELETED`), so the common case needs no network call.
2. **Cache.** A per-process dict memo (`_isdeleted_cache`) so `/meta` is fetched
   at most once per entity.
3. **`/meta` scan.** On cache miss, fetch `/meta/{entity}` and scan `fields` for
   the answer.
4. **Fail-safe fallback.** On `/meta` error, return the value that fails safe,
   and do NOT cache it so a later call can re-detect. For isDeleted, safe = keep
   appending the soft-delete clause. Choose the safe direction per gate.

### Verified Phase 3 candidates (each is real in code)

| Assumption | Location | Fail-safe direction | Gating recipe |
|---|---|---|---|
| Note default field lists exclude `clientCorporation` | `server.py:1650` `_NOTE_DEFAULT_FIELDS`, `:1663` `_NOTE_SEARCH_DEFAULT_FIELDS` (byte-identical; keep-in-sync comment) | Prefer FEWER fields (dropping a rejected field never 500s; requesting an invalid one does) | Gate the association field list against `/meta/Note`: include an optional field only if `/meta` confirms it; on `/meta` error, use the current minimal set. Would have absorbed CR25 fix 3 automatically. |
| Email sort field is `smtpReceiveDate` | `server.py:1252` `sort="-smtpReceiveDate"` | Prefer the field known indexed on this tenant | Gate: only sort by a field `/meta` says exists; on error keep `smtpReceiveDate`. Note the unindexed-date-range issue is a separate accepted limitation, not a gate. |
| Placement defaults include `customText41` | `client.py:19` | Prefer omitting a custom field the tenant lacks | Gate the custom field into defaults only if `/meta/Placement` confirms it; else omit. Overlaps Phase 1 CR-B; do whichever CR reaches it first, not both. |
| `entityId` mandatory on `/search/UserMessage` | `search_emails` | n/a | **DO NOT gate away.** Universal Bullhorn requirement; removing it caused a 12-day production outage (see fences). |

`_NOTE_ENTITY_SUBJECT_FIELD` (server.py:1640) is defined but unreferenced by any
tool body, and the two note field constants are byte-identical duplicates that
diverged once (CR22). These are OPEN DEBT, not gating targets: a Phase 3 CR may
collapse the duplicates (reference one from the other) and delete or wire up the
dead constant, but treat that as a scoped cleanup with its own tests, not as
part of a gate.

### Step 3.x: Phase 3 exit gate

- [ ] For each gated assumption, a test proves BOTH branches: `/meta` says
  present (use it) and `/meta` errors (fall back safe). The CR33 `/meta` test
  gotcha applies: a respx test without a registered `/meta` route silently
  exercises only the fallback branch (owned by bullhorn-mcp-testing-playbook).
- [ ] Test count monotonically non-decreasing.
- [ ] No behavior change for this tenant when `/meta` returns the expected shape.
- [ ] Clean review cycle, then tag.

---

## Fenced-off wrong paths (with their history)

Each of these has bitten this project. Do not re-walk them during any phase.

| Fence | Why | Evidence |
|---|---|---|
| **Never guess an instance-specific Bullhorn field name.** Verify on live `/meta` first. | Invented param names made a whole tool uncallable under any input. | CR13/CR14 `create_job` dead end (nine live payload attempts, zero successes). |
| **Never merge placements with extensions.** | An extension is a `PlacementChangeRequest` with `requestType='Contract Extension'`; `Placement.dateBegin` never moves. `list_placements` returns two separate envelopes. | CR33 data model. |
| **Never resurrect NoteEntity queries.** Notes are read via `GET /entity/{E}/{id}/notes`. | `targetEntityName` is unreliable ('User' for Candidate rows); there is no `/query/Note`. | CR21 through CR23 (feature rewritten twice in one day). |
| **Never write `.env` (or any config file) at runtime.** | Hosted deploys run on read-only filesystems. | CR15 rejected option. |
| **Never bypass or remove dedup guards** during a refactor. | Bullhorn partially persists on error and LLMs retry, creating silent duplicates. | CR5 (real dup IDs 170841-170843). |
| **Never remove a review-pattern guard while consolidating.** | The 8 known failure patterns are auto-CRITICAL on recurrence; the company-reassignment guard must fire after label resolution. | Review protocol; pattern 6 recurred at CR19. |
| **Never remove a mandatory Bullhorn parameter on a "cleaner API" argument.** | Dropping `entityId` from `search_emails` caused a 12-day production outage. | db78771 removed it, c5cdfaa restored it. |

---

## Promotion protocol and success criteria

Each phase is a sequence of CRs, and each CR exits ONLY via a clean review cycle
followed by a tag. There is no "productization branch that skips review." The
CR then review then tag machinery is owned by bullhorn-mcp-change-control and
bullhorn-mcp-review-protocol; this campaign supplies the phase content, not a
shortcut around them. If the review loop hits its 5-cycle safety valve, STOP and
alert the owner; do not force a phase through.

Success stated as numbers:

- **Phase 1 done** when: 0 move-to-env-config hits remain unmoved (re-run the
  Step 1.1 greps; every remaining hit is classified universal-keep or
  docstring-only), `.env.example` documents every axis, and default-only output
  is byte-identical to the pre-Phase-1 baseline.
- **Phase 2 done** when: measured description tokens are below the Step 2.0
  baseline by the CR's stated target, tool count dropped by the stated amount,
  every Step 2.3 capability still passes, and test count did not decrease.
- **Phase 3 done** when: every assumption in the Phase 3 table is either gated
  (with both-branch tests) or explicitly documented as do-not-gate, and no
  tenant-visible behavior changed on the happy path.

Overall: another Bullhorn customer can stand the server up by editing `.env`
only; the tool surface is smaller and its token cost is measured, not guessed;
and a Bullhorn server-side field or index change degrades gracefully instead of
erroring every call.

---

## When NOT to use this skill

- For the mechanics of writing a CR, committing, pushing, tagging, or updating
  IMPLEMENTATION-PLAN.md: use **bullhorn-mcp-change-control**.
- For running the adversarial review, severity classification, or the 8 failure
  patterns: use **bullhorn-mcp-review-protocol**.
- For the actual token-cost measurement script and how to run the server: use
  **bullhorn-mcp-run-and-operate**.
- For the authoritative Bullhorn quirk truth (what a field means, which endpoint
  an entity supports): use **bullhorn-mcp-api-quirks** and
  **bullhorn-mcp-query-and-entity-model**.
- For read-only live verification before you move or gate anything: use
  **bullhorn-mcp-live-api-method**.
- For the full env-var table, read-time semantics, and how to add a config axis:
  use **bullhorn-mcp-config-and-flags**.
- For the payload-assertion law, the `/meta` respx test gotcha, and fixture
  traps: use **bullhorn-mcp-testing-playbook**.
- For docstring token-budget rules and post-tag doc-sync: use
  **bullhorn-mcp-docs-and-writing**.
- To look up whether a bug has happened before: use
  **bullhorn-mcp-failure-archaeology**.

---

## Provenance and maintenance

Re-verify each drift-prone claim with the command shown.

| Claim category | Re-verification command |
|---|---|
| Baseline tag | `git tag \| sort -V \| tail -1` (expect v0.0.46) |
| Test count | `.venv/bin/pytest --co -q \| tail -1` (expect 648) |
| Tool count | `grep -c "@mcp.tool()" src/bullhorn_mcp/server.py` (expect 38) |
| Phase 1 inventory | the seven greps in Step 1.1; compare against the Step 1.2 table |
| CR35 still unspecced | `ls CR35*.md 2>/dev/null \|\| echo "no CR35 spec yet"` |
| Placement `customText41` still hardcoded | `grep -n customText41 src/bullhorn_mcp/client.py` |
| JobOrder `customText12` alias location | `grep -n "publish on website" src/bullhorn_mcp/metadata.py` |
| Extension literals | `grep -n "Contract Extension\|requestCustomDate1" src/bullhorn_mcp/server.py` |
| Note duplicate constants | `grep -n "_NOTE_DEFAULT_FIELDS\|_NOTE_SEARCH_DEFAULT_FIELDS\|_NOTE_ENTITY_SUBJECT_FIELD" src/bullhorn_mcp/server.py` |
| Email sort field | `grep -n "smtpReceiveDate" src/bullhorn_mcp/server.py` |
| isDeleted gate template | `grep -n "_entity_has_isdeleted\|_isdeleted_cache\|_ENTITIES_WITHOUT_ISDELETED" src/bullhorn_mcp/client.py` |
| `TOOL_ENTITY_MAP` / `GENERIC_DISCOVERY_TOOLS` | `grep -n "TOOL_ENTITY_MAP\|GENERIC_DISCOVERY_TOOLS" src/bullhorn_mcp/descriptions.py` |
| Config-axis template | read `src/bullhorn_mcp/joborder_config.py` (the pattern to copy) |
