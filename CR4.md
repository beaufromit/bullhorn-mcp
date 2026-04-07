# CR4: Fix update_record Docstring Using Wrong Field Name for Job Title

## Summary

The `update_record` tool's docstring example uses `{"title": "CTO"}` to demonstrate updating a job title. This is incorrect — `title` in Bullhorn's ClientContact schema is the salutation/name prefix (Mr, Ms, Dr), not the job title. The correct field is `occupation`.

Calling agents (e.g. Claude) read tool docstrings to learn the correct field names. When the docstring shows `title` as the field for job title, agents follow that pattern. The key `"title"` doesn't match the FIELD_ALIASES entry `"job title"` (which correctly maps to `occupation`), so it passes through to Bullhorn unchanged and gets rejected.

This is the same class of issue fixed in CR1 for the `create_contact` docstring, but it was missed in the `update_record` docstring during Sprint 8.

## Root Cause

Sprint 8 (CR1) fixed the `create_contact` docstring example but did not audit the `update_record` docstring, which contains the same incorrect field name:

```python
Examples:
    - update_record("ClientContact", 54321, {"title": "CTO"})
```

This should be:

```python
Examples:
    - update_record("ClientContact", 54321, {"occupation": "CTO"})
```

## Required Changes

1. **Fix `update_record` docstring example** in `src/bullhorn_mcp/server.py` — change `{"title": "CTO"}` to `{"occupation": "CTO"}`.
2. **Audit all remaining tool docstrings** for any other references to `title` where `occupation` is meant. Check `list_contacts`, `list_companies`, `find_duplicate_contacts`, `bulk_import`, and any other tool that references ClientContact fields in its docstring or examples.

## Affected User Stories

- US-12: Update fields on a contact or company — agents following the docstring example will send the wrong field name, causing updates to fail
- US-15: Use field labels or API names interchangeably — the incorrect docstring undermines the field resolution system by teaching agents the wrong name

## Acceptance Criteria

- The `update_record` docstring example uses `"occupation"` instead of `"title"` for job title.
- No other tool docstring in `server.py` uses `"title"` to mean job title on a ClientContact.
- A test confirms that the `update_record` docstring does not contain `"title": "CTO"` (regression guard).
