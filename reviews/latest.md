# Review: CR42 fix Bullhorn resume parser parameters (populateDescription=html on file parse, format/populateDescription as query params on text parse)

**Commit:** 62f73c6 (build 58fbf1d reviewed via `git diff HEAD~2`; HEAD~1 is a docs-only plan update)
**Date:** 2026-09-29
**Files changed:** 5 (CR42.md, IMPLEMENTATION-PLAN.md, PRD.md, src/bullhorn_mcp/client.py, tests/test_client.py)

## CRITICAL

None.

## MODERATE

- **M1: attach_cv preview now proposes a description overwrite while reporting the current value as null** — src/bullhorn_mcp/client.py:`parse_resume_file` (effect surfaces in the `attach_cv` / `_attach_cv` commit path)
  Before this diff the parser never returned a populated `description` (every call 400'd, and `populateDescription=true` would not have produced one anyway). With `populateDescription=html`, `parsed["candidate"]["description"]` now carries 3,000 to 5,000 chars of HTML. `_attach_cv` diffs every scalar in `parsed_candidate` against an `existing` record fetched with `fields="id,firstName,lastName,email,phone,mobile,occupation,companyName,skillSet,status,dateAdded"`, which does not include `description`. So for every existing Candidate the preview lists `{"field": "description", "current": null, "proposed": "<html...>"}` even when the Candidate already has a description, and a `force_all=True` commit then overwrites it. The consultant's consent is given against a preview that misstates the current value. The plan's "Concerns to verify" section flags the overwrite but not the false `current: null`. No test covers `attach_cv` with a parsed `description`. New class of issue (behavioral change activated by a client-layer fix in an unchanged caller), not one of the 8 known patterns.

## MINOR

- **m1: content_type match is case-sensitive** — `parse_resume_text` uses `content_type.startswith("text/html")`; MIME types are case-insensitive, so `Text/HTML` or ` text/html` (leading space) from a caller silently selects `format=text` / `populateDescription=text` for HTML content. `parse_cv_text` and `create_candidate_from_cv` pass the caller's string through unnormalized.
- **m2: HTML description inflates CV tool responses** — `parse_cv`, the `attach_cv` preview (`proposed` value) and the `create_candidate_from_cv` duplicate response now include several KB of HTML per call. Acknowledged in the plan as a concern; logged here as unmeasured.
- **m3: stale plan text** — IMPLEMENTATION-PLAN.md Sprint 40B heading still reads "BUILT (awaiting T40B.3, review, tag)" although T40B.3 is recorded as passed; the replan validation bullet and the Sprint 40B "PRD requirement" line still say the PRD amendments are "uncommitted", but they are committed in 58fbf1d.
- **m4: stale CR status** — CR42.md Status still says "Next: replan as Sprint 40B" after the replan and build are done.
- **m5: test case swapped versus CR42 change 2** — CR42.md says the rewritten file-parse test becomes a docx exact check and a pdf case is added; the build kept the rewritten test as pdf and added docx. Coverage is equivalent; the CR text and the tests disagree.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
