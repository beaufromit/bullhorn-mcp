---
name: bullhorn-mcp-auth-and-identity
description: Load when working on authentication or attribution in bullhorn-mcp-python. Triggers include editing src/bullhorn_mcp/auth.py or identity.py or server.py _build_auth; AuthenticationError, "Failed to get auth code", "Token exchange failed", "REST login failed", or 401 loops; import-time ValueError "HTTP transport requires Entra OAuth"; identity_resolution_failed JSON from a tool; wrong owner or sendingUser stamped on created records; users being re-prompted to sign in; regional auth redirect (auth-apac) questions; Entra/OIDC/JWT/scope/token-lifetime configuration. Provides both auth systems end to end (Bullhorn non-standard OAuth and Entra OIDC), the identity cache design, owner/sendingUser/commentingPerson stamping rules, and an auth-failure triage table.
---

# Bullhorn MCP: Auth and Identity

This project has TWO independent auth systems. Do not conflate them.

| System | Protects | Where | Credentials |
|---|---|---|---|
| A. Bullhorn OAuth | Outbound calls to the Bullhorn REST API | `src/bullhorn_mcp/auth.py` | `BULLHORN_CLIENT_ID/SECRET/USERNAME/PASSWORD` (service account) |
| B. Microsoft Entra OIDC | Inbound HTTP connections to the MCP server itself | `_build_auth()` in `src/bullhorn_mcp/server.py`, `src/bullhorn_mcp/identity.py` | `ENTRA_TENANT_ID/CLIENT_ID/CLIENT_SECRET`, `MCP_BASE_URL` |

Jargon used below: MCP = Model Context Protocol (the tool protocol this server speaks). OAuth = the token-based authorization protocol; Bullhorn implements a non-standard variant. BhRestToken = Bullhorn's REST session token, sent as a header on every API call. Entra = Microsoft Entra ID (formerly Azure AD). OIDC = OpenID Connect, the identity layer on OAuth that Entra speaks. JWT = the signed JSON Web Token Entra issues; a "claim" is one key in it. CorporateUser = the Bullhorn entity representing a consultant/staff login. CR = Change Request, this project's planning doc unit (CRx.md files in repo root).

All line numbers, counts, and tags below are as of 2026-07-03 (tag v0.0.46, 648 tests; auth.py is 212 lines, identity.py 95 lines).

## System A: Bullhorn's non-standard OAuth flow

Bullhorn does not use a browser consent flow. `BullhornAuth` (auth.py) submits the service-account username and password directly as query parameters. Full chain:

| Step | Method | What happens |
|---|---|---|
| 1. Auth code | `_get_auth_code()` | GET `{auth_url}/oauth/authorize` with query params `client_id`, `response_type=code`, `action=Login`, `username`, `password`. Response is a redirect whose Location contains `code=`. `follow_redirects=False`; the loop follows up to 5 redirects (301/302/303/307/308) manually. |
| 2. Token exchange | `_exchange_auth_code()` | POST `{auth_url}/oauth/token` with `grant_type=authorization_code`. Stores `access_token`, `refresh_token`, expiry (default 600s if `expires_in` absent). |
| 3. REST login | `_rest_login()` | GET `{login_url}/rest-services/login?version=*&access_token=...`. Response must contain `BhRestToken` and `restUrl`; stored as a `BullhornSession` with `expires_at = now + 600` (hardcoded client-side estimate). |
| 4. API calls | `client.py _request()` | Every request sends header `BhRestToken` to `f"{session.rest_url}{endpoint}"`. |

### Regional 307 redirects

Some Bullhorn accounts live on regional auth hosts (e.g. `auth-apac.bullhornstaffing.com`, `auth-emea...`). Rules implemented in `_get_auth_code()`:

