# Review: fix C1 infinite-loop next_start when all page notes are deleted

**Commit:** 1289e16
**Date:** 2026-05-29
**Files changed:** 3

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: `total` in pagination envelope counts soft-deleted notes** — `server.py:get_notes_for_entity`
  When `include_deleted=False` (the default), `pagination.total` is Bullhorn's unfiltered count of all notes including soft-deleted ones. A caller who uses `total` to estimate how many live notes exist will overcount. The docstring does not warn about this. Acceptable given the Bullhorn association endpoint offers no server-side `isDeleted` filter, but callers interpreting `total` as "live note count" will be misled.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
