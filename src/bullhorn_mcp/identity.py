"""Identity resolution for Bullhorn MCP.

Maps the authenticated Entra user (via JWT claims) to a Bullhorn CorporateUser record.
Used by create_contact and create_company to auto-populate the owner field when not
explicitly provided by the caller (CR9/CR10).

The resolved identity is cached per Entra user, keyed by the stable `sub` claim.
This is safe for multi-user HTTP deployments (Sprint 15 / FR-11) — each consultant
gets their own cache slot and receives only their own Bullhorn CorporateUser.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp.server.dependencies import get_access_token

if TYPE_CHECKING:
    from .client import BullhornClient


class IdentityResolutionError(Exception):
    """Raised when the authenticated user cannot be resolved to a Bullhorn CorporateUser."""


# Per-user identity cache, keyed by token claims["sub"].
# "sub" is the stable Entra object identifier scoped to the app registration —
# it does not change if a user's email or display name changes, making it a more
# reliable cache key than email.
_caller_cache: dict[str, dict] = {}


def _reset_caller_cache() -> None:
    """Clear the per-user identity cache. Used in tests for isolation."""
    global _caller_cache
    _caller_cache.clear()


def resolve_caller(client: "BullhornClient") -> dict:
    """Resolve the authenticated user's Entra token to a Bullhorn CorporateUser.

    Extracts the user's email from the FastMCP access token's claims, then queries
    Bullhorn's CorporateUser entity for an exact email match.  The result is cached
    by the token's ``sub`` claim so that each distinct user gets their own slot and
    subsequent calls for the same user skip the Bullhorn round-trip.

    Args:
        client: An initialised BullhornClient used to query CorporateUser.

    Returns:
        dict with keys: id (int), firstName (str), lastName (str), email (str).

    Raises:
        IdentityResolutionError: If no token is available, the token has no ``sub``
            claim, the token has no email claim, no CorporateUser matches the email,
            or multiple CorporateUsers match.
    """
    token = get_access_token()
    if token is None:
        raise IdentityResolutionError("No authentication token available")

    claims = getattr(token, "claims", {}) or {}

    # sub is required as the cache key — its absence indicates a misconfigured token.
    sub = claims.get("sub")
    if not sub:
        raise IdentityResolutionError(
            "No 'sub' claim found in token — cannot key identity cache"
        )

    if sub in _caller_cache:
        return _caller_cache[sub]

    email = claims.get("email") or claims.get("preferred_username")
    if not email:
        raise IdentityResolutionError("No email claim found in token")

    results = client.query(
        entity="CorporateUser",
        where=f"email='{email}'",
        fields="id,firstName,lastName,email",
        # Note: do NOT include 'department' — it is not a reliably queryable field
        # on CorporateUser across all Bullhorn instances (Sprint 10 / CR3 lesson).
    )

    if len(results) == 0:
        raise IdentityResolutionError(
            f"No Bullhorn CorporateUser found for email '{email}'"
        )
    if len(results) > 1:
        raise IdentityResolutionError(
            f"Multiple Bullhorn CorporateUsers found for email '{email}' — expected exactly one"
        )

    _caller_cache[sub] = results[0]
    return _caller_cache[sub]
