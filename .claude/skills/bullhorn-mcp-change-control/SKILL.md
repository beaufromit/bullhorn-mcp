---
name: bullhorn-mcp-change-control
description: Load when you are about to plan, start, resume, or close out ANY unit of work in this repo. Triggers include writing or editing a plan, authoring a new CR, running or being asked to follow PROMPT_PRD_to_PLAN.md / PROMPT_replan.md / PROMPT_build.md / PROMPT_iterate.md, deciding when to commit, push, or tag, updating IMPLEMENTATION-PLAN.md, reconciling test counts, or answering "what is the process from idea to release here". Provides the full CRx.md lifecycle, sprint planning rules, commit/push/tag discipline, IMPLEMENTATION-PLAN.md section anatomy, test-count bookkeeping, and a start-to-finish checklist.
---

# Bullhorn MCP Change Control

The repo runs a four-prompt AI-driven software lifecycle. Every change flows through one document chain, in order:

```
PRD.md  ->  CRx.md  ->  IMPLEMENTATION-PLAN.md (sprint)  ->  build commit  ->  review cycle  ->  push  ->  git tag
```

Never route around this chain. Skills, prompts, and CLAUDE.md all reinforce it.

## Jargon (defined once)

| Term | Meaning here |
|---|---|
| CR | Change Request: a numbered plan file `CR<n>.md` in the repo root (CR1.md through CR34.md exist as of 2026-07-03) |
| PRD | `PRD.md`, the Product Requirements Document: FRs, US, NFRs; the source of truth for WHAT the product does |
| FR / US / NFR | Functional Requirement / User Story / Non-Functional Requirement, the numbered units inside PRD.md |
| Sprint | One IMPLEMENTATION-PLAN.md section sized to roughly 100,000 tokens of AI-agent context; the unit of build work |
| Review cycle | The adversarial review and fix loop run after every build commit, before any push (see bullhorn-mcp-review-protocol) |
| Tag | Git tag `v0.0.N`, one per completed review cycle; the real versioning (pyproject version is static) |
| Replan | Re-running planning against the existing codebase via PROMPT_replan.md |

## The four prompt files (who does what)

| File | Role | Ends with |
|---|---|---|
| `PROMPT_PRD_to_PLAN.md` | Initial planning: PRD to plan | Updated IMPLEMENTATION-PLAN.md, no code |
| `PROMPT_replan.md` | Re-planning against existing code | Updated IMPLEMENTATION-PLAN.md, no code |
| `PROMPT_build.md` | Implement exactly one sprint | Local commit, NO push |
| `PROMPT_iterate.md` | Review-fix loop, then push and tag | `git push` + new tag, or safety-valve stop |

All four begin: study AGENTS.md (a symlink to CLAUDE.md) and strictly follow it.

## 1. CR authoring

### When a CR is required

CLAUDE.md rule (verbatim intent): whenever you write a plan and prompt the human to execute, write it as a `CRx.md` file in the project root. If the human edits the plan, write those edits back to the file BEFORE proceeding. Interactive sessions and the autonomous loop both obey this.

### Numbering

- Take the next free number: `ls CR*.md | sort -V | tail -1`. As of 2026-07-03 the highest is CR34.md.
- CR35 is RESERVED for tool consolidation (forward-referenced in CR34.md and IMPLEMENTATION-PLAN.md Sprint 35, no spec file yet; owned by bullhorn-mcp-productization-campaign). Do not reuse the number for something else without the owner's say-so.

### Structure (observed exemplars: CR33.md and CR34.md)

| Section | Required | Notes |
|---|---|---|
| `# CR<n>: <title>` | yes | One line |
| `## Status:` | yes | `DRAFT (awaiting approval)` until the human approves; `COMPLETE` after shipping. Flip it as part of the post-tag doc sync |
| `## Motivation` | yes | The observed problem, with measured evidence (CR34 cites live token measurements; CR33 cites the exact HTTP 400) |
| `## Goals` / `## Non-goals` | when scoping matters | CR34 has both; Non-goals is where you park adjacent work (CR34: "No tool consolidation, that is CR35") |
| `## Changes` or `## Design` | yes | Per-file: what changes in which `src/bullhorn_mcp/*.py` file |
| `## Tests` | yes | Named test classes/functions per file, plus expected count delta (CR33: "Test count: 629 (was 595 + 34 new)") |
| `## Verification` / `## Rollout` / `## Sequencing` | when relevant | CR34 includes live-tenant verification steps, service restart rollout, and an ordering constraint vs CR35 |

### The PRD-mapping rule

