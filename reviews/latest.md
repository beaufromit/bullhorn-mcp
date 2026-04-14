# Review: Fix M1 patch target, M2 restore reload safety, M3 fields param assertion

**Commit:** a33b8a3
**Date:** 2026-04-14
**Files changed:** 3 (src/bullhorn_mcp/identity.py, tests/test_identity.py, tests/test_server.py)

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: `mock_session` appears in test function signatures where it is only used indirectly** — `tests/test_identity.py`, multiple test methods
  Carried forward from prior commit. `test_resolve_caller_no_match`, `test_resolve_caller_multiple_matches`, `test_resolve_caller_cached`, and `test_resolve_caller_query_fields_no_department` accept `mock_session` as a direct parameter but never reference it; it flows in indirectly through the `client` fixture chain.

- **m2: `parse_qs` and `urlparse` imported inside the test body** — `tests/test_identity.py:164–165`
  `from urllib.parse import urlparse, parse_qs` is declared inside `test_resolve_caller_query_fields_no_department` rather than at module level. Functional but inconsistent with the module-level import style throughout this file.

- **m3: Unused import `mock_patch` persists** — `tests/test_server.py:7`
  `from unittest.mock import Mock, patch, patch as mock_patch`. Not introduced by this diff; carried forward from earlier sprints.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
