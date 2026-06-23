# Review: Trim startup tool-description enrichment (~80% token reduction)

**Commit:** 88cc709
**Date:** 2026-06-23
**Files changed:** 7

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: Dead code in `build_entity_section()` compact branch** — `src/bullhorn_mcp/descriptions.py:196-200`
  `default_names: set[str] = set()` is populated across a four-line loop but never referenced. The actual field iteration at line 203 uses an independent inline list comprehension over `default_str`. The set could be removed entirely without changing behaviour.

- **m2: `@pytest.mark.asyncio` on a synchronous test** — `tests/test_descriptions.py:test_generic_tool_static_docstring_mentions_get_entity_fields`
  The test body uses `ast.parse` and has no `await`. asyncio will run it as a zero-checkpoint coroutine without issue, but the decorator is misleading and the function signature could be `def` rather than `async def`.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
