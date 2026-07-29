---
name: bullhorn-mcp-config-and-flags
description: Load this skill whenever you need to know what an environment variable or code constant does in bullhorn-mcp-python, when it is read (import time vs lazily), what its default is, or where it lives; when adding, changing, or debugging any config axis (BULLHORN_*, MCP_TRANSPORT, PORT, HOST, ENTRA_*, UPLOAD_SECRET); when a server crashes at import or a tenant-specific behavior (required fields, aliases, defaults, shortlist status) needs adjusting; or when deciding whether a behavior belongs in code or in env config. Provides the complete verified env var table, the code constants table, the per-tenant config philosophy from CR14/CR15/CR25, and the checklist for adding a new config axis.
---

# Bullhorn MCP: Configuration and Flags

Single source of truth for every configuration axis in this repo. Two layers exist:

1. **Environment variables**: deployment-time and tenant-specific settings, loaded from the process environment or a `.env` file (a local key=value file read by `python-dotenv`).
2. **Code constants**: module-level Python values that encode API knowledge (default field lists, entity denylists, alias maps, thresholds).

Jargon used below: a **CR** is a Change Request, a numbered `CRx.md` plan file in the repo root that gates all non-trivial changes (see bullhorn-mcp-change-control). A **picklist** is a Bullhorn dropdown field whose valid values come from `/meta` metadata as `{value, label}` option dicts. An **alias** is a human-friendly label (e.g. "job title") mapped to a real Bullhorn API field name (e.g. `occupation`). **Enrichment** is the startup step that appends live field summaries from `/meta` to tool descriptions.

All line numbers below are as of 2026-07-03 (v0.0.46, 648 tests). Re-verify with the commands in Provenance before relying on them.

## Environment variable table (complete)

`load_dotenv()` runs twice: at `src/bullhorn_mcp/server.py:29` (module import) and inside `BullhornConfig.from_env()` at `src/bullhorn_mcp/config.py:22` (lazy). So `.env` values are available to the import-time reads below when the server module is imported.

### Bullhorn credentials and endpoints (read lazily)

Read inside `BullhornConfig.from_env()`, which `get_client()` (server.py:229) calls on first tool use, NOT at import. Importing server.py never requires credentials (see bullhorn-mcp-architecture-contract for why that invariant matters).

| Var | Read at | Required | Default | Effect |
|---|---|---|---|---|
| `BULLHORN_CLIENT_ID` | config.py:24 | yes | none | OAuth client id. Any of the four missing raises `ValueError` naming all missing vars (config.py:39-40) |
| `BULLHORN_CLIENT_SECRET` | config.py:25 | yes | none | OAuth client secret |
| `BULLHORN_USERNAME` | config.py:26 | yes | none | API user (service account recommended) |
| `BULLHORN_PASSWORD` | config.py:27 | yes | none | API user password |
| `BULLHORN_AUTH_URL` | config.py:47 | no | `https://auth.bullhornstaffing.com` | Initial auth host. Regional redirects are handled separately at runtime (see bullhorn-mcp-auth-and-identity) |
| `BULLHORN_LOGIN_URL` | config.py:48 | no | `https://rest.bullhornstaffing.com` | REST login host |

### Transport and hosting (read at IMPORT time)

These are read into module-level variables when `server.py` is imported. Changing the environment after import has no effect; `main()` dispatches on the module variable `_transport_mode`, not on `os.environ`.

