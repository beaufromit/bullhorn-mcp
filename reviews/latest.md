# Review: CR37 — expose note-field filtering via a `note_action` parameter, warn on the empty Lucene note route, and fix three enrichment field-selection bugs

**Commit:** d91e629
**Date:** 2026-07-29
**Files changed:** 10

Scope note: `git diff HEAD~1` is non-empty and `HEAD~1` is `8b5f377`, so the reviewed
diff covers the whole of CR37 in one commit. Suite: 707 passed.

## CRITICAL

None.

Checked against all 8 known failure patterns, with the following evidence:

- **Pattern 1 (title vs occupation):** no added line in the diff contains "title".
  The new `CorporateUser` DEFAULT_FIELDS entry correctly uses `occupation`, not `title`.
- **Patterns 2 and 3 (field injection / DEFAULT_FIELDS in write paths):** no write
  payload is touched. `add_note`'s POST body (client.py:487-492) is unchanged. The new
  `DEFAULT_FIELDS` entries reach a write path only through the post-write *read* at
  client.py:496, which is a read-back, not payload injection. See M1.
- **Patterns 4 and 5 (owner resolution leakage / CorporateUser query fields):**
  `resolve_owner` (client.py:515-519) and `identity.py:78` both pass an explicit
  `fields="id,firstName,lastName,email"`, so the new `CorporateUser` DEFAULT_FIELDS
  entry cannot reach either query. Verified by inspection of both call sites.
- **Patterns 6, 7, 8:** `update_record`'s guard ordering, `_process_single_contact`,
  and `resolve_fields()` alias precedence are untouched by this diff.

Live read-only verification of the assumptions this diff depends on (corp `5v598g`,
2026-07-29), because a clean diff review is not evidence that live-API assumptions hold:

| Assumption | Result |
|---|---|
| `get('Note', 2650512)` with the new field list | HTTP 200, all 9 fields returned |
| Each new Note sub-select bisected individually | all 5 OK; `candidates`/`clientContacts` populate correctly per note type |
| `get('CorporateUser', 172080)` with the new field list | HTTP 200, all 9 fields returned |
| `notes.action:"BD Call"` canary | ClientContact 1974, Candidate 221, JobOrder 34 (all > 0) |
| `note_search_returns_results()` | `False`, matching the CR's premise |
| `get_meta` with `meta=full` | `required` key present; 1/27 Note fields required; `action` returns 25 options |

## MODERATE

- **M1: `DEFAULT_FIELDS["Note"]` is now load-bearing for the `add_note` write path, and nothing pins it** — src/bullhorn_mcp/client.py:42-46, consumed at client.py:496

  `add_note()` ends with `record = self.get("Note", note_id)`, which resolves
  `fields` from `DEFAULT_FIELDS.get("Note", "*")`. Before this diff there was no
  `Note` key, so that call sent `fields=*` — and this tenant **rejects it**:

  ```
  GET /entity/Note/2500755?fields=*
  → 400 {"errorMessage":"You are not authorized to request all fields.",
         "errorMessageKey":"errors.allFieldsNotAllowed"}
  ```

  So `add_note` was raising `BullhornAPIError` *after* successfully writing the
  note, surfacing `ERROR: API request failed: 400 …` for a write that had already
  landed — the "write reported failure but the record exists" mode this repo has
  hit before. This diff incidentally fixes that, and the fix is entirely
  load-bearing on the new `DEFAULT_FIELDS` entry.

  No test covers the coupling. The existing `add_note` tests (tests/test_client.py:507-630)
  mock `/entity/Note/{id}` with respx, which does not match on query parameters, so
  they pass identically with `fields=*` or with the curated list. Consequences: (a) a
  future edit that removes or trims the `Note` entry — plausible, since the constant
  reads as a read-only concern and the CR itself framed it as an enrichment change —
  silently re-breaks `add_note` in production with green tests; (b) the tool's returned
  `data` narrowed from every Note field to 9, an unasserted contract change on a write
  tool's response. CR37's rollback section anticipated the `get()` behaviour change but
  did not identify `add_note` as the caller, and no acceptance criterion covers it.

