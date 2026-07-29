---
name: bullhorn-mcp-docs-and-writing
description: Load this skill whenever you write or edit ANY documentation in bullhorn-mcp-python. Triggers include editing a tool docstring in src/bullhorn_mcp/server.py, adding or changing an example payload in a docstring, wondering whether a doc change needs review or tests (it does), touching README.md, PRD.md, IMPLEMENTATION-PLAN.md, a CRx.md, or reviews/latest.md, deciding which document a fact belongs in, worrying about tool-description token cost, finishing a tag and needing the post-tag doc-sync checklist, or noticing stale docs (wrong tool counts, DRAFT statuses, Planned annotations). Provides the docstrings-are-the-interface doctrine with its evidence, the token budget rules, the docs-of-record map, house writing style, the current drift catalog as OPEN DEBT, and the post-tag doc-sync checklist.
---

# Documentation as Load-Bearing Infrastructure

Documentation in this repo is not commentary; it is executable interface. Tool docstrings are the only thing the LLM sees, so a wrong docstring ships bugs to every agent and a missing docstring line disables a working capability. Treat every doc edit with the same rigor as a code edit.

Jargon used below, defined once:

- **MCP**: Model Context Protocol, the standard this server implements; each `@mcp.tool()` function in `src/bullhorn_mcp/server.py` is exposed to LLM agents.
- **CR**: Change Request, a numbered spec file (`CR1.md` ... `CR34.md`) in the repo root; every unit of work has one.
- **Enrichment**: the startup step in `src/bullhorn_mcp/descriptions.py` that appends live Bullhorn field lists to tool descriptions before the server starts serving.
- **Picklist**: a Bullhorn field with a fixed set of allowed values (for example `status`), returned by the `/meta` endpoint as `options`.
- **Lucene**: the query syntax used by Bullhorn `/search` endpoints; docstring examples often contain Lucene snippets.
- **Tag**: a git version tag (`v0.0.N`) applied when a review cycle passes; the real versioning of this project.

Volatile baseline for this file: as of 2026-07-03 the repo is at tag v0.0.46 (CR34, Sprint 35), 648 tests passing, 38 MCP tools.

## 1. Doctrine: docstrings ARE the interface

The LLM calling this server never reads the code. It reads tool descriptions (docstring plus enrichment). Three proven consequences:

| Principle | Evidence (verified in repo) |
|---|---|
| A wrong docstring example ships a bug to every agent | CR4: the `update_record` docstring example used `{"title": "CTO"}`; on ClientContact `title` is a salutation (Mr/Ms/Dr), so every agent copying the example got a 400. The fix was docs-only. |
| Regression tests guard docstrings like code | `tests/test_server.py`, class docstring "CR4: Regression guards for incorrect field names in tool docstrings" (near line 2987 as of 2026-07-03): asserts `'"title": "CTO"'` is absent from the `update_record` docstring, `'"occupation": "CTO"'` is present, and `list_contacts` does not suggest `title:Manager`. |
| A docstring that omits a capability disables it | CR31 (see `CR31.md`): `update_record` already fully supported Candidate in code, but the docstring listed only ClientContact and ClientCorporation, so no agent ever tried. The entire CR was a docstring edit plus tests: a zero-code-change capability unlock. |
| Docstring errors are review-CRITICAL | `.claude/commands/review.md` line 20 (as of 2026-07-03): any docstring, test, or comment that uses `title` to mean job title is CRITICAL severity. |

### WHERE you put text decides whether the agent ever sees it (verified live 2026-07-28, CR37)

FastMCP does NOT ship the whole docstring. It parses the Google-style docstring and splits it:

| Docstring region | Where it goes | Does the agent see it? |
|---|---|---|
| Everything BEFORE `Args:` | `tool.description` | YES |
| Each `Args:` entry | that parameter's `description` in the JSON schema | YES |
| `Returns:`, `Examples:`, and any other section at or after `Args:` | nowhere | **NO — silently dropped** |

Verify for any tool:

```bash
.venv/bin/python -c "
import asyncio
from bullhorn_mcp import server
async def go():
    t = {x.name: x for x in await server.mcp.list_tools()}['list_contacts']
    print(len(t.description or ''), repr((t.description or '')[:120]))
asyncio.run(go())"
```

Consequences you must design around:

