# CR7: Strip title From ClientContact Write Payloads and Log Warning

## Summary

The `title` field on Bullhorn's ClientContact entity is not usefully writable — it represents the salutation/name prefix (Mr, Ms, Dr) and is largely redundant with `namePrefix`. However, calling agents frequently send `title` intending it to mean job title (which is `occupation`). This causes write operations to fail.

Rather than mapping `title` to `occupation` (which would make the actual salutation field inaccessible), `title` should be silently stripped from ClientContact write payloads with a logged warning. Callers who want to set the salutation should use `namePrefix`. Callers who want to set the job title should use `occupation` or the alias `"job title"`.

## Background

The existing `FIELD_ALIASES` entry `"job title" -> "occupation"` (added in Sprint 8/CR1) handles the case where callers use the natural phrase "job title". However, callers also send the bare key `"title"` meaning job title — especially when copying from Bullhorn's UI or from tool docstrings that previously used `title` incorrectly.

Three options were considered:

- **Option A**: Map `"title"` to `"occupation"` in FIELD_ALIASES. Rejected because it makes the actual `title`/salutation field permanently inaccessible.
- **Option B**: Map `"title"` to `"occupation"` only in create/update contexts. Rejected as overly complex.
- **Option C (chosen)**: Strip `title` from ClientContact write payloads entirely. Callers use `namePrefix` for salutation and `occupation` for job title. Log a warning when `title` is stripped so the behaviour is visible but not blocking.

## Required Changes

1. **In `create_contact` and `update_record`** (or in a shared utility they both use): After field label resolution, if the entity is `ClientContact` and the resolved payload contains the key `title`, remove it from the payload and log a warning message.

2. **Warning message format**: `"Field 'title' was stripped from the ClientContact payload. Use 'occupation' for job title or 'namePrefix' for salutation."` This should be logged (Python `logging` module) and also included in the response as a `warnings` array so calling agents can see it.

3. **Response format when title is stripped**: The operation should proceed without `title` in the payload. The response should include a `warnings` field:

```json
{
  "changedEntityId": 54321,
  "changeType": "INSERT",
  "data": { ... },
  "warnings": [
    "Field 'title' was stripped from the ClientContact payload. Use 'occupation' for job title or 'namePrefix' for salutation."
  ]
}
```

4. **Do not strip `title` from read operations** — `DEFAULT_FIELDS["ClientContact"]` correctly includes `title` for GET responses and should remain unchanged.

5. **Do not strip `title` from other entity types** — this only applies to ClientContact write operations. Other entities may have a valid writable `title` field (e.g. JobOrder).

## Affected User Stories

- US-2: Create a contact record linked to a company — `title` in payload no longer causes failure
- US-12: Update fields on a contact or company — same protection for updates
- US-15: Use field labels or API names interchangeably — clarifies the correct field names

## Acceptance Criteria

- `create_contact` with `{"title": "CTO", ...}` in the payload succeeds — `title` is stripped, the contact is created without it, and the response includes a warning.
- `update_record("ClientContact", <id>, {"title": "VP"})` succeeds — `title` is stripped, the update proceeds with an empty payload (or remaining fields), and the response includes a warning.
- `update_record("ClientContact", <id>, {"occupation": "VP"})` succeeds as normal with no warning.
- `update_record("JobOrder", <id>, {"title": "Senior Engineer"})` is not affected — `title` is not stripped for non-ClientContact entities.
- A test confirms that when `title` is present in a ClientContact write payload, it is removed before the API call and a warning is included in the response.
- `namePrefix` continues to work normally for setting salutations on ClientContact.
