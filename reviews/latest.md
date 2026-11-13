# Review: CR46 v0.0.56 acceptance-test fixes (CV write path filter, file attach params, skillSet list, current company, match log ids, points removed, placeholder employers, upload box) plus CR48 per-field overwrite on attach_cv (Sprint 43)

**Commit:** 5acdf53
**Date:** 2026-11-13
**Files changed:** 21

## CRITICAL

None.

## MODERATE

- **M1: README documents the removed `confirm` parameter** - README.md:315 ("Current company" paragraph)
  The paragraph was added in this commit and says a different existing `companyName` "is written on `confirm=True`". CR48, built in the same commit, removed `confirm` from `attach_cv`; a call that follows this line fails with an unknown-argument error. The paragraph four lines below it (README.md:319) says the opposite ("The `confirm` parameter was replaced by `overwrite`"). The README contradicts itself and the code on the one interface change this commit makes.

- **M2: The `_Bullhorn` test harness does not answer the child read-back, so work history writes always "fail" in the non-E2E tests** - tests/test_server_cr46.py:77 (`_Bullhorn.__call__`)
  The dispatcher answers `PUT /entity/CandidateWorkHistory` and `PUT /entity/CandidateEducation` but has no route for `GET /entity/CandidateWorkHistory/{id}` or `GET /entity/CandidateEducation/{id}`. `client.create()` reads the row back, gets the 404 "unmocked" response, and `_write_candidate_children` reports "Work history entry failed" with an empty `written.work_history`. Confirmed by running `attach_cv` through the harness with one work history entry. This is the B3 symptom the sprint set out to remove, reproduced inside the suite whose docstring says it "answers like Bullhorn". Every test in this file that sends work history (`TestCurrentCompany`, all of `TestOverwriteChoice` via `OVERWRITE_PARSE`) therefore runs with a failed child write and an unasserted warning, and `assert data["written"]["work_history"] == []` in `test_attach_cv_overwrite_call_adds_nothing_twice` is true whether or not the dedupe works. Only the two `_E2EBullhorn` tests that write children see a successful child write.

- **M3: `title` in `fields_override` is written to `namePrefix` on both CV paths (not introduced here, carried through the new helper)** - src/bullhorn_mcp/server.py `_filtered_cv_override`
  Checked against live `/meta/Candidate` (read-only, 2026-11-13, with the aliases in the local `.env`; a production `BULLHORN_CANDIDATE_ALIASES` entry for `title` would change the result): `title` is not a Candidate field, and the label "Title" belongs to `namePrefix` (maxLength 20). `resolve_fields` matches labels case-insensitively, so `_filtered_cv_override(metadata, {"title": "Finance Manager"}, warnings)` returns `{"namePrefix": "Finance Manager"}` with no warning. A job title lands in the salutation field. The Candidate branch of `_strip_contact_title` ("Use 'occupation' for job title") can never fire on this tenant because the key is renamed before it runs, and `_ATTACH_SKIP_FIELDS` lists `title`, not `namePrefix`, so `attach_cv` proposes it as an addition or overwrite. The same result came out of HEAD~1 (the later `resolve_fields` call at old line 3338), so this commit did not create it. It is the title-versus-occupation class of known failure pattern 1 on a different entity. The new helper special-cases `description` and `name` at exactly this point and does not handle `title`, and no test in the diff covers a `title` override against a `/meta` that has a "Title" label.

- **M4: A list `skillSet` in `fields_override` on `create_candidate_from_cv` is not pinned by any test** - src/bullhorn_mcp/server.py `_filtered_cv_override` and `_create_candidate_from_cv`
  CR46 B8 promises that a list `skillSet` in `fields` or `fields_override` is joined to text before the write. The only test is `test_create_candidate_list_skillset_joined`, which covers `create_candidate`. Two new conversions sit on the CV create path (one in `_filtered_cv_override`, one before the skills merge in `_create_candidate_from_cv`) and no test fails if both are removed. Run through the harness, `fields_override={"skillSet": ["Excel", "IFRS"]}` sends `"Excel, IFRS"` and, with `skills=["Budgeting"]`, `"Excel, IFRS, Budgeting"`, so the behaviour is correct today and unguarded. Same shape as CR37 M1 (load-bearing and unpinned).

