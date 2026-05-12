# Review: Sprint 23 / CR15 — shortlist_candidate and shortlist_candidates tools (post-fix)

**Commit:** 0850269
**Date:** 2026-05-12
**Files changed:** 11

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: `status or get_shortlist_status()` silently swallows empty-string status** — `server.py:1190`, `server.py:1253`
  A caller that explicitly passes `status=""` gets the env-var default instead with no warning or error. Unlikely in practice but inconsistent with the integer validation style.

- **m2: CR15.md documents the duplicate-check `fields` argument as a Python list; implementation uses a comma string** — `CR15.md` vs `server.py:1119`
  The spec shows `fields=["id", "status", ...]` but `_shortlist_one` calls `client.query(..., fields="id,status,dateAdded,sendingUser")`. Implementation is correct; the spec example is misleading.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
