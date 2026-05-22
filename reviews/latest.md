# Review: fix C1 create path silently returns 200 on tool error, M1 add error-propagation test

**Commit:** f684bfc
**Date:** 2026-05-22
**Files changed:** 3 (server.py, tests/test_server.py, reviews/latest.md)

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: Error inspection fires on `duplicate_found` path only if Bullhorn ever adds an `"error"` key alongside `"duplicate_found"`** — `server.py:_upload_cv_handler`
  Current duplicate responses (`{"duplicate_found": true, ...}`) contain no `"error"` key and correctly return 200. The check is safe as written, but the logic silently depends on `create_candidate_from_cv` never co-locating both keys.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
