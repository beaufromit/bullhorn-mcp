# Review: CR40 (Sprint 39) review fixes: company redirect excludes archived contacts, orders and flags truncation, PRD FR-7 target list, test mock setup

**Commit:** 00e040a
**Date:** 2026-09-23
**Files changed:** 4

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: "Left Company" contacts are still offered as note targets** - src/bullhorn_mcp/server.py:add_note (ClientCorporation branch). The ClientContact `status` picklist on this tenant is `Active`, `Archive`, `Left Company`, `Private` (live `/meta`, read-only). The filter only removes `Archive`, so contacts marked `Left Company` still appear in the redirect list. This matches the amended PRD wording ("active (non-archived)") and the owner's chosen fix, so it is not a requirement mismatch; it is logged for awareness only.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
