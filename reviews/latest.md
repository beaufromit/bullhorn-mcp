# Review: Sprint 40 (CR41) review cycle 1 fixes: attach retry hint, upload claim, per-user cap, log redaction

**Commit:** a3a1db0
**Date:** 2026-09-29
**Files changed:** 7

## CRITICAL

None.

## MODERATE

- **M1: A failed claim releases a claim it never took** — src/bullhorn_mcp/server.py: `_load_received_upload` (`except UploadError` branch)
  When `upload_store.claim` raises anything other than `upload_in_use` (in practice `UploadNotFound`, because the caller does not own the upload or it was purged), the handler still calls `upload_store.release(upload_id)`. `release` is keyed by `upload_id` alone, so a commit call by a different user on the owner's `upload_id` clears the owner's live claim and reopens the overlapping-commit race the claim exists to close (the m4 fix). The same happens for the owner's own second call if the record is purged between the calls. No test covers a failed claim leaving another call's claim in place. New class of issue.

## MINOR

- **m1: `candidate_id` is now enforced, but CR41 and the PRD still call it a hint** — `attach_cv` refuses `upload_candidate_mismatch` when the ticket's `candidate_id` differs, but CR41.md ("`candidate_id` hint") and the Sprint 40 notes still describe it as advisory only.
- **m2: The access-log filter's wiring is untested** — the tests call `_RedactUploadTokenFilter` directly; nothing checks that `main()` adds it to `uvicorn.access` in HTTP mode, so removing that line would pass the suite.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
