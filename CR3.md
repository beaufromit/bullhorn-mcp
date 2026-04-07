# CR3: Fix Broken Owner Name Resolution and Remove Department Field Leak

## Summary

Two related issues are preventing contact creation:

1. **Owner name resolution is broken.** When a user provides an owner as a name string (e.g. "Beau Warren"), the MCP is passing the raw name string through to Bullhorn instead of resolving it to a CorporateUser ID first. Previously this worked correctly — the MCP would query the CorporateUser entity, find the matching user, and substitute `{"id": <int>}` into the payload. This resolution must be restored.

2. **A `department` field is leaking into the ClientContact creation payload.** The `resolve_owner` method queries CorporateUser with `fields="id,firstName,lastName,email,department"`. Data from this query (specifically the `department` field) is ending up in the ClientContact creation payload sent to Bullhorn. `department` is not a valid field on ClientContact, so Bullhorn rejects the request.

These two issues may be related — the `department` leak likely originates from the owner resolution path.

## Expected Behaviour (Previously Working)

1. Caller provides `owner: "Beau Warren"` in the `create_contact` fields.
2. `resolve_owner("Beau Warren")` queries CorporateUser by name.
3. Query returns the matching user record.
4. `resolve_owner` returns `{"id": <user_id>}` only.
5. `create_contact` replaces `fields["owner"]` with `{"id": <user_id>}`.
6. The ClientContact creation payload sent to Bullhorn contains `"owner": {"id": <user_id>}` and nothing else from the CorporateUser query.

## Current Broken Behaviour

1. Caller provides `owner: "Beau Warren"`.
2. The name string is passed through to Bullhorn without being resolved to an ID.
3. Additionally, a `department` field appears in the ClientContact creation payload, causing Bullhorn to reject the request.

## Required Investigation

Claude Code should trace the full execution path from `create_contact(fields)` through `resolve_owner()` and into `client.create()` to determine:

1. **Why the name is not being resolved.** Is `resolve_owner` being called? Is the CorporateUser query failing (perhaps because `department` is not a valid CorporateUser field in this instance)? Is the error being swallowed? Is the name string somehow bypassing the resolution logic?
2. **Where `department` is entering the ClientContact payload.** The `resolve_owner` query requests `department` as a field on CorporateUser. Even if this query succeeds, `resolve_owner` should return only `{"id": int}` — not the full CorporateUser record. Check whether the full query result (including `department`) is being merged into the contact fields somewhere.

## Required Fix

1. **Restore working name resolution.** When `owner` is a string, `resolve_owner` must query CorporateUser by name and return `{"id": <matched_user_id>}`. This is the behaviour specified in PRD FR-2 / US-5 and it previously worked.
2. **Prevent CorporateUser data from leaking.** Only the resolved `{"id": int}` from the owner lookup should be written into the contact creation payload. No other fields from the CorporateUser query (email, department, firstName, lastName) should end up in the ClientContact payload.
3. **Consider removing `department` from the CorporateUser query fields.** The `department` field is only needed for disambiguation when multiple users match. If it's causing issues, it can be removed from the default query and only included when disambiguation is needed. Alternatively, ensure it's strictly isolated to the disambiguation response and never touches the create payload.

## Affected User Stories

This bug blocks all contact creation, which cascades across 10 of 21 user stories.

**Directly broken (owner resolution fails):**
- US-2: Create a contact record linked to a company — fails on every attempt
- US-4: Owner is required when creating a contact — requirement is met in code but resolution doesn't execute, so creation fails
- US-5: Owner name resolves to user ID — the core broken functionality

**Broken as a consequence (depend on contact creation working):**
- US-3: Create a company on-the-fly for an unmatched contact — company may be created but the contact half fails
- US-9: Import a batch of companies and contacts — companies may import but all contacts fail
- US-10: Receive an import summary — summary will show all contacts as failed, giving a misleading picture
- US-11: Halt on consecutive errors — will trigger immediately on the contact phase since every contact create fails

**Indirectly affected (can't test properly until contacts can be created):**
- US-12: Update fields on a contact — works in principle but no new contacts can be created to update
- US-13: See the updated record after a change — same dependency
- US-16: Add a note to a contact — same dependency

## Acceptance Criteria

- Providing `owner: "Beau Warren"` in `create_contact` results in a CorporateUser query, resolution to the correct user ID, and the contact being created with `"owner": {"id": <resolved_id>}`.
- No `department` field is present in the ClientContact creation payload sent to Bullhorn.
- No other CorporateUser fields (email, firstName, lastName) leak into the ClientContact creation payload.
- The CorporateUser query in `resolve_owner` does not cause errors that silently prevent resolution.
- All existing owner resolution tests continue to pass.
