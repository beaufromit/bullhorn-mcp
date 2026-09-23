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

    @respx.mock
    def test_search_people_non_json_200_raises_invalid_response(self):
        respx.post(PERPLEXITY_SEARCH_URL).mock(return_value=httpx.Response(200, text="<html>oops</html>"))

        with pytest.raises(PerplexityError, match="invalid_response: body is not a JSON object"):
            search_people(API_KEY, ["x"])

    @respx.mock
    def test_search_people_json_array_200_raises_invalid_response(self):
        respx.post(PERPLEXITY_SEARCH_URL).mock(return_value=httpx.Response(200, json=["a", "b"]))

        with pytest.raises(PerplexityError, match="invalid_response: body is not a JSON object"):
            search_people(API_KEY, ["x"])

    @respx.mock
    def test_search_people_results_not_a_list_raises_invalid_response(self):
        respx.post(PERPLEXITY_SEARCH_URL).mock(return_value=httpx.Response(200, json={"results": {"x": 1}}))

        with pytest.raises(PerplexityError, match="invalid_response: results is not a list"):
            search_people(API_KEY, ["x"])

    @respx.mock
    def test_search_people_drops_non_dict_entries(self):
        good = {"title": "Jane Smith", "url": "https://linkedin.com/in/js"}
        respx.post(PERPLEXITY_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"results": ["a", None, 3, good]})
        )

        assert search_people(API_KEY, ["x"]) == [good]

    @respx.mock
    def test_search_people_non_json_error_body_falls_back_to_status(self):
        respx.post(PERPLEXITY_SEARCH_URL).mock(return_value=httpx.Response(502, text="Bad Gateway"))

        with pytest.raises(PerplexityError) as exc_info:
            search_people(API_KEY, ["x"])

        assert str(exc_info.value) == "HTTP 502"

    @respx.mock
    def test_search_people_error_body_without_error_key_falls_back_to_status(self):
        respx.post(PERPLEXITY_SEARCH_URL).mock(return_value=httpx.Response(500, json={"detail": "boom"}))

        with pytest.raises(PerplexityError) as exc_info:
            search_people(API_KEY, ["x"])

        assert str(exc_info.value) == "HTTP 500"

    @respx.mock
    def test_search_people_redacts_key_echoed_in_upstream_message(self):
        respx.post(PERPLEXITY_SEARCH_URL).mock(return_value=httpx.Response(401, json={
            "error": {"message": f"Invalid API key: {API_KEY}", "type": "invalid_api_key", "code": 401}
        }))

        with pytest.raises(PerplexityError) as exc_info:
            search_people(API_KEY, ["x"])

        assert API_KEY not in str(exc_info.value)
        assert "Invalid API key: ***" in str(exc_info.value)
