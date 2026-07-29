# NEXT STEPS

Written 2026-07-04 at baseline v0.0.46, 648 tests, 38 tools, CR34 complete, CR35 unspecced. This is the outgoing lead's directed roadmap: what to do next, in what order, and why. It is a roadmap, not a change spec: every item below must become its own CRx.md and route through the CR, review, tag loop before implementation (see `.claude/skills/bullhorn-mcp-change-control`). Nothing here overrides PRD.md; items marked "PRD amendment required" must amend the PRD first.

## Owner-confirmed direction (2026-07-04)

These four answers from the project owner anchor every priority below. If they change, re-derive the roadmap.

| Question | Answer |
|---|---|
| What is the tool for? | Built primarily for The Panel, but built so it COULD be transferred to any other agency using Bullhorn. Transferability is a design constraint, not a current deployment goal. |
| What is success in a year? | Consultant adoption, plus ease of integration for tools yet to be built. This product should be THE gateway to Bullhorn that users, tools, and automated workflows all go through. |
| Who operates it? | The AI loop (PROMPT files + skill library) with an occasional human approving CRs and deploys. Guardrails and self-verification therefore deserve heavy investment. |
| Unmet user wants? | Reporting/analytics, and better agent UX. |

## The strategic frame

"THE gateway to Bullhorn" is a stronger claim than "an MCP server with tools." A gateway is judged on three things this codebase does not yet fully deliver:

1. **It never lies and never silently fails.** The failure history (see `.claude/skills/bullhorn-mcp-failure-archaeology`) shows the biggest outages came from unverified live-API assumptions and silent degradation, not logic bugs. A gateway must detect Bullhorn drift before users do.
2. **Consumers can build on it without reading the source.** Tool contracts (names, envelopes, error shapes) must be stable and their changes announced. Today a docstring edit can silently add or remove a capability (the CR31 lesson).
3. **It runs itself.** With an AI loop as the operator, anything a human would "just notice" must instead be a check that runs automatically and fails loudly.

Everything below serves one of those three.

## Priority 0: Housekeeping sprint (one CR, do first)

Small, verified loose ends. All are already labeled OPEN DEBT in the skill library; each entry names the skill that documents it.

| Item | What to do | Why now | Skill reference |
|---|---|---|---|
| Undeclared fastmcp | Add `fastmcp` to pyproject.toml with a version bound (installed: 3.2.4). Fresh installs currently fail at server import. | Blocks any new environment, including CI | build-and-env |
| WHERE-clause injection asymmetry | Add the CR33 M2 quote guard + validation test to `get_job_submissions`, `resolve_owner`, and `identity.resolve_caller` | Known pattern class; the fix template already exists | architecture-contract |
| Doc drift | Run the post-tag doc-sync checklist once: CR34.md still says DRAFT, IMPLEMENTATION-PLAN.md header still says 630 tests / v0.0.45, README lists 18 of 38 tools, PRD FR-18 still says Planned | Docs of record must be trustworthy before an AI loop relies on them | docs-and-writing |
| Duplicated note constants | Merge `_NOTE_DEFAULT_FIELDS` / `_NOTE_SEARCH_DEFAULT_FIELDS` (byte-identical) and remove unused `_NOTE_ENTITY_SUBJECT_FIELD` | They diverged once before (CR22) | architecture-contract |
| Dead remote branch | Delete `origin/claude/fix-api-url-formatting-jn0DQ` (fully merged) | Hygiene | none needed |
| Skill library commit | Decide whether `.claude/skills/` is committed to the repo (recommended: yes, it is operational tooling) | The library is currently untracked and unversioned | none needed |
| CASE_STUDY.md history | Make an explicit decision: accept that the reverted confidential case study remains in git history, or rewrite history once (disruptive; requires force-push coordination). Record the decision in IMPLEMENTATION-PLAN.md either way | An undecided exposure is worse than a decided one | failure-archaeology |

## Priority 1: Guardrails for unattended operation

Justified directly by "AI loop + occasional human." Today the adversarial review loop is the ONLY quality gate and a human eyeball is the only drift detector. Three additions, each its own CR:

1. **Minimal CI.** A GitHub Actions workflow that runs `pytest` on every push. Nothing fancy. It catches environment drift (the Sprint 15 FastMCP breakage class) and push mistakes the local loop cannot. The repo has no `.github/` today.
2. **A scheduled live canary.** `.claude/skills/bullhorn-mcp-live-api-method/scripts/smoke_read.py` already does the right thing (read-only auth + one search per core entity). Run it on a schedule from the production box and alert on failure. This converts the project's worst incident class (Bullhorn changing behavior server-side, e.g. the notes 500 and the entityId outage) from user-reported to self-detected. Keep it strictly read-only.
3. **A token-budget regression gate.** `.claude/skills/bullhorn-mcp-run-and-operate/scripts/measure_descriptions.py` measures enriched tool-description size. Record the current number after CR34, set a threshold, and re-run it in the review checklist for any CR that touches docstrings or descriptions.py. CR18's flagged risk materialized once (~118k tokens); do not let it creep back.

## Priority 2: The productization campaign

Already fully runbooked with real inventory numbers, ranked options, numeric gates, and fenced wrong paths in `.claude/skills/bullhorn-mcp-productization-campaign`. Execute it as written:

