---
name: bullhorn-mcp-build-and-env
description: Load when setting up this repo from scratch, when a fresh install or fresh clone fails (especially "ModuleNotFoundError: No module named 'fastmcp'"), when tests will not collect or import, when you need the canonical test commands and expected counts, when editing pyproject.toml or dependency versions, when a FastMCP upgrade breaks APIs, or when asked about CI. Provides the verified install runbook, pyproject anatomy, Python and dependency version facts, the undeclared-fastmcp open debt, the FastMCP 3.x breakage history, and the no-CI reality.
---

# Build and Environment: bullhorn-mcp-python

Everything needed to recreate a working dev environment from a bare clone and to understand the dependency landscape. All commands run from the repo root. All facts verified against the repo on 2026-07-03 (tag v0.0.46, 648 tests).

Jargon used below: MCP is the Model Context Protocol; FastMCP is the third-party Python framework this server is built on (distinct from the official `mcp` SDK package, which is also installed); uv is the Python package manager used here; an editable install (`pip install -e`) links the venv to the source tree so code edits take effect without reinstall; a venv is a Python virtual environment; a CR is a Change Request document (CRx.md in repo root) under this project's change control.

## Install runbook (verified 2026-07-03 in a fresh venv)

Run in order:

```bash
uv venv
uv pip install -e ".[dev]"
uv pip install fastmcp    # REQUIRED workaround, see OPEN DEBT below
```

Then verify:

```bash
.venv/bin/python -c "import bullhorn_mcp.server; print('server import OK')"
.venv/bin/pytest
```

Expected: `648 passed` in roughly 38 to 40 seconds, as of 2026-07-03 (v0.0.46).

If you skip step 3, step 4's import fails and the entire test suite fails at collection. This is not your mistake; it is known debt, next section.

## OPEN DEBT: fastmcp is imported but not declared

- `pyproject.toml` declares only `mcp>=1.0.0`, `httpx>=0.27.0`, `python-dotenv>=1.0.0`, `uvicorn>=0.30.0`. `fastmcp` appears nowhere in it (verify: `grep fastmcp pyproject.toml` returns nothing).
- But the code hard-imports it: `from fastmcp import FastMCP` (src/bullhorn_mcp/server.py:14), `from fastmcp.server.auth.oidc_proxy import OIDCProxy` (server.py:15), `from fastmcp.server.dependencies import get_access_token` (src/bullhorn_mcp/identity.py:16), plus `fastmcp.Client` in tests/test_server.py. Line numbers as of 2026-07-03.
- Proven fresh-install failure (reproduced 2026-07-03 in an isolated venv): `uv venv && uv pip install -e ".[dev]"` then `import bullhorn_mcp.server` raises `ModuleNotFoundError: No module named 'fastmcp'`, and `pytest tests/test_server.py` dies with a collection error.
- The `mcp` package does NOT pull in `fastmcp` (fastmcp depends on mcp, not the reverse).
- This gap was explicitly flagged in CR18.md ("Surface separately, not part of this CR") and never fixed. It is OPEN BACKLOG, not accepted design.
- Version drift is already real: the project venv has fastmcp 3.2.4 (installed ad hoc); a fresh `uv pip install fastmcp` on 2026-07-03 pulled 3.4.2. The full 648-test suite passed under 3.4.2 in a fresh venv, so 3.4.2 is compatible today, but nothing pins this.

**Workaround:** always run `uv pip install fastmcp` after the editable install. Check what you got with `.venv/bin/pip show fastmcp`.

**Suggested CR:** declare `fastmcp` in `[project].dependencies` with an upper-bounded version range (for example `fastmcp>=3.2,<4`). Pin carefully: FastMCP has broken this project before within a major version series (see the Sprint 15 history below), so a CR that adds the declaration should also record the tested version and keep the bound tight enough that a surprise major bump cannot land silently.

## Python version facts

