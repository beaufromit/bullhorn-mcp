# Review: CR43 review cycle 1 fixes: created upload attaches file only, stricter education matching, minors m1-m5

**Commit:** aed0457
**Date:** 2026-10-02
**Files changed:** 4

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: `create_candidate_from_cv` still writes duplicate entries from one list** — src/bullhorn_mcp/server.py: `_create_candidate_from_cv`
  The within-list de-dup (cycle 1 m3) was added to `_plan_cv_update` only. Two identical entries in the `work_history` or `education` argument of `create_candidate_from_cv` are both written, so the two CV tools handle the same input differently.
- **m2: The `fields_to_update` warning names the resolved field, not what the caller sent** — src/bullhorn_mcp/server.py: `_attach_cv`
  Labels are now resolved before the unknown check, so a label that resolves to a field not in the parse is reported under its API name, which the caller never typed.
- **m3: `UploadStore.mark_created` has no unit test** — src/bullhorn_mcp/uploads.py
  It is covered only through the server tests. `tests/test_uploads.py` tests `mark_attached` and `attached_candidate_id` directly but not the new method, the unknown-upload no-op or that the id survives the attached tombstone.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
