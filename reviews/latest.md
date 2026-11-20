# Review: Sprint 44 review cycle 1 fixes (F10 logger name under `python -m`, F3 points pinned, max_employers cap tested, acceptance hint steps, attach_file 404 status match, education reason merge, description strip, get_file_types lock, Placement on the isDeleted denylist)

**Commit:** e7906a2
**Date:** 2026-11-20
**Files changed:** 11

## CRITICAL

None.

## MODERATE

- **M1: Adding Placement to the denylist left a /meta-gate test that no longer reaches /meta** — tests/test_client.py `TestMetadataDrivenIsDeletedGate::test_query_skips_isdeleted_when_meta_lacks_field` (about line 1260), with src/bullhorn_mcp/client.py:26
  The test mocks `/meta/Placement` with no `isDeleted` field and asserts that `query("Placement", ...)` leaves out `isDeleted=false`. Since m11, `_entity_has_isdeleted` returns False for Placement from the static denylist before any `/meta` read. Checked on this commit: the `/meta/Placement` route is called 0 times and the test still passes, so it now tests the denylist and not the metadata path its name and class describe. No other test covers "/query omits the clause because /meta lacks the field". The search side is still covered through PlacementChangeRequest. The commit moved two other tests off Placement for this reason (`test_meta_result_is_cached`, and the `TestCR16DeletedRecordFilter` case in test_server.py) but missed this one, and the class docstring still gives Placement as its example entity. This is a test validity problem: a passing test that no longer exercises what it claims to.

## MINOR

None.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
