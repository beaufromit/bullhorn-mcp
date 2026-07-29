"""Measure the token cost of enriched MCP tool descriptions against the live tenant.

Read-only: makes GET /meta/{entity} calls only. Never writes to Bullhorn.

Run from the repo root (needs a working .env with the 4 BULLHORN_* credentials):

    .venv/bin/python scripts/measure_descriptions.py

Output: per-tool description size (chars and a chars/4 token estimate), sorted
descending, plus the total. Compare against the CR34 targets: total under ~20k
estimated tokens; each of the 4 generic discovery tools (search_entities,
query_entities, update_record, get_entity_fields) under ~1.5k estimated tokens.

Measured live 2026-07-03 (v0.0.46, 38 tools): TOTAL 55,123 chars, ~13,780
estimated tokens. Largest tools were the 4 generic ones at ~2.9k chars
(~730-740 tokens) each. Pre-CR34 baseline was ~111k tokens; a total drifting
back toward six figures means the CR34 trim has regressed.
"""

import asyncio
import logging

logging.basicConfig(level=logging.WARNING)

from bullhorn_mcp.config import BullhornConfig
from bullhorn_mcp.auth import BullhornAuth
from bullhorn_mcp.client import BullhornClient
from bullhorn_mcp import server
from bullhorn_mcp.descriptions import enrich_tool_descriptions, GENERIC_DISCOVERY_TOOLS


async def main() -> None:
    config = BullhornConfig.from_env()
    client = BullhornClient(BullhornAuth(config))

    # Same call main() makes at startup; hits GET /meta/{entity} for each
    # entity in SUPPORTED_ENTITIES, then appends field sections to tools.
    await enrich_tool_descriptions(server.mcp, client)

    tools = await server.mcp.list_tools()
    sizes = {t.name: len(t.description or "") for t in tools}
    total = sum(sizes.values())

    print(f"{'chars':>8} {'~tokens':>8}  tool")
    for name in sorted(sizes, key=lambda k: -sizes[k]):
        marker = "  [generic]" if name in GENERIC_DISCOVERY_TOOLS else ""
        print(f"{sizes[name]:>8} {sizes[name] // 4:>8}  {name}{marker}")

    print(f"\nTOTAL: {total} chars, ~{total // 4} estimated tokens "
          f"across {len(sizes)} tools")


if __name__ == "__main__":
    asyncio.run(main())
