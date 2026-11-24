# Review: Sprint 45 (CR49) review cycle 1 fixes (start dates limited to 1980-2100, per-tool invalid_start_date hints, empty caller start date falls back to the env default, test and plan tidy-ups)

**Commit:** d8552d5
**Date:** 2026-11-24
**Files changed:** 4

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: Out-of-range message talks about seconds for string input** — src/bullhorn_mcp/server.py `_job_start_date_ms`. The range error always ends "Numbers must be epoch milliseconds, not seconds.", so a string such as `"0202-11-20"` or `"2101-01-01"` returns a message about numbers and seconds that does not apply to what the caller sent.
- **m2: Plan test count is stale** — IMPLEMENTATION-PLAN.md Sprint 45 "Actual: 1,615 passing ... 69 new in tests/test_server_cr49.py" is unchanged; the suite now runs 1,626 (commit message and `.venv/bin/pytest`), and 69 no longer matches the file after two tests were removed and thirteen cases added.
- **m3: T45.7 still describes the removed E2E test** — IMPLEMENTATION-PLAN.md T45.7 now places "`update_job` with a midnight-UTC epoch (51533's shape) writes the corrected value" in `tests/test_server_cr49.py` as an E2E test, but this commit deleted `TestStartDateEndToEnd::test_update_job_midnight_utc_epoch_writes_corrected_value`; the behaviour is covered only by `TestUpdateJobStartDate::test_update_job_start_date_normalised`.
- **m4: Range rejection not exercised through update_job** — the new range check is tested on the helper and through `create_job` (`test_create_job_epoch_seconds_rejected`), but no `update_job` test sends an epoch-seconds or out-of-range value and asserts `invalid_start_date` with no POST.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
