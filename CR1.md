# CR1: Fix title/occupation Field Mapping Bug in create_contact

## Summary

The `create_contact` tool incorrectly maps job title data to the `title` field on the ClientContact entity. In Bullhorn's schema, `title` refers to the salutation/name prefix (Mr, Ms, Dr, etc.), not the person's job title. Job title should be mapped to the `occupation` field.

## Problem

When creating a ClientContact via the MCP, the server appears to inject or map a `title` field into the API request payload. Bullhorn rejects this because `title` on the ClientContact entity expects a salutation value (and may have validation constraints that reject freeform text like "Kid" or "VP of Engineering").

This causes all contact creation attempts to fail with an error, regardless of the payload the caller provides. The bug is in the MCP server's request construction, not in the calling agent's data.

## Root Cause

The Bullhorn ClientContact entity has two distinct concepts that are easily confused:

- **`title`** — salutation/name prefix (Mr, Ms, Dr, etc.). This is equivalent to `namePrefix`.
- **`occupation`** — the person's job title or role (e.g. "VP of Engineering", "HR Director").

The `create_contact` tool is mapping job title input to `title` instead of `occupation`.

## Required Changes

1. **In the `create_contact` tool**: Do not send a `title` field unless the caller explicitly provides a salutation. Job title data must be sent as `occupation`.
2. **Field label resolution**: Ensure the metadata/label resolution (FR-8) correctly distinguishes between these fields. If a user or agent says "job title", it should resolve to `occupation`, not `title`.
3. **PRD schema update**: The Create ClientContact request schema in PRD.md Section 10 currently shows `"title": "VP of Engineering"` — this should be updated to `"occupation": "VP of Engineering"`.
4. **Review for similar issues**: Check all field mappings in create and update tools for other cases where Bullhorn field names don't match common assumptions.

## Affected User Stories

- US-2: Create a contact record linked to a company
- US-4: Owner is required when creating a contact
- US-9: Import a batch of companies and contacts (contacts will fail during bulk import)
- US-15: Use field labels or API names interchangeably

## Acceptance Criteria

- Creating a ClientContact with `occupation: "VP of Engineering"` succeeds without error.
- The `title` field is not sent in the creation payload unless the caller explicitly provides a salutation value.
- If a caller provides `"job title": "VP of Engineering"` using the label, the metadata resolution maps it to `occupation`, not `title`.
- Existing contact creation tests are updated to reflect the correct field mapping.
