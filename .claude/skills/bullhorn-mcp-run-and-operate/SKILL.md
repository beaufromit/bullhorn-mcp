---
name: bullhorn-mcp-run-and-operate
description: Load this skill when starting, deploying, or operating the Bullhorn MCP server in any mode. Triggers include launching the server (stdio or HTTP), writing or debugging an MCP client config (Claude Desktop, Claude Code, Cursor), "server refuses to start" or an import-time ValueError about Entra vars, questions about which URL the MCP endpoint lives at, tool descriptions missing their field reference (enrichment failure), operating or debugging the POST /upload-cv endpoint (401/400/500 responses, X-Upload-Secret), deploying or restarting the production box, and measuring or re-checking tool-description token cost after any docstring or descriptions.py change. Provides launch runbooks for both transports, verified client configs, the main() startup anatomy, /upload-cv operations, the production topology and human-in-the-loop deployment rule, and a runnable token-cost measurement script.
---

# Run and Operate the Bullhorn MCP Server

Operational runbook for the Bullhorn MCP server: an MCP (Model Context Protocol, the standard by which AI clients call external tools) server built on FastMCP (the Python MCP framework this project uses) that exposes Bullhorn CRM to AI assistants. All commands run from the repo root.

Volatile facts in this file are correct as of 2026-07-03 (tag v0.0.46, 648 tests, 38 tools). Line numbers cite src/bullhorn_mcp/server.py at that tag and will drift.

For installing the environment from scratch (including the undeclared fastmcp dependency trap), see the sibling skill bullhorn-mcp-build-and-env. For the full env var reference, see bullhorn-mcp-config-and-flags.

## stdio mode (default, local clients)

stdio is the default transport: the client spawns the server as a subprocess and talks over stdin/stdout. Requires a `.env` file (or exported env vars) with the 4 Bullhorn credentials (`BULLHORN_CLIENT_ID`, `BULLHORN_CLIENT_SECRET`, `BULLHORN_USERNAME`, `BULLHORN_PASSWORD`).

Start manually:

```bash
.venv/bin/python -m bullhorn_mcp.server
```

Or via the console script (entry point `bullhorn_mcp.server:main` in pyproject.toml):

```bash
.venv/bin/bullhorn-mcp
```

A stdio server prints nothing and waits for MCP protocol messages on stdin; that is normal. Ctrl-C to stop.

### Client configs (verified against README.md "Client Configuration", 2026-07-03)

Replace `/path/to/bullhorn-mcp-python` with the real install path.

**Claude Desktop** (add to its MCP config JSON):

```json
{
  "mcpServers": {
    "bullhorn": {
      "command": "/path/to/bullhorn-mcp-python/.venv/bin/python",
      "args": ["-m", "bullhorn_mcp.server"],
      "cwd": "/path/to/bullhorn-mcp-python"
    }
  }
}
```

**Claude Code** (CLI, passes credentials explicitly):

```bash
claude mcp add bullhorn \
  -e BULLHORN_CLIENT_ID=your_client_id \
  -e BULLHORN_CLIENT_SECRET=your_client_secret \
  -e BULLHORN_USERNAME=your_username \
  -e BULLHORN_PASSWORD=your_password \
  -- /path/to/bullhorn-mcp-python/.venv/bin/python -m bullhorn_mcp.server
```

**Cursor** (same JSON shape as Claude Desktop, including the `cwd` key).

Operational note on the JSON configs: they carry no `env` block, so credentials come from `.env` found via the working directory (`load_dotenv()` runs at server import). If a client ignores the `cwd` key, the server starts but `BullhornConfig.from_env()` raises on the first tool call because `.env` was never found. Symptom: every tool returns a credentials ValueError. Fix: add an `env` block with the 4 Bullhorn vars to the client config (the Claude Code example already does the equivalent with `-e`).

README staleness check (2026-07-03): the three client-config examples above match README.md exactly and are correct. However the README "Available tools" lists only 18 of the 38 actual tools and the write-target scope predates Candidate/JobSubmission/Tearsheet writes. OPEN DEBT: README tool inventory is stale; workaround is to trust `grep -c "@mcp.tool()" src/bullhorn_mcp/server.py`; suggest a docs CR (the drift catalog lives in bullhorn-mcp-docs-and-writing).

## HTTP mode (hosted, multi-user)

Set in the environment (or `.env`):

