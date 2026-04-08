# Review: Fix HOST env var not read and main() transport/host mismatch

**Commit:** ee7c4fa
**Date:** 2026-04-08
**Files changed:** 2

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: No test for HOST env var being read** — `_host = os.environ.get("HOST", _default_host)` is a new one-liner in server.py but no test verifies that setting `HOST=192.168.1.1` in the environment results in `mcp.settings.host == "192.168.1.1"`. The port has an analogous reload-based test (`test_fastmcp_port_configured_from_env`); HOST does not. The code is simple enough that this is low-risk, but it is a gap in the test pattern established by the sprint.

- **m2: Unused import `mock_patch` persists** — `from unittest.mock import Mock, patch, patch as mock_patch` on line 7 of `test_server.py`. The previous review flagged this. This diff does not introduce it and does not fix it (correctly, per constraints), but it remains.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
