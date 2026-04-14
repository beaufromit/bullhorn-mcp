"""Identity resolution for Bullhorn MCP.

Maps the authenticated Entra user (via JWT claims) to a Bullhorn CorporateUser record.
Used by create_contact and create_company to auto-populate the owner field when not
explicitly provided by the caller (CR9/CR10).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client import BullhornClient


class IdentityResolutionError(Exception):
    """Raised when the authenticated user cannot be resolved to a Bullhorn CorporateUser."""


# Module-level cache — resolved once per server process.
# Acceptable because the server runs as a single-user service; one authenticated user per process.
# If multi-user support is added later, scope this cache by token.claims["sub"] or email.
_resolved_caller: dict | None = None


def _reset_caller_cache() -> None:
    """Clear the module-level identity cache. Used in tests for isolation."""
    global _resolved_caller
    _resolved_caller = None


def resolve_caller(client: "BullhornClient") -> dict:
    """Resolve the authenticated user's Entra token to a Bullhorn CorporateUser.

    Extracts the user's email from the FastMCP access token's claims, then queries
    Bullhorn's CorporateUser entity for an exact email match.

    Args:
        client: An initialised BullhornClient used to query CorporateUser.

    Returns:
        dict with keys: id (int), firstName (str), lastName (str), email (str).

    Raises:
        IdentityResolutionError: If no token is available, the token has no email claim,
            no CorporateUser matches the email, or multiple CorporateUsers match.
    """
    global _resolved_caller

    if _resolved_caller is not None:
        return _resolved_caller

    # Import here to avoid circular imports and to allow easy mocking in tests.
    from fastmcp.server.dependencies import get_access_token

    token = get_access_token()
    if token is None:
        raise IdentityResolutionError("No authentication token available")

    claims = getattr(token, "claims", {}) or {}
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

    _resolved_caller = results[0]
    return _resolved_caller
