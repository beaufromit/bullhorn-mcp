# Review: Surface pagination metadata on list/search/query tools (CR28)

**Commit:** b71ef66
**Date:** 2026-05-29
**Files changed:** 6

## CRITICAL

None.

## MODERATE

- **M1: `get_notes_for_entity` pagination envelope is internally inconsistent when deleted notes are filtered** — `server.py:get_notes_for_entity` (~line 2638)
  `has_more` and `next_start` are computed from `raw_count` (the count returned by Bullhorn before the Python-side `isDeleted` filter runs), but `count` in the envelope is `len(cleaned_notes)` (after filtering). When any notes are filtered out, `start + count < next_start`, breaking the invariant that holds for all other 8 tools. A caller who computes the next offset as `start + count` will request overlapping records. The discrepancy is untested — no test exercises both `include_deleted=False` (the default) and asserts `pagination` values when deleted records are present. New class of issue.

- **M2: `_wrap_with_meta` silently mishandles callable `side_effect` in both test fixtures** — `tests/test_server.py` (conftest `mock_client` fixture, ~line 12; `TestSearchEmails` `email_client` fixture, ~line 218)
  Both copies of `_wrap_with_meta` have a dead branch: when `bare_mock.side_effect` is set and is not a `BaseException` instance, the code does `raise se`. If `se` is a callable (a valid Mock `side_effect` type), this raises `TypeError` at runtime instead of delegating to the callable. Any future test that sets `client.search.side_effect = some_callable` expecting it to propagate through the delegation will get a confusing `TypeError` rather than the intended behavior. Currently no test exercises this path, so no existing test fails — but the fixture contract is not what it appears to be. New class of issue.

## MINOR

- **m1: `meta["count"]` populated by client but unused by `_paginate_envelope`** — `client.py` (all three `*_with_meta` methods) and `server.py:_paginate_envelope`
  All three `*_with_meta` methods populate `"count"` in the returned dict from `result.get("count", len(data))` (Bullhorn's own count field). `_paginate_envelope` ignores it and recomputes from `len(data)`. In practice they will be the same, but the populated key travels unused through every call.

## Verdict

2 MODERATE issue(s) to consider before pushing.
