# CR5: Add Duplicate Check to create_contact Before Creation

## Summary

`create_contact` currently creates a record without checking whether the contact already exists at the specified company. Bullhorn can partially persist a record even when it returns an error (e.g. due to an invalid field), leading to silent duplicates when the caller retries.

`bulk_import` already performs duplicate detection before creating contacts via `score_contact_match`. The same check should be applied in `create_contact` so that individual contact creation is equally safe.

## Problem

During testing, multiple `create_contact` calls returned errors (due to the `title` field injection from CR6). However, Bullhorn had partially processed each request and created the contact records before returning the error. This resulted in three duplicate contacts (IDs 170841, 170842, 170843) that the caller had no way of knowing existed, because the error response gave no indication a record had been created.

A pre-creation duplicate check would have caught the second and third attempts and surfaced the existing record instead of creating duplicates.

## Required Changes

1. **Add duplicate detection to `create_contact`** in `src/bullhorn_mcp/server.py`. Before calling `client.create("ClientContact", ...)`, search for existing contacts at the same company with the same name using the same approach as `bulk_import` (search by `clientCorporation.id`, score with `score_contact_match`).

2. **If a duplicate is found (score >= 0.95)**: Return the existing record details to the caller instead of creating. The response should include the matched record's key fields (id, firstName, lastName, email, phone, clientCorporation) and a clear message indicating a duplicate was found. Do not create the record.

3. **If a likely/possible match is found (score 0.50-0.95)**: Return the match details with the confidence score and category, and a message asking the caller to confirm whether to proceed. Do not create the record. The caller can then choose to call `update_record` on the existing record or call `create_contact` again with a `force` parameter to bypass the check.

4. **Add a `force: bool = False` parameter** to `create_contact`. When `force=True`, skip the duplicate check entirely. This allows callers who have already verified (or who explicitly want to create regardless) to bypass the check.

5. **If no match is found**: Proceed with creation as normal.

## Response Format for Duplicates

When a duplicate or near-match is found, return:

```json
{
  "duplicate_found": true,
  "match": {
    "confidence": 0.97,
    "category": "exact",
    "record": {
      "id": 170841,
      "firstName": "Conor",
      "lastName": "Warren",
      "email": "kid@warrenhouse.com",
      "clientCorporation": {"id": 10666}
    }
  },
  "message": "A contact matching this name already exists at this company. Use update_record to modify the existing record, or set force=True to create regardless."
}
```

## Affected User Stories

- US-2: Create a contact record linked to a company
- US-7: Check if a contact already exists at a company (this check is now built into create_contact)

## Acceptance Criteria

- `create_contact` searches for existing contacts at the specified company before creating.
- If an exact match exists (>= 0.95), the existing record is returned with `duplicate_found: true`. No new record is created.
- If a likely/possible match exists (0.50-0.95), the match is returned for caller review. No new record is created.
- If no match exists, the contact is created as normal.
- `force=True` bypasses the duplicate check and creates regardless.
- `bulk_import` is not affected (it performs its own duplicate check and calls `client.create()` directly, not `create_contact`).