Every CR must trace to a PRD requirement. If none exists, amend the PRD FIRST, then plan the CR against it. This is enforced by the replan's bidirectional coverage validation (section 2), not by a standalone rule sentence.

Worked example (verify with `grep -n "NFR-8" PRD.md IMPLEMENTATION-PLAN.md`): CR34 trimmed the CR18 enrichment, which had never been a numbered requirement. The 2026-06-23 replan added **NFR-8 (Tool Description Context Budget)** to PRD.md so the PRD stayed the source of truth, and Sprint 35 records `**PRD requirement:** NFR-8`. Earlier examples: FR-20 was added for CR31, FR-21 for CR32.

## 2. Planning rules (PROMPT_PRD_to_PLAN.md and PROMPT_replan.md)

Both prompts share a core; replan adds code-reconciliation. The actual rules:

- **Bidirectional coverage validation.** Check that every FR/NFR is covered by user stories AND that no user story implements something absent from the requirements. On ANY discrepancy: **stop and check with the human.** Do not paper over gaps.
- **Sprint sizing.** Group user stories into tasks, tasks into a sprint sized to what an AI coding agent can achieve within an estimated **100,000-token context window**.
- **Discretely testable tasks.** Each task defines its own named unit tests. Each sprint ends with working code plus end-to-end tests covering this sprint AND all prior sprints.
- **Replan-specific rules:**
  - Study the codebase first (the prompt authorizes large parallel-subagent fanout; scale to what your session supports).
  - **Never assume functionality is missing; confirm with code search first.** The Sprint 35 planning entry models this: it lists the exact symbols confirmed absent (`select_fields`, `GENERIC_DISCOVERY_TOOLS`, `MAX_FIELDS_PER_ENTITY`) before declaring CR34 unimplemented.
  - Leftover tasks from prior sprints MUST be prioritized into the forthcoming sprint.
  - **Plan only.** Update IMPLEMENTATION-PLAN.md and stop. Do not implement code. Do not offer to implement.
  - Search for TODOs, placeholders, skipped/flaky tests, and inconsistent patterns while reconciling.
- Record the replan as a dated entry under `## PRD Validation Notes` at the top of IMPLEMENTATION-PLAN.md (format: `**Replan validation (YYYY-MM-DD, post-CRnn):** ...` with test count, tag, and findings).

## 3. Build rules (PROMPT_build.md)

Checklist for the build phase:

- [ ] IMPLEMENTATION-PLAN.md exists; if not, stop and alert the human.
- [ ] Work **one sprint only**, then stop and await instructions. Never roll into the next sprint.
- [ ] All testing runs in the venv: `.venv/bin/pytest`.
- [ ] Test fails: a quick fix plus retest is allowed; an involved fix becomes a documented task for the NEXT sprint.
- [ ] On failures or discoveries, update IMPLEMENTATION-PLAN.md immediately; remove the item when resolved.
- [ ] Document ANY bug you notice in the plan, even if unrelated to current work.
- [ ] No placeholders or stubs; implement functionality completely.
- [ ] Single sources of truth; no migrations or adapters. If unrelated tests fail, fix them as part of the increment.
- [ ] Capture the WHY in documentation, not just the what.
- [ ] Spec inconsistencies escalate to a heavier model to update the specs; do not silently reconcile.
- [ ] **AGENTS.md stays operational-only.** No status updates or progress notes in it; those belong in IMPLEMENTATION-PLAN.md. Stated rationale: "a bloated AGENTS.md pollutes every future loop's context." (Update it only when you learn something operational, e.g. a command you got wrong repeatedly.)
- [ ] Periodically prune completed items when the plan file gets large.
- [ ] When tests pass: update the plan, then `git commit` locally with a descriptive message. **DO NOT PUSH.** The review cycle owns pushing.

Observed feature-commit convention: `feat: CR<n> <short description>` for new capability, `fix: CR<n> <short description>` for bug-fix CRs (verify: `git log --oneline | grep -E "feat: CR|fix: CR"`).

## 4. Review, push, tag (exit mechanics)

The review loop itself (adversarial persona, C/M/m severity, the 8 known failure patterns, verdict format, 5-cycle safety valve) is owned by **bullhorn-mcp-review-protocol**; run it per `.claude/commands/review.md` and `PROMPT_iterate.md`. This skill owns the surrounding commit/push/tag discipline:

1. Fix commits during the loop use the exact convention from PROMPT_iterate.md: `review: fix C1 <title>, M1 <title>, ...`, listing every CRITICAL and MODERATE addressed. Commit locally, do not push (as of 2026-07-03, 27 of 130 commits are `review:` commits).
2. Exit condition: zero CRITICAL and zero MODERATE. Then:
   - Update IMPLEMENTATION-PLAN.md with review-cycle learnings (via subagent in the autonomous loop).
   - `git push`
   - Tag the next patch version and push tags:
     ```bash
     git tag                # find the latest, e.g. v0.0.46
     git tag v0.0.47        # N+1, never reuse or skip
     git push --tags
     ```
