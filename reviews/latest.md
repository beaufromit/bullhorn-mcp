# Review: Sprint 43 review cycle 2 fixes (title dropped before resolution on create_candidate and update_record, plan passed_match_check_id wording, repeated "all", startDate warning narrowed, repeated-entries wording, non-JSON /meta fallback)

**Commit:** 008a6c8
**Date:** 2026-11-13
**Files changed:** 5

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: Two separate title guards with different rules and different messages** - src/bullhorn_mcp/server.py `_drop_title_to_salutation` and `_filtered_cv_override`. The new helper keeps a `title` key that resolves to `occupation` or stays `title` (leaving the second case to `_strip_contact_title`) and warns "Field 'title' was stripped from the Candidate payload". The CV path's inline loop keeps only a key that resolves to `occupation` and warns "fields_override 'title' was ignored". Same failure pattern 1 guard, implemented twice, so a later change to one (for example a new alias rule) can miss the other, and a caller sees two wordings for the same thing.

- **m2: `overwrite=["title"]` and `fields_to_update=["title"]` on `attach_cv` still resolve to `namePrefix`** - `_attach_cv`. The name lists are resolved with `resolve_fields`, so on this tenant "title" selects the pending `namePrefix` change, not `occupation`. If the parse proposes a `namePrefix` that differs from the record, a caller who says "accept the new title" overwrites the salutation and keeps the old job title; otherwise the name is reported as not pending. Not introduced here (the resolution lines are unchanged), and Claude normally echoes the API names from the `overwrites` list, but it is the last Candidate path where "title" is read as a field name after this commit closed the write paths.

- **m3: README states the title drop without the alias exception** - README.md:666. It says a `title` key on a Candidate write "is dropped with a warning". With a `BULLHORN_CANDIDATE_ALIASES` entry mapping `title` to `occupation`, both helpers keep it (pinned by `test_title_alias_to_occupation_kept`). The note is unconditional.

- **m4: `get_candidate_defaults()` is not passed through the title guard** - `create_candidate`. Only caller `fields` go through `_drop_title_to_salutation`; a tenant default with a `Title` key is resolved to `namePrefix` and written without a warning. Configuration-only edge.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
