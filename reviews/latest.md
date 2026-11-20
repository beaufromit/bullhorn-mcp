# Review: Sprint 44 build (CR45 generic file upload, renamed upload tools, new attach_file, CV tools refuse non-CV files, carried fixes F1 to F10)

**Commit:** d91143e
**Date:** 2026-11-17
**Files changed:** 19

## CRITICAL

Issues that must be fixed before pushing. Correctness bugs, data integrity risks,
security issues, or violations of known failure patterns listed above.

- **C1: F10 does nothing when the server is started with `python -m bullhorn_mcp.server`** — src/bullhorn_mcp/server.py:49 (`_logger = logging.getLogger(__name__)`) and `_configure_logging()` (server.py:5053-5071)
  `_configure_logging()` sets level INFO and a stderr handler on the logger named `bullhorn_mcp`. All five INFO lines F10 is meant to release (resource read, upload rejected, upload received, two startup lines) are emitted by server.py's own `_logger`, which is named from `__name__`. Under `python -m bullhorn_mcp.server` that name is `__main__`, which is not a child of `bullhorn_mcp`, so it stays at the root default (WARNING) and every INFO line is still dropped. Verified on this commit with `MCP_TRANSPORT=stdio`: `python -m bullhorn_mcp.server` prints 0 "Starting Bullhorn MCP server" lines; the `bullhorn-mcp` console script prints 1. `-m` is the launch command given in CLAUDE.md, in README.md (lines 192, 223, and every client config) and for HTTP mode. The systemd unit is not in the repo, so which form production uses could not be checked; if it uses `-m`, T44.8 step 5.1 (journal shows "MCP App resource read") fails exactly as it did before this sprint. `test_resource_read_line_reaches_handler` cannot detect this: it imports the module as `bullhorn_mcp.server` and asserts `INFO bullhorn_mcp.server`, so it only proves the import path. That is the same defect F10 was raised for (a passing test while nothing reaches the journal). The new README line "The `bullhorn_mcp` logger writes INFO to stderr, so lines such as `MCP App resource read: ui://...` reach the journal" is untrue for the README's own launch command. New class of issue (not one of the 8 known patterns): a planned fix that does not work in the documented run mode, with a test that only covers the other mode.

## MODERATE

Issues worth fixing but not blocking. Design problems, missing edge cases,
inconsistencies with existing patterns, scope creep.

- **M1: F3 changes match scores, not only the reason text, and nothing pins or records it** — src/bullhorn_mcp/duplicate_retrieval.py `_count_title_employers`, src/bullhorn_mcp/duplicates.py `_score_employers.add`
  CR45 lists F3 as a missing clause in the reason ("N candidates list this employer") and says of the carried fixes "None changes what is written to Bullhorn. Each needs a test." The new count is written into `context.employer_counts`, which `_score_employers` also feeds to `_count_u`, so a title-found employer is now scored with `count / n` instead of `default_u`. On the sprint's own fixture (`cv_parse_sample.json`, count 7) the employer entry moves from 8.41 to 10.24 points and the pair total from 55.5 to 57.34. A commonly listed employer moves the other way. These points decide the band that stops `create_candidate` and `create_candidate_from_cv`. The three new tests assert only the reason string; no test asserts the points, and the build notes describe the change as counts and "a little latency" only.

- **M2: The `max_employers` cap in `_count_title_employers` is not tested** — tests/test_duplicate_retrieval.py `test_title_employer_count_adds_no_searches_beyond_max_employers`
  The fixture profile has no employers of its own and the pool has one, so exactly one employer search can ever run and `1 <= n <= max_employers` passes whatever the `room` arithmetic does. The cases the cap exists for (a profile that already used some or all of its `max_employers` searches, and more title-found keys than room) are not exercised. The plan (T44.11) asked for "a guard that the search count is unchanged"; the count is not unchanged (new sequential searches run after the pool fetch) and the test's name claims a cap it does not check.

- **M3: The acceptance script expects `request_file_upload` to echo the hint, and it does not** — COWORK_TEST_v0.0.59.md steps 1.1 and 4.2; src/bullhorn_mcp/server.py `request_file_upload` (response at 3095-3111)
  Step 1.1 says "The response echoes `entity` and `entity_id`" and step 4.2 says "Confirm the hint from 4.1 was echoed by `request_file_upload`". The tool's response has `upload_id`, `upload_url`, `expires_at`, `expires_in_seconds`, `max_bytes` and `next_steps` only. The hint is echoed by `get_file_upload` (CR45 R2). As written, steps 1.1 and 4.2 fail on a correct deploy, or the tester marks them passed without the evidence they ask for.

