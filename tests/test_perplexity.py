"""Tests for the Perplexity people-search client (CR38)."""

import json

import httpx
import pytest
import respx

from bullhorn_mcp.perplexity import PERPLEXITY_SEARCH_URL, PerplexityError, search_people

API_KEY = "pplx-test-secret-key"


class TestSearchPeople:
    @respx.mock
    def test_search_people_happy_path(self):
        results = [{"title": "Jane Smith - Financial Controller", "url": "https://linkedin.com/in/js",
                    "snippet": "Financial Controller at Acme", "last_updated": "2026-09-11"}]
        route = respx.post(PERPLEXITY_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"results": results, "id": "abc"})
        )

        out = search_people(API_KEY, ["financial controller Dublin"], max_results=7)

        assert out == results
        request = route.calls.last.request
        assert json.loads(request.content) == {
            "query": ["financial controller Dublin"],
            "search_type": "people",
            "max_results": 7,
        }
        assert request.headers["Authorization"] == f"Bearer {API_KEY}"

    @respx.mock
    def test_search_people_401_raises_with_api_message(self):
        respx.post(PERPLEXITY_SEARCH_URL).mock(return_value=httpx.Response(401, json={
            "error": {"message": "Invalid API key provided.", "type": "invalid_api_key", "code": 401}
        }))

        with pytest.raises(PerplexityError) as exc_info:
            search_people(API_KEY, ["x"])

        assert "invalid_api_key" in str(exc_info.value)
        assert "Invalid API key provided." in str(exc_info.value)
        assert API_KEY not in str(exc_info.value)

    @respx.mock
    def test_search_people_400_raises(self):
        respx.post(PERPLEXITY_SEARCH_URL).mock(return_value=httpx.Response(400, json={
            "error": {"message": "query validation: query 1 length must be between 1 and 8192 characters, got 0",
                      "type": "invalid_request", "code": 400}
        }))

        with pytest.raises(PerplexityError, match="invalid_request: query validation"):
            search_people(API_KEY, [""])

    @respx.mock
    def test_search_people_transport_error_wrapped(self):
        respx.post(PERPLEXITY_SEARCH_URL).mock(side_effect=httpx.ConnectError("connection refused"))

        with pytest.raises(PerplexityError, match="transport_error: ConnectError"):
            search_people(API_KEY, ["x"])