| Var | Read at | Required | Default | Effect |
|---|---|---|---|---|
| `MCP_TRANSPORT` | server.py:160 | no | `stdio` | `stdio` or `http`. Any other value raises `ValueError` inside `main()` (server.py:3376-3379), not at import |
| `PORT` | server.py:161 | no | `8000` | HTTP listen port. Ignored in stdio mode |
| `HOST` | server.py:163 | no | `0.0.0.0` in http mode, `127.0.0.1` in stdio | Bind address |
| `ENTRA_TENANT_ID` | server.py:177 | http mode only | none | Entra (Microsoft's identity platform) tenant for OIDC |
| `ENTRA_CLIENT_ID` | server.py:178 | http mode only | none | Entra app registration id |
| `ENTRA_CLIENT_SECRET` | server.py:179 | http mode only | none | Entra app secret |
| `MCP_BASE_URL` | server.py:180 | http mode only | none | Public base URL of the hosted server |

The four Entra vars are read inside `_build_auth()` (server.py:166), which runs at import because `mcp = FastMCP(..., auth=_build_auth())` is a module-level statement (server.py:212). In http mode, ANY missing Entra var raises `ValueError` at import: deliberate fail-closed design so an unprotected HTTP endpoint cannot start. In stdio mode `_build_auth()` returns `None` without reading them. What the Entra values do at runtime is owned by bullhorn-mcp-auth-and-identity.

**Import-time hazards:**

- `PORT` goes through `int()` at import (server.py:161). A non-numeric value (e.g. `PORT=default`) crashes EVERY import of server.py, including `pytest` collection, with a `ValueError` traceback that does not mention PORT by name. If imports suddenly fail, check `PORT` first.
- `MCP_TRANSPORT` is read at import, so tests that `importlib.reload(server)` must pin the environment (e.g. `patch.dict(os.environ, {"MCP_TRANSPORT": "stdio"})`) or a stale `http` value makes the reload demand Entra vars and fail. Tests of `main()` dispatch should patch `server._transport_mode` directly (see bullhorn-mcp-testing-playbook for the fixture mechanics).

### Per-request secret

| Var | Read at | Required | Default | Effect |
|---|---|---|---|---|
| `UPLOAD_SECRET` | server.py:3266 | no | none | Shared secret for the `POST /upload-cv` route, compared timing-safe per request. Unset means the route returns 400 on every request (fail-closed). Generate with `openssl rand -hex 32` |

### Per-tenant business config (JSON in env)

All parsed by a `_load_json_env()` helper (identical in both config modules): missing var returns the default; invalid JSON logs a warning and returns the default so the server ALWAYS starts. Wrong top-level type (e.g. a JSON string where an object is expected) also falls back silently.

| Var | Read at | When read | Default | Effect |
|---|---|---|---|---|
| `BULLHORN_JOBORDER_ALIASES` | joborder_config.py:33 | metadata.py module import (merged into `FIELD_ALIASES["JobOrder"]`) | `{}` | JSON object `{"alias_lowercase": "api_field_name"}`. Keys lowercased. Env entries override hardcoded aliases on conflict |
| `BULLHORN_JOBORDER_REQUIRED` | joborder_config.py:41 | each `create_job` call (server.py:1514) | `[]` | JSON array of extra required fields beyond Bullhorn's hard minimum (`title`, `clientCorporation`, `clientContact`) |
| `BULLHORN_JOBORDER_DEFAULTS` | joborder_config.py:47 | each `create_job` call (server.py:1510) | `{}` | JSON object of default values. Caller values always win on conflict |
| `BULLHORN_CANDIDATE_ALIASES` | candidate_config.py:33 | metadata.py module import (merged into `FIELD_ALIASES["Candidate"]`) | `{}` | Same alias pattern for Candidate |
| `BULLHORN_CANDIDATE_REQUIRED` | candidate_config.py:41 | each `create_candidate` / `create_candidate_from_cv` call (server.py:1987, 2328) | `[]` in code, but `.env.example` ships it UNCOMMENTED as `'["firstName","lastName","occupation","companyName","email","source"]'` (a CR25 data-quality decision), so fresh deployments that copy the example inherit that list |
| `BULLHORN_CANDIDATE_DEFAULTS` | candidate_config.py:47 | each create-candidate call (server.py:1969, 2317) | `{}` | Default values; caller wins |
| `BULLHORN_MCP_SOURCE` | candidate_config.py:57 | each create-candidate call (server.py:1984, 2322), only when caller omits `source` | `"Claude"` | Value stamped into `source` on MCP-created candidates. Must be a valid `Candidate.source` picklist value in the tenant. Plain string, not JSON. `.env.example` ships it uncommented as `BULLHORN_MCP_SOURCE=Claude` |
| `BULLHORN_SHORTLIST_STATUS` | shortlist_config.py:13 | each shortlist call (server.py:2903) | `"Shortlisted"` (`DEFAULT_SHORTLIST_STATUS`, shortlist_config.py:5) | JobSubmission status used by the shortlist tools. Validated ONCE per process against the live picklist by `_validate_shortlist_status_once` (server.py:2793): mismatch logs a warning listing valid values, never blocks. Plain string, not JSON |

Because ALIASES vars are consumed when `metadata.py` is imported (the `FIELD_ALIASES` dict is built at module load), changing them requires a process restart; REQUIRED/DEFAULTS/SOURCE/STATUS are re-read on every relevant tool call, but in practice all env changes should be treated as restart-required.

`.env.example` note: the four `ENTRA_*`/`MCP_BASE_URL` lines are present uncommented with EMPTY values. That is harmless in stdio mode (never read) and in http mode empty strings are falsy, so the fail-closed ValueError still fires.

## Per-tenant config philosophy (CR14, CR15, CR25)

These rules are the settled design, established after CR13's `create_job` shipped hardcoded instance-specific field rules and was uncallable (see bullhorn-mcp-failure-archaeology for that story):

| Rule | Rationale | Origin |
|---|---|---|
| Instance-specific business rules (aliases, required fields, defaults, status strings, source stamps) live in env config, never in code | Other Bullhorn tenants must not inherit one consultancy's local rules; operators fix mappings without a code release | CR14 |
| Invalid JSON warns and falls back to the empty default; the server always starts | A typo in one config value must not take the whole server down | CR14 |
| Caller-supplied values always win over env DEFAULTS | Defaults are a floor, not an override; the agent's explicit intent is authoritative | CR14 |
| Env alias entries override hardcoded `FIELD_ALIASES` entries on key conflict | Operators can correct a wrong built-in mapping without waiting for a code change | CR14 |
| Alias targets are NOT validated at load time | Misconfiguration surfaces as a Bullhorn error at write time, close to the operator who set it | CR14 |
| Never write `.env` at runtime | Hosted deployments often have read-only filesystems; production env comes from systemd/k8s/compose where the file may not exist; mutating config from inside the app blurs deploy-time vs runtime | CR15 (explicit rejected-alternative record) |
| Ship opinionated data-quality defaults in `.env.example` where the tenant wants them (e.g. `BULLHORN_CANDIDATE_REQUIRED` uncommented) | Real production data-quality gaps found in live stress testing | CR25 |
| Env picklist-dependent values (shortlist status, MCP source) are validated against live metadata with warn-only semantics | Catch misconfiguration without making startup depend on Bullhorn being reachable | CR25 |

## Code constants table

Locations as of 2026-07-03 (v0.0.46). Paths are relative to repo root, under `src/bullhorn_mcp/`.

| Constant | Location | What it controls |
|---|---|---|
| `DEFAULT_FIELDS` | client.py:14-39 | Per-entity default field selection, 8 entities (JobOrder, Candidate, Placement, ClientCorporation, ClientContact, JobSubmission, UserMessage, Tearsheet). Fallback for unlisted entities: `"id"` on search/query (client.py:249, 324), `"*"` on get (client.py:389). The `"*"` fallback is a hazard: some tenants reject `fields=*` per entity (see bullhorn-mcp-api-quirks) |
| `_ENTITIES_WITHOUT_ISDELETED` | client.py:11 | `frozenset({"ClientCorporation", "UserMessage"})`. Fast-path denylist: skip the auto-appended soft-delete clause for entities known to lack `isDeleted` |
| `_isdeleted_cache` | client.py:49 (instance attr, populated by `_entity_has_isdeleted` at client.py:51) | Per-process memo of `/meta`-detected `isDeleted` presence per entity. On `/meta` error: returns True (append clause, safe default) and does NOT cache, so it can re-detect later |
| `FIELD_ALIASES` | metadata.py:23-38 | Hardcoded label-to-API-name overrides per entity, checked BEFORE dynamic metadata lookup (review failure pattern 8). Candidate and JobOrder entries merge env aliases at module load, env wins. `"JobSubmission": {}` is reserved, currently empty |
| `SUPPORTED_ENTITIES` | descriptions.py:26-37 | The 10 entities fetched from `/meta` at startup for enrichment (includes Tearsheet since CR32) |
| `PICKLIST_FIELDS_TO_EXPAND` | descriptions.py:41-47 | `{status, employmentType, category, type, source}`: the only field names whose picklist options get inlined into tool descriptions |
| `GENERIC_DISCOVERY_TOOLS` | descriptions.py:51-56 | `{search_entities, query_entities, update_record, get_entity_fields}`: get compact name-only field sections instead of full ones (CR34 token-cost split) |
| `TOOL_ENTITY_MAP` | descriptions.py:61-100 | Tool name to entity list for enrichment; 38 entries. Any new tool touching an entity must be added here or it gets no field reference |
| `MAX_FIELDS_PER_ENTITY` | descriptions.py:16 | 40, cap on fields per full entity section |
| `_CUSTOM_FIELD_RE` | descriptions.py:21-23 | Matches generated custom-field names (`customText1` etc.); such fields are included in descriptions only when their label differs from their name |
| `_PLACEMENT_DEFAULT_FIELDS` | server.py:513 | `= DEFAULT_FIELDS["Placement"]`, a REFERENCE, deliberately not a copied string (see rule below) |
| `_PCR_DEFAULT_FIELDS` | server.py:514-519 | PlacementChangeRequest default fields with nested `placement(...)` projection |
| `_NOTE_TARGET_ENTITIES` | server.py:1622 | The 7 entity types accepted by the note tools |
| `_CC_TAG_RE` | server.py:1633 | Regex stripping click-to-call telemetry tags from note comments into `call_metadata` |
| `_NOTE_ENTITY_SUBJECT_FIELD` | server.py:1640 | Entity-to-subject-field map mirroring `add_note`'s internal `_ENTITY_FIELD` (client.py:435). OPEN DEBT: currently unreferenced by any tool body; keep or delete via a CR (natural candidate: the CR35 consolidation), do not silently remove |
| `_NOTE_DEFAULT_FIELDS` / `_NOTE_SEARCH_DEFAULT_FIELDS` | server.py:1650 / 1663 | Default field strings for note reads. Both deliberately exclude `clientCorporation` (Bullhorn rejects it). OPEN DEBT: they are byte-identical duplicates with a keep-in-sync comment and have diverged once before (CR22); consolidating to one constant is a CR35-sized cleanup |
| `_SUFFIXES` / `_STOP_WORDS` | fuzzy.py:9 / fuzzy.py:15 | Company-name normalization noise lists for fuzzy matching |
| Fuzzy thresholds | fuzzy.py:74-90 (`categorize_score`) | exact >= 0.95, likely >= 0.75, possible >= 0.50, else none; acronym matches boosted to 0.82 (fuzzy.py:69). How dedup guards consume these is owned by bullhorn-mcp-architecture-contract |
| `DEFAULT_SHORTLIST_STATUS` | shortlist_config.py:5 | `"Shortlisted"`, fallback for `BULLHORN_SHORTLIST_STATUS` |
| Lazy globals | server.py:223-226 | `_client`, `_metadata`, `_shortlist_status_validated`, `_valid_note_actions`: per-process lazy singletons. Tests reset them via the autouse fixture (bullhorn-mcp-testing-playbook) |
| `_caller_cache` | identity.py:30 | Identity cache dict keyed by Entra `sub` claim; runtime semantics owned by bullhorn-mcp-auth-and-identity |

### The reference-never-copy rule (CR33 M1)

Never duplicate a constant's VALUE at a second site; reference the source symbol instead. CR33 shipped `_PLACEMENT_DEFAULT_FIELDS` as a copied string of `DEFAULT_FIELDS["Placement"]`; review flagged it M1 (drift risk) and the fix made it `= DEFAULT_FIELDS["Placement"]`. The note-fields duplicate pair above is the standing counterexample and it did drift once. When you need an existing field list elsewhere, import and reference it. If two constants must stay equal but cannot share a symbol, add a keep-in-sync comment at BOTH sites and prefer proposing a CR to unify them.

## How to add a new config axis

Route through change control; a config axis is a behavior contract with operators, not a quick edit.

1. **Write a CR first** (`CRx.md` in repo root, per CLAUDE.md and bullhorn-mcp-change-control). State the tenant-specific behavior being externalized and why code is the wrong home for it.
2. **Follow the `joborder_config.py` pattern**: a small module `src/bullhorn_mcp/<entity>_config.py` with a `_load_json_env(var_name, default)` helper and one getter per var. Copy the shape from `src/bullhorn_mcp/candidate_config.py` (the most complete example).
3. **Warn-and-continue parsing**: invalid JSON or wrong top-level type logs a warning and returns the default. The server must always start. Never raise from a config getter.
4. **Respect precedence rules**: caller values win over env defaults; env aliases win over hardcoded `FIELD_ALIASES` entries (merge env LAST with `**get_..._aliases()`).
5. **Decide read timing consciously**: aliases merge at metadata module import (restart required); required/defaults/status read per call. Document which in the module docstring. Avoid new import-time reads in server.py; they crash pytest collection when malformed (the `PORT` lesson).
6. **Never write `.env` at runtime** (CR15). Config flows in one direction: environment to process.
7. **Add a `.env.example` entry**: commented-out by default with format documentation and a realistic example value; uncommented only if the CR explicitly decides to ship an opinionated default (the `BULLHORN_CANDIDATE_REQUIRED` precedent).
8. **Add a README entry** in the per-instance configuration tables (README.md has existing `BULLHORN_JOBORDER_*` and `BULLHORN_CANDIDATE_*` sections to mirror).
9. **Write tests** in `tests/test_<entity>_config.py` covering at minimum: default when unset, override when set, invalid-JSON fallback, wrong-type fallback. Model on `tests/test_candidate_config.py` (10 tests) or `tests/test_joborder_config.py` (10 tests). Run them: `.venv/bin/pytest tests/test_candidate_config.py tests/test_joborder_config.py tests/test_shortlist_config.py`.
10. **If the axis touches a write path**, add payload-assertion tests proving the env value lands in (or stays out of) the raw request body (law owned by bullhorn-mcp-testing-playbook).
11. **If a tool call reads the var lazily**, remember existing server tests may inherit your shipped `.env` default: the `TestCreateCandidate` classes need an autouse fixture patching `get_candidate_required` to `[]` for exactly this reason.

## When NOT to use this skill

| Adjacent topic | Owning skill |
|---|---|
| What the config-related invariants mean architecturally (lazy client, import purity, error surfaces) | bullhorn-mcp-architecture-contract |
| Runtime behavior of the auth vars: OAuth flow, Entra OIDC, identity resolution, `_caller_cache` semantics, owner stamping | bullhorn-mcp-auth-and-identity |
| Install, venv, dependency traps (including the undeclared `fastmcp` dependency), pyproject anatomy | bullhorn-mcp-build-and-env |
| Starting the server, client configs, production topology, `/upload-cv` operations | bullhorn-mcp-run-and-operate |
| Test fixtures, mocking, env pinning mechanics in tests | bullhorn-mcp-testing-playbook |
| Writing the CR itself, tagging, plan bookkeeping | bullhorn-mcp-change-control |
| Bullhorn field/endpoint quirks that motivated specific constants | bullhorn-mcp-api-quirks |
| Enrichment content rules and token budgets (what goes INTO descriptions) | bullhorn-mcp-docs-and-writing |

## Provenance and maintenance

Every fact above was verified against the working tree at v0.0.46 on 2026-07-03. Re-verify before trusting line numbers or counts:

| Claim | Re-verification command |
|---|---|
| Complete env var read sites | `grep -rn "os.environ\|getenv\|load_dotenv" src/` |
| Import-time transport/port/host reads and Entra fail-closed | `sed -n '156,214p' src/bullhorn_mcp/server.py` |
| PORT int() at import | `grep -n 'int(os.environ.get("PORT"' src/bullhorn_mcp/server.py` |
| UPLOAD_SECRET per-request read | `grep -n UPLOAD_SECRET src/bullhorn_mcp/server.py` |
| Config getter call sites (lazy vs import) | `grep -n "get_joborder_\|get_candidate_\|get_mcp_source\|get_shortlist_status" src/bullhorn_mcp/*.py` |
| Warn-and-fallback JSON parsing | `grep -n "_load_json_env" -A 9 src/bullhorn_mcp/candidate_config.py` |
| .env.example shipped defaults (uncommented lines) | `grep -vn '^#\|^$' .env.example` |
| DEFAULT_FIELDS entities and fallbacks | `sed -n '9,40p' src/bullhorn_mcp/client.py && grep -n 'DEFAULT_FIELDS.get' src/bullhorn_mcp/client.py` |
| FIELD_ALIASES contents and env merge | `sed -n '23,38p' src/bullhorn_mcp/metadata.py` |
| descriptions.py constants and TOOL_ENTITY_MAP size | `grep -n "MAX_FIELDS_PER_ENTITY\|SUPPORTED_ENTITIES\|PICKLIST_FIELDS_TO_EXPAND\|GENERIC_DISCOVERY_TOOLS\|TOOL_ENTITY_MAP" src/bullhorn_mcp/descriptions.py` |
| server.py constants (placement, notes, lazy globals) | `grep -n "_PLACEMENT_DEFAULT_FIELDS\|_PCR_DEFAULT_FIELDS\|_NOTE_TARGET_ENTITIES\|_NOTE_ENTITY_SUBJECT_FIELD\|_NOTE_DEFAULT_FIELDS\|_NOTE_SEARCH_DEFAULT_FIELDS\|_CC_TAG_RE\|_shortlist_status_validated\|_valid_note_actions" src/bullhorn_mcp/server.py` |
| Fuzzy thresholds | `sed -n '60,90p' src/bullhorn_mcp/fuzzy.py` |
| Shortlist default and warn-only validation | `cat src/bullhorn_mcp/shortlist_config.py && sed -n '2793,2815p' src/bullhorn_mcp/server.py` |
| Config test suites pass | `.venv/bin/pytest tests/test_candidate_config.py tests/test_joborder_config.py tests/test_shortlist_config.py tests/test_config.py -q` |
| CR14/CR15/CR25 philosophy sources | `grep -n "environment configuration\|falls back" CR14.md; grep -n "Why not write" CR15.md; grep -n "BULLHORN_CANDIDATE_REQUIRED\|BULLHORN_MCP_SOURCE" CR25.md` |
| CR33 M1 reference-never-copy | `git show 9da82c4 --stat && git log --oneline --grep="M1 duplicated Placement"` |
