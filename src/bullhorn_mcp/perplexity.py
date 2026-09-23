"""Perplexity people-search client (CR38).

The only non-Bullhorn outbound dependency in this server. It is kept fully
isolated from BullhornClient, BullhornAuth and BullhornConfig so a Perplexity
outage or missing key can never affect a Bullhorn tool, and vice versa.

The public Perplexity connector cannot reach the people index: none of its tools
accept `search_type`. This module sends `search_type: "people"`, which returns
individual profiles (mostly LinkedIn) instead of curated web pages.
"""

import httpx

PERPLEXITY_SEARCH_URL = "https://api.perplexity.ai/search"


class PerplexityError(Exception):
    """Raised on a non-200 response or a transport failure.

    Messages never contain the API key.
    """


def search_people(
    api_key: str,
    queries: list[str],
    max_results: int = 10,
    timeout: float = 30.0,
) -> list[dict]:
    """POST /search with search_type='people' and return the raw `results` list.

    `query` is always sent as a list. The API merges multi-query results into one
    ranked list capped at max_results, and does not paginate (offset and page are
    silently ignored, verified live 2026-09-23).
    """
    body = {"query": list(queries), "search_type": "people", "max_results": max_results}
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(PERPLEXITY_SEARCH_URL, json=body, headers=headers)
    except httpx.HTTPError as exc:
        # Transport errors carry the request, not the headers, in their message,
        # so the key cannot leak through str(exc). Name the class only to be safe.
        raise PerplexityError(f"transport_error: {type(exc).__name__}") from None

    if response.status_code != 200:
        message = f"HTTP {response.status_code}"
        try:
            error = response.json().get("error")
            if isinstance(error, dict) and error.get("message"):
                message = f"{error.get('type', 'error')}: {error['message']}"
        except (ValueError, AttributeError):
            pass
        raise PerplexityError(message.replace(api_key, "***") if api_key else message)

    try:
        results = response.json().get("results", []) or []
    except (ValueError, AttributeError):
        raise PerplexityError("invalid_response: body is not a JSON object") from None
    if not isinstance(results, list):
        raise PerplexityError("invalid_response: results is not a list")
    # Drop malformed entries rather than fail the whole call.
    return [item for item in results if isinstance(item, dict)]