- Redirects are followed ONLY if the target host contains `bullhornstaffing.com`. A non-Bullhorn redirect without a `code` param aborts the loop.
- If the redirect that carries the auth code is on a `bullhornstaffing.com` host whose hostname starts with `auth`, that origin is saved as `self._regional_auth_url`.
- `_exchange_auth_code()` and `_refresh_access_token()` both use `self._regional_auth_url or self.config.auth_url`. Token exchange against the wrong (non-regional) host fails. `_rest_login()` always uses `config.login_url`; it is not affected by the regional URL.
- History: this broke twice (commits 058c365 and 6d40090); full narrative in bullhorn-mcp-failure-archaeology.

### Session lifetime and refresh

- The public entry point is the synchronous `session` property. It refreshes when `self._session is None` or within 60 seconds of `expires_at` (the 60s buffer prevents using a token that expires mid-request). All of auth.py is sync httpx; async callers must wrap client work in `asyncio.to_thread` (see bullhorn-mcp-run-and-operate).
- `_refresh_session()` strategy: if a refresh token exists and the OAuth access token is still valid (same 60s buffer on `_token_expires_at`), try `_refresh_access_token()`; on ANY exception, or if no refresh token, fall back to `_full_auth()` (steps 1-2). Either way it then always runs `_rest_login()` to mint a fresh BhRestToken.
- Client-layer safety net: `BullhornClient._request()` and `_request_multipart()` (client.py lines 89-94 and 131-135) retry exactly ONCE on HTTP 401 by calling `auth._refresh_session()` and re-sending. A second 401 raises `BullhornAPIError`.

### Quick live auth check (safe, performs login only)

```bash
.venv/bin/python -c "
from bullhorn_mcp.config import BullhornConfig
from bullhorn_mcp.auth import BullhornAuth
auth = BullhornAuth(BullhornConfig.from_env())
s = auth.session
print('rest_url:', s.rest_url)
print('regional:', auth._regional_auth_url)
"
```

If this prints a rest_url, System A is healthy. Note: `rest_url` may come back with a trailing slash from some tenants; the client concatenates `rest_url + endpoint` directly, so test fixtures must never add one (owned by bullhorn-mcp-testing-playbook and bullhorn-mcp-architecture-contract).

## System B: Entra OIDC for hosted HTTP mode

Only active when `MCP_TRANSPORT=http`. In stdio mode `_build_auth()` returns `None` (no inbound auth, no JWT, no identity).

### Configuration (server.py `_build_auth()`, line 166)

- Requires ALL FOUR of `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`, `MCP_BASE_URL`. Any missing raises `ValueError` listing them. This fires at MODULE IMPORT TIME (the `FastMCP(...)` constructor call at server.py line 212 evaluates `_build_auth()`), deliberately fail-closed: you cannot accidentally run an unprotected HTTP endpoint. Consequence for tests and tooling: importing server.py with `MCP_TRANSPORT=http` and missing vars crashes; pin `MCP_TRANSPORT=stdio` when reloading the module.
- Builds a FastMCP `OIDCProxy` against `https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration` with `audience=client_id`, `verify_id_token=True`, `forward_resource=False`.
- Full env var reference table lives in bullhorn-mcp-config-and-flags.

### required_scopes vs extra_authorize_params (they are different things)

- `required_scopes=["openid", "profile", "email"]`: validation of INCOMING tokens; a token missing these is rejected.
- `extra_authorize_params={"scope": "openid profile email offline_access"}`: what the server REQUESTS during the outbound authorization redirect. `offline_access` here makes Entra issue a refresh token so MCP clients silently renew sessions. It must NOT go in `required_scopes` (it is not a claim on the access token). CR12 added it after users were forced to re-login after idle periods.

### Entra token lifetime (CR12)

Entra access tokens default to a 1 hour lifetime. Extending it requires a Token Lifetime Policy, and there is NO Azure Portal UI for this: it is Microsoft Graph only (PowerShell `New-MgPolicyTokenLifetimePolicy` then `Invoke-MgGraphRequest POST .../servicePrincipals/<sp-object-id>/tokenLifetimePolicies/$ref`). A complete copy-pasteable PowerShell snippet is in README.md under "Session Persistence" (verify with the provenance command below).

