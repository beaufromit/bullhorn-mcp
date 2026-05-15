# Review: Add get_notes_for_entity and search_notes tools (CR21)

**Commit:** 7b06fe8
**Date:** 2026-05-15
**Files changed:** 7

## CRITICAL

- **C1: Missing `targetEntityType` filter in NoteEntity where clause** — `server.py`, `get_notes_for_entity()`, line ~532

  The NoteEntity query is built as `where=f"targetEntityID={entity_id}"` with no `AND targetEntityType='{entity}'` constraint. In Bullhorn, entity IDs are independent sequences per entity type — a Candidate and a JobOrder can both have ID 169020. Without the `targetEntityType` filter, `get_notes_for_entity("Candidate", 169020)` will return notes attached to any entity with ID 169020 regardless of type, silently mixing notes from unrelated records (contacts, jobs, companies) into the result. The test `test_query_calls_note_entity_with_correct_where` only asserts that the entity_id value appears in the where clause; it does not assert that `targetEntityType` is also present, so it does not catch this bug. New class of issue.

## MODERATE

- **M1: `entity_filter` for Placement, Lead, and Opportunity silently returns empty results in `search_notes`** — `server.py`, `search_notes()`, `_NOTE_DEFAULT_FIELDS` constant

  `_NOTE_DEFAULT_FIELDS` does not include the `placements`, `leads`, or `opportunities` association fields. When `search_notes` is called with `entity_filter={"type": "Placement", "id": N}` and no explicit `fields` argument, Bullhorn does not return the `placements` field on each note. The client-side filter calls `note.get("placements")` → `None`, which is neither a `list` nor a `dict`, so no note matches and the result is `[]`. This affects three of the seven entity types supported by `_NOTE_ENTITY_SUBJECT_FIELD`. No error is raised and no warning is surfaced to the caller. `TestSearchNotes` has no test for Placement, Lead, or Opportunity entity filters. New class of issue.

## MINOR

None.

## Verdict

2 CRITICAL issue(s) must be resolved before pushing.
