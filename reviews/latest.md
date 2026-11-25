# Review: Sprint 46 (CR50) review cycle 1 fixes (attach_cv already_attached reports the stored file type, search file-row branch removed, single description cap pass, Candidate hint named in CV next step, isDeleted in file_not_found, get_file_text auth test, plan and PRD wording)

**Commit:** b8605f1
**Date:** 2026-11-25
**Files changed:** 6

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: the plan's Sprint 46 test count is stale after this diff** — IMPLEMENTATION-PLAN.md "Expected test count after Sprint 46" still records "Added 73 in `tests/test_server_cr50.py`" and "**Actual: 1,701 passing**", and the baseline paragraph and the Sprint 46 status row both say 1,701. This commit edits the plan but leaves those figures, while its test changes remove 1 test and add 5 (the search/query cap-once pair, the `get_file_text` auth test, the two `attach_cv`-after-`attach_file` cases). `.venv/bin/pytest` at HEAD gives 1,705 passed.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