### Identity resolution (`identity.py resolve_caller`)

Maps the authenticated Entra user to a Bullhorn CorporateUser so writes are attributed to the human consultant, not the shared service account.

1. `get_access_token()` (imported from `fastmcp.server.dependencies`; note identity.py therefore needs the `fastmcp` package even in stdio mode, an OPEN DEBT dependency gap owned by bullhorn-mcp-build-and-env). `None` token raises `IdentityResolutionError`.
2. Reads claims. `sub` is REQUIRED (its absence is itself an `IdentityResolutionError`); email comes from `email`, falling back to `preferred_username`. Other claims present in Entra tokens (`name`, `oid`) are not used.
3. Cache check: `_caller_cache: dict[str, dict]` keyed by `sub`. Hit returns immediately, no Bullhorn round-trip.
4. Miss: queries `CorporateUser` with `where=f"email='{email}'"`, `fields="id,firstName,lastName,email"`. Exactly one match required; zero or multiple raises `IdentityResolutionError`. Result cached under `sub` and returned as `{id, firstName, lastName, email}`.

Why `sub` is the cache key (the CR11 story, one paragraph): CR9 built the cache as a single module-level slot with a written assumption ("the server runs as a single-user service; one authenticated user per process"). Sprint 15 then added shared HTTP transport, invalidating that assumption, and CR9/CR10 shipped afterwards without revisiting it. Result: first-writer-wins. The first consultant to resolve identity poisoned the cache for everyone; every subsequent `create_contact`/`create_company` was silently stamped with the first user's ID, no error surfaced. CR11 (Sprint 18, commit 37fde9c) replaced the slot with a per-`sub` dict. `sub` is Entra's stable per-user, per-app-registration identifier; unlike email it survives renames, so it is the only safe key. Full incident narrative: bullhorn-mcp-failure-archaeology.

Cache semantics to preserve:

- Process-lifetime, no TTL, no invalidation. A CorporateUser email change only takes effect after a server restart. Acceptable by design.
- `_reset_caller_cache()` exists solely for test isolation; it calls `.clear()`. `tests/test_identity.py` has an autouse `reset_cache` fixture calling it before and after every test; any new test module touching identity must do the same.
- Tests patch the USE site: `patch("bullhorn_mcp.identity.get_access_token", ...)`, and every mock token's claims MUST include `"sub"` or resolution raises before reaching your code path. (Broader fixture rules: bullhorn-mcp-testing-playbook.)

### The department ban

CorporateUser queries must NEVER request or filter on `department`: it is not a reliably valid field on CorporateUser across Bullhorn instances and including it silently killed owner resolution (CR3; known review failure pattern 5, auto-CRITICAL on recurrence). `identity.py` carries an inline comment enforcing this on `resolve_caller`; `client.resolve_owner` uses the same field list. Never widen either field list to include `department`.

## Attribution rules (who gets stamped on writes)

Two resolution paths:

- `resolve_caller(client)` (identity.py): JWT -> CorporateUser. Used when the caller omits the attribution field.
- `client.resolve_owner(owner)` (client.py line 461): explicit input. Dict `{"id": N}` passes through untouched; a name string queries `CorporateUser where name='<string>'`. Zero matches raises `ValueError`; multiple matches returns the list and the tool responds with `owner_ambiguous` (or `user_ambiguous`) JSON so the model can disambiguate.

### The hard-fail vs degrade-gracefully split

Policy: tools where the write is MEANINGLESS or WRONG without correct attribution refuse to proceed; tools where attribution is a nice-to-have degrade (stdio mode has no JWT, so degrading keeps those tools usable locally).

