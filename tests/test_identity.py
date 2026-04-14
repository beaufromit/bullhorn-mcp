"""Tests for identity resolution (CR9).

All tests mock get_access_token() via unittest.mock.patch and use a real BullhornClient
backed by respx-mocked httpx calls, consistent with other test files in this suite.
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


class TestResolveCaller:
    """Unit tests for resolve_caller()."""

    @respx.mock
    def test_resolve_caller_success(self, client, mock_session):
        """Returns dict with id/firstName/lastName/email on a single match."""
        respx.get(QUERY_URL_PATTERN).mock(
            return_value=httpx.Response(200, json={"data": [SAMPLE_USER]})
        )
        token = _make_token({"email": "beau@thepanel.com"})

        with patch("bullhorn_mcp.identity.get_access_token", return_value=token):
            result = resolve_caller(client)

        assert result == SAMPLE_USER

    def test_resolve_caller_no_token(self, client):
        """Raises IdentityResolutionError when get_access_token returns None."""
        with patch("bullhorn_mcp.identity.get_access_token", return_value=None):
            with pytest.raises(IdentityResolutionError, match="No authentication token available"):
                resolve_caller(client)

    def test_resolve_caller_no_email_claim(self, client):
        """Raises IdentityResolutionError when token has neither email nor preferred_username."""
        token = _make_token({"name": "Beau Warren", "oid": "some-oid"})
        with patch("bullhorn_mcp.identity.get_access_token", return_value=token):
            with pytest.raises(IdentityResolutionError, match="No email claim found"):
                resolve_caller(client)

    @respx.mock
    def test_resolve_caller_fallback_to_preferred_username(self, client, mock_session):
        """Falls back to preferred_username when email claim is absent."""
        respx.get(QUERY_URL_PATTERN).mock(
            return_value=httpx.Response(200, json={"data": [SAMPLE_USER]})
        )
        token = _make_token({"preferred_username": "beau@thepanel.com"})

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
        token = _make_token({"email": "unknown@example.com"})

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
        token = _make_token({"email": "beau@thepanel.com"})

        with patch("bullhorn_mcp.identity.get_access_token", return_value=token):
            with pytest.raises(IdentityResolutionError, match="Multiple Bullhorn CorporateUsers found"):
                resolve_caller(client)

    @respx.mock
    def test_resolve_caller_cached(self, client, mock_session):
        """Second call returns cached result without querying Bullhorn again."""
        route = respx.get(QUERY_URL_PATTERN).mock(
            return_value=httpx.Response(200, json={"data": [SAMPLE_USER]})
        )
        token = _make_token({"email": "beau@thepanel.com"})

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
        token = _make_token({"email": "beau@thepanel.com"})

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


class TestResolveCaller_E2E:
    """End-to-end test for the full resolve_caller flow."""

    @respx.mock
    def test_resolve_caller_e2e_full_flow(self, client, mock_session):
        """Full flow: token → email claim → CorporateUser query → cached result.

        Verifies that:
        - resolve_caller() returns the expected dict from Bullhorn.
        - A second call returns the same result without a second HTTP request.
        """
        route = respx.get(QUERY_URL_PATTERN).mock(
            return_value=httpx.Response(200, json={"data": [SAMPLE_USER]})
        )
        token = _make_token({"email": "beau@thepanel.com", "name": "Beau Warren"})

        with patch("bullhorn_mcp.identity.get_access_token", return_value=token):
            result1 = resolve_caller(client)
            result2 = resolve_caller(client)

        assert result1 == SAMPLE_USER
        assert result2 == SAMPLE_USER
        assert route.call_count == 1  # cache hit on second call
