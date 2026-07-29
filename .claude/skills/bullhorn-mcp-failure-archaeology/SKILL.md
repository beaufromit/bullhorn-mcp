---
name: bullhorn-mcp-failure-archaeology
description: Load this skill when you want the origin story behind a bug you suspect has happened before in this repo, when planning a change that touches an area with scar tissue (notes, isDeleted, create_job, identity cache, search_emails, pagination envelopes), or when a review cites a known failure pattern and you need its history. For live triage of a current failure, load bullhorn-mcp-debugging-playbook FIRST; come here for the incident chronicle behind a symptom, not to triage the symptom itself. Provides the verified chronological chronicle of every major incident, dead end, revert, and production outage (symptom, root cause, commit/CR evidence, status) plus the 10 recurring meta-patterns distilled from 29 review cycles.
---

# Bullhorn MCP Failure Archaeology

The complete incident history of this repo, verified against git and the CR files on 2026-07-03 (v0.0.46, 648 tests passing, 130 commits). A CR (Change Request) is a numbered `CRx.md` spec/bug-report file in the repo root; every incident below cites its CR file and/or commit hash. All hashes were verified with `git show`.

Purpose: before you code, check whether your bug or design idea has already been tried, broken, or reverted here. History says it probably has.

## Quick-lookup index

| Symptom keywords | Incident |
|---|---|
| "Invalid field 'title'", contact create/update fails | A3, A6, A8, A9 |
| "Invalid field 'title'" on Candidate (not ClientContact) | A18 |
| `department` rejected, owner not resolved, wrong owner name | A4, A5 |
| Duplicate records after errors, retry created dupes | A7 |
| Wrong owner stamped in multi-user HTTP deployment | A12 |
| Tool uncallable under ANY input, validation deadlock | A14 |
| Deleted records appear as duplicates or in results | A16, A20 |
| Write succeeded but tool reports failure, records exist anyway | A17 |
| Notes tools return `[]` or 500, note search returns 0 | A19 |
| `search_emails` 400 "Missing parameter entityId" | A24 |
| "Bad sort: unknown field", date filters silently return 0 | A21 |
| Infinite pagination loop, `next_start` never advances | A26 |
| 400 on `/query` with a quoted string filter | A27 |
| Tests broke after a tag with no code change | A11 |
| Six identical commit messages in a row | A10 |
| HTTP 200 returned for a failed operation | A25 |
| `name` is null, record invisible in Bullhorn UI | A23 |
| Massive token cost from tool descriptions | A29 |
| Placement extension logic, customInt3 | A28 |
| Confidential file in git history | A2 |
| OAuth fails for regional (APAC/EMEA) accounts | A1 |
| Review fix itself introduced a bug | A19 (step 2), A26 |

Format per incident: **Symptom** -> **Root cause** -> **Evidence** -> **Status** (FIXED / REVERTED / ACCEPTED / OPEN DEBT).

## Era 1: Bootstrap (2026-01 to 2026-03)

### A1. Regional OAuth redirects broken
- Symptom: authentication failed for Bullhorn accounts hosted on regional servers.
- Root cause: Bullhorn 307-redirects some accounts to regional auth domains (auth-apac, auth-emea); the code neither followed them nor tracked the regional URL for later token exchanges. A second pass was needed for regional URL capture and token body encoding.
- Evidence: commits 058c365 (2026-01-15) and 6d40090 (2026-03-10). Current code: `src/bullhorn_mcp/auth.py` follows max 5 redirects, only to `bullhornstaffing.com` hosts, and stores `_regional_auth_url`.
- Status: FIXED. Mechanics owned by bullhorn-mcp-auth-and-identity.

### A2. CASE_STUDY.md confidential leak
- Symptom: a client-confidential case study was committed to the repo.
- Root cause: accidental commit (cdca5f8), reverted the same day.
- Evidence: revert c570499, gitignore entry added in 17b6f06 (all 2026-01-15). The content still exists in git history at cdca5f8.
- Status: REVERTED; history exposure OPEN DEBT (no history rewrite was ever performed). Workaround: keep `CASE_STUDY.md` gitignored and local-only. Candidate CR: history rewrite plus force-push, owner decision required.

## Era 2: The ClientContact field-injection saga (CR1 to CR7, Sprints 8-13, 2026-03)

