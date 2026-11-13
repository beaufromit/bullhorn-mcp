"""Static checks on upload_box.html, the CV upload MCP App (CR46 B6).

The repo has no browser test runner, so these tests read the HTML source and
assert the MCP Apps handshake matches the spec (ext-apps spec.types.ts,
LATEST_PROTOCOL_VERSION 2026-01-26). The live retest (T43.15) is the real proof.

Why they exist: v0.0.56's box sent ui/initialize with clientInfo/capabilities
instead of appInfo, the host rejected it, the box swallowed the rejection and
never reported a size, so it rendered at zero height in every host.
"""

import re
from pathlib import Path

import pytest

BOX = Path(__file__).resolve().parents[1] / "src" / "bullhorn_mcp" / "upload_box.html"


@pytest.fixture(scope="module")
def script() -> str:
    html = BOX.read_text(encoding="utf-8")
    match = re.search(r"<script>(.*?)</script>", html, re.S)
    assert match, "upload_box.html has no inline script"
    return match.group(1)


def _call_block(script: str, method: str) -> str:
    """Return the source from request("<method>", up to the end of that statement.

    The statement ends at the first "});" that closes a line, so handlers with
    their own inner calls (notify(...);) stay inside the block.
    """
    start = script.index(f'request("{method}"')
    end = re.compile(r"^\s*\}\)(\.catch\(.*\))?;\s*$", re.M).search(script, start).end()
    return script[start:end]


class TestUploadBoxSpec:
    def test_upload_box_initialize_uses_app_info(self, script):
        block = _call_block(script, "ui/initialize")
        params = block.split("}).then(")[0]
        assert re.search(r"appInfo:\s*\{\s*name:", params)
        assert "appCapabilities:" in params
        assert 'protocolVersion: "2026-01-26"' in params
        # The fields that broke the handshake must be gone.
        assert "clientInfo" not in params
        assert re.search(r"\bcapabilities:", params) is None

    def test_upload_box_message_content_is_array(self, script):
        block = _call_block(script, "ui/message")
        assert 'role: "user"' in block
        assert re.search(r"content:\s*\[\s*\{\s*type:\s*\"text\"", block)

    def test_upload_box_init_failure_shows_error_and_size(self, script):
        block = _call_block(script, "ui/initialize")
        # The rejection handler is the second function passed to .then().
        then_args = block.split("}).then(", 1)[1]
        handlers = then_args.split("}, function", 1)
        assert len(handlers) == 2, "ui/initialize has no rejection handler"
        on_reject = handlers[1]
        assert 'setStatus(' in on_reject and '"err"' in on_reject
        assert "reportSize()" in on_reject

    def test_upload_box_reports_size_before_handshake(self, script):
        # A size is reported on load, before the initialize request, so the
        # frame is never zero height while waiting for the host.
        # Anchored to the statement directly before the request: the tool-result
        # handler further up also calls reportSize(), so a looser slice would pass
        # against the v0.0.56 box too.
        assert re.search(r'^\s*reportSize\(\);\s*\n\s*request\("ui/initialize"', script, re.M)
