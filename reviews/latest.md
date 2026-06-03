# Review: Extend update_record docstring to advertise Candidate support

**Commit:** f143418
**Date:** 2026-06-03
**Files changed:** 6

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: Plan-test mismatch in CR31.md** — `CR31.md` and `IMPLEMENTATION-PLAN.md` (T32.2) both describe `test_update_candidate_name_recomputed` as passing `{"firstName": "John", "lastName": "Smith"}` and also verifying that `client.get` fetches current name fields. These two claims are mutually exclusive: if both firstName and lastName are present, the code takes the branch at line 1211 (`_compute_person_name(resolved)` directly) and never calls `client.get`. The test correctly implements the one-sided case (`{"firstName": "John"}` only, which does trigger `client.get`), so the behavior under test is right. The plan documents are wrong. The "both fields provided, no GET call" branch is therefore not exercised for Candidate specifically, though it is covered by pre-existing ClientContact tests.

- **m2: Docstring omits namePrefix for ClientContact salutation** — The new line in `update_record` reads "For ClientContact and Candidate: 'title' is stripped with a warning — use 'occupation' for job title." This is accurate but omits that `namePrefix` is the correct field to set a salutation on a ClientContact. The in-process warning message at line 40 already names `namePrefix`, so a caller who triggers the warning is informed, but a caller who reads the docstring proactively is not.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
