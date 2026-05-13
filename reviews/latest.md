# Review: Fix M1 startup metadata cache discarded; fix M2 get_entity_fields missing from TOOL_ENTITY_MAP

**Commit:** d806940
**Date:** 2026-05-13
**Files changed:** 2

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: `patch` imported but unused** — `tests/test_descriptions.py:6`
  `from unittest.mock import AsyncMock, Mock, patch` — `patch` is not referenced anywhere in the file. Pre-existing from CR18 build; not introduced by this fix.

- **m2: `_make_mock_mcp` return type annotation is wrong** — `tests/test_descriptions.py:TestEnrichToolDescriptions._make_mock_mcp`
  Method signature declares `-> Mock` but returns `tuple[Mock, dict]`. Pre-existing from CR18 build; not introduced by this fix.

- **m3: `main()` stores `_metadata` only on success; exception path leaves `_metadata = None` silently** — `server.py:main()`
  If `asyncio.run(enrich_tool_descriptions(...))` raises an unhandled exception (caught by the outer `except`), the assignment `_metadata = ...` never executes and `_metadata` stays `None`. `get_metadata()` then lazily creates a fresh instance on first tool call, which is the correct fallback. However, the intent (`global _metadata` declared, assignment inside try) is not obvious to a future reader — it reads as though `_metadata` is always set, but the except path silently leaves it None. Not a bug, but worth noting.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
