# Review: Sprint 20 PRD parity hardening

**Commit:** 1fb56e2
**Date:** 2026-04-29
**Files changed:** 6

## CRITICAL

None.

## MODERATE

- **M1: Company-name duplicate lookup still misses acronym/abbreviation inputs** — src/bullhorn_mcp/server.py:754
  The new `find_duplicate_contacts(company_name=...)` path searches companies with `name:{first_word}*` before fuzzy scoring. For an input such as `company_name="BNY"`, this issues `name:BNY*`, so Bullhorn is unlikely to return `Bank of New York Mellon`; the local acronym scorer never sees the candidate. This leaves FR-4's company-name path weaker than the PRD's fuzzy/abbreviation requirement, and the new E2E-style test masks the issue by returning `Bank of New York Mellon` regardless of the actual query.

## MINOR

None.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