| Fact | Value (as of 2026-07-03) | Verify |
|---|---|---|
| `requires-python` in pyproject | `>=3.10` | `grep requires-python pyproject.toml` |
| Actual dev venv interpreter | Python 3.14.6 | `.venv/bin/python --version` |
| `.python-version` file | none exists; uv picks the interpreter | `ls .python-version` (errors) |

Implication: a fresh `uv venv` on another machine may pick a different 3.10+ interpreter. No pinning mechanism exists. If interpreter-specific behavior ever matters, adding a `.python-version` would be a one-line CR.

## pyproject.toml anatomy (as of 2026-07-03)

| Section | Content | Notes |
|---|---|---|
| `[project]` | name `bullhorn-mcp`, version `0.1.0` (static) | Real versioning is git tags v0.0.N; the pyproject version is never bumped |
| `dependencies` | `mcp>=1.0.0`, `httpx>=0.27.0`, `python-dotenv>=1.0.0`, `uvicorn>=0.30.0` | fastmcp missing (OPEN DEBT above) |
| `[project.optional-dependencies].dev` | `pytest>=8.0.0`, `pytest-asyncio>=0.23.0`, `respx>=0.21.0` | respx mocks httpx in tests |
| `[project.scripts]` | `bullhorn-mcp = "bullhorn_mcp.server:main"` | Console script; only exists after an editable or wheel install |
| `[build-system]` | hatchling | `[tool.hatch.build.targets.wheel] packages = ["src/bullhorn_mcp"]` (src layout) |
| `[tool.pytest.ini_options]` | `testpaths = ["tests"]`, `pythonpath = ["src"]` | Nothing else; no `asyncio_mode` key |

Installed versions in the project venv as of 2026-07-03: mcp 1.26.0, fastmcp 3.2.4, httpx 0.28.1, uvicorn 0.41.0, python-dotenv 1.2.2, pytest 9.0.2, pytest-asyncio 1.3.0, respx 0.22.0. Check any of these with `.venv/bin/pip show <name>`.

What the pytest config implies:

- `pythonpath = ["src"]` means pytest imports `bullhorn_mcp` straight from source. Tests run even with the package uninstalled (verified 2026-07-03: uninstalling `bullhorn-mcp` from a venv left the suite green). The editable install is still needed for the `bullhorn-mcp` console script and to pull in runtime dependencies.
- `testpaths = ["tests"]` means bare `.venv/bin/pytest` from repo root finds everything.
- pytest-asyncio runs in strict mode by its own default (no `asyncio_mode` is configured). Every async test needs an explicit `@pytest.mark.asyncio` marker; there are 10 in tests/test_server.py and 10 in tests/test_descriptions.py as of 2026-07-03. An unmarked async test silently never runs its body under strict mode, so always add the marker.

## Test commands

| Task | Command | Expected (as of 2026-07-03) |
|---|---|---|
| Full suite | `.venv/bin/pytest` | 648 passed, ~38-40s |
| Quiet, stop at first failure | `.venv/bin/pytest -q -x` | same |
| Single file | `.venv/bin/pytest tests/test_auth.py` | 13 passed |
| Single test | `.venv/bin/pytest tests/test_auth.py::TestBullhornAuth::test_full_auth_flow` | 1 passed |
| Single class | `.venv/bin/pytest tests/test_server.py::TestCreateCandidate` | subset passes |

For how to WRITE tests (mocking layers, fixture traps, payload-assertion law), see bullhorn-mcp-testing-playbook.

## FastMCP 3.x dependency-drift history (why pinning matters)

After tag v0.0.15, a FastMCP upgrade within the 3.x series broke 4 tests with zero code changes in this repo. Fixed in Sprint 16 (commit 60cc9f7). The breakages and the current correct APIs:

| Old API (gone) | Current API (in use as of 2026-07-03) |
|---|---|
| `mcp._tool_manager._tools` for tool inventory | `asyncio.run(mcp.list_tools())` |
| `mcp.settings.port` | keep the port in a module variable (`_port` in server.py) |
| `mcp.run()` without server kwargs | `mcp.run(transport="streamable-http", host=_host, port=_port)` (server.py:3372) |

