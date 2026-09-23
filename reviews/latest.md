# Review: CR36 housekeeping (Sprint 37) - declare fastmcp, single-quote guards on three WHERE interpolations, collapse note constants, docs-of-record sync

**Commit:** 7142cbb (build) + bf91c18 (T37.7 docs), reviewed as `git diff HEAD~2`
**Date:** 2026-09-23
**Files changed:** 11

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: Quote rejection surfaces under a "not found" error code** - `resolve_owner`'s new quote `ValueError` reaches the agent as `owner_not_found` (`create_contact`, `create_job`, `create_candidate`) or `user_not_found` (`search_emails`). The input was rejected, not looked up and missed. The message text is accurate, but the error code is not. This follows T37.3's "no new handling" instruction, so it is logged only. The comment at `server.py:1415` ("resolve_owner raises ValueError when no CorporateUser matches") is now incomplete.
- **m2: `resolve_owner` docstring `Raises:` is stale** - `client.py` still documents `ValueError` only for "no CorporateUser matches". It does not mention the new quote rejection.
- **m3: Legitimate apostrophe names and emails are now hard-rejected** - Owner names like "O'Brien" and RFC-valid emails like `o'brien@...` can never resolve. This is not a regression, because the old unescaped query was already malformed for them. But CR36 allowed "reject or escape", and this tenant is Irish, so the reject-only choice has a real user population. A caller whose Entra email has an apostrophe is locked out of every write path that needs `resolve_caller`.
- **m4: Test docstrings misname the query syntax** - `tests/test_client.py::test_owner_with_single_quote_raises` and `tests/test_identity.py::test_email_with_single_quote_raises` call the `/query` `where` clause "Lucene". It is the SQL-style `/query` syntax. Lucene is `/search`.
- **m5: Sprint status row contradicts the Sprint 37 detail** - `IMPLEMENTATION-PLAN.md:94` still says "T37.7 operational items pending owner". bf91c18 records T37.7 as closed in the Build notes but did not update the row.
- **m6: README write-target and Features sections still stale** - These are out of T37.6 scope and already noted in the build notes. They are logged here so the drift stays visible.


## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