3. Doc-sync commit: the observed practice is a final `chore: post-review doc updates for CR<n> ...` commit carrying the plan updates, and the tag lands on that last commit of the cycle (verified: v0.0.46 points at the CR34 chore commit, v0.0.45 at the CR33 chore commit). Doc-sync content detail is owned by **bullhorn-mcp-docs-and-writing**.
4. Never address MINOR findings, never touch unrelated code, never proceed to the next sprint after pushing; the turn ends at the tag.

### Tagging conventions

- **One tag per review cycle**, monotonic `v0.0.N+1`. As of 2026-07-03: v0.0.1 through v0.0.46, 46 tags, contiguous.
- Tags are the real version; `pyproject.toml` version is static (0.1.0) and not bumped per release.
- Tag only at a clean review exit. Never tag mid-cycle, never tag unpushed speculative states.
- **Cautionary anecdote:** v0.0.33 and v0.0.34 both point to the same commit `710e756` (verify: `git rev-list -n1 v0.0.33; git rev-list -n1 v0.0.34`). It was a tagging slip on a day with an intense multi-patch cycle (the notes saga, see bullhorn-mcp-failure-archaeology), not two releases. Before tagging, run `git tag | sort -V | tail -3` and confirm the previous tag is not already on HEAD.

## 5. IMPLEMENTATION-PLAN.md anatomy

The plan file has a fixed shape. Preserve it when editing (as of 2026-07-03 the newest section is Sprint 35 / CR34):

