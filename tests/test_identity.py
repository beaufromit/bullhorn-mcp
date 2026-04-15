"""Tests for identity resolution (CR9/CR11).

All tests mock get_access_token() via unittest.mock.patch and use a real BullhornClient
backed by respx-mocked httpx calls, consistent with other test files in this suite.

CR11 note: the cache is now keyed by token claims["sub"].  All token fixtures include
a "sub" claim so they exercise the full resolution path.  test_resolve_caller_no_sub_claim
is the sole test whose token intentionally omits "sub".
"""

import httpx
import pytest
import respx
from unittest.mock import Mock, PropertyMock, patch

from bullhorn_mcp.auth import BullhornAuth, BullhornSession
from bullhorn_mcp.client import BullhornClient
from bullhorn_mcp import identity
from bullhorn_mcp.identity import resolve_caller, IdentityResolutionError


@pytest.fixture(autouse=True)
def reset_cache():
    """Clear the module-level identity cache before every test."""
    identity._reset_caller_cache()
    yield
    identity._reset_caller_cache()


@pytest.fixture
def mock_auth(mock_session):
    """BullhornAuth mock with a valid session."""
    auth = Mock(spec=BullhornAuth)
    type(auth).session = PropertyMock(return_value=mock_session)
    return auth


@pytest.fixture
def client(mock_auth):
    """BullhornClient backed by a mock auth."""
    return BullhornClient(mock_auth)


def _make_token(claims: dict):
    """Return a simple mock AccessToken with the given claims."""
    token = Mock()
    token.claims = claims
    return token


QUERY_URL_PATTERN = "https://rest99.bullhornstaffing.com/rest-services/abc123/query/CorporateUser"

SAMPLE_USER = {
    "id": 7,
    "firstName": "Beau",
    "lastName": "Warren",
    "email": "beau@thepanel.com",
}

SAMPLE_USER_2 = {
    "id": 99,
    "firstName": "Fergal",
    "lastName": "Keys",
    "email": "fergal@thepanel.com",
}