| Tool | Field stamped | On IdentityResolutionError |
|---|---|---|
| `create_company` | `owner` | HARD FAIL: returns `{"error": "identity_resolution_failed", "message", "hint"}` JSON |
| `create_contact` | `owner` | HARD FAIL, same JSON |
| `create_job` | `owner` | HARD FAIL, same JSON |
| `create_candidate` | `owner` | HARD FAIL, same JSON |
| `create_candidate_from_cv` | `owner` | HARD FAIL, same JSON |
| `create_tearsheet` | `owner` | HARD FAIL (message says "Provide owner explicitly") |
| `shortlist_candidate` / `shortlist_candidates` | `sendingUser` on JobSubmission | DEGRADE: warning in result; Bullhorn defaults "Added By" to the service account |
| `add_note` | `commentingPerson` on Note | DEGRADE: silently omitted (note author shows as service account) |
| `search_emails` | `user` filter (read path) | DEGRADE: searches without the user filter |
| `bulk_import` | `owner` per contact | NO auto-stamp by design (inline comment): callers must supply `owner` explicitly per contact |

Rules when adding or editing a tool with attribution:

1. Auto-stamp ONLY when the caller omitted the field: `if "owner" not in fields` / `if "sendingUser" not in payload`. Caller-supplied values always win; never overwrite after resolution (dict-merge precedence is recurring meta-pattern 1, see bullhorn-mcp-review-protocol).
2. Copy the dict before mutating (`fields = dict(fields)`).
3. Pick hard-fail or degrade deliberately per the table's logic and say which in the CR.
4. `resolve_owner` results that are lists must surface as disambiguation JSON, never guessed from.
5. On JobSubmission, `sendingUser` is Bullhorn's "Added By"; the dedup pre-check in `_shortlist_one` also fetches `sendingUser` so duplicates are reported with their creator.

## Triage: auth failure symptoms

| Symptom | Likely cause | First check |
|---|---|---|
| Import-time `ValueError: HTTP transport requires Entra OAuth. Missing env vars: ...` | `MCP_TRANSPORT=http` with incomplete Entra config | Set all 4 vars, or unset `MCP_TRANSPORT` for stdio. In tests, pin `MCP_TRANSPORT=stdio`. |
| `AuthenticationError: OAuth error: <err> - <desc>` | Bullhorn rejected the authorize request (bad `BULLHORN_CLIENT_ID`, disabled API access) | Read the error_description; verify client id with the vendor. |
| `AuthenticationError: Failed to get auth code. Status: 200` | Bullhorn served a page instead of redirecting; most commonly wrong `BULLHORN_USERNAME`/`BULLHORN_PASSWORD` | Verify creds; run the live auth check snippet above. |
| `AuthenticationError: Failed to get auth code. Status: 30x` | Redirect chain ended off-domain or exceeded 5 hops | Print the Location headers; check regional redirect handling in `_get_auth_code()`. |
| `Token exchange failed: 400 ...` | Auth code reused/expired, wrong `BULLHORN_CLIENT_SECRET`, or exchange hitting the wrong host for a regional account | Confirm `_regional_auth_url` was captured (live snippet prints it). |
| `REST login failed: ...` | Wrong `BULLHORN_LOGIN_URL` or dead access token | Default login URL is `https://rest.bullhornstaffing.com`; run auth tests: `.venv/bin/pytest tests/test_auth.py` |
| `BullhornAPIError: API request failed: 401 ...` (after the built-in retry) | Refresh chain itself failing | The retry already ran `_refresh_session()`; debug System A steps 1-3 in order. |
| Tool returns `identity_resolution_failed` | Entra email claim does not match exactly ONE CorporateUser email; or stdio mode (no JWT) calling a hard-fail create | Read-only check: `client.query("CorporateUser", where="email='<the email>'", fields="id,email")`. Zero or 2+ rows is your answer. Workaround: pass `owner` explicitly. |
| `No 'sub' claim found in token` | Misconfigured token, or a test mock token missing `"sub"` | Add `"sub"` to mock claims; for real tokens, inspect the JWT. |
| Users re-prompted to sign in after ~1h idle | Token lifetime, not a bug: `offline_access` covers silent renewal, but very long idle needs a longer access token | Apply an Entra Token Lifetime Policy via Graph PowerShell (README "Session Persistence"). |
| Created records show the wrong owner | Caller passed wrong `owner`; or (historically) the CR11 single-slot cache bug | Confirm `_caller_cache` is still a per-`sub` dict; never regress to a single slot or email key. |
| Owner resolution errors mentioning invalid field | `department` crept into a CorporateUser query | Grep and remove; see the department ban above. |

