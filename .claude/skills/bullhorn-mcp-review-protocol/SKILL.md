---
name: bullhorn-mcp-review-protocol
description: Load this skill when you are about to review a commit in this repo, act as the adversarial critic, fix review findings, decide whether a diff is clear to push, classify an issue as CRITICAL/MODERATE/MINOR, check a diff against the known failure patterns, or when you see reviews/latest.md, a "review: fix ..." commit, or the PROMPT_iterate fix-review loop. Provides the full adversarial review protocol: reviewer persona and rules, severity taxonomy, the 8 known failure patterns, standing checks, exact verdict strings, the fix loop and exit conditions, the 5-cycle safety valve, false-positive handling, and the documented live-API blind spot.
---

# Bullhorn MCP Adversarial Review Protocol

The only quality gate in this repo (there is no CI) is an adversarial self-review loop. Every feature commit is reviewed before push; the push and the version tag happen only after a clean cycle. Primary sources of truth: `.claude/commands/review.md` (the reviewer persona and output format) and `PROMPT_iterate.md` (the fix-review loop). This skill restates both faithfully and adds the practice knowledge around them. As of 2026-07-03 (v0.0.46, 648 tests), 27 of 130 commits contain "review:", roughly one fix commit per five commits.

Jargon: a **CR** is a Change Request, a `CRx.md` spec file in the repo root (e.g. `CR33.md`). A **replan commit** is a planning-only commit (IMPLEMENTATION-PLAN.md update) that can sit between the build commit and the review. A **payload-assertion test** asserts the exact body sent to Bullhorn on a write (raw HTTP body via respx, or exact `create.assert_called_once_with(...)` args on a mock). **respx** is the httpx-mocking library used at the client layer; **DI** is dependency injection (mock clients patched into `server.get_client`).

## The reviewer persona

Opening line of `.claude/commands/review.md`: "You are an adversarial code reviewer. You did not write this code. You have no relationship with the author. Your only job is to find problems."

Hard rules (verbatim intent from the Rules section):

| # | Rule |
|---|------|
| 1 | Output only issues. No praise. No "the rest looks good." No hedging. |
| 2 | If a section has no issues, write "None." under the heading. Never omit headings. |
| 3 | Every CRITICAL must name which known failure pattern it matches, or state it is a new class. |
| 4 | Do not invent issues. If the code is correct, say so in the verdict. |
| 5 | Review only files in the diff. Do not review unchanged code. |
| 6 | Never suggest fixes or write code. Identify problems only. |
| 7 | Touch no file other than `reviews/latest.md`. |

`reviews/latest.md` is a rolling file, overwritten every cycle. Review history lives in git history of that file and in the "Review cycle findings" sections of IMPLEMENTATION-PLAN.md.

## What diff is reviewed

Run these in order:

```bash
git log --oneline -1        # identify the commit under review
git diff HEAD~1             # the diff to review
```

If `git diff HEAD~1` is empty, run `git diff HEAD~2`: a replan commit may sit between the build commit and the review. Then read `CLAUDE.md`, `PRD.md`, and any `CRx.md` relevant to the changed code before judging anything.

## Severity taxonomy (exact semantics)

| Label | Name | Meaning | Push policy |
|-------|------|---------|-------------|
| C1, C2, ... | CRITICAL | Correctness bug, data-integrity risk, security issue, or ANY recurrence of a known failure pattern (recurrence is auto-CRITICAL and the finding must name its pattern). Untested write-path logic in server.py is also CRITICAL. | Blocks push. Must be fixed. |
| M1, M2, ... | MODERATE | Design problems, missing edge cases, inconsistency with existing patterns, scope creep. | The loop requires fixing before push: exit needs the MODERATE section to read "None." |
| m1, m2, ... | MINOR | Style, naming, documentation nits. | Logged only. By policy never fixed (PROMPT_iterate constraint 1). One historical exception: commit e284427 (Sprint 18) fixed m1/m2/m3; treat that as the exception, not license. |

## The 8 known failure patterns

These are baked into `.claude/commands/review.md` as real bugs that each recurred at least once. Check EVERY diff against ALL of them. Any recurrence is CRITICAL and the finding must cite the pattern number.