- **M4: `attach_file` decides "not found" by looking for "404" anywhere in the error text** — src/bullhorn_mcp/server.py `attach_file` (`if "404" in str(e)`)
  `BullhornAPIError` text is `API request failed: {status} - {response.text}`, so the check also matches the response body. A 400, 403 or 500 whose body contains the characters "404" (an id such as 140455, a timestamp, a request id) is reported as `record_not_found` ("was not found (or is deleted)") instead of the `ERROR:` string the build notes say non-404 errors get. Nothing is written in that case, but the consultant is told a live record does not exist. The build notes list this as "open, minor, not fixed"; the only test for the non-404 branch uses a body ("server error") that cannot contain "404". No other error-handling in this diff matches on substrings of the body.

## MINOR

Style, naming, documentation nits. Logged only.

- **m1: Build notes contradict the commit** — IMPLEMENTATION-PLAN.md Sprint 44 build notes say "Open for the owner: PRD.md FR-15 `attach_cv` bullet ... Not changed, because it is an FR; needs the owner's OK", but this commit rewrites that bullet (PRD.md line 199). The notes also say "no test for a non-404 record-read error in attach_file" two lines above "Added a non-404 record-read error case".
- **m2: Plan header still says PLANNED** — IMPLEMENTATION-PLAN.md line 5 ends "Sprint 44 ... is PLANNED, target v0.0.59" while the status table and the sprint heading say BUILT. The heading and build notes date the build 2026-11-13; the commit is dated 2026-11-17.
- **m3: F4 dedupe key is the exact normalised pair** — duplicates.py `_score_education`: `pair_key = ("school", sx, sy)`, while the rows were matched with the fuzzy `_employers_match`. Two rows for one school spelled two ways on either side give two keys, so the education reason is still repeated in that case. No test covers differing spellings.
- **m4: F4 merged entry keeps the first reason only** — a "graduating within a year" pair and a plain same-school pair for the same school merge under whichever sorted first, so the one reason shown can carry points from a pair it does not describe.
- **m5: `description` is passed through unstripped** — `attach_file` strips `type` and treats blank as none, but sends `description=""` or whitespace as given. CR45 Live evidence 5 says Bullhorn fills the description from the file's text only when the parameter is absent; the behaviour for an empty value is not recorded.
- **m6: `_CV_FILE_EXTERNAL_ID` now labels non-CV files** — `attach_file` reuses the CV-named constant for every entity and file type.
- **m7: `test_upload_expired` sets `rec.status = "expired"` on a private store attribute** — it does not exercise the clock-driven expiry path (already listed as open in the build notes).
- **m8: Entity names are matched exactly** — `request_file_upload` and `attach_file` refuse `candidate` or `joborder` as `unsupported_entity` with a message listing the six names; the `type` label is matched ignoring case, the entity is not. Not stated in either tool description.
- **m9: `get_file_types` holds `_file_type_lock` across the HTTP call** — the first labelled attaches on a cold client queue behind one `/settings` read, including its 401 refresh and retry.
- **m10: attach_file's entity_files warning log includes the Bullhorn error body** — `_logger.warning("attach_file: could not read existing files of %s %s: %s", entity, entity_id, e)`; the comment says "no filename or personal data in the log", which holds only if Bullhorn's error body carries none. The test asserts only that the upload's own filename is absent.
- **m11: Placement record check depends on `/meta` being up** — `attach_file` asks for `isDeleted` when `client._entity_has_isdeleted(entity)` is true. `Placement` is not in `_ENTITIES_WITHOUT_ISDELETED`, and that helper returns True when the `/meta` read fails, so `attach_file` then requests `fields=id,isDeleted` on Placement. Checked live (read-only, 2026-11-17): Bullhorn answers 400 "Invalid field 'isDeleted'", so the call returns an `ERROR:` string and nothing is attached. No test covers this path.
- **m12: Not reviewed** — the `tests/test_client.py` part of the diff (+185 lines: `description` param, `get_file_types`, `get_entity_files`, content types) could not be read in this review session (the read was blocked by a local permission rule). Its tests pass in the full run (1,526 passed), but their assertions were not inspected, so the payload-assertion check for `client.attach_file(description=...)` rests on `tests/test_server_cr45.py::test_write_payload_exact` alone.

## Verdict

1 CRITICAL issue(s) must be resolved before pushing. 4 MODERATE issues are also open.
