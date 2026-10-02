# Review: CR44 Sprint 42, pure match-check scorer, normalisers, profile shape and versioned match_config.json (not wired)

**Commit:** 219f2d9
**Date:** 2026-10-02
**Files changed:** 6

## CRITICAL

None.

## MODERATE

- **M1: One employer is counted more than once when a record holds two key variants of it** — src/bullhorn_mcp/duplicates.py:756 (`_employers`) and :848-875 (`_score_employers`)
  `_employers` dedupes only on the exact normalised key, and the greedy pairing then matches each variant to its twin. Verified: both records holding "Abbey Capital" and "Corporate with Abbey Capital" (the prefixed-employer parser form recorded in CR44's investigation) get two `employer` entries of 9.23 points each, "Both worked at Abbey Capital" and "Both worked at Corporate with Abbey Capital", so one real firm takes two of the three employer slots. CR44 says "Count distinct employers, never rows". 27% of sampled candidates carry repeated employer rows from re-parses, so variant keys inside one record are common. `test_duplicate_rows_not_counted_twice` covers only identical company text.

## MINOR

- **m1: Displayed percentage and band can disagree at the threshold** — `score_pair` computes `band` from the unrounded percentage but returns `round(percentage, 2)`, so a value of 97.996 is shown as 98.0 with band `uncertain`, while the high band is documented as ">= 98".
- **m2: Config validation does not check level shapes or the non-probability numbers** — `validate_match_config` checks that `forename.exact`, `surname.different` and so on exist, but not that each holds `m`/`u` or a numeric `points`. A level of `{}` passes load and raises `KeyError` at scoring time. A sign-flipped `different.points` or `differ_points` (for example `6`), `caps.max_employers` of 0 (the cap check `len(chosen) == 0` never fires, so the cap is removed), and non-numeric `generic_min_holders` or `year_tolerance` all load cleanly. This contradicts the `load_match_config` docstring promise that a broken calibration change "fails at startup rather than scoring quietly wrong".
- **m3: A null end year on an old record counts as current forever** — `_spans_overlap` treats `end_year=None` as 9999, so a 2009 record with an open-ended role overlaps any later role at the same employer and earns `overlap_bonus`. CR44 notes that a null `endDate` means current only as of when the record was written.
- **m4: Any national-format number is mapped to +353** — `normalize_phone` turns any leading `0` into `+353`, so a UK `07700 900123` becomes `+3537700900123` and never matches the same person's `+447700900123`. The default country code is a config value, but non-Irish numbers on this tenant are not mentioned in the docstring or the build notes.
- **m5: Gendered forename pairs score as a one-letter typo** — `forename_relation` classes Paul/Paula, Mark/Mary, John/Joan, Louis/Louise and Daniel/Daniela as `typo` (+3.3 points), not `different` (-6). As a result they also never trip the forename identifier guard. The owner ruled the shared-phone consequence (raised as C1 in the first pass) a non-issue on 2026-10-02: home phones are unused and mobile is the main number. Logged for the name-only scoring effect only.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