| # | Pattern | Origin | Semantics |
|---|---------|--------|-----------|
| 1 | title vs occupation | CR1, CR4, CR6, CR7 | Bullhorn ClientContact uses `title` for salutation (Mr/Ms/Dr) and `occupation` for job title. Any code, docstring, test, or comment that uses `title` to mean job title is CRITICAL. |
| 2 | Field injection into write payloads | CR2, CR6 | `create_contact`, `create_company`, and `update_record` must send only caller-supplied fields to Bullhorn. Code that adds keys from DEFAULT_FIELDS, metadata iteration, parameter defaults, or template dicts is CRITICAL. |
| 3 | DEFAULT_FIELDS in write paths | CR2 | `DEFAULT_FIELDS` in client.py is for read operations only. Any write method referencing it is CRITICAL. |
| 4 | Owner resolution data leakage | CR3 | `resolve_owner()` returns only `{"id": int}`. If CorporateUser fields (email, firstName, department) reach a ClientContact write payload, CRITICAL. |
| 5 | CorporateUser query fields | CR3 | `resolve_owner()` queries `id,firstName,lastName,email` only. Adding fields (especially `department`) breaks some Bullhorn instances. CRITICAL. |
| 6 | Company reassignment guard ordering | Sprint 6 | The guard in `update_record` must fire AFTER label resolution. If it fires before, callers bypass it by using the label "Company" instead of `clientCorporation`. CRITICAL. |
| 7 | Bulk import error handling | CR3 | `_process_single_contact` must catch both `ValueError` and `BullhornAPIError` from `resolve_owner`. Missing either aborts the entire batch. CRITICAL. |
| 8 | FIELD_ALIASES precedence | Sprint 8 | Hardcoded aliases in metadata.py must be checked before dynamic metadata lookup in `resolve_fields()`. Reordering breaks "job title" to `occupation` resolution. CRITICAL. |

## Standing checks (beyond the 8 patterns)

Apply to every diff:

- [ ] **Correctness:** does the code do what the implementation plan (and the CR) says it should?
- [ ] **Payload-assertion law:** every new write path has a payload-assertion test ("Sprint 9 pattern"). Untested write-path logic in server.py is CRITICAL. How to write these tests: see bullhorn-mcp-testing-playbook.
- [ ] **Test validity:** each test asserts what it claims. A test that mocks the thing it is supposed to test is not a test.
- [ ] **Consistency:** respx for HTTP mocking, unittest.mock for server-layer DI, `format_response` for structured errors.
- [ ] **Scope:** the diff touches nothing beyond what the sprint requires. Unsolicited refactoring is MODERATE.

## Review output format

Write to `reviews/latest.md` using exactly the structure in `.claude/commands/review.md`: title line, `**Commit:**` / `**Date:**` / `**Files changed:**` header, then `## CRITICAL`, `## MODERATE`, `## MINOR` sections (each finding as `- **C1: <title>**` with file:line and explanation, "None." where empty), then `## Verdict`.

**Exact verdict strings** (nothing else counts as a verdict):

- `NO CRITICAL ISSUES. This diff is clear to push.`
- `X CRITICAL issue(s) must be resolved before pushing.` (variants also count the MODERATEs)

Note the asymmetry: the clean verdict string mentions only CRITICALs, but the loop exit ALSO requires the MODERATE section to say "None." (PROMPT_iterate Step 1). A "no critical" verdict with open M findings is still a dirty cycle.

## The fix loop (PROMPT_iterate.md)

Run this loop until clean, then push. Never proceed to the next sprint mid-loop; the job ends after the push.

1. **Check the verdict** in `reviews/latest.md`. Clean (no CRITICALs, MODERATE section "None.") goes to step 5. Otherwise continue.
2. **Fix all CRITICALs first (C1, C2, ...), then MODERATEs (M1, M2, ...).** For each finding: locate the referenced file/function; if it cites a known failure pattern, read the corresponding CRx.md before fixing; implement the MINIMAL fix, no refactoring, no unrelated code; run the relevant unit tests. Then run the full suite: `.venv/bin/pytest`. All tests must pass. A failing test related to your fix: resolve it. Unrelated: document in IMPLEMENTATION-PLAN.md via a subagent and continue.
3. **Commit locally, do not push:**
   ```bash
   git add -A
   git commit -m "review: fix C1 <title>, M1 <title>, ..."
   ```
   List every CRITICAL and MODERATE addressed.
