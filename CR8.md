# CR8: Add HTTP Transport Mode for Remote Hosting

## Summary

The server currently uses stdio transport exclusively. This means clients must spawn it as a local child process and communicate over stdin/stdout. Claude.ai (web), ChatGPT, and any other remotely-hosted AI client cannot use this transport — they require a public HTTP endpoint. Without this change, the server cannot be hosted on infrastructure (Proxmox, Azure, etc.) and exposed via a Cloudflare tunnel or similar for multi-user access.

The fix is to add support for the MCP Python SDK's `streamable-http` transport alongside the existing stdio transport. The active transport should be selectable via an environment variable so existing local setups continue working without any configuration changes.

## Issue 1: Server Only Supports stdio Transport

The server starts with `mcp.run()` or equivalent, which defaults to stdio. This is appropriate for local use with Claude Desktop and Claude Code but blocks any hosted deployment scenario.

The MCP Python SDK supports `streamable-http` transport natively. Switching transports requires changing only how `mcp.run()` is called — no tool logic changes.

### Required Changes

- Read a `MCP_TRANSPORT` environment variable on startup.
- If `MCP_TRANSPORT=http`, start the server using `transport="streamable-http"`.
- If `MCP_TRANSPORT` is absent or set to `stdio`, retain the existing stdio behaviour. This preserves backward compatibility for all current local users.
- Read a `PORT` environment variable to control the HTTP listening port. Default to `8000` if not set.
- Log the active transport and port on startup so it is immediately clear which mode is running.

## Issue 2: Missing Dependencies for HTTP Mode

`uvicorn` is required by the MCP SDK's HTTP transport but is not currently listed as a project dependency. It must be added explicitly to avoid import errors when HTTP mode is activated.

### Required Changes

- Add `uvicorn` to the dependencies in `pyproject.toml`.

## Issue 3: Environment Variables Not Documented

The two new variables (`MCP_TRANSPORT`, `PORT`) need to be reflected in `.env.example` so anyone setting up a hosted instance knows they exist and what values to use.

### Required Changes

- Add `MCP_TRANSPORT=http` and `PORT=8000` to `.env.example` with comments explaining their purpose and valid values.

## Issue 4: README Does Not Cover Hosted Setup

The README currently only documents local client configuration (Claude Desktop, Claude Code, Cursor, etc.). A hosted deployment requires different setup steps. These should be documented to make the hosted path self-contained for anyone following the repo.

### Required Changes

- Add a `Hosted Deployment` section to `README.md` covering:
  - Setting `MCP_TRANSPORT=http` and `PORT`
  - Running the server so it binds to the configured port
  - That a reverse proxy or tunnel (e.g. Cloudflare Tunnel) should point to that port over HTTPS
  - That Claude.ai and ChatGPT connect via the public HTTPS URL in their connector settings

## Affected User Stories

This CR is infrastructure — it does not map to a specific PRD user story but is a prerequisite for all multi-user hosted scenarios, including the planned Entra OAuth integration (future CR) and per-user ownership stamping.

## Acceptance Criteria

- Running the server with `MCP_TRANSPORT=http` causes it to bind on the configured `PORT` and respond to HTTP requests from an MCP client.
- Running the server without `MCP_TRANSPORT` set (or with `MCP_TRANSPORT=stdio`) behaves identically to the current behaviour. No existing local configuration files need to change.
- A `curl` or browser request to `http://localhost:<PORT>/` returns a valid response (not a connection error), confirming the server is listening.
- `uvicorn` is listed in `pyproject.toml` and installs cleanly with `pip install -e .` or `uv pip install -e .`
- `.env.example` includes `MCP_TRANSPORT` and `PORT` with comments.
- `README.md` includes a hosted deployment section.

## Out of Scope

- Entra OAuth / token validation (separate future CR)
- Per-user identity and owner injection (separate future CR)
- Proxmox LXC setup or Cloudflare Tunnel configuration (infrastructure, not code)
- Any changes to existing tool definitions or Bullhorn API logic
