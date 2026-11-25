# Review: Sprint 46 (CR50) file upload follow-ups: file description cap on every response, new get_file_text tool, upload box always offered, next_steps by hint and extension, attach reporting, wording, box URI rename

**Commit:** 83186aa
**Date:** 2026-11-25
**Files changed:** 10

## CRITICAL

None.

## MODERATE

- **M1: `attach_cv` reports `"type": "Original CV"` for a file that was stored with a different label or none** — src/bullhorn_mcp/server.py: `_attach_cv` (the `already_attached` branch) and `_attach_created_cv_file` (the `already_attached` branch)
  F4 adds `"type": _CV_FILE_TYPE` to both `already_attached` sites as a constant. Those branches are reached for any upload whose tombstone names this Candidate, not only for one the CV tools attached. `attach_file` also calls `upload_store.mark_attached(upload_id, file_id, "Candidate", id)`, which sets `attached_candidate_id` and keeps `parsed`, so `_load_received_upload(attached_ok_for=candidate_id)` lets a later `attach_cv` through. Reproduced against HEAD with the suite's own helpers (scratch test, not added to the repo): `parse_cv` on a pdf, then `attach_file(entity="Candidate", entity_id=900, upload_id=...)` returned `"type": null`, then `attach_cv(candidate_id=900, upload_id=...)` returned `written.file == {"file_id": 4321, "name": "Jane_Doe_CV.pdf", "type": "Original CV", "already_attached": true}`. The file in Bullhorn has no type (or whatever label `attach_file` was given), so the response states something that is not stored. CR50's goal for F4 is that `attach_cv` reports what it stored so Claude does not need to read the record back; in this sequence the report is false and Claude will pass it on to the consultant. `test_attach_cv_file_has_type` only covers tombstones made by calling `mark_attached` directly, so no test exercises a tombstone written by `attach_file`. New class of issue (a response field asserted from a constant instead of from what was written).

## MINOR

- **m1: the `search_entities` file-row branch cannot fire, and its test mocks a route Bullhorn does not have** — src/bullhorn_mcp/server.py `search_entities` (`file_rows=_is_file_entity(entity)`), tests/test_server_cr50.py `test_search_entities_file_attachment_rows_capped`. Read-only live check on 2026-11-25: `/search/CandidateFileAttachment` and `/search/ClientCorporationFileAttachment` both return 400 "Unknown search entity". The plan's live evidence (P2) covers `/query/*FileAttachment` only. The test passes against a respx mock of `/search/CandidateFileAttachment`, so it pins behaviour that cannot occur on the tenant.
- **m2: the plan's verification box is ticked on a claim that is not true** — IMPLEMENTATION-PLAN.md Sprint 46 Verification: "`grep -rn "cv-upload-box" src/ tests/ README.md` returns nothing" is marked done. The grep matches `src/bullhorn_mcp/server.py` (the F7 comment naming the old URI) and `tests/test_server_cr50.py` (two negative assertions). The build note beside it says the grep returns "only two negative assertions", which also leaves out the server.py match.
- **m3: PRD wording now disagrees with the F1 behaviour** — PRD.md FR-15 Amendment ("Where the client supports MCP Apps, an upload box ... shall be the fallback") and the US-48 acceptance ("When the client does not support MCP Apps, Claude reports that the file could not be sent") describe the branch this diff removes. README.md was updated to "always offers this step"; the PRD was not, and CR50's PRD trace says F1 needed no amendment.
- **m4: `get_file_text` has an untested branch** — src/bullhorn_mcp/server.py `get_file_text`: the `except AuthenticationError` return has no test (the `BullhornAPIError` 403, 404 and 500 paths do).
- **m5: `file_not_found` lists deleted files without saying so** — src/bullhorn_mcp/server.py `get_file_text`: the success response echoes `isDeleted`, but the `files` list in `file_not_found` returns only `id` and `name`, so a deleted row is offered as a candidate id with nothing to tell it apart.
- **m6: the CV branch of `_upload_next_step` ignores a Candidate hint it was given** — src/bullhorn_mcp/server.py `_upload_next_step`: the non-CV branch names the hinted record (`attach_file(entity='JobOrder', entity_id=51437, ...)`), while the CV branch with `entity="Candidate", entity_id=N` still prints `attach_cv(candidate_id=..., ...)` and `attach_file(entity, entity_id, ...)`.
- **m7: search and query results are walked twice** — src/bullhorn_mcp/server.py `search_entities`, `query_entities`: `_cap_file_descriptions(envelope, file_rows=...)` runs, then `format_response` runs `_cap_file_descriptions` over the same envelope again.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