- **M2: the Change 2 probe is wired into `search_notes` only, so `search_entities(entity="Note")` still returns the silent empty envelope** — src/bullhorn_mcp/server.py:3400-3406

  The warning fires only inside `search_notes`' Lucene branch. `search_entities(entity="Note", query=…)`
  reaches the same `/search/Note` route through `search_with_meta` and returns
  `{"data": [], "pagination": {"total": 0, …}}` with no `warnings` key — byte-identical
  for a phrase present in thousands of notes and for gibberish. That is precisely the
  ambiguity CR37 Change 2 describes as "an unusable route being rendered as a factual
  answer about your data", and the same diff's `search_entities` docstring now
  documents `entity="Note"` behaviour to the agent (server.py:1171-1174), making that
  route more likely to be tried, not less. CR37 scoped Change 2 to `search_notes`, so
  this is a design gap rather than a spec violation, but the change the CR calls its
  highest-value reliability fix is absent from a reachable sibling path.

- **M3: the entire Part 6 deliverable, including the live canary that is Change 1's only stated risk mitigation, is untracked** — `.claude/skills/` (git status: `?? .claude/skills/`)

  The work exists on disk and is correct as far as it can be checked: no file under
  `.claude/skills/` still references the ATS UI option, and
  `bullhorn-mcp-live-api-method/scripts/smoke_read.py` carries both halves of the
  two-way canary (the match-all probe at line 111 and the nested `notes.action`
  assertion at lines 127-140). But the whole directory is untracked, so none of it is
  in this commit, none of it is versioned, and none of it is reviewable from the diff.
  CR37 names the canary as the sole mitigation for its one stated risk — that the dot
  notation is undocumented by Bullhorn — and an untracked file does not survive a clean
  checkout by whoever inherits that risk. Acceptance criterion 11 explicitly scopes
  `.claude/skills/`, so Part 6 is not landed. Separately, IMPLEMENTATION-PLAN.md has no
  Sprint 36 section, so the 648 → 707 test-count change is unrecorded.

## MINOR

- **m1: `note_action=""` and `note_action="   "` behave differently** — the `if note_action:`
  guard in all three tools (server.py:404, 481, 557) makes the empty string a silent
  no-op, while a whitespace-only value reaches `_note_action_clause` and returns
  `invalid_note_action`. The empty-value branch at server.py:311-315 is therefore
  unreachable from any tool.

- **m2: a trailing backslash survives the quote-character check** — `_note_action_clause`
  (server.py:316-324) rejects `"` and `'` but not `\`, so on the picklist-unavailable
  path `note_action='BD Call\'` renders `notes.action:"BD Call\"`. Verified live: this
  returns 400 `errors.badSearch`, not the silent match-everything behaviour CR37 warns
  about for malformed clauses, so the failure is loud. Baseline check on the same
  tenant: `notes.action:"BD Call"` → 1974 against an unfiltered 54284, so no broadening.

- **m3: acceptance criterion 10 (token-cost delta) is not recorded anywhere in the
  commit.** Measured for this review by running both the old and new selection paths
  over live `/meta` for all 10 `SUPPORTED_ENTITIES`: total appended enrichment payload
  48,695 → 56,175 chars, **+7,480 chars (~+1,870 tokens, +15.4%)**. The increase is
  dominated by `[required]` markers, which now render for the first time (0 → 59
  occurrences, Bug A), and by the previously empty `Note` (15 → 755 chars) and compact
  `CorporateUser` (24 → 298) sections. The tightened custom-field filter pulls the other
  way (Placement 40 → 25 selected fields, CorporateUser 30 → 9). Checked that the filter
  costs nothing real: of the 87 fields it drops across all entities, **every one is a
  Bullhorn auto-labelled placeholder** — no genuinely renamed custom field is hidden.
  AC 5, 6 and 7 also confirmed live: the Note section renders `action` with all 25
  values, CorporateUser carries `id`/`firstName`/`lastName`/`email`, and no entity
  renders header-only at either level.

- **m4: test count is materially above the CR's own estimate.** CR37 predicted ~660
  ("Flag it if materially different rather than adjusting quietly"); actual is 707.
  The gap is parametrisation, not extra test functions — `test_build_entity_section_never_header_only`
  alone expands to 20 cases across 10 entities × 2 levels — so this is bookkeeping, not
  a coverage discrepancy.

- **m5: `_and_clause(search_query, clause)` annotates `clause` as `str`** (server.py:344)
  but every caller passes the `str | None` first element of `_note_action_clause`'s
  tuple. Runtime-safe because the `err` check returns first; a type checker would flag it.

## Verdict

NO CRITICAL ISSUES. 3 MODERATE issue(s) must be resolved before pushing.