| Section | Content |
|---|---|
| `## PRD Validation Notes` | Dated replan entries, newest context at top, each stating test count + tag + findings + any PRD amendments |
| `## Current Status` | One table row per sprint: `Sprint N | **COMPLETE** | summary, X tests passing, tagged v0.0.N`, with inline review-finding summaries for the bigger cycles |
| `## Architecture Overview` | Module lists (existing, new, extended, test files) |
| Per-sprint sections | `## Sprint N: <CR title> ...` containing: header block (**Change request**, **PRD requirement**, **User stories**, **Dependency**, **Risk**), `### Problem`, `### Tasks` with IDs `T{sprint}.{n}` each naming the target file and its named unit tests, `### Verification` checklist ending with "Tag vX after review cycle passes" |
| `### Expected test count after Sprint N` | `Previous: X. Added Y (breakdown). **Actual: Z passing, 0 failing.** Tagged v0.0.N` |
| `### Review cycle findings` | Every C/M finding with resolution, explicitly including **false positives** (Sprint 33 M1 is recorded as a false positive with the reasoning), plus **pattern learnings** appended for future reviews (see Sprint 34's three learnings) |

Rules of thumb:
- Findings and learnings accumulate; they are the institutional memory the reviewer reads. Never delete a recorded false positive or pattern learning.
- Task IDs are `T{sprint}.{n}` (e.g. T35.1); keep numbering dense and per-sprint.

## 6. Test-count bookkeeping

Test counts are tracked in four places and must agree at tag time:

1. The CR's Tests section (expected delta, e.g. CR33: "629 (was 595 + 34 new)").
2. The sprint's "Expected test count after Sprint N" section (Previous + Added, then the measured `Actual`).
3. The Current Status table row.
4. The plan-header baseline line in PRD Validation Notes.

Always record the MEASURED number (`.venv/bin/pytest -q` final line), never the predicted one. Regressions are themselves bookkept: the Sprint 15 post-tag regression (4 tests broken by a FastMCP dependency-drift change) has its own named subsection with a per-test root-cause table. As of 2026-07-03 the suite is **648 passed** at v0.0.46.

## 7. Idea to tagged release: the full path

You have an idea (feature, bug fix, or refactor). Follow this exactly:

1. **Check precedent.** Search CR1-CR34 and IMPLEMENTATION-PLAN.md: has this been tried, rejected, or reserved (CR35)? `grep -il "<topic>" CR*.md IMPLEMENTATION-PLAN.md`
2. **Check the PRD.** Find the FR/US/NFR the idea serves. If none exists, draft the PRD amendment first and get it approved with the CR.
3. **Author `CR<n>.md`** in the repo root using the section structure in section 1. Status: `DRAFT (awaiting approval)`. State assumptions; surface uncertainty; list Non-goals.
4. **Wait for human approval.** If the human edits the plan, write the edits back into the CR file before proceeding (CLAUDE.md rule).
5. **Plan the sprint.** Add a `## Sprint N: CR<n> ...` section to IMPLEMENTATION-PLAN.md per section 5 anatomy: header block, tasks `T{N}.{n}` with named tests, verification checklist, expected test count. In the autonomous loop this is PROMPT_replan.md's job; interactively, follow the same rules (coverage validation, confirm-by-code-search, plan-only).
6. **Build** per section 3: one sprint, plan updated on discovery, full suite green, local commit (`feat:`/`fix:` convention), NO push.
7. **Run the review cycle** per bullhorn-mcp-review-protocol. Fix C then M findings with minimal diffs, `review: fix ...` commits, re-review until clean (safety valve: 5 dirty cycles means stop and alert the human).
8. **Exit clean:** update plan learnings, `git push`, tag `v0.0.N+1`, `git push --tags` (section 4). Confirm the previous tag is not already on HEAD first.
9. **Doc sync:** flip the CR Status to COMPLETE, reconcile the four test-count locations, update Current Status, fix any PRD "Planned" annotations. Detail owned by bullhorn-mcp-docs-and-writing.
10. **Stop.** Do not start the next sprint in the same turn.

## OPEN DEBT (change-control-adjacent, as of 2026-07-03)

- **CR34.md Status still says `DRAFT (awaiting approval)`** although CR34 shipped and tagged v0.0.46. Workaround: trust IMPLEMENTATION-PLAN.md Current Status and git tags over CR Status lines. Suggest fixing in the next post-tag doc-sync commit.
- **IMPLEMENTATION-PLAN.md header baseline is stale:** says "630 tests passing, tagged v0.0.45" while the actual state is 648 tests at v0.0.46 (the Sprint 35 COMPLETE marker was added without refreshing the numbers). Same workaround and fix path. The wider drift catalog is owned by bullhorn-mcp-docs-and-writing; a standing post-tag doc-sync step is a candidate CR, not current policy.

## When NOT to use this skill

| If you need... | Load instead |
|---|---|
| Review loop internals: severity taxonomy, the 8 known failure patterns, verdict format, safety valve | bullhorn-mcp-review-protocol |
| History of specific incidents, dead ends, reverts | bullhorn-mcp-failure-archaeology |
| Docstring rules, token budgets, the doc-drift catalog, doc-sync detail | bullhorn-mcp-docs-and-writing |
| Environment setup, pytest mechanics, dependency traps | bullhorn-mcp-build-and-env |
| How to write or structure the tests a CR names | bullhorn-mcp-testing-playbook |
| The CR35 consolidation campaign itself | bullhorn-mcp-productization-campaign |
| Deploying/operating the tagged release | bullhorn-mcp-run-and-operate |

## Provenance and maintenance

Re-verify before trusting; every dated fact above is volatile.

| Claim | Re-verify with |
|---|---|
| CRx.md plan rule and edit-writeback rule | `grep -n "CRx" CLAUDE.md` |
| Planning rules (coverage, 100k sizing, stop-and-check) | `cat PROMPT_PRD_to_PLAN.md PROMPT_replan.md` |
| Build rules (one sprint, no push, AGENTS.md operational-only) | `cat PROMPT_build.md` |
| Push/tag exit mechanics and review-fix commit format | `sed -n '39,84p' PROMPT_iterate.md` |
| Highest CR number | `ls CR*.md | sort -V | tail -1` |
| CR structure exemplars | `head -60 CR33.md CR34.md` |
| PRD-mapping example (NFR-8 for CR34) | `grep -n "NFR-8" PRD.md IMPLEMENTATION-PLAN.md` |
| Latest tag, contiguity, duplicate-tag anecdote | `git tag | sort -V | tail -3` and `git rev-list -n1 v0.0.33 v0.0.34` |
| Tag lands on the cycle's last (doc) commit | `git log --oneline -2 v0.0.46` |
| Commit conventions and counts | `git log --oneline | grep -cE "^\S+ review: "` and `git log --oneline | grep "chore: post-review"` |
| Current test count | `.venv/bin/pytest -q | tail -1` |
| Plan anatomy (task IDs, Expected/Actual, findings, learnings) | `grep -n "Expected test count\|Review cycle findings\|Pattern learnings\|^#### T" IMPLEMENTATION-PLAN.md | tail -30` |
| AGENTS.md is a symlink to CLAUDE.md | `ls -la AGENTS.md` |
| CR34.md Status drift still open | `grep -n "^## Status" CR34.md` |
| Plan header baseline drift still open | `sed -n '5p' IMPLEMENTATION-PLAN.md` |
