#!/usr/bin/env python
"""Dump the /meta field inventory for a Bullhorn entity. READ-ONLY.

Usage (from repo root):
    .venv/bin/python .claude/skills/bullhorn-mcp-live-api-method/scripts/meta_dump.py <Entity> [field-filter]

Examples:
    .venv/bin/python .claude/skills/bullhorn-mcp-live-api-method/scripts/meta_dump.py Candidate
    .venv/bin/python .claude/skills/bullhorn-mcp-live-api-method/scripts/meta_dump.py ClientContact title
    .venv/bin/python .claude/skills/bullhorn-mcp-live-api-method/scripts/meta_dump.py Placement custom

Prints name / label / dataType / required for every field on the entity,
plus picklist options where present. The optional second argument filters
fields by case-insensitive substring match on name OR label.

Requires a .env in the repo root with the four BULLHORN_* credentials.
Calls only get_meta(); never writes anything.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from bullhorn_mcp.config import BullhornConfig  # noqa: E402
from bullhorn_mcp.auth import BullhornAuth  # noqa: E402
from bullhorn_mcp.client import BullhornClient  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    entity = sys.argv[1]
    needle = sys.argv[2].lower() if len(sys.argv) > 2 else None

    config = BullhornConfig.from_env()
    client = BullhornClient(BullhornAuth(config))

    meta = client.get_meta(entity)
    fields = meta.get("fields", [])
    print(f"# /meta/{entity}: {len(fields)} fields total")

    shown = 0
    for f in sorted(fields, key=lambda f: f.get("name", "")):
        name = f.get("name", "")
        label = f.get("label", "") or ""
        if needle and needle not in name.lower() and needle not in label.lower():
            continue
        shown += 1
        dtype = f.get("dataType", f.get("type", "?"))
        required = "REQUIRED" if f.get("required") else ""
        maxlen = f.get("maxLength")
        maxlen_s = f" maxLength={maxlen}" if maxlen else ""
        print(f"{name:40s} | {label:35s} | {dtype:12s} | {required}{maxlen_s}")
        options = f.get("options")
        if options:
            values = [str(o.get("value")) for o in options]
            preview = ", ".join(values[:15])
            more = f" ... (+{len(values) - 15} more)" if len(values) > 15 else ""
            print(f"{'':40s}   picklist: {preview}{more}")

    if needle:
        print(f"# {shown} field(s) matched filter '{sys.argv[2]}'")
    if needle and shown == 0:
        print("# NO MATCH: the field does not exist on this entity under that name.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