class TestResolveCaller:
    """Unit tests for resolve_caller()."""

    @respx.mock
    def test_resolve_caller_success(self, client, mock_session):
        """Returns dict with id/firstName/lastName/email on a single match."""
        respx.get(QUERY_URL_PATTERN).mock(
            return_value=httpx.Response(200, json={"data": [SAMPLE_USER]})
        )
        token = _make_token({"sub": "sub-beau", "email": "beau@thepanel.com"})

        with patch("bullhorn_mcp.identity.get_access_token", return_value=token):
            result = resolve_caller(client)

        assert result == SAMPLE_USER

    def test_resolve_caller_no_token(self, client):
        """Raises IdentityResolutionError when get_access_token returns None."""
        with patch("bullhorn_mcp.identity.get_access_token", return_value=None):
            with pytest.raises(IdentityResolutionError, match="No authentication token available"):
                resolve_caller(client)

    def test_resolve_caller_no_sub_claim(self, client):
        """Raises IdentityResolutionError when token has no sub claim.

        sub is required as the cache key.  A token without sub indicates a
        misconfigured Entra app registration or a non-Entra token.
        """
        token = _make_token({"email": "beau@thepanel.com", "name": "Beau Warren"})
        with patch("bullhorn_mcp.identity.get_access_token", return_value=token):
            with pytest.raises(IdentityResolutionError, match="sub"):
                resolve_caller(client)

    def test_resolve_caller_no_email_claim(self, client):
        """Raises IdentityResolutionError when token has neither email nor preferred_username."""
        token = _make_token({"sub": "sub-beau", "name": "Beau Warren", "oid": "some-oid"})
        with patch("bullhorn_mcp.identity.get_access_token", return_value=token):
            with pytest.raises(IdentityResolutionError, match="No email claim found"):
                resolve_caller(client)

    @respx.mock
    def test_resolve_caller_fallback_to_preferred_username(self, client, mock_session):
        """Falls back to preferred_username when email claim is absent."""
        respx.get(QUERY_URL_PATTERN).mock(
            return_value=httpx.Response(200, json={"data": [SAMPLE_USER]})
        )
        token = _make_token({"sub": "sub-beau", "preferred_username": "beau@thepanel.com"})

        with patch("bullhorn_mcp.identity.get_access_token", return_value=token):
            result = resolve_caller(client)

        assert result["email"] == "beau@thepanel.com"
        # Verify the CorporateUser query used the preferred_username value.
        # The URL is percent-encoded so decode it before checking.
        from urllib.parse import unquote
        decoded_url = unquote(str(respx.calls.last.request.url))
        assert "beau@thepanel.com" in decoded_url

    @respx.mock
    def test_resolve_caller_no_match(self, client, mock_session):
        """Raises IdentityResolutionError when no CorporateUser has the email."""
        respx.get(QUERY_URL_PATTERN).mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        token = _make_token({"sub": "sub-unknown", "email": "unknown@example.com"})

        with patch("bullhorn_mcp.identity.get_access_token", return_value=token):
            with pytest.raises(IdentityResolutionError, match="No Bullhorn CorporateUser found"):
                resolve_caller(client)

    @respx.mock
    def test_resolve_caller_multiple_matches(self, client, mock_session):
        """Raises IdentityResolutionError when multiple CorporateUsers share the email."""
        respx.get(QUERY_URL_PATTERN).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        SAMPLE_USER,
                        {"id": 8, "firstName": "Beau2", "lastName": "Warren2", "email": "beau@thepanel.com"},
                    ]
                },
            )
        )
        token = _make_token({"sub": "sub-beau", "email": "beau@thepanel.com"})

        with patch("bullhorn_mcp.identity.get_access_token", return_value=token):
            with pytest.raises(IdentityResolutionError, match="Multiple Bullhorn CorporateUsers found"):
                resolve_caller(client)

    @respx.mock
    def test_resolve_caller_cached(self, client, mock_session):
        """Second call for the same user returns cached result without querying Bullhorn again."""
        route = respx.get(QUERY_URL_PATTERN).mock(
            return_value=httpx.Response(200, json={"data": [SAMPLE_USER]})
        )
        token = _make_token({"sub": "sub-beau", "email": "beau@thepanel.com"})

        with patch("bullhorn_mcp.identity.get_access_token", return_value=token):
            first = resolve_caller(client)
            second = resolve_caller(client)

        assert first == second == SAMPLE_USER
        # CorporateUser endpoint only called once — second call hit the cache
        assert route.call_count == 1

    @respx.mock
    def test_resolve_caller_query_fields_no_department(self, client, mock_session):
        """CorporateUser query does not request the department field.

        department is not a reliably queryable field across all Bullhorn instances
        (Sprint 10 / CR3 lesson). Including it causes BullhornAPIError on some tenants.
        """
        route = respx.get(QUERY_URL_PATTERN).mock(
            return_value=httpx.Response(200, json={"data": [SAMPLE_USER]})
        )
        token = _make_token({"sub": "sub-beau", "email": "beau@thepanel.com"})

        with patch("bullhorn_mcp.identity.get_access_token", return_value=token):
            resolve_caller(client)

        # Parse the query string and check the 'fields' parameter specifically.
        # Checking the full URL string would be a false negative if the email
        # address itself happened to contain the word "department".
        from urllib.parse import urlparse, parse_qs
        request = route.calls.last.request
        qs = parse_qs(urlparse(str(request.url)).query)
        fields_value = qs.get("fields", [""])[0]
        assert "department" not in fields_value

    @respx.mock
    def test_resolve_caller_multi_user_isolation(self, client, mock_session):
        """Two distinct users resolve to their own CorporateUser records.

        Each user's token has a different sub claim and a different email.
        Both should hit Bullhorn exactly once (no cross-user cache poisoning).
        This is the core correctness test for the CR11 per-user cache fix.
        """
        route = respx.get(QUERY_URL_PATTERN).mock(
            side_effect=[
                httpx.Response(200, json={"data": [SAMPLE_USER]}),
                httpx.Response(200, json={"data": [SAMPLE_USER_2]}),
            ]
        )
        token_beau = _make_token({"sub": "sub-beau", "email": "beau@thepanel.com"})
        token_fergal = _make_token({"sub": "sub-fergal", "email": "fergal@thepanel.com"})

        # The two patch blocks share the same _caller_cache (the autouse fixture does not
        # clear between them). Each resolve_caller call lands in a different cache slot
        # because the sub values differ — that is the property under test.
        with patch("bullhorn_mcp.identity.get_access_token", return_value=token_beau):
            result_beau = resolve_caller(client)

        with patch("bullhorn_mcp.identity.get_access_token", return_value=token_fergal):
            result_fergal = resolve_caller(client)

        assert result_beau == SAMPLE_USER
        assert result_fergal == SAMPLE_USER_2
        # Bullhorn was queried once per user — no cross-user cache hit
        assert route.call_count == 2

    @respx.mock
    def test_resolve_caller_multi_user_cache_hit(self, client, mock_session):
        """Two calls from the same user (same sub) only query Bullhorn once."""
        route = respx.get(QUERY_URL_PATTERN).mock(
            return_value=httpx.Response(200, json={"data": [SAMPLE_USER]})
        )
        token = _make_token({"sub": "sub-beau", "email": "beau@thepanel.com"})

        with patch("bullhorn_mcp.identity.get_access_token", return_value=token):
            first = resolve_caller(client)
            second = resolve_caller(client)

        assert first == second == SAMPLE_USER
        assert route.call_count == 1

    @respx.mock
    def test_reset_caller_cache_clears_all(self, client, mock_session):
        """_reset_caller_cache() clears all cached identities, not just one slot.

        Populates the cache with two distinct users via resolve_caller, then confirms
        both slots are gone after calling _reset_caller_cache().
        """
        respx.get(QUERY_URL_PATTERN).mock(
            side_effect=[
                httpx.Response(200, json={"data": [SAMPLE_USER]}),
                httpx.Response(200, json={"data": [SAMPLE_USER_2]}),
            ]
        )
        token_a = _make_token({"sub": "sub-a", "email": "beau@thepanel.com"})
        token_b = _make_token({"sub": "sub-b", "email": "fergal@thepanel.com"})

        with patch("bullhorn_mcp.identity.get_access_token", return_value=token_a):
            resolve_caller(client)
        with patch("bullhorn_mcp.identity.get_access_token", return_value=token_b):
            resolve_caller(client)

        assert len(identity._caller_cache) == 2

        identity._reset_caller_cache()

        assert len(identity._caller_cache) == 0


class TestResolveCaller_E2E:
    """End-to-end test for the full resolve_caller flow."""

    @respx.mock
    def test_resolve_caller_e2e_full_flow(self, client, mock_session):
        """Full flow: token → sub cache key → email claim → CorporateUser query → cached result.

        Verifies that:
        - resolve_caller() returns the expected dict from Bullhorn.
        - A second call returns the same result without a second HTTP request.
        """
        route = respx.get(QUERY_URL_PATTERN).mock(
            return_value=httpx.Response(200, json={"data": [SAMPLE_USER]})
        )
        token = _make_token({"sub": "sub-beau", "email": "beau@thepanel.com", "name": "Beau Warren"})

        with patch("bullhorn_mcp.identity.get_access_token", return_value=token):
            result1 = resolve_caller(client)
            result2 = resolve_caller(client)

        assert result1 == SAMPLE_USER
        assert result2 == SAMPLE_USER
        assert route.call_count == 1  # cache hit on second call
