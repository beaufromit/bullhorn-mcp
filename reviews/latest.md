# Review: Sprint 43 review cycle 1 fixes (README overwrite wording, harness child read-back, title override dropped on the CV paths, CV list skillSet tests, overwrite warnings, repeated-entry and startDate warnings, /meta exceptions narrowed, passed_match_check_id, attach_file file_type)

**Commit:** 58b2e14
**Date:** 2026-11-13
**Files changed:** 10

## CRITICAL

None.

## MODERATE

- **M1: The title-to-namePrefix fix covers only the CV paths; `create_candidate` and `update_record` on a Candidate still write a job title sent as `title` into the salutation** - src/bullhorn_mcp/server.py `create_candidate` (~line 2350) and `update_record` (~line 1856)
  This commit adds a `title` guard in `_filtered_cv_override` only. Both other Candidate write paths in the same file still call `metadata.resolve_fields(...)` first and `_strip_contact_title(...)` second, so the strip never sees a `title` key. Confirmed live (read-only, 2026-11-13, local `.env` aliases): `resolve_fields("Candidate", {"title": "Finance Manager"})` returns `{"namePrefix": "Finance Manager"}`, and `_strip_contact_title` on that result returns it unchanged with no warning. A job title therefore goes into `namePrefix` (maxLength 20) with no message, and the Candidate branch of `_strip_contact_title` ("Use 'occupation' for job title") can still never fire. This is known failure pattern 1 (title vs occupation) on the Candidate entity. The lines are unchanged in this diff and were not introduced here, so it is logged as MODERATE. But the commit presents M3 as fixing pattern 1 for Candidate, and the README now says a `title` key is dropped only in the CV section, while the two general write tools keep the same hole.

## MINOR

- **m1: The plan still describes the old response key** - IMPLEMENTATION-PLAN.md T43.8 (line ~4221) and the build note at line ~4299 still say the response "adds `match_check_id` = the passed id". This commit renamed it to `passed_match_check_id` (m7) and updated CR46.md and README.md, but not the plan.

- **m2: `["all", "all"]` is reported as "mixes all with field names"** - `_attach_cv`. Any list with more than one entry that contains "all" takes the mixed branch, so a repeated "all" overwrites nothing and gets a warning that says it was mixed with field names when it was not. It fails safe; the message is wrong.

- **m3: The no-numeric-startDate warning fires on `attach_cv` when the record already holds a company** - `_attach_cv` checks `_is_blank(candidate_fields.get("companyName"))`, which is the proposed value, not the record's. With a record that already has the right `companyName` and work history given with ISO dates, the response still tells the caller to "Pass companyName in fields_override". On the create path the same warning also fires for a CV whose roles simply have no dates, where the advice to give epoch milliseconds does not apply.

- **m4: The repeated-entries warning says "given" for lists the caller never gave** - `_create_candidate_from_cv`. When `work_history` or `education` is omitted, the counts come from the parse, but the message reads "work history 3 given, 2 written". It also explains only the work history key; the education match rule is not described.

- **m5: `_writable_candidate_fields` no longer falls back on a malformed `/meta` body** - Narrowing to `AuthenticationError`, `BullhornAPIError` and `httpx.HTTPError` means a `ValueError` from a non-JSON `/meta` response now fails the CV tool instead of using the two-name fallback. Intended per the new test (`test_writable_fields_meta_bug_is_not_swallowed`), but no test covers a JSON decode failure, so whether that should count as a network-class error was not decided.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
