# Review: fixes CR38 review minors m1 (malformed Perplexity 200 body), m2 (untested error branches), m4 (.env.example spacing)

**Commit:** 46adb31
**Date:** 2026-09-23
**Files changed:** 6

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: `search_people` docstring still says it returns the raw `results` list** (`src/bullhorn_mcp/perplexity.py`, `search_people`). The function now drops non-dict entries and raises `invalid_response` on a non-list `results`, so "return the raw `results` list" no longer describes the behavior.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