1. **Put load-bearing guidance before `Args:`.** CR37 first added its nested-note-search guidance after `Examples:`; the rendered description was 50 characters and none of it reached the agent. Caught only by measuring the rendered description.
2. **Per-parameter guidance belongs in `Args:`**, where it becomes the schema description — the most discoverable place for anything tied to one parameter.
3. **Docstring tests must assert on the rendered description, not `__doc__`.** A test reading `tool.__doc__` passes for text the agent never receives. `TestNoteActionFilter::test_note_guidance_reaches_the_rendered_tool_description` (tests/test_server.py) is the pattern: read `mcp.list_tools()` and assert against `description` and `parameters`. Runbook step 3 below predates this finding and still says `tool.__doc__`; prefer the rendered form.
4. **OPEN DEBT:** every `Returns:` and `Examples:` section across all 38 tools is currently dropped, so the examples the docstrings carefully curate are invisible to agents. Not investigated further, not in CR37's scope. Worth a CR: either promote the load-bearing examples above `Args:` or stop paying to maintain them. Do not assume any existing `Examples:` block is reaching an agent today.

### Docstring editing runbook

1. Treat the edit as a code change: it needs a CR (or belongs to the current CR), review, and tests. Never hotfix a docstring outside change control (see bullhorn-mcp-change-control).
2. Verify every field name in every example against the live `/meta` endpoint before writing it (see bullhorn-mcp-live-api-method). CR4 and CR18 both started as invented-example bugs.
3. If the docstring gates entity coverage (lists which entities a tool accepts), check the code path actually supports what you add, and add a docstring-content regression test in the CR4 style: assert the bad string is absent and the good string is present, via `tool.__doc__`.
4. If you fix a wrong example, ALSO add the negative assertion so it cannot come back.
5. Remember the enrichment appends a `## Field reference (auto-populated at startup)` section at runtime; do not hand-duplicate field lists that enrichment already provides. Static docstrings must stand alone when enrichment fails (Bullhorn down at startup), so keep the 2 to 4 most load-bearing examples static.

## 2. Token budgets: every character loads into every conversation

Tool descriptions are sent to the model in every conversation where the connector is enabled, including conversations that never touch Bullhorn. History (verified against `CR18.md`, `CR34.md`, and commit 88cc709):

- CR18 (2026-05) introduced enrichment because static docstrings gave the LLM no field inventory (a live session repeatedly sent `title` on Candidate, which has no `title` field at all). CR18 itself flagged "monitor token cost" as a risk.
- That risk materialized. CR34 measured, on the live tenant: ~111k tokens of tool descriptions plus ~7k of parameter schemas, ~118k total per conversation. The 4 generic tools alone carried ~51.6k (each duplicated the full field list of all 10 entities, ~12.8k to 13.0k tokens each). Candidate's 274-field block (~3.0k tokens) repeated across 7 tools.
- CR34 (tag v0.0.46, commit 88cc709, "trim startup tool-description enrichment, ~80% token reduction") fixed it with a full-vs-compact split.

### The rules going forward (constants verified in `src/bullhorn_mcp/descriptions.py` as of 2026-07-03)

| Rule | Mechanism |
|---|---|
| Entity-specific tools get FULL sections, but curated | `select_fields()`: DEFAULT_FIELDS first, then required fields, then `PICKLIST_FIELDS_TO_EXPAND` ({status, employmentType, category, type, source}), then custom fields with a human label; capped at `MAX_FIELDS_PER_ENTITY = 40` (line 16). Full sections carry `[required]` markers and inlined picklist values. |
| Generic tools get COMPACT sections | `GENERIC_DISCOVERY_TOOLS = {search_entities, query_entities, update_record, get_entity_fields}` (line 51) receive only the DEFAULT_FIELDS subset per entity (name, type, label; no picklist expansion, no required marker), plus a trailing pointer: For the full field list of any entity, call get_entity_fields(entity="<Entity>"). |
| Guidance survives enrichment failure | The same get_entity_fields pointer is baked into the STATIC docstrings of the 4 generic tools (grep `server.py` for it: 3 hits in docstrings plus the tool itself). If you add a generic tool, add the static pointer too. |
| Never uncap or de-curate without a budget measurement | Any change that grows descriptions needs a before/after token measurement; the measurement procedure is owned by bullhorn-mcp-run-and-operate. |

When writing any new tool docstring, budget it: a docstring is paid for on every conversation forever. Prefer one precise example over three redundant ones. Enumerate values only for fields the enrichment does not cover.

## 3. Docs of record: which document owns which truth

One home per fact. Before writing anything, pick the right file from this map (all verified present as of 2026-07-03):

