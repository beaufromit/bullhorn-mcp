# Review: Sprint 43 review cycle 3 fixes (one title rule and warning for every Candidate write, title in attach_cv overwrite/fields_to_update never selects namePrefix, README alias exception, title in tenant defaults dropped)

**Commit:** 5d70bd6
**Date:** 2026-11-13
**Files changed:** 4

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: The shared warning states a tenant fact on the branch where it is not true, and the message on that branch is not pinned** - src/bullhorn_mcp/server.py `_drop_title_to_salutation` / `_title_dropped_warning`. The helper now also drops a `title` key that stays an unknown `title` (no "Title" label in /meta, or the /meta fallback), which used to be left for `_strip_contact_title`. The caller is then told "'Title' is the salutation (namePrefix)" on a tenant where no such label exists. The two tests that reach this branch (tests/test_server.py `test_create_candidate_strips_title_field`, `test_update_candidate_strips_title`) assert only that some warning contains "title", so neither pins which helper drops the key nor which message comes back.

- **m2: `title` in `attach_cv` `overwrite` or `fields_to_update` is ignored without pointing to `occupation`** - `_attach_cv`. The name is mapped to a `title` sentinel that matches nothing, so the caller gets the generic "overwrite names that are not pending overwrites, ignored: ['title']" or "fields_to_update not in the parse or fields_override, ignored: ['title']". A caller who meant job title while `occupation` is a pending overwrite is told the name is not pending and the job title is kept, with none of the "use 'occupation'" guidance every other Candidate path now gives. The commit message says the paths share one warning; these two do not.

- **m3: `attach_cv` docstring still says `overwrite` accepts any display label** - `attach_cv` docstring, `overwrite` argument ("API name or display label"). "Title" is the display label of `namePrefix` on this tenant and now never selects it. The exception is written in README.md only; the docstring is what the agent reads and was not changed. CR48.md (line 38) also still says the names are "API names or display labels" without the exception.

- **m4: The tenant-defaults warning does not say the key came from configuration** - `create_candidate`, `_create_candidate_from_cv`. A `Title` key in the tenant Candidate defaults produces "Field 'Title' was stripped from the Candidate payload" on every create, worded as if the caller sent it. The caller sent no such field and cannot act on it; nothing names the defaults setting as the source.

- **m5: The alias exception is not tested on the two new `attach_cv` name paths** - tests/test_server_cr46.py. `test_title_alias_to_occupation_kept` covers `fields_override` on `create_candidate_from_cv` only. No test passes `overwrite=["title"]` or `fields_to_update=["title"]` with a tenant alias mapping `title` to `occupation`, so the `else` side of the new conditional (the name selects `occupation`) is unpinned for a `title` spelling.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