The founding bug cluster. One confusion (Bullhorn's `title` field) generated seven CRs. On ClientContact, `title` is the salutation (Mr/Ms/Dr) and the job title lives in `occupation`.

### A3. CR1: job title mapped to `title`
- Symptom: every `create_contact` call rejected by Bullhorn.
- Root cause: `create_contact` mapped job-title data to `title`, which expects a salutation.
- Evidence: CR1.md; commit ed7adcb (tag v0.0.8).
- Status: FIXED via `FIELD_ALIASES["ClientContact"]["job title"] = "occupation"`.

### A4. CR2: whack-a-mole field injection (`department`)
- Symptom: after CR1, creates failed on `department` next.
- Root cause: a default-field-template pattern injected fields the caller never sent; ClientContact has NO `department` field (the equivalent is `division`).
- Evidence: CR2.md.
- Status: FIXED: write payloads audited against `/meta/{entity}` (Bullhorn's field-inventory endpoint) as source of truth; only caller-provided fields are sent.

### A5. CR3: owner resolution broken twice over
- Symptom: owner set as a raw name string (not a resolved ID); `department` leaking from the CorporateUser lookup into the contact payload; blocked 10 of 21 user stories.
- Root cause: `resolve_owner` queried CorporateUser with `department` in its field list (invalid on some tenants, silently killing resolution) and its query result leaked into the create payload.
- Evidence: CR3.md; commit bb4c7f9 (tag v0.0.10).
- Status: FIXED: `resolve_owner` returns only `{"id": int}`; `department` is banned from CorporateUser queries forever (comment in `src/bullhorn_mcp/identity.py` line 81 enforces it).

### A6. CR4: the docstring-example bug
- Symptom: every agent following the `update_record` docstring example failed.
- Root cause: the example used `{"title": "CTO"}`. Agents learn field names from docstring examples; a wrong example is a wrong API.
- Evidence: CR4.md (lines 5, 17, 24).
- Status: FIXED (docs-only) plus a regression test asserting the docstring does not contain `"title": "CTO"`. Lesson owned in depth by bullhorn-mcp-docs-and-writing.

### A7. CR5: Bullhorn partial persistence creates silent duplicates
- Symptom: `create_contact` returned errors, yet three duplicate contacts (real IDs 170841, 170842, 170843) appeared in the CRM.
- Root cause: Bullhorn can PARTIALLY PERSIST a record and still return an error, with no indication a record was created. LLM callers retry on error, minting duplicates.
- Evidence: CR5.md (IDs quoted at line 11).
- Status: FIXED with pre-create fuzzy dedup guards (refuse at score >= 0.95, confirm 0.50 to 0.95, `force=True` bypass). This behavior is why dedup guards exist on every create path.

### A8. CR6: the 5-layer title-injection hunt
- Symptom: every ClientContact `update_record` returned "Invalid field 'title' at position 42" even for single-field payloads like `{"firstName": "Aleksandr"}`.
- Root cause: `title` was being injected somewhere in a 5-layer path; CR6 mandated tracing all five: (1) label remapping in `resolve_fields`, (2) client body mutation in `client.update`, (3) a stale MCP tool schema causing agents to send `title: null`, (4) `DEFAULT_FIELDS` bleeding into writes, (5) the calling agent itself.
- Evidence: CR6.md (the 5 investigation areas are its "Required Investigation" section).
- Status: FIXED. Established the payload-assertion law: regression tests must capture the RAW HTTP POST body, not method arguments (CR6.md line 34). Testing mechanics owned by bullhorn-mcp-testing-playbook.

### A9. CR7: the strip-and-warn policy decision
- Symptom: agents kept sending bare `title` meaning job title, despite all prior fixes.
- Root cause: the ambiguity is in the callers, not the code; no mapping fixes it without breaking something.
- Decision record (CR7.md): Option A (global title -> occupation alias) REJECTED, it makes the real salutation field permanently inaccessible. Option B (context-dependent mapping) REJECTED as overly complex. Option C CHOSEN: strip `title` from ClientContact write payloads, log a warning, surface it in a `warnings` array; `namePrefix` for salutation, `occupation` for job title; `title` stays in read DEFAULT_FIELDS; NOT stripped on other entities (JobOrder `title` is a real job title).
- Evidence: CR7.md; commit 7e92fa4 (tag v0.0.13).
- Status: FIXED (policy). Later extended to Candidate and to `name` (see A23).

## Era 3: Transport and identity (2026-04)

### A10. "fixing OIDC scopes" x6: the commit-hygiene cautionary tale
- Symptom: six consecutive commits titled exactly "fixing OIDC scopes" in 24 minutes (15:02 to 15:26, 2026-04-08).
- Root cause: live trial-and-error debugging of Entra (Microsoft's identity platform) OIDC auth directly against a deployment, committing each guess.
- Evidence: commits 5186b24, 1a66c0b, 4905eed, ef50089, bb8fb83, c0fe2ed.
- Status: ACCEPTED as history; treat as the anti-example. Rule: debug live-auth problems in a scratch branch or with local experiments, then commit one coherent change with the why captured.

### A11. Sprint 15 post-tag FastMCP regressions
- Symptom: 4 tests broke AFTER tag v0.0.15 with no code change in this repo.
- Root cause: FastMCP 3.x API changes: `_tool_manager._tools` removed (use `asyncio.run(mcp.list_tools())`), `mcp.run()` gained host/port kwargs, `mcp.settings` removed.
- Evidence: commit 60cc9f7 (2026-04-14, Sprint 16) lists each broken test and its fix in the commit body.
- Status: FIXED. Canonical "dependency API drift" incident; the undeclared `fastmcp` dependency in pyproject is related OPEN DEBT owned by bullhorn-mcp-build-and-env.

### A12. CR11: first-writer-wins identity cache (documented-assumption rot)
- Symptom: in the shared HTTP deployment, user B's contacts were created with user A as owner, silently.
- Root cause: CR9 deliberately built a single-slot module-level cache with a written comment: "Acceptable because the server runs as a single-user service; one authenticated user per process." Sprint 15 then added HTTP multi-user transport, invalidating the assumption; CR9/CR10 were implemented AFTER Sprint 15 without revisiting it.
- Evidence: CR11.md (quotes the original comment at its line 23-25); commit 37fde9c (Sprint 18, 2026-04-15).
- Status: FIXED: `_caller_cache: dict` keyed by the Entra `sub` claim (stable per user). Meta-lesson: a documented assumption is a tripwire; when the architecture shifts, grep for written assumptions and re-validate each one.

### A13. CR12: forced re-auth after inactivity
- Symptom: hosted users forced through full Microsoft sign-in after ~1 hour idle.
- Root cause: `offline_access` scope absent, so Entra never issued refresh tokens.
- Evidence: CR12.md; commit 3fd950f (2026-04-28).
- Status: FIXED (one line). Auth details owned by bullhorn-mcp-auth-and-identity.

## Era 4: The create_job dead end (CR13 -> CR14, 2026-04-29)

### A14. CR13's create_job was uncallable under ANY input
- Symptom: nine live payload attempts, zero successful JobOrder creates.
- Root cause: three stacked defects (CR14.md, Problem section):
  1. Invented parameter names (`website_sector_range`, `website_salary_range`, `website_location`, hardcoded `fee`) that are not real Bullhorn fields (real ones: `customText1`, `customText10`, `customText11`, `feeArrangement`).
  2. Validation deadlock: the required-check rejected null placeholders while the known-fields check rejected non-null ones; no input satisfied both gates.
  3. Structured Python parameters bypass label resolution entirely; only dict keys get remapped through metadata.
- The bitter detail: CR13.md itself (line 145) contained the warning that would have prevented it: "do not guess instance-specific Bullhorn API names".
- Evidence: implementation commit 6cd4a04; CR13.md; CR14.md ("nine attempts produced no successful create", line 15); rewrite commit d4716b1 (2026-04-29).
- Status: FIXED by full rewrite in CR14: `create_job(clientCorporation, clientContact, title, fields)` with everything else in a dict; all four broken validators deleted; instance-specific rules moved to env config (`joborder_config.py`). The project's biggest documented dead end. Design lessons: instance business rules live in env config, not code; bad env JSON warns and falls back so the server always starts; caller values win over defaults.
- Same review cycle also produced the first dict-merge precedence bug: `payload.update(extra_fields)` after owner resolution let callers silently overwrite the resolved owner (commit 15a4d8e; meta-pattern 1).

## Era 5: Shortlist and dedup (CR15 to CR17, 2026-05-13)

### A15. CR15: JobSubmission quirks absorbed (feature, not a bug)
- JobSubmission create is `PUT`, requires `dateWebResponse` (Unix epoch milliseconds), `sendingUser` defaults to the service account if omitted, and Bullhorn does NOT prevent duplicate JobSubmissions (caller's job). Rejected design: writing status config back to `.env` at runtime (hosted deploys have read-only filesystems).
- Evidence: CR15.md (Bullhorn behavior section). Per-entity quirks owned by bullhorn-mcp-api-quirks.

### A16. CR16: soft-deleted records as false-positive duplicates
- Symptom: dedup tools flagged soft-deleted records as duplicates, blocking legitimate creates.
- Root cause: inconsistent `isDeleted` filtering across call sites; Bullhorn's Lucene index (the full-text query syntax behind `/search`) INCLUDES deleted records by default.
- Evidence: CR16.md; commit 5b269de.
- Status: FIXED with a blanket `exclude_deleted=True` default on client `search()`/`query()`. But its assumption that all entities have `isDeleted` was itself a latent bug: see A20.

### A17. CR17: success-looks-like-failure (fields=*)
- Symptom: `shortlist_candidates` reported an error for every candidate while the JobSubmissions WERE created (real IDs 94607 to 94612 written; tool said created: 0). The agent then retried and mislabeled its own fresh writes as pre-existing duplicates.
- Root cause: `create()` never returns the POST response; it does a post-write `get()`. JobSubmission was absent from `DEFAULT_FIELDS`, so the get fell back to `fields=*`, and this tenant rejects `fields=*` on JobSubmission with 400 "You are not authorized to request all fields." Successful write plus failed read-back equals apparent failure.
- Evidence: CR17.md (IDs at line 31, error at line 17); commit 5b269de.
- Status: FIXED by adding JobSubmission to `DEFAULT_FIELDS`. Scope decision: only the observed entity was fixed (touch only what you are asked to touch). Any entity still missing from `DEFAULT_FIELDS` on a `fields=*`-restricted tenant can reproduce this: OPEN DEBT class, check `DEFAULT_FIELDS` when adding write support for a new entity.

### A18. CR18 origin: Candidate has no `title` field at all
- Symptom: a live claude.ai session repeatedly sent `title` on Candidate queries and field lists; 400 "Invalid field 'title'".
- Root cause: unlike ClientContact (where `title` exists as salutation), Candidate has NO `title` field whatsoever (job title = `occupation`); static docstrings gave the LLM no field inventory to learn from.
- Rejected alternatives (recorded in CR18.md): server-side field substitution (hides errors), pre-send validation (moves the error away from its cause), static description edits (does not scale to custom fields).
- Evidence: CR18.md.
- Status: FIXED by startup enrichment: fetching `/meta/{entity}` at server start and appending live field references to tool descriptions. CR18 flagged its own risk: "Monitor token cost after rollout" (CR18.md line 243). That risk detonated in A29.

## Era 6: The notes saga (CR21 -> CR22 -> CR23 -> CR25, four breakages of one feature)

The single most reworked feature. Six tags (v0.0.29 to v0.0.34) were minted on 2026-05-15 alone, two of them (v0.0.33, v0.0.34) on the same commit 710e756 (a tagging slip, not two releases).

1. **CR21 (7b06fe8, tag v0.0.30):** `get_notes_for_entity` built on a NoteEntity two-step query. Review C1 (f77e36b) added a `targetEntityType` filter to prevent cross-entity ID collisions (Bullhorn entity IDs are per-type sequences; Candidate 123 and JobOrder 123 can both exist).
2. **CR22 (10e6d8b, tag v0.0.32):** that review fix used a NONEXISTENT field; the real NoteEntity column is `targetEntityName`. The tool had been broken for every entity by its own review fix. Also fixed: `clientCorporation` is valid on `/entity/Note/<ids>` but invalid on `/search/Note` (constants split), and a bare `*` query yields "Bad Query: {0}". A review-introduced bug whose fix was STILL insufficient:
3. **CR23 (710e756, tags v0.0.33 and v0.0.34):** even with the right column, the tool returned `[]` for candidate 169020 (Barry Delaney) with 6 confirmed notes. Bullhorn stores `targetEntityName='User'` for Candidate rows (Candidate is internally a subtype of User) and MIXES 'JobOrder'/'User' rows for the same job, so ANY targetEntityName filter silently drops notes. A naive Candidate -> 'User' mapping was considered and rejected as incomplete (Postman evidence in CR23.md line 21). Second dead end in the same CR: `search_notes` entity_filter depended on `/search/Note`, which returns `total: 0` for every query on this account. **Mechanism superseded by CR37 (2026-07-28):** the `fieldsFromIndex: false` reading cited here was falsified — working searches return `false` too (`/search/JobOrder`: `false` with `total: 50271`), so it never evidenced anything. The observed 0-result behaviour of `/search/Note` is real and unchanged; only the explanation was wrong. CR37 also found that note fields ARE reachable as nested fields on the parent entity's index (`notes.action`), which CR23 never tried. Resolution: abandon NoteEntity entirely; use `GET /entity/{Entity}/{id}/notes` (the association endpoint); entity-scoped search filters locally in Python; `get_many()` (added in CR21) deleted, `get_association()` added. The feature was rewritten twice in one day.
4. **CR25 fix 3 (cfc9090, tag v0.0.35):** notes broke a THIRD time in production: Bullhorn STARTED rejecting `clientCorporation(id,name)` on the association endpoint too (500 on every `get_notes_for_entity` call), i.e. the server-side API surface shifted underneath a previously working field. Dropped from `_NOTE_DEFAULT_FIELDS`.
- Status: FIXED (current design uses the association endpoint). Standing lessons: NoteEntity's `targetEntityName` is untrustworthy; Lucene indexes are per-tenant configuration, not API guarantees; Bullhorn's API drifts server-side, so a working field can start failing with zero code change. Endpoint reference owned by bullhorn-mcp-api-quirks.

## Era 7: The isDeleted arc (four design iterations)

### A20. From blanket clause to metadata gate
1. **CR16 (5b269de):** blanket auto-append of the isDeleted clause to every search/query.
2. **CR24:** UserMessage has no `isDeleted`; the clause 400s. Patch: per-call `exclude_deleted=False`.
3. **CR25 (cfc9090):** ClientCorporation also lacks it (it uses `status` instead); `query_entities("ClientCorporation", ...)` 400'd. Patch: static denylist `_ENTITIES_WITHOUT_ISDELETED = {ClientCorporation, UserMessage}` replacing the per-call opt-out.
4. **CR33 (c9df0ac, tag v0.0.45):** Placement and PlacementChangeRequest also lack it; a denylist does not scale. Final design: metadata-driven `_entity_has_isdeleted()` gate (denylist fast path, then a `/meta` scan, cached per process; on `/meta` error fall back to appending the clause, the safe default).
- Evidence: CR16.md, CR24.md, CR25.md, CR33.md.
- Status: FIXED (fourth iteration is current). Meta-lesson: a "universal" Bullhorn field is a hypothesis; the schema varies per entity, and hardcoded lists of exceptions rot. Test-side gotcha (the `/meta` fallback masking clause assertions) owned by bullhorn-mcp-testing-playbook.

## Era 8: Email search and stress-test fallout (2026-05 to 2026-06)

### A21. CR24: unindexed sort field on UserMessage
- Symptom: `search_emails` failed with "Bad sort: unknown field smtpSendDate".
- Root cause: `smtpSendDate` (client timestamp) is not indexed for sorting, `smtpReceiveDate` (server timestamp) is. **Framing superseded by CR37:** CR24 attributed this to `/search/UserMessage` returning `fieldsFromIndex: false`, which carries no such information (working searches return it too). The conclusion is unaffected — the unsortable field was proven by an actual "Bad sort: unknown field smtpSendDate" error, not by that key. Do not revisit the sort choice on the strength of the falsified signal.
- Evidence: CR24.md.
- Status: FIXED (sort switched). OPEN DEBT, explicitly deferred in CR24.md line 27: `since`/`until` Lucene date-range filters silently return 0 results on unindexed fields. Workaround: treat empty date-filtered email results as suspect; verify with an unfiltered query. Candidate CR: warn or fall back when a date-range clause is the difference between 0 results and some — note that the once-suggested `fieldsFromIndex` detector is NOT viable, per CR37; use a match-all probe or a with/without-clause comparison instead.

### A22. CR25: the Pinergy stress test (four production bugs in one live session)
- A stress test against live Job #51227 ("Interim CIO", client Pinergy) surfaced, in one session: (1) no ID-based company lookup (`search_entities("ClientCorporation", "id:9493")` returns `[]` because Lucene cannot do ID lookups; `get_company` tool added); (2) the ClientCorporation isDeleted 400 (A20 step 3); (3) the notes 500 (A19 step 4); (4) data-quality gaps (required-fields default shipped in `.env.example`, `add_note` action validated against the live picklist (a picklist is Bullhorn's per-tenant enumerated value list for a field), `BULLHORN_MCP_SOURCE` stamping added).
- Evidence: CR25.md; commit cfc9090 (tag v0.0.35).
- Status: FIXED. Meta-lesson: named live stress tests find bug clusters that 500+ mocked tests cannot; see bullhorn-mcp-live-api-method.

### A23. CR26: the `name` reversal (a guard built on a false assumption caused the bug)
- Symptom: API-created candidates and contacts had `name=null`: invisible in Bullhorn list views, unopenable in the UI.
- Root cause: Bullhorn REST does NOT auto-compute `name` from firstName+lastName; only the UI does (three support-forum threads cited in CR26.md lines 17-19). This directly reversed CR19's belief that `name` was auto-computed. Worse: `_strip_contact_title` had been actively REMOVING caller-supplied names on that false assumption, guaranteeing null names. IMPLEMENTATION-PLAN.md had recorded the correct recommendation earlier; the code never acted on it.
- Evidence: CR26.md; feature commit 06133df (2026-05-20).
- Status: FIXED: `name` is MCP-owned (strip caller value, always recompute from firstName+lastName, fetch the record for partial-name updates). Historical broken records deliberately left unbackfilled (ACCEPTED). Follow-up: the review found `attach_cv` was missed by the fix (commit 76c9889; meta-pattern 6).

### A24. The entityId 12-day production outage
- Symptom: every `search_emails` call failed with 400 "Missing parameter entityId" from 2026-05-22 to 2026-06-03.
- Root cause: commit db78771 removed `extra_params={"entityId": person_id}` on a semantic argument (the implicit AND with the Lucene sender/recipient clause can drop emails synced under a different primary entity). The argument was plausible; the removal was fatal because Bullhorn REQUIRES `entityId` on `GET /search/UserMessage`. The review cycle passed it clean ("no CRITICAL, no MODERATE", recorded in IMPLEMENTATION-PLAN.md, tag v0.0.38): reviews cannot catch live-API contract violations (meta-pattern 10).
- Evidence: removal db78771 (2026-05-22); restore c5cdfaa (2026-06-03), confirmed live.
- Status: FIXED (parameter restored). Split the outcome in two: (1) `entityId` being mandatory is an accepted API constraint, permanent, never remove it; (2) the residual limitation that emails synced under a different primary entity can be missed is OPEN DEBT, not accepted design. The workaround is to also query with the other party's `entityId`, and a multi-entity-sweep CR is the suggested fix (debt entry owned by bullhorn-mcp-architecture-contract, workaround detail by bullhorn-mcp-api-quirks). Do not "fix" this again by removing the parameter.

### A25. /upload-cv returned HTTP 200 for failures
- Symptom: the `/upload-cv` HTTP route returned 200 even when the underlying tool returned an error JSON (e.g. `identity_resolution_failed`).
- Root cause: the route did not parse the tool result before choosing a status code.
- Evidence: review C1, commit f684bfc (2026-05-22).
- Status: FIXED: parse the result, return 500 when an `"error"` key is present.

### A26. CR28: the pagination triple-cycle (a review fix flagged by the next review)
- Cycle 1 (feature b71ef66, 2026-05-29): pagination envelopes added to 9 tools. Review M1: the `get_notes_for_entity` envelope was inconsistent when deleted notes were filtered client-side.
- Cycle 2 (fix a579c8e): the prescribed fix used filtered counts for offset arithmetic.
- Cycle 3 (C1, fixed in 1289e16): the next review proved the M1 fix creates an INFINITE LOOP: a page where every note is soft-deleted gives `next_start == start` with `has_more=True`, so an LLM following `next_start` re-requests the same page forever. The review file states it plainly: "The M1 fix restored the `start + count == next_start` invariant but introduced this regression." Reverted to raw-count offset arithmetic: `next_start` advances by the RAW page size while `count` reflects filtered rows.
- Evidence: commits b71ef66, a579c8e, 1289e16; `git show 1289e16:reviews/latest.md` and `git show 16e84d1:reviews/latest.md`.
- Status: FIXED. Residual OPEN DEBT (minor m1, logged unfixed by policy in the v0.0.40 review): `pagination.total` on `get_notes_for_entity` counts soft-deleted notes, so it overcounts live notes. Workaround: clients must paginate by `has_more`/`next_start` and never treat `total` as a live count or compute `start + count`. Candidate CR: docstring warning on `total`. The only case in repo history where one review's fix was invalidated by the next review.

### A27. Double quotes in /query WHERE clauses
- Symptom: the `get_job_submissions` status filter 400'd.
- Root cause: Bullhorn `/query` (SQL-style WHERE syntax) requires SINGLE-quoted string literals; double quotes parse as a field name.
- Evidence: commit 01cc962 (2026-06-02).
- Status: FIXED. Syntax rules owned by bullhorn-mcp-query-and-entity-model.

## Era 9: Placements and token cost (2026-06)

### A28. CR33: extension model, the customInt3 dead end, and two review fixes
- Investigation dead end: `customInt3` on Placement was investigated as the contract-extension signal; it is null everywhere in this tenant and is NOT the signal. It was dropped from default fields, with a regression test pinning the exclusion (`tests/test_server.py::test_new_default_fields_exclude_custom_int3`, line ~924 as of 2026-07-03). Note: CR33.md documents the confirmed model, not the failed hypothesis; the customInt3 record lives in the test and project memory.
- Confirmed model (CR33.md): an extension is NEVER a new Placement row; it is a `PlacementChangeRequest` with `requestType='Contract Extension'`; `Placement.dateBegin` stays pinned to the original start; the extension date is `requestCustomDate1`.
- Review fixes (commit 9da82c4): M1, a duplicated Placement default-fields string in server.py (drift risk; now references `DEFAULT_FIELDS["Placement"]`); M2, the `status` param interpolated into SQL without a single-quote guard (injection).
- Evidence: CR33.md; commits c9df0ac, 9da82c4, aad6046 (tag v0.0.45).
- Status: FIXED; dead end documented. Related OPEN DEBT: `get_job_submissions`, `resolve_owner`, and `identity.resolve_caller` still interpolate strings into WHERE clauses unescaped (only `list_placements` has the quote guard). Workaround: never pass untrusted strings to those paths. Candidate CR: extend the CR33 M2 quote guard to all interpolated params. Architectural framing owned by bullhorn-mcp-architecture-contract.

### A29. CR34: CR18's flagged risk materializes (token cost)
- Symptom: ~111k tokens of tool descriptions (~118k with parameter schemas) loaded into EVERY conversation with the connector enabled; the 4 generic tools alone were ~51.6k.
- Root cause: CR18's enrichment (A18) appended the FULL field inventory of every entity to every mapped tool. CR18 itself had flagged "Monitor token cost after rollout"; nobody measured until CR34.
- Evidence: CR34.md (measurements at lines 11-14, 103-107); commit 88cc709 (tag v0.0.46).
- Status: FIXED: curated field selection (capped at 40 fields) plus a full/compact split (generic discovery tools get name-only lists and a `get_entity_fields` pointer); ~80% reduction (~111k -> ~15k description tokens). Meta-lesson: when a CR writes "monitor X", schedule the measurement; a flagged-but-unmeasured risk is a scheduled incident. Measurement method owned by bullhorn-mcp-run-and-operate.

## The 10 recurring meta-patterns (from 29 review cycles)

Each of these recurred at least once after being "fixed". If your change touches one, assume the reviewer will check it (a recurrence of a known pattern is auto-CRITICAL in the review protocol).

| # | Pattern | What goes wrong | Verified evidence |
|---|---|---|---|
| 1 | Dict-merge precedence | `payload.update(X)` after a resolved/validated value lets callers silently override it | Sprint 21 owner override (15a4d8e); Sprint 23 status override (IMPLEMENTATION-PLAN.md ~line 2174) |
| 2 | Guards before label resolution | A guard checked before `resolve_fields` is bypassable via a display label | Sprint 6 origin (`.claude/commands/review.md` pattern 6); recurred as CR19 M3 (61af032) |
| 3 | Untested write paths | New write logic ships with no payload assertion; bugs invisible until live | CR19 C1 (61af032), CR25 C1 (d8c5903), e5b8a52 M1 |
| 4 | Vacuous or masking tests | `or True` assertions, no-op tests, mocks that succeed regardless of input, testing one leg of a two-leg flow | e5b8a52 (C1 no-op label test, M2 or-True assertion); IMPLEMENTATION-PLAN.md ~line 2211 (one-leg test) |
| 5 | Pagination arithmetic + client-side filtering | Filtered counts corrupt offset math; worst case an LLM infinite loop | A26: three consecutive review cycles on one envelope |
| 6 | Incomplete fix scope | A fix applied to N call sites misses call site N+1 | `attach_cv` missed the title strip (CR19 M2, 61af032) AND the name recompute (CR26 M1, 76c9889) in separate CRs |
| 7 | Duplicated constants drift | Copied field strings silently diverge from their source | CR33 M1 (9da82c4); `_NOTE_DEFAULT_FIELDS`/`_NOTE_SEARCH_DEFAULT_FIELDS` byte-identical duplicates remain OPEN DEBT |
| 8 | Input-validation asymmetry | One tool validates, its sibling or batch variant does not; new interpolated params miss the quote guard | CR33 M2 (9da82c4); unescaped WHERE interpolation in 3 other paths is OPEN DEBT (see A28) |
| 9 | Doc/plan drift | Specs, statuses, and docstrings lag the code (e.g. CR34.md still says "Status: DRAFT" though shipped, as of 2026-07-03) | Drift catalog and post-tag doc-sync owned by bullhorn-mcp-docs-and-writing |
| 10 | The review blind spot: live-API assumptions | Reviews catch logic and test defects (6 C1 fix commits ever: e5b8a52, 61af032, f77e36b, d8c5903, f684bfc, 1289e16) but passed the entityId removal (A24), blessed the NoteEntity design (A19), and cannot see server-side Bullhorn drift | Mitigation: verify every Bullhorn behavioral assumption read-only against the live API BEFORE coding; see bullhorn-mcp-live-api-method |

## When NOT to use this skill

- Triage of a CURRENT symptom you have not matched to history yet: start with bullhorn-mcp-debugging-playbook (its routing table links back here).
- The per-entity / per-endpoint Bullhorn quirk reference (which fields exist, which endpoints behave how): bullhorn-mcp-api-quirks.
- Lucene vs SQL syntax and the entity model: bullhorn-mcp-query-and-entity-model.
- How the review loop, severities, and the 8 reviewer-baked failure patterns work: bullhorn-mcp-review-protocol.
- The CR lifecycle and tagging discipline these incidents flowed through: bullhorn-mcp-change-control.
- Auth flow mechanics behind A1/A10/A12/A13: bullhorn-mcp-auth-and-identity.
- Current invariants that these incidents produced (the "what to obey now" view): bullhorn-mcp-architecture-contract.
- Running live read-only verification experiments: bullhorn-mcp-live-api-method.

## Provenance and maintenance

All claims verified 2026-07-03 against the repo at v0.0.46 (648 tests). Re-verification commands (run from repo root):

- Commit hashes and dates: `git show --no-patch --format='%h %ad %s' --date=short 058c365 c570499 cdca5f8 ed7adcb bb4c7f9 5186b24 60cc9f7 37fde9c 6cd4a04 d4716b1 5b269de 7b06fe8 f77e36b 10e6d8b 710e756 cfc9090 06133df 76c9889 db78771 c5cdfaa b71ef66 a579c8e 1289e16 f684bfc 01cc962 c9df0ac 9da82c4 88cc709`
- Tag-to-commit mapping (incl. the v0.0.33/v0.0.34 duplicate on 710e756): `for t in v0.0.8 v0.0.10 v0.0.13 v0.0.30 v0.0.32 v0.0.33 v0.0.34 v0.0.35 v0.0.38 v0.0.45 v0.0.46; do echo "$t $(git rev-list -n1 $t | cut -c1-7)"; done`
- CR decision records: `grep -n 'Option A' CR7.md; grep -n 'nine attempts' CR14.md; grep -n '94607' CR17.md; grep -n "targetEntityName='User'" CR23.md; grep -n 'auto-compute' CR26.md; grep -n 'Monitor token cost' CR18.md`
- The six OIDC commits: `git log --oneline --grep='fixing OIDC scopes'`
- The six C1 fix commits: `git log --oneline --all | grep -i 'review: fix C'`
- CR28 triple-cycle and residual m1: `git log --oneline b71ef66~1..1289e16` and `git show 16e84d1:reviews/latest.md | grep -n m1`
- customInt3 exclusion test still present: `grep -n customInt3 tests/test_server.py`
- Open-debt WHERE interpolation still unguarded: `grep -n "WHERE\|where=" src/bullhorn_mcp/server.py src/bullhorn_mcp/client.py src/bullhorn_mcp/identity.py | grep -i "status\|owner\|email"`
- Duplicate note constants still duplicated: `grep -n '_NOTE_DEFAULT_FIELDS\|_NOTE_SEARCH_DEFAULT_FIELDS' src/bullhorn_mcp/server.py`
- Test count / suite health: `.venv/bin/pytest -q | tail -1`
- CR34.md status label (drift check): `grep -n 'Status' CR34.md`
