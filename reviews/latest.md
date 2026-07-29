# Review: fix the three MODERATE findings from the CR37 review — pin the `DEFAULT_FIELDS["Note"]` → `add_note` coupling, extend the empty-route probe to `search_entities`, and land the untracked Part 6 deliverable

**Commit:** bfb6561
**Date:** 2026-07-29
**Files changed:** 27 (2 source, 2 test, 2 docs-of-record, 21 newly tracked)

Scope note: `git diff HEAD~1` is non-empty and `HEAD~1` is `d91e629` (the CR37 build
commit), so the reviewed diff is exactly the fix commit. Suite: 715 passed
(707 at CR37, +8 here: 1 client, 7 server counting the ×2 parametrisation).

## CRITICAL

None.

Checked against all 8 known failure patterns:

- **Pattern 1 (title vs occupation):** no added or removed line in `src/` or `tests/`
  contains "title" in any form. Verified by grepping the diff.
- **Pattern 2 (field injection into write payloads):** no write payload is touched.
  `add_note`'s PUT body (client.py:487-492) is byte-identical; `create_contact`,
  `create_company` and `update_record` are not in the diff.
- **Pattern 3 (DEFAULT_FIELDS in write paths):** this needs stating explicitly,
  because the diff *documents and pins* a coupling between `DEFAULT_FIELDS["Note"]`
  and `add_note`, which is a write method. **It is not a recurrence.** Pattern 3
  guards against DEFAULT_FIELDS keys reaching a request **body**; here the constant
  is consumed only by the post-write `get("Note", note_id)` at client.py:496, a GET
  whose `fields` query parameter it supplies. The PUT payload is built solely from
  caller arguments and is unchanged. The client.py hunk is a comment; it adds no
  code. Confirmed by reading both the payload construction and the read-back.
- **Patterns 4 and 5 (owner resolution leakage / CorporateUser query fields):**
  `resolve_owner` and `identity.py` are not in the diff and their explicit
  `fields="id,firstName,lastName,email"` is untouched.
- **Patterns 6, 7, 8:** `update_record`'s guard ordering, `_process_single_contact`,
  and `resolve_fields()` alias precedence are all absent from this diff.

Closure of the three findings was verified structurally, not taken on trust:

| Finding | Verification |
|---|---|
| M1 | `read_back.calls[0].request.url.params["fields"]` asserts the **outgoing request**, not a return value. respx does not match on query parameters, so this is the only assertion shape that can catch the regression; the previous tests could not. |
| M2 | Enumerated every `client.search_with_meta(` call site in `src/` (8 total). Six hardcode a non-Note entity; the only two that can reach `/search/Note` are `search_entities` (server.py:1204) and `search_notes` (server.py:3406). Both now probe. `get_notes_for_entity` uses the CR23 association endpoint and `query_entities` hard-refuses `entity="Note"` (CR21), so no third path exists. M2 is fully closed, not partially. |
| M3 | `.claude/skills/` was never gitignored (`git check-ignore` exits 1; only the nested `__pycache__` dirs match). It was merely unstaged. All 18 files are now tracked, including `bullhorn-mcp-live-api-method/scripts/smoke_read.py`, which carries both halves of the two-way canary (match-all probe at line 111, nested `notes.action` assertion at lines 127-140). Re-confirmed CR37 AC 11 and AC 12 by grep: zero "advanced note searching" references in `src/`, `PRD.md` or `.claude/skills/`, and zero occurrences of "broken", "misconfigured", "outage", "not enabled" or "contact Bullhorn" in `server.py`/`client.py`. |

## MODERATE

None.

## MINOR

- **m1: the commit silently normalised 56 lines of `tests/test_client.py` from LF to
  CRLF**, which is why that file shows 137 changed lines for ~25 lines of new test.
  CR37 appended `TestNoteSearchProbe` with LF endings into a file that is otherwise
  entirely CRLF (as is every file under `src/` and `tests/`), leaving it mixed:
  `HEAD~1` was 1596 CRLF of 1652 lines. This commit's edit rewrote it to 1677 of
  1677. The outcome is correct — the file is now internally consistent and matches
  the repo — but it was incidental, it inflates the diff, and it means the reviewed
  `TestNoteSearchProbe` block is unchanged content presented as a rewrite. Worth
  knowing that the repo has no `.gitattributes`, so the next editor on a different
  toolchain can reintroduce the same churn.

- **m2: `test_add_note_read_back_uses_curated_note_fields` includes one
  self-referential assertion** — tests/test_client.py, `assert requested ==
  DEFAULT_FIELDS["Note"]` compares the request against the very constant that
  produced it, so it cannot fail while the plumbing works. The test is still valid:
  `assert requested != "*"` catches the actual regression M1 described (removing the
  key entirely, which restores the `fields=*` fallback and the 400), and the
  four-name loop catches trimming `id`/`action`/`comments`/`dateAdded`. But a trim
  of the association sub-selects (`candidates`, `clientContacts`, `jobOrders`,
  `placements`) passes silently. That does not break `add_note`, so it is a narrower
  guard than the assertion count suggests, not a hole.

- **m3: `test_entity_name_match_is_case_and_space_insensitive` asserts a path that
  may be unreachable in production.** `search_entities` passes the raw `entity`
  string to `search_with_meta`, so `entity="  Note  "` issues `GET /search/  Note  `
  and `entity="note"` issues `GET /search/note`. Whether Bullhorn accepts either is
  not verified anywhere in the repo; if it 400s, the call raises before the
  normalised comparison at server.py:1218 is ever evaluated. The defensiveness costs
  nothing, but the test's claim of coverage is stronger than the evidence for it.

- **m4: nothing pins that `search_entities` passes the entity string to
  `search_with_meta` unnormalised.** The new code normalises only for the
  comparison, deliberately. A future edit that hoists `(entity or "").strip()` into
  the `search_with_meta(entity=...)` argument for tidiness would change the outgoing
  URL for every entity, and every existing test would still pass.

- **m5: the commit tracks three files beyond the M3 finding's scope** — `CR36.md`,
  `NEXT_STEPS.md`, `support-ticket-notes.md`. Two are named CR37 Part 6 artifacts
  and belong with it. `CR36.md` is an unrelated DRAFT housekeeping CR. Mitigating:
  `git add -A` is the command PROMPT_iterate Step 3 prescribes, 36 other `CRx.md`
  files are tracked so this matches convention, and no file content was modified —
  only its tracked status. Logged for awareness rather than as scope creep.

- **m6: the new Sprint 36 section quotes an exact live count that has already
  drifted** — IMPLEMENTATION-PLAN.md records `notes.action:"BD Call"` on
  ClientContact as 1978 (CR37's figure); the previous review measured 1974 on the
  same tenant six days later. The canary in `smoke_read.py` correctly asserts `> 0`
  rather than an exact number; the plan text does not carry that caveat, so a future
  reader may treat a drifted figure as a regression signal.

- **m7: the `warnings` key is documented in the docstring prose but not in the
  `Returns:` block** of `search_entities` (server.py:1171-1175 vs 1187-1192). This
  is correct rather than an omission — FastMCP passes only the text before `Args:`
  to the agent and silently drops `Returns:` — and it matches how `search_notes`
  documents the same key. Noted so it is not "fixed" into the dead section later.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
