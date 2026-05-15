# Review: CR22 — Fix targetEntityName, search_notes clientCorporation, wildcard guard

**Commit:** 83e9da9 + uncommitted CR22 changes
**Date:** 2026-05-15
**Files changed:** 2 (server.py, tests/test_server.py)

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: `get_notes_for_entity` docstring omits placements/leads/opportunities from default fields list** — `server.py:2427–2429`
  The "Default includes" line in the `fields` arg docstring still reads `id, action, comments, dateAdded, commentingPerson, personReference, jobOrder, clientCorporation, isDeleted` — it does not mention `placements`, `leads`, or `opportunities`, which were added to `_NOTE_DEFAULT_FIELDS` in f77e36b. Callers reading only the docstring will be unaware these associations are returned by default.

- **m2: `test_empty_query_returns_invalid_query_error` does not assert the redirect hint** — `tests/test_server.py`
  The parallel wildcard test asserts `"get_notes_for_entity" in data["message"]`; the empty-query test does not. Minor inconsistency in test thoroughness.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
