# Review: fix M1 get_notes_for_entity pagination inconsistency, M2 _wrap_with_meta callable side_effect

**Commit:** a579c8e
**Date:** 2026-05-29
**Files changed:** 3

## CRITICAL

- **C1: Fully-deleted page causes infinite-loop next_start when total is known** — `server.py:get_notes_for_entity` (line 2636)
  `filtered_meta = {**meta, "data": cleaned_notes}` is passed to `_paginate_envelope`. When `include_deleted=False` (the default) and every note in a fetched page has `isDeleted=True`, `len(cleaned_notes) == 0`, so `_paginate_envelope` computes `next_start = start + 0 = start`. Bullhorn's association endpoint returns `total` (the unfiltered count), so the `total is None` fallback (`has_more = returned == count`) is never reached; instead `has_more = (start + 0) < total` evaluates True as long as any notes exist. An LLM following `next_start` re-requests the same page forever. The M1 fix restored the `start + count == next_start` invariant but introduced this regression. New class of issue.

## MODERATE

None.

## MINOR

None.

## Verdict

1 CRITICAL issue(s) must be resolved before pushing.
