# Review: CR40 (Sprint 39) add_note always sends personReference, adds person_id, redirects company notes to contacts, reads clientContactNotes for companies

**Commit:** 0775f8f (build; HEAD 33e2bce is a docs-only T39.5 results commit, reviewed together via `git diff HEAD~2`)
**Date:** 2026-09-23
**Files changed:** 8

## CRITICAL

None.

## MODERATE

- **M1: Company redirect lists archived contacts, but the PRD says "active contacts"** - src/bullhorn_mcp/server.py:add_note (ClientCorporation branch)
  FR-7 Amendment 2 says the `company_notes_live_on_contacts` error "lists the company's active contacts", and US-47 acceptance says it returns "the company's active contacts". The query is `clientCorporation.id=<id>` with only the automatic isDeleted gate, so it returns every non-deleted contact whatever its `status`. Read-only live check on company 10666: 22 contacts come back, with statuses `Active`, `Archive` and `New Lead` mixed together (32 including deleted). The agent is therefore invited to put a new note on an archived contact. Plan assumption A3 redefines "active" as "non-deleted", but the PRD and US-47 text were not changed to match, so the code and the requirement of record disagree. The server test (`test_company_target_rejected_with_contact_list`) pins the WHERE clause exactly, so it locks in the mismatch rather than catching it.

## MINOR

- **m1: Contact list in the company redirect is silently truncated and unordered** - `count=50` with no `order_by` and no truncation signal in the response. For a company with more than 50 non-deleted contacts, the contact the user means may be missing, and nothing in the payload says the list is partial.
- **m2: FR-7 Amendment (first paragraph) still lists ClientCorporation among the seven supported add_note targets** - PRD.md FR-7 Amendment was edited in this diff (the `commenting_person_id` sentence) but still says the tool supports "Candidate, ClientContact, ClientCorporation, JobOrder, ...", which FR-7 Amendment 2 directly below now contradicts.
- **m3: `test_other_entities_still_use_notes` sets `get_association.return_value` but asserts on `get_association_with_meta`** - it passes only because of the `mock_client` delegation side_effect; the setup line reads as if it configures the call under test.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