```env
MCP_TRANSPORT=http
PORT=8000
HOST=0.0.0.0
MCP_BASE_URL=https://your-domain.example.com
ENTRA_TENANT_ID=...
ENTRA_CLIENT_ID=...
ENTRA_CLIENT_SECRET=...
```

Then start the server exactly as in stdio mode (`.venv/bin/python -m bullhorn_mcp.server`). It runs FastMCP's streamable-http transport via `mcp.run(transport="streamable-http", host=..., port=...)`.

| Fact | Detail |
|---|---|
| Transport selection | `MCP_TRANSPORT`: `stdio` (default) or `http`; any other value raises ValueError in `main()` |
| Read at | Module import time (server.py lines 160-163 as of v0.0.46); `PORT` is `int()`-cast at import, so a non-numeric PORT crashes the import itself |
| PORT | Default 8000; ignored in stdio mode |
| HOST | Default `0.0.0.0` in http mode, `127.0.0.1` in stdio mode |
| Fail-closed auth | In http mode, `_build_auth()` (server.py line 166) requires ALL FOUR of `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`, `MCP_BASE_URL`; any missing raises `ValueError: HTTP transport requires Entra OAuth. Missing env vars: ...` at import time. It is impossible to accidentally run an unprotected HTTP endpoint |
| MCP endpoint URL | `{MCP_BASE_URL}/mcp` (locally `http://HOST:PORT/mcp`). `/mcp` is FastMCP's default `streamable_http_path` (verified in installed fastmcp 3.2.4 settings); this repo does not override it |
| Protection | Microsoft Entra (Azure AD) OIDC proxy; callers authenticate with their Entra identity |

Entra app registration, token lifetimes, scopes, and identity resolution are owned by the sibling skill bullhorn-mcp-auth-and-identity.

Because transport vars are read at import, tests or scripts that import server.py under a mutated environment must pin `MCP_TRANSPORT=stdio` (see bullhorn-mcp-testing-playbook).

## Startup anatomy: what main() does

`main()` (server.py line 3349 as of v0.0.46) runs, in order:

1. `asyncio.run(enrich_tool_descriptions(mcp, get_client()))`, stored into the module-global `_metadata`.
2. `mcp.run(...)` with the transport selected above.

