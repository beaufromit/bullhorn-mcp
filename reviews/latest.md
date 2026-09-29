# Review: CR41 CV upload tickets replace base64 CV inputs and the /upload-cv endpoint (Sprint 40)

**Commit:** 412f1d1
**Date:** 2026-09-29
**Files changed:** 13

## CRITICAL

None.

## MODERATE

- **M1: Retrying after a failed CV attach on create points the model back at a duplicate-creating path** — src/bullhorn_mcp/server.py: `create_candidate_from_cv` (file attachment block)
  When `create_candidate_from_cv(upload_id=...)` creates the Candidate but `attach_file` raises, the upload is deliberately kept "so the user can retry" (CR41 File lifecycle), but the only signal returned is the bare warning `CV file attachment failed: ...`. Nothing tells the agent that the correct retry is `attach_cv(candidate_id=<the new id>, upload_id=...)`. The obvious retry, calling `create_candidate_from_cv` again with the same `upload_id`, hits the duplicate check against the Candidate just created, and the documented escape (`force=True`) then creates a second Candidate and attaches the CV to it. `test_create_attach_failure_keeps_upload` asserts the bytes are kept but does not cover what the retry does. New class of issue (partial-write retry path), not one of the 8 known patterns.

## MINOR

- **m1: Misleading hint when `show_cv_upload_box` is called on an upload that already received its file** — `reissue_token` raises `UploadAlreadyUsed("This upload is already received.")`, and `_upload_error` attaches the fixed hint "Call request_cv_upload for a new one." For a `received` upload the right next step is to carry on with `create_candidate_from_cv` / `attach_cv`, not to start over and resend the file.
- **m2: The ticket's `candidate_id` is stored but never checked** — `request_cv_upload(candidate_id=A)` then `attach_cv(candidate_id=B, upload_id=...)` attaches the CV to B with no warning. CR41 calls it a "hint", so this matches the spec, but the hint has no effect anywhere except the `get_cv_upload` output.
- **m3: Attached-tombstone lifetime is described inconsistently** — `uploads.py` module docstring and the Sprint 40 build notes say tombstones live "30 minutes later" / "30 more minutes", but `mark_attached` sets `remove_at = received_at + FILE_TTL_SECONDS`. An upload attached at minute 29 keeps its `attached` tombstone for about 1 minute, after which `get_cv_upload` answers `upload_not_found` instead of `attached`. The code matches CR41 ("until the 30-minute purge"); the docstring and notes do not.
- **m4: No claim or lock between reading an upload and marking it attached** — `_load_received_upload` returns the bytes without reserving the upload, so two overlapping `create_candidate_from_cv` / `attach_cv` commit calls on one `upload_id` can both parse, write and attach. The duplicate check narrows this for create, but it does not remove it.
- **m5: Live token sits in the request path** — uvicorn (and Caddy) access logs record `POST /upload/<token>`. A rejected file does not consume the ticket, so a token seen in the logs stays redeemable for up to 15 minutes. This follows the CR41 design (`/upload/{token}`) and the build notes already raise it; logged here for the owner.
- **m6: No per-user cap on outstanding uploads** — any authenticated caller can mint tickets without limit and park up to 10 MB each in process memory for 30 minutes. Only the TTLs bound memory. The build notes already raise this.
- **m7: `test_upload_box_ui_domain_hash` rebuilds the formula it tests** — the expected value is computed with the same `sha256(f"{base}/mcp")[:32]` expression as `_upload_box_app_config`, so the test proves only slash normalisation, not that the domain is correct. The production value is unverified until the T40.8 live step.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