- **Phase 1, de-instance.** Move remaining tenant-specific literals into env config (the one genuinely undefended field is `customText41` in `DEFAULT_FIELDS["Placement"]`). Gate: this tenant's behavior is byte-identical before and after.
- **Phase 2, CR35 tool consolidation.** Measure first, then work the ranked menu (the four by-ID getters are the obvious first merge). Gates are numeric: token target, test count non-decreasing, and the 8-item capability scenario list must still pass.
- **Phase 3, drift hardening.** Retrofit the metadata-gate pattern (the `_entity_has_isdeleted` template) onto the remaining hardcoded behavioral assumptions so future Bullhorn drift degrades gracefully instead of erroring.

This campaign IS the "could be transferred to another agency" requirement. Do not expand it into multi-tenant hosting; per the owner, transferability of the codebase is the goal, not SaaS operation.

## Priority 3: Gateway hardening (PRD amendment required)

To honestly claim "THE gateway," add a PRD section defining what consumers are promised, then implement it. Suggested scope for the amendment:

1. **Contract stability.** Define the stable surface: tool names, the pagination envelope, the error shapes (`ERROR:` strings and structured JSON). Adopt a rule: any change to that surface gets a line in a `CHANGELOG.md` written at tag time (fold into the post-tag doc-sync checklist). Consumers, human or automated, must be able to learn what changed without diffing docstrings.
2. **Observability.** The server currently logs warnings and nothing else. Add structured logging (per-tool call counts, Bullhorn error rates, dedup blocks, enrichment success/failure at startup) so the occasional human can answer "is it healthy?" in one look, and the AI loop can cite evidence. Start with logs; do not build a metrics stack until logs prove insufficient.
3. **Resilience mitigations already promised in the PRD but never built** (rate limiting/backoff for bulk imports, transient-error retry, 204 verification on association deletes, /upload-cv rate limiting and per-uploader audit). Once all traffic funnels through this gateway, these stop being nice-to-haves. Implement behind the existing warn-and-continue philosophy: fail safe, never block startup.
4. **The second consumer interface, decided deliberately.** `/upload-cv` proves non-MCP consumers exist. Before more ad hoc endpoints appear, decide ONE pattern for future machine consumers (more custom routes vs telling integrators to speak MCP over HTTP). This is a candidate decision, not a recommendation; take it to the PRD.

## Priority 4: Better agent UX (user ask; measure first)

Do not guess at UX improvements; the project's own history shows guesses about agent behavior are usually wrong. Sequence:

1. **Instrument first.** Add lightweight telemetry on tool errors (which tool, which error class, how often agents retry). One sprint, read-only in effect.
2. **Fix what the data names.** Likely candidates based on history, to be confirmed by the data: error messages rewritten to be self-correcting (tell the agent what to do next, the way `add_note` lists valid actions), dedup threshold tuning with real false-positive rates, and picklist coverage in enrichment.
3. **CR35 itself is UX.** Fewer, clearer tools with better descriptions is the single biggest agent-experience lever, and it is already Priority 2.

## Priority 5: Reporting and analytics (user ask; PRD amendment required)

A genuinely new capability area. Direction:

1. **Discovery CR first.** Collect the top five questions consultants actually ask (e.g. CVs sent this week, pipeline for a job, placements this quarter, activity per consultant, jobs with no submissions). Verify per question, against the live API read-only, whether the data is reachable (see `.claude/skills/bullhorn-mcp-live-api-method`). Write the findings before designing anything.
2. **Design principle: aggregate server-side, answer small.** Paginating raw records through the LLM to count them is slow and token-expensive. Analytics tools should loop/aggregate in Python and return compact JSON summaries. `list_placements` with its date-range filtering (CR33) is the first analytics-shaped tool; extend that pattern.
3. **Expect route and field gaps.** Some `/search` routes return nothing on this account (`/search/Note`) and some fields are not indexed for sort or range (`smtpSendDate`); date-range analytics may need /query instead of /search per entity. Verify per entity, never assume. Test a route with a match-all probe (`query=id:[0 TO 99999999]`, read `total`) — **not** with `fieldsFromIndex`, which CR37 falsified as a signal, since working searches return `false` too.

## Standing disciplines (never stop)

- Every Bullhorn behavioral assumption verified live (read-only) before coding against it.
- Every write path gets a payload-assertion test.
- Every CR routes through the adversarial review loop; exit only clean; tag every cycle.
- Post-tag doc-sync checklist every tag.
- Re-run skill Provenance checks when a skill's facts look stale; update date stamps when re-verified.

## Explicitly deferred or fenced off

- **Multi-tenant SaaS hosting**: out of scope per owner; transferable codebase only.
- **Delete/merge/archive tools and contact company reassignment**: permanently excluded by PRD NFR-1/NFR-2.
- **A parallel REST API surface**: not without the Priority 3 PRD decision.
- **Backfilling historical null-name records** (CR26): deliberately left alone; do not revisit without a user request.

## What "perfect" looks like in a year (acceptance picture)

- The Panel's consultants use it daily and trust it: wrong-field errors and duplicate blocks are rare enough that the telemetry, not user complaints, finds problems.
- A new automated workflow integrates against it in a day using only README, tool descriptions, and CHANGELOG, without reading the source.
- Bullhorn server-side drift is caught by the canary before a user sees it.
- A second agency could take the repo, fill in a config file, and run it without code changes.
- The AI loop ships CRs end to end with the human only approving and deploying, and CI plus the review loop catch what the human used to.