Enrichment (the CR18/CR34 feature; CR means Change Request, the project's plan-file unit, see bullhorn-mcp-change-control) fetches `GET /meta/{entity}` (Bullhorn's field-metadata endpoint) for each of the 10 entities in `SUPPORTED_ENTITIES` (descriptions.py; Candidate, ClientContact, ClientCorporation, JobOrder, JobSubmission, Note, Placement, UserMessage, CorporateUser, Tearsheet as of v0.0.46) and appends a `## Field reference (auto-populated at startup)` section to each tool description per `TOOL_ENTITY_MAP`. Picklist values (a picklist is Bullhorn's admin-configured dropdown of valid values for a field) are inlined for a small set of field names. The returned `BullhornMetadata` instance is reused as the server's runtime metadata cache, so no second round of /meta fetches happens later. Design rationale is owned by bullhorn-mcp-docs-and-writing.

### Failure behavior: a dead Bullhorn still starts the server

The entire enrichment call in `main()` is wrapped in try/except. Failure layers, all non-fatal:

| Layer | Log line (logger name) | Effect |
|---|---|---|
| Whole enrichment (auth down, network dead) | `Could not enrich tool descriptions at startup: ...` (`bullhorn_mcp.server`, WARNING) | Server starts with static docstrings only |
| One entity's /meta fails | `Could not load metadata for {entity}: ...` (`bullhorn_mcp.descriptions`, WARNING) | Other entities still enrich |
| Zero entities loaded | `No entity metadata loaded -- tool descriptions will use static fallbacks` (`bullhorn_mcp.descriptions`, WARNING) | Static docstrings only |
| One tool lookup fails | `Could not enrich description for tool {name}: ...` (`bullhorn_mcp.descriptions`, WARNING) | Other tools still enrich |

How to notice enrichment failed:

- Check the server log (stderr locally; `journalctl -u bullhorn-mcp.service` in production) for the WARNING lines above.
- From the client side: tool descriptions lack the `## Field reference (auto-populated at startup)` header. The static docstrings of the 4 generic tools still point at `get_entity_fields`, so field discovery survives (a deliberate CR34 fallback).
- Definitive check: run the measurement script below; a total near the static baseline (6,428 chars measured 2026-07-03) instead of ~55k chars means enrichment did not run.

## Operating POST /upload-cv

`/upload-cv` is a non-MCP HTTP route registered via `mcp.custom_route` (server.py line 3346 as of v0.0.46). It accepts a CV as raw multipart bytes for automated pipelines (containerized CV intake, email-to-Bullhorn), bypassing the MCP tool layer so no base64 blob enters any conversation context. Only reachable in HTTP mode.

| Aspect | Behavior (verified in `_upload_cv_handler`, server.py line 3264) |
|---|---|
| Auth | `X-Upload-Secret` request header compared to the `UPLOAD_SECRET` env var with `hmac.compare_digest` (timing-safe; defeats timing attacks that guess a secret byte-by-byte) |
| `UPLOAD_SECRET` unset | Every request gets 400 `upload_secret_not_configured`: fail-closed, the endpoint is dead until configured |
| Wrong or missing header | 401 `unauthorized`, plus a WARNING log with the client IP |
| Generate a secret | `openssl rand -hex 32` |
| Two paths | `candidate_id` present: attach file to that Candidate. Absent: parse-and-create via `create_candidate_from_cv` (respects `force=true` to skip the duplicate check) |
| Bullhorn API error | 500 `bullhorn_error`; unexpected exception: 500 `internal_error` |
| Tool-level error JSON | 500, see below |

The f684bfc lesson (review finding C1, 2026-05-22): the create path calls the `create_candidate_from_cv` MCP tool function, which reports failures such as `identity_resolution_failed` by RETURNING an error-JSON string, not by raising. The handler originally forwarded that with HTTP 200, so callers logged success on failure. The fix parses the tool result and returns 500 whenever the JSON has an `"error"` key. If you touch this handler, preserve that mapping and its regression test; a 200-carrying-error response is a known, previously shipped bug class.

Smoke test:

```bash
curl -X POST https://your-server/upload-cv \
     -H "X-Upload-Secret: $UPLOAD_SECRET" \
     -F file=@jane_doe_cv.pdf -F filename=jane_doe_cv.pdf -F format=pdf
```

## Production topology and deployment

As documented in CR34-prompt-check.md and IMPLEMENTATION-PLAN.md Sprint 35 (the only docs of record for the deployment):

| Item | Value |
|---|---|
| Install path on the server | `/opt/bullhorn-mcp` |
| Process manager | systemd unit `bullhorn-mcp.service` |
| Rollout | `git pull` in `/opt/bullhorn-mcp`, then `systemctl restart bullhorn-mcp.service` (restart-based; no blue-green, no migrations) |
| Deploy verification | Compare `git rev-parse HEAD` on the box against the tagged commit; tree must be clean (`git status --short` empty) |

**Human-in-the-loop rule (mandatory):** the agent cannot reach the production server and must NOT SSH into it or run remote commands. To verify a deployment, print the exact commands for the human to run over their own SSH session, then STOP and wait for them to paste the output back before judging. CR34-prompt-check.md Part 2 is the canonical template for this loop; follow its shape for any future deploy check.

Commands to hand the human for a standard deploy check:

```bash
cd /opt/bullhorn-mcp && git rev-parse HEAD && git status --short
sudo systemctl restart bullhorn-mcp.service
systemctl status bullhorn-mcp.service --no-pager
journalctl -u bullhorn-mcp.service -n 50 --no-pager
```

In the journal output, look for the enrichment WARNING lines from the startup-anatomy table; their absence plus `Starting Bullhorn MCP server in HTTP mode on ...` means a healthy start.

OPEN DEBT: there is no documented rollback procedure, and how code reaches the box beyond `git pull` (deploy user, branch policy) is undocumented. Workaround: hand the human `cd /opt/bullhorn-mcp && git checkout <previous-tag> && sudo systemctl restart bullhorn-mcp.service`, verify with the deploy-check commands, and treat it as untested until exercised. Suggest a CR documenting deploy and rollback end to end. Never route around the CR, review, tag change control to "hotfix" the box directly.

## Token-cost operations

Tool descriptions are shipped to the client in every conversation; on clients that fetch tool definitions eagerly (claude.ai does), the entire payload is context overhead before the user types a word. This makes total description size an operational metric, not a style concern. History (CR34, tag v0.0.46): the payload had grown to ~111k estimated tokens of descriptions (~118k with parameter schemas), with 4 generic tools accounting for ~51.6k alone; CR34 cut it by roughly 80%.

Re-measure after ANY change to: descriptions.py (especially `TOOL_ENTITY_MAP`, `SUPPORTED_ENTITIES`, `MAX_FIELDS_PER_ENTITY`, `GENERIC_DISCOVERY_TOOLS`), any tool docstring, or when adding or removing a tool. Also re-measure occasionally with no code change: enrichment content comes from the live tenant's /meta, so an admin adding custom fields or picklist values grows the payload silently.

### scripts/measure_descriptions.py

Runnable, read-only (Bullhorn OAuth login plus one `GET /meta/{entity}` per supported entity; nothing is written). Requires a working `.env`. Run from the repo root:

```bash
.venv/bin/python .claude/skills/bullhorn-mcp-run-and-operate/scripts/measure_descriptions.py
```

It runs `enrich_tool_descriptions` exactly as `main()` does, then prints per-tool description size (chars and a chars/4 token estimate) sorted descending, plus the total, with the 4 generic tools marked `[generic]`.

Verified live 2026-07-03 (v0.0.46) against this tenant:

| Metric | Measured | Alarm threshold |
|---|---|---|
| Total | 55,123 chars, ~13,780 est. tokens across 38 tools | CR34 target is under ~20k tokens; anything drifting toward six figures is a regression |
| Largest tools | the 4 generic tools, ~2.9k chars (~730-740 tokens) each | CR34 target: each generic tool under ~1.5k tokens |
| Largest entity tools | list_placements ~706, attach_cv ~641, create_candidate_from_cv ~611 est. tokens | An entity tool jumping past the generic tools deserves a look |

If the total comes out near the static baseline of ~6.4k chars, enrichment did not run (you measured static docstrings); check credentials and the WARNING log lines first. The chars/4 figure is an estimate, good for trend detection, not billing. Note the script measures description text only; parameter schemas add roughly 7k more tokens on top (the CR34 figure), which this script does not count.

## When NOT to use this skill

| Topic | Go to |
|---|---|
| Installing the venv, dependency traps, pyproject, test commands | bullhorn-mcp-build-and-env |
| What an env var or constant means, defaults, per-tenant config | bullhorn-mcp-config-and-flags |
| Entra app setup, Bullhorn OAuth internals, identity resolution, token lifetimes | bullhorn-mcp-auth-and-identity |
| Why enrichment exists, docstring discipline, README drift catalog | bullhorn-mcp-docs-and-writing |
| Changing server.py code, invariants, tool inventory | bullhorn-mcp-architecture-contract |
| A tool returns wrong data or errors at runtime | bullhorn-mcp-debugging-playbook |
| Planning, committing, tagging the change you deploy | bullhorn-mcp-change-control |
| Live read-only verification of Bullhorn behavior | bullhorn-mcp-live-api-method |

## Provenance and maintenance

Every claim category below can drift; re-verify with the listed command before relying on it.

| Claim | Re-verify with |
|---|---|
| Transport/PORT/HOST defaults and import-time read | `sed -n '156,164p' src/bullhorn_mcp/server.py` |
| Fail-closed Entra check and the four var names | `grep -n -A28 "def _build_auth" src/bullhorn_mcp/server.py` |
| main() order (enrichment before mcp.run) and transport dispatch | `grep -n -A20 "def main" src/bullhorn_mcp/server.py` |
| MCP endpoint path `/mcp` | `.venv/bin/python -c "from fastmcp import settings; print(settings.streamable_http_path)"` |
| SUPPORTED_ENTITIES count and members | `grep -n -A13 "^SUPPORTED_ENTITIES" src/bullhorn_mcp/descriptions.py` |
| Enrichment warning log lines | `grep -n "logger.warning" src/bullhorn_mcp/descriptions.py src/bullhorn_mcp/server.py` |
| /upload-cv auth, status codes, error-JSON-to-500 mapping | `grep -n -B2 -A12 "UPLOAD_SECRET" src/bullhorn_mcp/server.py` and `git show f684bfc --stat` |
| Client config examples | `grep -n -A12 "### Claude Desktop" README.md` |
| README tool-list staleness (18 listed vs actual) | `grep -c "@mcp.tool()" src/bullhorn_mcp/server.py` vs the bullet count under README "Read tools"/"Write tools" |
| Production topology facts | `grep -n "opt/bullhorn-mcp\|bullhorn-mcp.service" CR34-prompt-check.md CR34.md IMPLEMENTATION-PLAN.md` |
| Token-cost numbers | rerun `scripts/measure_descriptions.py` (see above) |
| Tag/test-count stamps | `git describe --tags` and `.venv/bin/pytest -q` |
