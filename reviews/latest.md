# Review: CR44 match check wired in (Sprint 42B): parallel retrieval and pool fetch, find_duplicate_candidates takes a profile, D9 create policy, match_check_id outcomes, JSONL match log, calibration script

**Commit:** e45b789
**Date:** 2026-10-06
**Files changed:** 12

## CRITICAL

None.

## MODERATE

- **M1: Exact-surname commonness is taken from a fuzzy (~1) search total** - src/bullhorn_mcp/duplicate_retrieval.py:138-147, 306-309 (`_surname_query(with_initial=False)`, the `surname_count` branch)
  The count-only surname search is `lastName:<form>~1`, and its total is stored in `context.surname_counts`. The scorer (`duplicates.py` `_score_names`) uses that count as the `u` for an **exact** surname agreement (`_count_u(..., n)` only when `sur == "exact"`) and quotes it in the reason "Same surname (X), shared by N candidates". An edit-distance-1 total counts every one-letter variant (for short surnames such as Lee, Ng, Roe or Kay it takes in Lea, Leo, Le, Lees, Bee, See and so on), so exact-surname evidence gets fewer points than it should and the reason shown to the consultant overstates how many candidates share the name. Fewer surname points push real duplicates towards the low band, where the create goes ahead. This also contradicts the calibration: `scripts/calibrate_match.py` measures exact and fuzzy separately, and the build notes set the config from the **exact** shares ("Surnames (exact share of N)"). At runtime the fuzzy total is used. The forename count search uses exact forms, so the two name signals are counted on different bases. Not a known failure pattern.

- **M2: `_run_match_check` now fails open on every exception** - src/bullhorn_mcp/server.py `_run_match_check`
  The old wrapper (`_check_candidate_duplicates`) swallowed only `AuthenticationError` and `BullhornAPIError`. The new one catches `Exception`, so any programming error in the 400 new lines of `duplicate_retrieval.py`, in the scorer, or in a profile builder (KeyError on config, TypeError on an unexpected row shape) turns off duplicate protection on every `create_candidate`, `create_candidate_from_cv`, `parse_cv` and `parse_cv_text` call. The only sign is a warning string. The test suite cannot detect this: the module-level autouse `match_stub` replaces `match_candidates` for all of `test_server.py`, and `test_check_failure_does_not_block_create` asserts that the create goes ahead. The tool path (`find_duplicate_candidates`) still catches only the two API errors, so a bug surfaces as an exception there but is silently skipped on the write paths. The build notes flag this for the reviewer. It is a design regression from the narrowed handler, so it is not a known failure pattern.

- **M3: Outcome logging on the file-only attach path and the "nothing written" branch are untested** - src/bullhorn_mcp/server.py `_log_attached`, `_attach_created_cv_file`
  The build notes say `attached_to` is logged "only when the call wrote something ... on both the normal and the file-only paths". The new tests (`test_attach_cv_logs_outcome_under_given_id`, `test_attach_cv_logs_nothing_without_id`, `test_attach_cv_runs_no_check`) cover only the normal `_attach_cv` path with a write. No test calls `attach_cv` with a `match_check_id` for the Candidate the upload created (the `_attach_created_cv_file` branch, which now takes the new argument). No test covers the `already_attached` / nothing-written case, where `_log_attached` must not log. Both are new branches that decide what goes into the calibration record.

## MINOR

- **m1: Employer rerun threshold sits above the pool cap** - `retrieval.employer_rerun_over` is 200 and `retrieval.pool_cap` is 100. An employer search totalling 101 to 200 is neither narrowed nor complete: its ids are cut at 100 and `lookup_hit_cutoff` is set. For a common surname plus initial (whose pool search also truncates at 100) and an employer in that range, with no identifiers, a real duplicate can fall outside both searches. Both values are as planned (CR44 retrieval bullet, P13). The interaction between them is not addressed.
- **m2: Text-path stop hint names a call that cannot succeed** - `_create_candidate_from_cv` builds `attach_cv(candidate_id=..., match_check_id=...)` with no `upload_id` when the CV came in as `content`, but `attach_cv` requires `upload_id`. The old hint named `attach_cv` too but gave no call syntax.
- **m3: `match_config.json` `_comment` is stale** - it still says "Placeholder values until calibration (Sprint 42B T42B.6 ...)", but this commit sets the values from T42B.6.
- **m4: Parallel fan-out against an unlocked session refresh** - `retrieve_pool` runs up to 8 concurrent requests on one client. `BullhornAuth._refresh_session` has no lock, so a 401 mid-flight (server-side session invalidation, which the up-front `client.auth.session` read does not prevent) triggers up to 8 simultaneous refresh or full password logins.
- **m5: Retrieval reaches into client internals** - `retrieve_pool` calls the private `client._entity_has_isdeleted("Candidate")` and evaluates the bare expression `client.auth.session` for its side effect.
- **m6: Pass-through tests** - `TestFindDuplicateCandidates::test_deleted_match_flagged` and `test_response_has_reasons` set the stubbed `match_candidates` return value and assert that the same value comes back. They test the stub, not deleted-match flagging or reason generation, despite their names.
- **m7: Possible-duplicates message hint picks `listed[0]`** - the `possible_duplicates` hint fills `{candidate_id}` from the top uncertain match only. It does not say that the other listed candidates exist when it suggests `update_record` on one id.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