## OPEN DEBT in this domain

- Unescaped WHERE interpolation: `identity.resolve_caller` builds `where=f"email='{email}'"` and `client.resolve_owner` builds `where=f"name='{owner}'"` with no single-quote escaping (same class as the `list_placements` bug fixed as CR33 M2). Inputs are semi-trusted (verified JWT claim; LLM-supplied names) but a name containing `'` breaks the query and the pattern is an injection surface. This is open backlog, not accepted design. Workaround: pass `{"id": N}` owners. Suggested fix: a CR adding the CR33-style quote guard plus validation tests to both call sites (and `get_job_submissions`, tracked by bullhorn-mcp-architecture-contract).
- `fastmcp` is imported by identity.py and server.py but undeclared in pyproject; fresh installs fail until it is installed manually. Owned by bullhorn-mcp-build-and-env.

## When NOT to use this skill

| Topic | Go to |
|---|---|
| Full incident write-ups (regional-redirect commits, CR11 rot, the six "fixing OIDC scopes" commits) | bullhorn-mcp-failure-archaeology |
| Env var reference table, config philosophy | bullhorn-mcp-config-and-flags |
| Installing deps, the fastmcp pyproject gap fix | bullhorn-mcp-build-and-env |
| Mock/fixture architecture beyond identity specifics | bullhorn-mcp-testing-playbook |
| Starting the server, transports, production topology, /upload-cv secret | bullhorn-mcp-run-and-operate |
| Bullhorn query syntax and entity semantics | bullhorn-mcp-query-and-entity-model |
| Module invariants and error-surface conventions generally | bullhorn-mcp-architecture-contract |
| Writing/reviewing a CR that touches auth | bullhorn-mcp-change-control, bullhorn-mcp-review-protocol |

## Provenance and maintenance

Re-verify before trusting volatile facts:

- OAuth flow steps, regional redirect rules, 60s buffers: `grep -n "action.*Login\|_regional_auth_url\|expires_at - 60\|_token_expires_at - 60" src/bullhorn_mcp/auth.py`
- 401 retry-once locations: `grep -n "status_code == 401" src/bullhorn_mcp/client.py`
- `_build_auth` line number, 4 required vars, scopes split: `grep -n "_build_auth\|required_scopes\|extra_authorize_params\|offline_access\|ENTRA_" src/bullhorn_mcp/server.py`
- Cache key, department ban, email fallback: `grep -n "sub\|department\|preferred_username" src/bullhorn_mcp/identity.py`
- Hard-fail vs degrade tool inventory: `grep -n "identity_resolution_failed\|except IdentityResolutionError" src/bullhorn_mcp/server.py` (hard-fail sites return the error JSON; degrade sites pass or warn)
- `resolve_owner` semantics: `grep -n "def resolve_owner" -A 27 src/bullhorn_mcp/client.py`
- Token Lifetime PowerShell snippet still in README: `grep -n "TokenLifetimePolicy\|offline_access" README.md`
- CR11 story: `git show 37fde9c --stat` and `head -30 CR11.md`
- Test suite still green (13 auth + 13 identity as of 2026-07-03): `.venv/bin/pytest tests/test_auth.py tests/test_identity.py -q`
- Injection debt still open: `grep -n "where=f" src/bullhorn_mcp/identity.py src/bullhorn_mcp/client.py`
