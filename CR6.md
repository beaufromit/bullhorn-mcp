# CR6: Investigate and Fix title Field Injection in update_record

## Summary

Every `update_record` call on a ClientContact returns `"Invalid field 'title' at position 42"` regardless of what fields the caller provides. Even a request containing only `{"firstName": "Aleksandr"}` triggers this error. The `title` field is being injected into the request payload somewhere in the execution path.

This is distinct from CR4 (docstring fix). CR4 addresses the calling agent learning the wrong field name from examples. This CR addresses a code-level injection where `title` appears in the Bullhorn API request even when the caller never sent it.

## Problem

When calling `update_record("ClientContact", <id>, {"firstName": "Aleksandr"})`, the Bullhorn API returns an error about an invalid `title` field. The caller did not include `title` in the request. This means something in the MCP's request construction path is adding it.

This was the root cause of Issue 1 (CR5) — contacts were partially created by Bullhorn before the `title` error was returned, leading to silent duplicates when the caller retried.

## Required Investigation

Claude Code must trace the complete execution path for `update_record` and identify exactly where `title` is being added. Specific areas to check:

1. **`update_record` in `server.py`**: Does `get_metadata().resolve_fields(entity, fields)` add `title` to the output? It shouldn't — Sprint 9 confirmed `resolve_fields` never adds keys. But verify by checking the actual metadata response from the Bullhorn instance. If the metadata for ClientContact has a field whose *label* happens to match one of the caller's input keys, `resolve_fields` could silently remap it.

2. **`client.update()` in `client.py`**: Does `_request("POST", ...)` add anything to the JSON body beyond what's passed in? Check whether the `json` parameter is being modified before or during the HTTP call.

3. **MCP tool schema/signature**: When the MCP server exposes `update_record` to a calling agent, does the tool's parameter schema include a `title` field? If `update_record` previously had `title` as an explicit parameter (from an earlier implementation), it may still be in the schema. The calling agent would then send `title: null` or `title: ""` as part of every call because the schema says it's a parameter.

4. **`DEFAULT_FIELDS`**: Although Sprint 9 confirmed `DEFAULT_FIELDS` is not used in write paths, verify there is no code path where the default ClientContact fields (`"id,firstName,lastName,email,phone,status,title,dateAdded,clientCorporation,owner"`) are being read during an update operation.

5. **The calling agent itself**: Capture the exact JSON that the calling agent sends to the MCP tool. If the agent is adding `title` to every request based on having seen it in tool examples or schema, the fix is at the schema/docstring level rather than in code. But given that the user observed this happening "regardless of what fields I passed," it's more likely a code-level issue.

## Required Fix

Once the source of injection is identified:

1. **Remove the injection** — ensure `update_record` sends exactly and only the fields the caller provides (after label resolution).
2. **Add a regression test** — a test that calls `update_record("ClientContact", <id>, {"firstName": "Test"})` and asserts the POST body sent to Bullhorn contains exactly `{"firstName": "Test"}` with no additional keys. This test must use a mock that captures the raw HTTP request body, not just the method arguments.
3. **Verify with the full MCP tool chain** — if the issue is in the MCP schema, ensure the schema is regenerated/updated after the fix so calling agents pick up the corrected version.

## Affected User Stories

This bug blocks all ClientContact updates:

- US-12: Update fields on a contact or company — every update fails
- US-13: See the updated record after a change — can't get updated record if update fails
- US-15: Use field labels or API names interchangeably — irrelevant if updates don't work at all

## Acceptance Criteria

- `update_record("ClientContact", <id>, {"firstName": "Test"})` succeeds and the POST body sent to Bullhorn contains exactly `{"firstName": "Test"}` — no `title` field present.
- `update_record("ClientContact", <id>, {"occupation": "CTO"})` succeeds with only `{"occupation": "CTO"}` in the POST body.
- A regression test captures the raw POST body for update_record and asserts no extra keys beyond what the caller specified.
- The root cause is documented in the implementation plan's "What was delivered" section for this sprint, including where the injection was found and how it was removed.
