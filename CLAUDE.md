# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Core Principles

**Surface uncertainty early.** Never silently fill in ambiguous requirements. If something is unclear, ask before implementing.

**State assumptions explicitly.** Before non-trivial work, list what you're assuming. Wrong assumptions caught early cost minutes. Wrong assumptions caught late cost hours.

**Stop when confused.** If you encounter conflicting requirements or inconsistencies, name the specific confusion and wait for resolution. Do not guess and proceed.

**Push back when warranted.** Point out problems directly. Propose alternatives. Accept override decisions. Sycophancy helps no one.

**Prefer simplicity.** If 100 lines would suffice, don't write 1000. Choose the boring, obvious solution. Cleverness is expensive.

**Touch only what you're asked to touch.** No unsolicited refactoring, no removing code you don't understand, no "cleaning up" adjacent systems.

## Before You Start

For non-trivial tasks, emit a brief plan and your assumptions. Wait for confirmation before proceeding.

## After You Finish

Summarise what changed, what you intentionally left alone, and any concerns or risks to verify.

## Important files

PRD.md - Product requirements document.

IMPLEMENTATION-PLAN.md - Module reference and sprint status (all complete).

## Commands

**Install dependencies:**
```bash
uv venv && uv pip install -e ".[dev]"
```

**Run all tests:**
```bash
.venv/bin/pytest
```

**Run a single test file:**
```bash
.venv/bin/pytest tests/test_auth.py
```

**Run a single test:**
```bash
.venv/bin/pytest tests/test_auth.py::TestBullhornAuth::test_full_auth_flow
```

**Run the MCP server manually:**
```bash
.venv/bin/python -m bullhorn_mcp.server
```

## Architecture

This is a Python MCP (Model Context Protocol) server that exposes Bullhorn CRM data to AI assistants. The server uses `mcp[server]` via `FastMCP` and communicates over stdio.

### Module layout (`src/bullhorn_mcp/`)

- **`server.py`** — MCP entry point. Defines the 6 tools (`list_jobs`, `list_candidates`, `get_job`, `get_candidate`, `search_entities`, `query_entities`) using `@mcp.tool()` decorators. Holds a lazily-initialized global `BullhornClient` instance via `get_client()`.
- **`auth.py`** — OAuth 2.0 flow. `BullhornAuth` manages the full multi-step Bullhorn auth: get auth code → exchange for access token → REST login to get `BhRestToken`. Handles regional server redirects (e.g., `auth-apac.bullhornstaffing.com`) by tracking `_regional_auth_url`. Sessions auto-refresh before expiry (60-second buffer). `BullhornSession` holds the `bh_rest_token` and `rest_url` returned from Bullhorn's REST login.
- **`client.py`** — REST API wrapper. `BullhornClient` provides `search()` (Lucene syntax → `/search/{entity}`), `query()` (SQL WHERE syntax → `/query/{entity}`), and `get()` (single entity by ID → `/entity/{entity}/{id}`). Automatically retries once on 401 by calling `auth._refresh_session()`. `DEFAULT_FIELDS` defines the default field sets per entity type.
- **`config.py`** — `BullhornConfig` dataclass loaded from env via `BullhornConfig.from_env()`. Calls `load_dotenv()` automatically.

### Authentication flow detail

Bullhorn uses a non-standard OAuth flow: credentials (username/password) are submitted directly in the authorization URL as query parameters (`action=Login`). The response is a redirect containing the auth code. Some accounts are hosted on regional servers and the initial request gets a 307 redirect to a regional auth domain — `BullhornAuth` follows these and tracks the regional URL for subsequent token exchanges and refreshes.

### Testing

Tests use `respx` to mock `httpx` HTTP calls. The `conftest.py` provides shared fixtures (`sample_config`, `mock_session`, `sample_job`, `sample_candidate`). Tests are synchronous (no `pytest-asyncio` needed for current tests, though it's installed).

### Environment variables

Required: `BULLHORN_CLIENT_ID`, `BULLHORN_CLIENT_SECRET`, `BULLHORN_USERNAME`, `BULLHORN_PASSWORD`
Optional: `BULLHORN_AUTH_URL` (default: `https://auth.bullhornstaffing.com`), `BULLHORN_LOGIN_URL` (default: `https://rest.bullhornstaffing.com`)

Copy `.env.example` to `.env` to configure locally.
