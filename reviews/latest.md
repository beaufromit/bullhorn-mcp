# Review: Fix M1 extra_fields owner override and M2 null defaults for create_job

**Commit:** 15a4d8e
**Date:** 2026-04-29
**Files changed:** 3

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: Large diff is a line-ending normalisation artifact** — `src/bullhorn_mcp/server.py` — git reports ~1644 changed lines but the Python-level semantic changes are exactly 6 lines. The normalisation affects lines outside the M1/M2 scope. Not a correctness issue, but inflates code-review noise for unchanged functions.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
