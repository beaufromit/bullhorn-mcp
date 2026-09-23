# Review: CR39 (Sprint 37B) escape apostrophes in resolve_owner / resolve_caller CorporateUser lookups instead of rejecting them

**Commit:** 2ce3bfe
**Date:** 2026-09-23
**Files changed:** 8

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: Stray bold marker in plan header** — IMPLEMENTATION-PLAN.md, "Current baseline" paragraph: `...PLANNED, target v0.0.50).**` ends with an unmatched `**`, so the bold runs on into the following sentence when rendered.
- **m2: CR39.md Status line is stale** — `CR39.md` Status still reads "APPROVED ... Next: replan." The replan and the build are both done in this commit, and IMPLEMENTATION-PLAN.md says Sprint 37B is BUILT. T37B.3 defers only the COMPLETE flip to post-tag, so the intermediate state is now inaccurate.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
