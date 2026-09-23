# Review: CR38 adds the isolated `people_search_perplexity` tool and `perplexity.py` module (Sprint 38)

**Commit:** a745417
**Date:** 2026-09-23
**Files changed:** 10

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: A malformed 200 body raises instead of returning error JSON** (`src/bullhorn_mcp/server.py`, `people_search_perplexity` result loop; `src/bullhorn_mcp/perplexity.py`, `search_people` return). `search_people` returns `results` unchecked whenever it is truthy. The tool then calls `item.get(...)` and `len(snippet)` with no guard. Probed locally with respx: `{"results": ["a"]}` and `{"results": {"x": 1}}` raise `AttributeError`, and a non-string `snippet` raises `TypeError`, so the caller gets an exception rather than `perplexity_error` JSON. CR38 R2 only promised tolerance for a missing `date` and extra keys, and the live contract was verified, so this is a drift-hardening gap and not a defect against the spec.
- **m2: Two `search_people` error branches have no tests** (`tests/test_perplexity.py`). Nothing covers the `invalid_response` branch (a 200 whose body is not a JSON object) or the `HTTP <status>` fallback for a non-200 with a non-JSON or error-less body. The key-redaction `replace` on the upstream message is also never exercised with a body that echoes the key. The 401 test only shows that a body without the key does not leak it.
- **m3: CR39 post-tag bookkeeping is bundled into the CR38 feature commit** (`CR39.md`, `PRD.md` FR-2/FR-12 markers, IMPLEMENTATION-PLAN.md Sprint 37B checklist). This is unrelated to CR38. It is documented as carried-over T37B.3 work, but it muddies the revert boundary that CR38 "Rollback" describes as isolated.
- **m4: `.env.example` has no blank line before the new section header.** `# === External people search (CR38) ===` sits directly under `# UPLOAD_SECRET=...`, unlike the other sections in the file.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
