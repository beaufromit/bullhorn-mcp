# Review: list_tearsheets moves from /search/Tearsheet to /query/Tearsheet with name, owner_id and where filters (CR47, Sprint 42C)

**Commit:** b89d0ea
**Date:** 2026-11-11
**Files changed:** 5

## CRITICAL

Issues that must be fixed before pushing. Correctness bugs, data integrity risks,
security issues, or violations of known failure patterns listed above.

None.

## MODERATE

Issues worth fixing but not blocking. Design problems, missing edge cases,
inconsistencies with existing patterns, scope creep.

- **M1: `limit` outside 1-500 gives a wrong `has_more` now that `total` is always null**: src/bullhorn_mcp/server.py, `list_tearsheets`
  `limit` is passed to `query_with_meta` unvalidated. The client caps `count` at 500, `/query` returns `total: null`, and `_paginate_envelope` then decides `has_more` by comparing the rows returned with the caller's uncapped `limit`. Observed live (read-only, 2026-11-11, 920 tearsheets on the tenant):
  - `list_tearsheets(limit=600)` returns 500 rows with `has_more: false, next_start: null`. 420 tearsheets are silently missing and the envelope tells the agent the list is complete.
  - `list_tearsheets(limit=0)` returns 0 rows with `has_more: true, next_start: 0`. An agent that follows `next_start` repeats the same call forever (the pagination-loop failure class already seen in this repo).
  The docstring states "1-500" but nothing enforces it, and CR47 goal 2 ("paging ... behave as on the other list tools") is not met for these inputs. Compared live on the same day: `list_jobs(limit=600)` returns 500 rows with `total: 50319, has_more: true, next_start: 500`, and `list_jobs(limit=0)` returns a Bullhorn 400 ("Invalid count"), so the `/search`-backed list tools neither truncate silently nor loop. `query_entities(entity="Tearsheet", where="id>0", limit=600)` shows the same truncation as this tool; that behaviour is shared with the existing `/query` path and is newly carried onto a `list_*` tool by this diff. The CR recorded `total: null` in T47.1 and concluded the envelope "already handles this" without considering an out-of-range `limit`. No test covers either input.

## MINOR

Style, naming, documentation nits. Logged only.

- **m1: LIKE wildcards in `name` are not handled**: src/bullhorn_mcp/server.py, `list_tearsheets`. Only `'` is rejected. Observed live: `name="_"` and `name="%"` both match every tearsheet, so a name search for a literal underscore or percent sign (for example "SK_GC") is treated as a pattern, not as the substring the docstring and FR-21 Amendment promise.
- **m2: whitespace-only `where` produces a Bullhorn error**: src/bullhorn_mcp/server.py, `list_tearsheets`. `where="  "` is truthy, becomes `(  )` and returns an `ERROR:` string from the API (observed live) instead of being treated as no filter.
- **m3: the case the parentheses exist for is not asserted**: tests/test_server.py. `test_list_tearsheets_raw_where` uses an `OR` clause alone and `test_list_tearsheets_filters_combined` uses a `where` with no `OR`. No test combines an `OR` where with `name` or `owner_id`, so removing the parentheses in the combined path would break precedence with every test still passing on a where such as `isPrivate=false`.
- **m4: `test_list_tearsheets_pagination` only covers the full-page branch**: tests/test_server.py. With `total: None` the last (short) page giving `has_more: false, next_start: null` is not asserted for this tool.
- **m5: CR47.md contradicts itself on `total`**: CR47.md. The Verification section still says "Paging: ... `total` is populated", while "T47.1 live results" in the same file records that `/query` returns `total: null`.
- **m6: stale tearsheet risk row left in the amended PRD**: PRD.md line 1079. The row still says Tearsheet "may lack `isDeleted`" and that `list_tearsheets` may need `_ENTITIES_WITHOUT_ISDELETED`; T47.1 in this same commit establishes that `/meta/Tearsheet` has `isDeleted`. The FR-21 and US-40 edits did not touch it.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
