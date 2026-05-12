# Review: fix M1 tighten extra_params assertion; fix M2 add empty-name test for find_duplicate_companies

**Commit:** cd4d014
**Date:** 2026-05-13
**Files changed:** 3 (reviews/latest.md, tests/test_client.py, tests/test_server.py)

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: `test_search_with_extra_params` still doesn't anchor assertion to the `query=` parameter** — `tests/test_client.py:TestSearchExtraParams`
  The fix changed `assert "sender.id" in url` to `assert "sender.id%3A1" in url`, adding the value `1` to the check. However, it still does not confirm that `sender.id%3A1` appeared specifically inside the `query=` parameter (vs any other parameter). In practice there is no other parameter that could contain this substring, so the test is sound. The original `"query=sender.id%3A1"` form is unachievable after CR16's wrapping adds a leading `(`, so this is an acceptable trade-off.

- **m2: `test_find_duplicate_companies_empty_name_sends_isdeleted_filter` uses `name%3A` as the negative assertion** — `tests/test_server.py:TestCR16DeletedRecordFilter`
  The assertion `assert "name%3A" not in captured["url"]` checks that no URL-encoded `name:` term appears. If Bullhorn or httpx ever changed encoding (e.g., the colon appeared unencoded in some field value context), this guard could become vacuous. Low real-world risk but the assertion's precision depends on URL-encoding behaviour.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
