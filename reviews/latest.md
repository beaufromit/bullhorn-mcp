# Review: CR49 (Sprint 45) job start date defaults to today and is stored as midnight New York on create_job and update_job

**Commit:** f497e16
**Date:** 2026-11-24
**Files changed:** 6

## CRITICAL

None.

## MODERATE

- **M1: A number that is not epoch milliseconds is written as a 1970 start date with no error** — src/bullhorn_mcp/server.py:370 `_job_start_date_ms`
  Any int or float is read as epoch milliseconds with no check that the result is a believable date. Run against the built helper: `1801458000` (1 Feb 2027 in epoch seconds) returns `1746000000` (21 Jan 1970); `20270201`, `0` and `-1` all return `18000000` (1 Jan 1970). Both `create_job` and `update_job` then send that value to Bullhorn and report success. The same gap exists for strings: `"0202-11-20"` returns `-55764788638000` (year 202) and is sent. The FR-13 Amendment says the tools "shall refuse any other value with a clear error"; a value that is plainly not a job start date is accepted and silently stored as a wrong date on a live record. The code follows CR49 Design 2 as written and the build notes disclose the epoch-seconds case as an open note, which is why this is MODERATE and not CRITICAL. No test pins the behaviour either way: `test_rejects_nan_inf_and_out_of_range_numbers` covers only values that cannot become a date at all.

- **M2: The `invalid_start_date` hint is false on `update_job`** — src/bullhorn_mcp/server.py:404 `_invalid_start_date_error`, used at `update_job`
  Both tools return the same hint: "Pass the date as YYYY-MM-DD, or leave it out for today." On `update_job`, leaving the start date out does not set today; it leaves the job's existing date unchanged (CR49 Q1, and the tool's own Args text says "an empty one sets today"). An agent that follows the hint after a rejected update will drop the field, the update will succeed, and the job keeps its old date while the agent believes it is today. The error text is the interface the agent reads at the point of failure, and here a write tool misdescribes its own behaviour. The source is CR49 Design 4 ("the same error shape"). `test_update_job_invalid_start_date_returns_error_no_api_call` asserts only that `"YYYY-MM-DD"` is in the hint, so the wrong half is unpinned.

## MINOR

- **m1: Invalid env default is reported with a caller-facing hint** — when `BULLHORN_JOBORDER_DEFAULTS` holds a bad `startDate`, every `create_job` without a start date returns `invalid_start_date` with "Pass the date as YYYY-MM-DD, or leave it out for today." The caller did leave it out; nothing in the message says the bad value came from server configuration. `test_create_job_invalid_env_default_start_date_returns_error` pins the error code only.
- **m2: An explicit empty caller value skips the configured default** — `merged = {**resolved_defaults, **resolved_caller}` lets `{"startDate": None}` or `""` from the caller overwrite a `BULLHORN_JOBORDER_DEFAULTS` start date, so the result is today, not the configured default. CR49 states the precedence as caller value, then default, then today, and does not say which an empty caller value counts as. No test covers the combination (`test_create_job_blank_or_null_start_date_sends_today` runs with the env default cleared).
- **m3: Nothing tests the `tzdata` dependency** — `test_time_zones_load` (tests/test_server_cr49.py:47) is named in the plan as the T45.1 test for the new dependency, but `ZoneInfo` reads the system tz database first, so the test passes with `tzdata` uninstalled on any machine that has `/usr/share/zoneinfo`.
- **m4: Unused constant** — `DEC_25_2026` (tests/test_server_cr49.py:36) is defined and never referenced.
- **m5: Duplicate tests in `TestStartDateEndToEnd`** — `test_update_job_midnight_utc_epoch_writes_corrected_value` repeats `TestUpdateJobStartDate::test_update_job_start_date_normalised` (same input, same asserted body), and `test_update_job_read_back_value_round_trips_unchanged` repeats the tool-level form of `test_already_correct_value_is_unchanged`. They add to the 69 count without adding coverage.
- **m6: Most create_job tests assert one key, not the payload** — the `TestCreateJobStartDate` tests check `env.body["startDate"]` only. The single full-body assertion for a create with a start date is the edited `test_e2e_create_job_minimal` in tests/test_server.py; no test asserts the exact create body when the caller supplies a start date (by API name or by label).
- **m7: Plan text out of step with the build** — IMPLEMENTATION-PLAN.md Sprint 45 tasks T45.2, T45.3 and T45.7 still name `tests/test_server.py` as the home of the new tests, which are in `tests/test_server_cr49.py` (recorded only in the build notes); the Verification box "Local commit `feat: CR49 ...`" is unchecked in the commit that is that local commit.
- **m8: `update_job` Args text omits epoch milliseconds** — the `fields` entry says only `Pass startDate as "YYYY-MM-DD"`, and the `create_job` entry the same; the accepted epoch-millisecond form (and that it must be a number, not a numeric string, per the build notes) is documented in README.md only, which the agent does not see.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
