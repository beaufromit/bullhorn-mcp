# Review: CR16 blanket isDeleted filter + M1 fix (two-leg dedup test)

**Commit:** 58684ff
**Date:** 2026-05-12
**Files changed:** 6 (IMPLEMENTATION-PLAN.md, reviews/latest.md, src/bullhorn_mcp/client.py, src/bullhorn_mcp/server.py, tests/test_client.py, tests/test_server.py)

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: `test_search_with_extra_params` assertion weakened** — `tests/test_client.py:318`
  The original assertion `assert "query=sender.id%3A1" in url` verified the exact encoded query string. The replacement `assert "sender.id" in url` is a loose substring check that would pass even if the URL structure changed significantly.

- **m2: CR16.md acceptance criterion #7 divergence** — `src/bullhorn_mcp/server.py:38`
  CR16.md acceptance criterion #7 states "`_company_name_search_query` is removed from server.py; its acronym/first-word logic is inlined at the two call sites." The implementation renamed the function to `_company_broad_query` and retained it as a shared helper. Functionally equivalent but diverges from the spec's stated approach.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