| File | Owns | Rules |
|---|---|---|
| `PRD.md` | Product truth: 21 FRs, 46 user stories, 8 NFRs, non-goals | Every CR must trace to a PRD requirement; if a CR is out of scope, amend the PRD FIRST (precedent: NFR-8 was added to back CR34 before it shipped). |
| `CRx.md` (repo root) | The spec for one change: Status, Motivation, Goals/Non-goals, per-file Changes, Tests | Written before implementation; Status flipped to COMPLETE after the tag. Lifecycle mechanics: see bullhorn-mcp-change-control. |
| `IMPLEMENTATION-PLAN.md` | Execution log: dated replan entries, Current Status table (sprint, test count, tag), per-sprint tasks, review cycle findings, pattern learnings | The only place for status and progress notes. Findings and learnings are appended here, never to AGENTS.md. |
| `README.md` | User-facing: what the server does, tool list, setup, env vars, client configs | Serves two audiences (automation builders and consultants' admins). Currently badly stale, see section 5. |
| `reviews/latest.md` | The CURRENT review verdict only | A rolling file, overwritten every review cycle; history lives in git and in the plan's "Review cycle findings" sections. Never append; never archive copies in the working tree. Verdict format: see bullhorn-mcp-review-protocol. |
| `AGENTS.md` | Nothing of its own: it is a symlink to `CLAUDE.md` (verify: `ls -la AGENTS.md` shows `AGENTS.md -> CLAUDE.md`) | Operational content ONLY (how to run, test, and call the live API). `PROMPT_build.md` states the rule and the why: status updates and progress notes belong in IMPLEMENTATION-PLAN.md; a bloated AGENTS.md pollutes every future loop's context. Update it when you learn a better command; keep it brief. |

If a fact fits two files, the spec goes in the CR, the outcome goes in the plan, and the user-visible consequence goes in the README. Never duplicate the text; cross-reference.

## 4. House style (observed, enforced by the build prompts)

- **Capture the why.** `PROMPT_build.md`: "When authoring documentation, capture the why." Record rejected alternatives and the reason (model examples: CR7 records why the global title alias was rejected; CR18 records three rejected designs).
- **Single source of truth.** No parallel copies of the same table or constant in two docs. In code the same rule bit once: CR33 M1, a duplicated field string, fixed by referencing the constant.
- **Absolute dates.** Date every entry `YYYY-MM-DD` (observed style: "Replan validation (2026-06-23, post-CR33)" in the plan; "Date: 2026-06-23" in reviews/latest.md). Never "today", "last week", or "recently".
- **Date-stamp volatile numbers.** Test counts, tool counts, tags, and token figures drift within weeks; anchor them ("648 tests, v0.0.46, as of 2026-07-03").
- **Never commit client-confidential material.** Standing scar: `CASE_STUDY.md` (a client case study) was committed at cdca5f8, reverted at c570499, and is now in `.gitignore` under "Local files (not for repo)". The content lives in git history PERMANENTLY. Before committing any doc, ask: does this name a client, a real record ID, or a commercial detail that must not leave the org? If yes, gitignore it; a revert does not un-publish.

## 5. Current drift catalog (OPEN DEBT, each item verified 2026-07-03)

Doc drift is a known recurring failure pattern in this repo. None of the following is accepted design; each is unfixed backlog. Suggested remedy: a small doc-sync chore CR (CR35 is already reserved for tool consolidation, so propose CR36 or fold these into the next CR's post-tag checklist).

| # | OPEN DEBT item | Verified evidence | Workaround until fixed |
|---|---|---|---|
| 1 | README.md lists only 18 tools (9 read, 7 write, 2 dedup) vs 38 actual | Count bullets under "## MCP Tools" in README.md; `grep -c "@mcp.tool" src/bullhorn_mcp/server.py` returns 38 | Treat `server.py` as the tool inventory of record, never the README |
| 2 | README.md "Supported write targets" lists 4 entities (ClientCorporation, ClientContact, JobOrder, Note); Candidate, JobSubmission, and Tearsheet writes shipped since | README.md "Supported write targets" section; tools `create_candidate`, `shortlist_candidate`, `create_tearsheet` exist in server.py | Same as above |
| 3 | CR34.md Status still says "DRAFT (awaiting approval)" though CR34 shipped and tagged | `head -5 CR34.md`; commit 88cc709 and tag v0.0.46 exist; contrast CR33.md which says COMPLETE | Read the plan's Current Status table, not CR Status lines, for shipped-or-not |
| 4 | IMPLEMENTATION-PLAN.md header baseline says "630 tests passing, tagged v0.0.45" while the same paragraph says Sprint 35 is COMPLETE; actual is 648 tests, v0.0.46 | `head -6 IMPLEMENTATION-PLAN.md`; `.venv/bin/pytest -q` (648 passed); `git tag \| sort -V \| tail -1` | Trust pytest and git tags over the plan header |
| 5 | PRD.md FR-18 still marks `get_job_submissions` as "Planned (CR30)" though CR30 shipped (tool exists in server.py) | `grep -n "Planned (CR30)" PRD.md`; note precedent commit 9a8beb1 already fixed one such annotation for CR29, so the practice exists but missed this one | Grep server.py for the tool before believing any Planned annotation |
| 6 | Session auto-memory (MEMORY.md) carries stale claims ("Sprint 26 untagged", "CR28 untagged") | `git tag` shows 46 contiguous tags v0.0.1 through v0.0.46 | Git is authoritative; correct memory whenever you touch it |

## 6. Post-tag doc-sync checklist (run after every `git push --tags`)

The repo already has the habit (commits named "chore: post-review doc updates for CRnn"; 9a8beb1 even fixed a PRD Planned annotation). This checklist makes it complete so section 5 stops growing. After tagging (tag mechanics: bullhorn-mcp-change-control):

- [ ] `IMPLEMENTATION-PLAN.md`: update the header baseline (test count, tag, sprint status) AND the Current Status table row. Both; item 4 above happened because only one was updated.
- [ ] The shipped `CRx.md`: flip `## Status:` from DRAFT to COMPLETE.
- [ ] `README.md`: if the CR added, removed, or renamed tools, entities, or env vars, update the tool list, Supported Entity Scope, and env var tables.
- [ ] `PRD.md`: flip any "Planned (CRn)" annotation for the shipped CR to "Implemented (CRn)"; confirm the CR's FR/NFR text matches what actually shipped.
- [ ] Session auto-memory (MEMORY.md): add the sprint row (tag, test count) and any new key pattern; correct anything git now contradicts.
- [ ] `reviews/latest.md`: no action; the review loop overwrites it (bullhorn-mcp-review-protocol).
- [ ] Docstrings touched by the CR: confirm regression tests exist for any corrected example (section 1, step 3).
- [ ] Re-run the drift greps in "Provenance and maintenance" below; anything still stale goes into the next CR as a doc-sync task.

## When NOT to use this skill

| Adjacent topic | Owner skill |
|---|---|
| CR lifecycle, sprint planning, commit/push/tag discipline, plan section anatomy | bullhorn-mcp-change-control |
| Review verdicts, C/M/m severity, the fix loop, reviews/latest.md workflow mechanics | bullhorn-mcp-review-protocol |
| Enrichment startup behavior, failure modes, and token-cost measurement operations | bullhorn-mcp-run-and-operate |
| The enrichment-is-additive architecture invariant and module map | bullhorn-mcp-architecture-contract |
| Verifying field names live before putting them in a docstring | bullhorn-mcp-live-api-method |
| Env var and constant reference (what BULLHORN_* does) | bullhorn-mcp-config-and-flags |
| Why a specific past docstring bug happened (full incident detail) | bullhorn-mcp-failure-archaeology |

## Provenance and maintenance

Re-verify each claim category before relying on it; all numbers above were true on 2026-07-03.

| Claim | Re-verification command |
|---|---|
| Tool count (38) | `grep -c "@mcp.tool" src/bullhorn_mcp/server.py` |
| Test count (648) | `.venv/bin/pytest -q \| tail -1` |
| Latest tag (v0.0.46) | `git tag \| sort -V \| tail -1` |
| CR4 docstring regression tests exist | `grep -n '"title": "CTO"' tests/test_server.py` |
| CR31 was docstring-only | `head -20 CR31.md` |
| Docstring misuse is review-CRITICAL | `grep -n docstring .claude/commands/review.md` |
| Token figures (~111k/~118k, ~51.6k, ~80% cut) | `head -30 CR34.md` and `git log --oneline v0.0.45..v0.0.46` |
| descriptions.py constants (MAX_FIELDS_PER_ENTITY=40, GENERIC_DISCOVERY_TOOLS, PICKLIST_FIELDS_TO_EXPAND, 10 SUPPORTED_ENTITIES) | `grep -n "MAX_FIELDS_PER_ENTITY\|GENERIC_DISCOVERY_TOOLS\|PICKLIST_FIELDS_TO_EXPAND\|SUPPORTED_ENTITIES" src/bullhorn_mcp/descriptions.py` |
| Static get_entity_fields pointer in generic docstrings | `grep -n "For the full field list of any entity" src/bullhorn_mcp/server.py` |
| AGENTS.md symlink | `ls -la AGENTS.md` |
| AGENTS.md operational-only rule and rationale | `grep -n "operational only" PROMPT_build.md` |
| reviews/latest.md rolling-overwrite practice | `git log --oneline -5 -- reviews/latest.md` |
| Drift item 1/2 (README tool list and write targets) | `sed -n '38,80p' README.md` |
| Drift item 3 (CR34 DRAFT) | `head -5 CR34.md` |
| Drift item 4 (plan header) | `head -6 IMPLEMENTATION-PLAN.md` |
| Drift item 5 (PRD Planned) | `grep -n "Planned (CR" PRD.md` |
| CASE_STUDY.md leak history | `git log --oneline --all -- CASE_STUDY.md` and `grep -n CASE_STUDY .gitignore` |
