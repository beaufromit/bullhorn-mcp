# Review: Sprint 42 review cycle 1 fixes, employer key variants merged per record, shown percentage clamped to its band, config shape and number checks

**Commit:** e5d425d
**Date:** 2026-10-02
**Files changed:** 4

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: The employer merge depends on row order** (`src/bullhorn_mcp/duplicates.py`, `_employers`)
  `merge` folds a key into the first existing key it matches and can re-key that entry to a shorter key. With rows "Quillon Brewer", "Quillon", "Quillon Foods", the bare "quillon" becomes the key and then also absorbs "Quillon Foods", so two firms become one. With "Quillon Brewer", "Quillon Foods", "Quillon" they stay two. The effect is fewer employer slots (an under-count, never a double count), and only when a record holds a bare key made of one distinctive word.
- **m2: Some config values are still unvalidated** (`_check_shapes`)
  `default_country_code` (a non-string raises `TypeError` in `normalize_phone`), the list-valued keys (a string `generic_mailbox_prefixes` becomes a set of characters), and a `points` key added to an m/u level (which `_level_points` silently prefers) all still load cleanly.
- **m3: Two blank lines inside a class** (`tests/test_duplicates_scoring.py`, before `test_key_variants_of_one_employer_not_counted_twice`).

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
