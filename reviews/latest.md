# Review: Sprint 23 / CR15 — shortlist_candidate and shortlist_candidates tools

**Commit:** working tree (uncommitted)
**Date:** 2026-05-12
**Files changed:** 10

## CRITICAL

None.

## MODERATE

- **M1: `payload.update(resolved_fields)` allows `fields={"status": ...}` to silently override the `status` parameter** — `server.py:1129` (`_shortlist_one`)
  CR15.md states the `status` override risk is "handled by not putting it in resolved_fields in the callers." Neither `shortlist_candidate` (line 1196) nor `shortlist_candidates` (line 1259) strips `status` from `resolved_fields` before passing it to `_shortlist_one`. A caller that passes `fields={"status": "Rejected"}` alongside `status="Shortlisted"` will silently get `"Rejected"` in the payload. No test covers this interaction. New class of issue — no matching known failure pattern, but follows the same structural risk as known pattern #2 (field injection into write payloads).

- **M2: `shortlist_candidates` does not validate individual `candidate_id` values** — `server.py:1246–1249` (`shortlist_candidates`)
  `job_id > 0` is validated, but no per-element check is applied to `candidate_ids`. A non-positive value reaches `_shortlist_one` unchanged: it is written into the Lucene query (`candidate.id=0 AND ...`) and into the create payload (`"candidate": {"id": 0}`). The per-candidate `except` block only catches `AuthenticationError` and `BullhornAPIError`, so a Bullhorn 400 for a bad ID surfaces as an opaque error entry without a useful diagnostic. `shortlist_candidate` validates `candidate_id > 0` (line 1179); the batch variant is inconsistent.

- **M3: `TestShortlistCandidates` has no test for the identity-resolution-failure path** — `tests/test_server.py` (`TestShortlistCandidates`)
  The `except IdentityResolutionError` block in `shortlist_candidates` (after line 1262) catches failure from `resolve_caller` and continues the batch with `sending_user=None`. This fallthrough is untested. `TestShortlistCandidate.test_sending_user_identity_failure` (line 3289) covers the equivalent path for the single-candidate tool; no counterpart exists in `TestShortlistCandidates`. The untested code path is a write-path fallthrough with different observable behavior (batch proceeds, single tool also proceeds but is tested).

## MINOR

- **m1: `status or get_shortlist_status()` silently swallows empty-string status** — `server.py:1190`, `server.py:1253`
  A caller that explicitly passes `status=""` gets the env-var default instead with no warning or error. The falsy-string case is unlikely but the inconsistency with the integer validation style is worth noting.

- **m2: CR15.md documents the duplicate-check `fields` argument as a Python list; implementation uses a comma string** — `CR15.md` vs `server.py:1116`
  The spec shows `fields=["id", "status", ...]` but `_shortlist_one` calls `client.query(..., fields="id,status,dateAdded,sendingUser")`. The implementation is correct per actual API usage; the spec example is misleading.

## Verdict

3 MODERATE issue(s) must be resolved before pushing.
