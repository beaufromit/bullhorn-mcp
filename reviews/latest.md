# Review: Sprint 41 (CR43) reviewed CV flow: stored parse, Claude's corrections written, attach_cv additions/overwrites split, shared duplicate check, education matching

**Commit:** 613a1cb (reviewed together with cfc8781; the Sprint 41 build spans both, diff `HEAD~2`)
**Date:** 2026-10-02
**Files changed:** 10

## CRITICAL

- **C1: The `cv_attach_retry` call (and any later `attach_cv` on the same upload) writes the raw parse over Claude's corrections** — src/bullhorn_mcp/server.py: `_create_candidate_from_cv` (`cv_attach_retry.next_call`) and `_attach_cv` (omitted lists fall back to `parsed[...]`)
  When the file attach fails after a create, the response tells the agent to call `attach_cv(candidate_id=<new>, upload_id=...)` with no corrections. `_attach_cv` then falls back to the stored *uncorrected* parse for `work_history`, `education`, `skills` and `primary_skills`, and de-dups those raw entries against the corrected records the create just wrote. They do not match, so they are written as additions. Concrete case from the CR43 fixture: Claude corrects work history to `{companyName: "Sample Gadgets Ireland", title: "Financial Accountant"}` and drops "Python" from skills. The retry adds a second work history row titled "Financial Accountant Sample Gadgets Ireland" with no companyName, appends "Python" to `skillSet` and links the raw `primarySkills` ids Claude removed. The corrected scalar fields also come back as `pending_overwrites` offering to revert Claude's corrections to the parser's values. The same happens for any `attach_cv(new_id, upload_id)` after a successful create, because P2 lets an attached upload through for its own Candidate. This writes exactly the parser errors US-50 exists to prevent, without telling anyone, on the path the server tells the agent to take. `test_create_attach_failure_points_retry_at_attach_cv` only covers the uncorrected path (no corrections passed to the create), so it passes while this fails. New class of issue (data integrity on a write path). It does not match a known failure pattern.

## MODERATE

- **M1: Education matching merges two different qualifications at the same school when they fill different fields** — src/bullhorn_mcp/server.py: `_education_matches` / `_education_view`
  Fields are only compared where both sides have a value, and a shared `school` alone is enough to count as a match. So existing `{school: "UCD", degree: "BComm"}` matches new `{school: "UCD", certification: "Professional Diploma in Tax"}`, and also new `{school: "UCD", major: "Finance"}` (an MSc with no degree text). The new entry is dropped and only shows up as a count in `already_present.education`. An undergraduate degree followed by a later diploma or masters at the same institution is common. B1's "known limit" only describes the opposite, conservative case, and no test covers this one (`test_plan_education_conflicting_field_not_matched` only covers degree against degree).

## MINOR

- **m1: `written.skill_set` can list names that were truncated away** — in `_create_candidate_from_cv`, `skill_set_written` is computed before `_truncate_against_meta(resolved)`. If the truncation cuts the merged `skillSet`, the response still reports every name as written.
- **m2: `fields_to_update` is not label-resolved, but `fields_override` is (B5)** — `attach_cv(fields_to_update=["Job Title"])` filters out every field and only warns. The two arguments resolve names differently.
- **m3: No de-dup within a list Claude passes** — `_plan_cv_update` de-dups work history and education only against the existing record. Two identical entries in the same `work_history` argument are both written.
- **m4: A truncated addition comes back as an overwrite** — a field written as an addition and cut by `_truncate_against_meta` no longer equals the proposed value on the confirm call. It is then listed in `pending_overwrites` and rewritten, although the hint says "Nothing above will be added twice."
- **m5: Over-long docstring line** — `_education_matches` docstring has one line far past the file's usual wrap ("...in the live replay). A field filled on one side only...").

## Verdict

1 CRITICAL issue(s) must be resolved before pushing (plus 1 MODERATE).
