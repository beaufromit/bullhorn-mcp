# Review: CR42 review fixes (attach_cv preview reads current description, case-insensitive content_type, doc status and text corrections)

**Commit:** 508a70f
**Date:** 2026-09-29
**Files changed:** 7 (CR42.md, IMPLEMENTATION-PLAN.md, reviews/latest.md, src/bullhorn_mcp/client.py, src/bullhorn_mcp/server.py, tests/test_client.py, tests/test_server.py)

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: attach_cv preview now echoes the Candidate's whole existing description** — src/bullhorn_mcp/server.py:`_attach_cv`. Adding `description` to the fetched fields makes the preview's `current` value truthful, but it also puts the existing description into the response in full. A read-only live check (2026-09-29) on the first Candidate returned by `/search/Candidate` found a 48,382-char description, roughly 12,000 tokens in one preview on top of the parsed HTML `proposed` value. Same class as the earlier response-size note, larger in size; unmeasured across the tenant.
- **m2: CR and plan text still describe the old content_type check** — CR42.md change 1 and IMPLEMENTATION-PLAN.md T40B.1 still say `content_type.startswith("text/html")`; the code now strips and lowercases first.
- **m3: stale concern and count in the plan** — the Sprint 40B "Concerns to verify" bullet on `attach_cv` and `description` still asks the reviewer to confirm the overwrite, with no mention that the preview now reports the real current value; the Response size bullet states the 5,028 / 3,402 figures twice; the Sprint 40B Actual count and header still read 841, the suite is now 843.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