Also relied on by the code and verified against fastmcp 3.2.4 (per CR18.md): `mcp.get_tool()` is async, and `FunctionTool.description` is mutable (the startup description enrichment depends on both). Any fastmcp upgrade should re-run the full suite and eyeball these call sites before tagging.

## No CI exists

There is no `.github/` directory, no pipeline config of any kind (verify: `ls .github` errors). Tests run locally only. The adversarial review loop (see bullhorn-mcp-review-protocol) is the ONLY quality gate before push and tag; do not assume anything re-runs the suite for you.

**OPEN DEBT, suggested CR:** a minimal CI workflow that runs `uv venv`, the install steps (including the fastmcp workaround until it is declared), and `.venv/bin/pytest` on push. This would also catch the undeclared-fastmcp class of bug automatically, since CI starts from a truly fresh environment every run. Candidate idea only; no spec exists.

## .env setup

```bash
cp .env.example .env
# then fill in the four required Bullhorn credentials:
# BULLHORN_CLIENT_ID, BULLHORN_CLIENT_SECRET, BULLHORN_USERNAME, BULLHORN_PASSWORD
```

- Missing any of the four makes `BullhornConfig.from_env()` raise; tests do NOT need a `.env` (everything is mocked), only live-API work and running the server do.
- `.gitignore` covers `.env`, `*.env.local`, and `CASE_STUDY.md` (a client-confidential file that was once committed and reverted; never re-add it). Verify: `grep -E "^\.env|CASE_STUDY" .gitignore`.
- A real `.env` with live credentials exists on the primary dev machine; the live-API rules for using it are owned by bullhorn-mcp-live-api-method.
- Full semantics of every env var (the optional BULLHORN_*, MCP_TRANSPORT, Entra, UPLOAD_SECRET, per-tenant config vars): see bullhorn-mcp-config-and-flags.

## When NOT to use this skill

| If you need... | Load instead |
|---|---|
| Writing or fixing tests, mocking architecture, fixture traps | bullhorn-mcp-testing-playbook |
| Starting the server (stdio or HTTP), client configs, production deploy at /opt/bullhorn-mcp | bullhorn-mcp-run-and-operate |
| Meaning and effect of individual env vars and constants | bullhorn-mcp-config-and-flags |
| Bullhorn OAuth or Entra identity internals | bullhorn-mcp-auth-and-identity |
| The CRx.md lifecycle, committing, tagging | bullhorn-mcp-change-control |
| Module map and code invariants | bullhorn-mcp-architecture-contract |

## Provenance and maintenance

Each row is a claim category above and a command a future session can run to re-verify it (all from repo root):

| Claim | Re-verify with |
|---|---|
| fastmcp absent from pyproject | `grep fastmcp pyproject.toml` (expect no output) |
| fastmcp import sites and line numbers | `grep -n "from fastmcp" src/bullhorn_mcp/*.py tests/*.py` |
| Installed fastmcp/mcp versions | `.venv/bin/pip show fastmcp mcp \| grep -E "^(Name\|Version)"` |
| Fresh-install failure still reproduces | in a throwaway dir: `uv venv && uv pip install -e "<repo>[dev]" && ./.venv/bin/python -c "import bullhorn_mcp.server"` |
| Test count and duration | `.venv/bin/pytest -q \| tail -1` |
| Python version facts | `.venv/bin/python --version; grep requires-python pyproject.toml; ls .python-version` |
| pyproject anatomy (deps, scripts, pytest config) | `cat pyproject.toml` |
| asyncio marker counts | `grep -c "pytest.mark.asyncio" tests/test_server.py tests/test_descriptions.py` |
| Sprint 15 FastMCP breakage record | `git show 60cc9f7 --stat` and read the commit message |
| Current mcp.run() call shape | `grep -n "mcp.run" src/bullhorn_mcp/server.py` |
| Still no CI | `ls .github` (expect error) |
| .gitignore coverage of .env and CASE_STUDY.md | `grep -E "^\.env\|CASE_STUDY" .gitignore` |
| CR18 flagged the dependency gap | `grep -n "pyproject" CR18.md` |
