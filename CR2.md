# CR2: Audit and Fix Auto-Injected Fields in create_contact

## Summary

The `create_contact` tool is injecting fields into the Bullhorn API request payload that the caller did not specify. This causes creation failures when the injected field names don't match what Bullhorn expects. After CR1 resolved the `title` issue, a `department` field is now surfacing as the next failure point. There may be additional fields being silently added.

## Problem

When creating a ClientContact, the MCP server constructs a request body that includes fields beyond what the caller provided. These appear to come from a default template or hardcoded field set in the tool's implementation. The Bullhorn API rejects the request because:

- The field name may not be valid on the ClientContact entity (e.g. `department` does not exist — the correct field is `division`).
- The field value may be empty or of the wrong type.
- The field may have validation constraints that reject the injected value.

This is the same class of bug as CR1 (`title` vs `occupation`), but affecting multiple fields.

## Known Affected Fields

1. **`title`** — resolved in CR1 (should be `occupation` for job title, `title`/`namePrefix` for salutation)
2. **`department`** — Bullhorn's ClientContact entity does not have a `department` field. The equivalent is `division`. If the intent is to set a department, it must be mapped to the correct field name. If there is no intent, it should not be sent at all.

## Required Changes

1. **Audit the `create_contact` tool**: Identify every field that the tool adds to the request payload beyond what the caller explicitly provides. Document each one.
2. **Remove auto-injected fields**: The tool should only send fields that the caller explicitly provides. Do not populate a default template with empty or assumed values.
3. **Validate field names against Bullhorn's schema**: Any field the tool does send must be a valid field on the ClientContact entity. Use the meta API (`/meta/ClientContact?fields=*`) as the source of truth for valid field names.
4. **Apply the same audit to `create_company`**: Check whether `create_company` has the same pattern of injecting unspecified fields into the ClientCorporation payload.
5. **Apply the same audit to `update_record`**: Ensure updates only send the fields the caller specifies, nothing extra.

## Root Cause Investigation

The implementation should determine where these extra fields originate. Likely causes:

- A default field dictionary or template that pre-populates the request body.
- Field mappings that include fields not present on the target entity.
- Parameter names in the tool's function signature that get passed through to the API even when not provided by the caller (e.g. a parameter with a default value of `None` still being included in the JSON body).

## Affected User Stories

- US-1: Create a company record
- US-2: Create a contact record linked to a company
- US-9: Import a batch of companies and contacts
- US-12: Update fields on a contact or company

## Acceptance Criteria

- The `create_contact` tool sends only the fields explicitly provided by the caller. No additional fields are injected.
- The `create_company` tool sends only the fields explicitly provided by the caller.
- The `update_record` tool sends only the fields the caller specifies for update.
- Creating a ClientContact with a minimal payload (firstName, lastName, name, clientCorporation, owner) succeeds without error.
- A full audit of the tool's request construction is documented, listing any fields that were being auto-injected and how each was resolved.