4. **Re-run the review:** act as the adversarial critic per `.claude/commands/review.md` against the new diff (`HEAD~1` is now your fix commit), overwrite `reviews/latest.md`, return to step 1.
5. **Exit (zero C, zero M):** update IMPLEMENTATION-PLAN.md with review-cycle learnings via a subagent, then `git push`, then tag the next patch version (`git tag`, increment, `git tag v0.0.N+1`, `git push --tags`). Full tagging and plan-bookkeeping discipline: see bullhorn-mcp-change-control.

Clean cycles get explicit commits too (observed: c150ec7 "Sprint 23 post-fix review, no CRITICAL or MODERATE issues"; 6337c2e "clear Sprint 20 findings").

## Safety valve

If you complete step 4 five times (five consecutive dirty review cycles) and CRITICALs or MODERATEs still remain: STOP. Do not push. Document the remaining issues in IMPLEMENTATION-PLAN.md and alert the human. Something structural is wrong and needs manual intervention.

## False positives

The reviewer can be wrong. Do not silently drop a finding: record the false positive in the sprint's "Review cycle findings" section of IMPLEMENTATION-PLAN.md with the reasoning, and make no code change. Precedent: Sprint 33 M1 flagged a plan-to-implementation mismatch (`resolve_caller` vs `resolve_owner`); investigation showed CR32.md used the wrong function name and the code was correct. Recorded as "M1 false positive" in both the sprint status row and the Sprint 33 findings section; zero code changed.

## Known limits of the review

1. **The live-API blind spot (documented, structural).** The review reads diffs, plans, and tests; it never executes against the live Bullhorn tenant. It has caught real logic and test defects pre-tag, but it has repeatedly missed live-API behavioral errors. Canonical case: commit db78771 (2026-05-22) removed the `entityId` parameter from `search_emails` on a plausible semantic argument; the review passed it and it was tagged v0.0.38; Bullhorn actually REQUIRES `entityId` on `/search/UserMessage`, so every call then failed with a 400 in production until c5cdfaa (2026-06-03) restored the line, 12 days later. Conclusion: a clean review verdict is NOT evidence that live-API assumptions hold. Live verification is a separate mandatory discipline: see bullhorn-mcp-live-api-method.
2. **Review-prescribed fixes can themselves be wrong.** It has happened twice: a review fix used a nonexistent field name (the notes saga, CR22), and one review's prescribed pagination fix was flagged CRITICAL as an infinite loop by the next cycle and reverted (commit 1289e16). Treat a reviewer finding as a problem report, not a design; you own the fix's correctness. Full incident narratives: see bullhorn-mcp-failure-archaeology.

## When NOT to use this skill

| Topic | Use instead |
|-------|-------------|
| CRx.md authoring, sprint planning, tag/push conventions, IMPLEMENTATION-PLAN.md structure | bullhorn-mcp-change-control |
| How to run read-only live verification before or after coding | bullhorn-mcp-live-api-method |
| Full chronological incident stories behind the failure patterns | bullhorn-mcp-failure-archaeology |
| Writing payload-assertion tests, mocking architecture, fixture traps | bullhorn-mcp-testing-playbook |
| Bullhorn API field/endpoint quirks referenced by the patterns | bullhorn-mcp-api-quirks |
| Triage when something is broken (not a review cycle) | bullhorn-mcp-debugging-playbook |

## Provenance and maintenance

Volatile facts in this file are stamped 2026-07-03 (v0.0.46, 648 tests). Re-verify with:

| Claim | Re-verification command |
|-------|------------------------|
| Reviewer persona, 8 patterns, verdict strings, output format | `cat .claude/commands/review.md` |
| Fix loop, exit conditions, safety valve, MINOR policy | `cat PROMPT_iterate.md` |
| Latest review content and verdict | `cat reviews/latest.md` |
| Review commit count and message convention | `git log --oneline --grep 'review:' \| wc -l` and `git log --oneline --grep 'review:'` |
| Total commits | `git log --oneline \| wc -l` |
| MINOR-fix exception | `git show --stat e284427` |
| entityId blind-spot dates and tags | `git log --format='%h %ad %s' --date=short -1 db78771; git log --format='%h %ad %s' --date=short -1 c5cdfaa; git tag --contains db78771 \| head -1` |
| Sprint 33 M1 false-positive record | `grep -n 'false positive' IMPLEMENTATION-PLAN.md` |
| Clean-cycle commit examples | `git show --stat c150ec7 6337c2e` |
| Test count | `.venv/bin/pytest -q` |
