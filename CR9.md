# CR9: Identity Resolution — Resolve Authenticated User to Bullhorn CorporateUser

## Summary

The MCP server authenticates users via Microsoft Entra but has no mechanism to map the authenticated user to a Bullhorn CorporateUser record. All Bullhorn API calls go through a shared service account, so the server cannot distinguish which consultant is making a request. CR9 adds identity resolution: extracting the user's email from the Entra ID token and resolving it to a Bullhorn CorporateUser. The resolved identity is cached per session and made available to downstream features (CR10 owner stamping, CR11 automated notes).

## Problem

After Entra OAuth was implemented, the server knows *who* is authenticated (via ID token claims) but does not use that information. Every tool call executes as the service account with no awareness of the individual consultant. This blocks two planned features:

- CR10 needs the caller's CorporateUser ID to auto-populate the `owner` field on new records.
- CR11 needs the caller's name to stamp notes attributing actions to the right person.

## Token Claims Available

Confirmed by diagnostic testing against the live Entra integration. The FastMCP-issued JWT (accessed via `get_access_token()` from `fastmcp.server.dependencies`) contains the following upstream Entra claims:

```json
{
  "email": "beau@thepanel.com",
  "name": "Beau Warren",
  "preferred_username": "beau@thepanel.com",
  "oid": "92621c75-bcd9-49d8-abce-cb3ff15e2bcd",
  "sub": "yBJP1xnVwrQy9mSAQRB-Urrn_KZlBp2ZIbHn0kDKRlY"
}
```

The `email` claim is the primary key for resolution. `name` is available for display purposes (CR11). `oid` is the Entra user ID but is not needed — we resolve via email against Bullhorn's CorporateUser entity.

## Required Changes

### 1. New module: `src/bullhorn_mcp/identity.py`

Create a module responsible for extracting the authenticated user's email from the token and resolving it to a Bullhorn CorporateUser record.

**`resolve_caller() -> dict`**

- Call `get_access_token()` from `fastmcp.server.dependencies`.
- If token is `None`, raise `IdentityResolutionError("No authentication token available")`.
- Extract `email` from `token.claims`. If `email` is not present, fall back to `preferred_username`. If neither is present, raise `IdentityResolutionError("No email claim found in token")`.
- Query Bullhorn: `client.query(entity="CorporateUser", where=f"email='{email}'", fields="id,firstName,lastName,email")`.
- If exactly one result: return the result dict `{"id": int, "firstName": str, "lastName": str, "email": str}`.
- If zero results: raise `IdentityResolutionError(f"No Bullhorn CorporateUser found for email '{email}'")`.
- If multiple results: raise `IdentityResolutionError(f"Multiple Bullhorn CorporateUsers found for email '{email}' — expected exactly one")`.

**Caching**

- Cache the resolved identity at module level (same pattern as `get_client()` and `get_metadata()` in `server.py`).
- Once resolved, subsequent calls to `resolve_caller()` return the cached result without querying Bullhorn again.
- The cache lives for the lifetime of the server process. This is acceptable because the server runs as a single-user systemd service behind Cloudflare Tunnel — the authenticated user does not change within a session.

**Note on future multi-user support:** If the server later needs to support concurrent users, the cache must be scoped per-session (e.g. keyed by `token.claims["sub"]` or `token.claims["email"]`). This is out of scope for CR9 but should be a straightforward change when needed.

### 2. New exception class

Add `IdentityResolutionError` as a custom exception, either in `identity.py` or in a shared exceptions module. It should extend `Exception` (not `BullhornAPIError` — identity resolution is a server-side concern, not a Bullhorn API failure).

### 3. No changes to existing tools in CR9

CR9 only introduces the identity resolution module and makes it importable. Tools do not call `resolve_caller()` yet — that happens in CR10 (owner stamping) and CR11 (automated notes). This keeps CR9 small and independently testable.

## Failure Behaviour

**Hard fail.** If identity resolution fails for any reason (no token, no email claim, no matching CorporateUser, multiple matches), the operation must raise an error. There is no fallback to the service account.

Rationale: falling back to the service account would silently break the audit trail that CR10 and CR11 depend on. A configuration problem (e.g. a consultant's email not matching their Bullhorn record) should surface immediately and loudly, not be papered over.

## Affected User Stories

- No existing user stories are directly affected. CR9 is infrastructure for CR10 and CR11.

## Acceptance Criteria

1. `resolve_caller()` returns `{"id": int, "firstName": str, "lastName": str, "email": str}` when called with a valid token whose email matches exactly one CorporateUser.
2. `resolve_caller()` raises `IdentityResolutionError` with a clear message when:
   - No token is available.
   - The token has no `email` or `preferred_username` claim.
   - No CorporateUser matches the email.
   - Multiple CorporateUsers match the email.
3. The result is cached — a second call to `resolve_caller()` does not query Bullhorn again.
4. The `email` claim is used as the primary lookup key. `preferred_username` is used as a fallback only if `email` is absent.
5. The CorporateUser query does not include `department` in the fields list (per CR3 fix).
6. No existing tools are modified in CR9.
7. All existing tests pass unchanged.

## Testing

- `test_resolve_caller_success` — mock `get_access_token()` returning a token with `email` claim, mock CorporateUser query returning one result, assert returned dict matches.
- `test_resolve_caller_no_token` — mock `get_access_token()` returning `None`, assert `IdentityResolutionError`.
- `test_resolve_caller_no_email_claim` — mock token with no `email` and no `preferred_username`, assert `IdentityResolutionError`.
- `test_resolve_caller_fallback_to_preferred_username` — mock token with no `email` but `preferred_username` present, assert query uses `preferred_username` value.
- `test_resolve_caller_no_match` — mock empty query result, assert `IdentityResolutionError`.
- `test_resolve_caller_multiple_matches` — mock query returning two results, assert `IdentityResolutionError`.
- `test_resolve_caller_cached` — call twice, assert Bullhorn query only called once.
- `test_resolve_caller_query_fields_no_department` — assert the CorporateUser query fields string does not contain `department`.