## MINOR

- **m1: An `overwrite` name that was written as an addition is reported as ignored** - `_attach_cv`. With the record's `companyName` empty, `overwrite=["companyName"]` writes `companyName` (it is in `written.fields`) and also returns the warning "overwrite names that are not pending overwrites, ignored: ['companyName']". The warning says the opposite of what happened. Confirmed by running it.

- **m2: `"all"` together with other names is not treated as all, and that case has no test** - `_attach_cv`. `overwrite=["companyName", "all"]` resolves `all` as a field name and reports it as not pending; nothing extra is written. It fails safe, but the tool text does not say `"all"` must be the only entry, and the tests cover only the single-entry spellings.

- **m3: The skills half of `test_attach_cv_overwrite_call_adds_nothing_twice` proves nothing** - tests/test_server_cr46.py:744. `OVERWRITE_EXISTING` already holds `skillSet: "Excel"` and the parse's only skill is Excel, so no skill is added on the first call. "No `skillSet` in the second call's POSTs" passes with or without the de-duplication. The work history half also uses an existing row with the same `endDate` as the parse, so B10 is not exercised at the tool level; it is covered only on the pure helper `_new_cv_children`.

- **m4: B10 side effect on the create path is silent** - `_create_candidate_from_cv` calls `_new_cv_children([], [], work_history, education)`. With `endDate` out of the key, two entries that share company, title and `startDate` (or share company and title and have no `startDate`) are collapsed to one, and the create response has no `already_present` or warning to say an entry was dropped. The plan's build notes accept the collapse; they do not mention that the create path does not report it.

- **m5: `_writable_candidate_fields` swallows every exception from `/meta`** - `except Exception` around `metadata.get_fields("Candidate")` turns an `AuthenticationError`, a network error or a bug in the projection into the two-name fallback filter with no log line. Sprint 42B's review narrowed `_run_match_check` to API and network errors for the same reason; this new helper goes the other way.

- **m6: The upload box fix cannot be verified by the suite** - tests/test_upload_box.py asserts on the HTML source with regular expressions; nothing runs the script or a host. The root cause in CR46 B6 is stated as "high confidence", not observed. In the same change `show_cv_upload_box` lost its output schema (annotation `str | ToolResult`), so the result no longer carries `structuredContent`, and the box now sends `ui/notifications/size-changed` before `ui/initialize` has completed. None of the three has been seen in a real host; T43.15 is the only check.

- **m7: Top-level `match_check_id` means two different things** - On a stop response (`duplicate_found`, `possible_duplicates`) the top-level `match_check_id` is the fresh check's id. On a successful create it is the id the caller passed in, and the fresh id is under `duplicate_check.match_check_id`. Same key, same tools, different check.

- **m8: D1 proposes no company when `startDate` is not a number, with no message** - `_current_company_name` skips entries whose `startDate` is not int or float. A corrected `work_history` with an ISO date string gets no `companyName` proposal and no warning; on a tenant where `companyName` is required the caller then gets `required_fields_missing` with no hint why. Confirmed by running `attach_cv` with `"startDate": "2021-01-01"`.

- **m9: Plan names tests that do not exist** - IMPLEMENTATION-PLAN.md T43.5 (marked DONE) lists `test_write_children_reports_rows_when_readback_uses_default_fields`; no test has that name. Its two halves are split between `test_create_candidate_children_readback_uses_default_fields` (client level, the GET `fields`) and `test_e2e_create_from_cv_real_parse` (the reported rows). T43.12 lists `test_e2e_attach_cv_real_parse_additions_then_confirm`; the test is now `..._additions_then_overwrite_choice`.

- **m10: `attach_file` parameter named `type`** - src/bullhorn_mcp/client.py:292. Shadows the builtin inside the method.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
