# Review: remove entityId param from search_emails + CR26 documentation

**Commit:** e3cb8c2 (HEAD) + uncommitted working tree changes
**Date:** 2026-05-22
**Files changed:** 4 (IMPLEMENTATION-PLAN.md, reviews/latest.md, server.py [uncommitted], tests/test_server.py [uncommitted])

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: Missing commit message for `entityId` removal** — `src/bullhorn_mcp/server.py:731–737`
  The uncommitted change removes `extra_params={"entityId": person_id}` from `search_emails`. The change is correct (the Lucene `sender.id OR recipients.id` clause is sufficient; `entityId` is redundant), but no commit message documents that decision. The original implementation commit (`64ad4b5`) described `entityId` as "required" — a future reader seeing both commits will be confused about the reversal without an explanation. The `client.py` docstring still cites `{"entityId": 123}` as the intended use of `extra_params` for UserMessage; that example is now misleading and could be updated or removed.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
