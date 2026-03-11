"""Bullhorn REST API client."""

import httpx
from typing import Any

from .auth import BullhornAuth


# Default fields for common entities
DEFAULT_FIELDS = {
    "JobOrder": "id,title,status,employmentType,dateAdded,startDate,salary,clientCorporation,owner,description,numOpenings,isOpen",
    "Candidate": "id,firstName,lastName,email,phone,status,dateAdded,occupation,skillSet,owner",
    "Placement": "id,candidate,jobOrder,status,dateBegin,dateEnd,salary,payRate",
    "ClientCorporation": "id,name,status,phone,address,dateAdded",
    "ClientContact": "id,firstName,lastName,email,phone,status,title,dateAdded,clientCorporation,owner",
}


class BullhornClient:
    """Client for interacting with Bullhorn REST API."""

    def __init__(self, auth: BullhornAuth):
        self.auth = auth

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make authenticated request to Bullhorn API."""
        session = self.auth.session

        url = f"{session.rest_url}{endpoint}"
        headers = {"BhRestToken": session.bh_rest_token}

        with httpx.Client() as client:
            response = client.request(method, url, params=params, json=json, headers=headers)

            if response.status_code == 401:
                # Session expired, force refresh and retry
                self.auth._refresh_session()
                session = self.auth.session
                headers = {"BhRestToken": session.bh_rest_token}
                response = client.request(method, url, params=params, json=json, headers=headers)

            if response.status_code not in (200, 201):
                raise BullhornAPIError(
                    f"API request failed: {response.status_code} - {response.text}"
                )

            return response.json()

    def create(self, entity: str, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new entity in Bullhorn.

        Args:
            entity: Entity type (ClientCorporation, ClientContact, etc.)
            data: Field values for the new entity

        Returns:
            Dict with changedEntityId, changeType, and full data of created record
        """
        result = self._request("PUT", f"/entity/{entity}", json=data)
        entity_id = result["changedEntityId"]
        record = self.get(entity, entity_id)
        return {"changedEntityId": entity_id, "changeType": "INSERT", "data": record}

    def search(
        self,
        entity: str,
        query: str,
        fields: str | None = None,
        count: int = 20,
        start: int = 0,
        sort: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search entities using Lucene query syntax.

        Args:
            entity: Entity type (JobOrder, Candidate, etc.)
            query: Lucene query string (e.g., "isOpen:1 AND title:Engineer")
            fields: Comma-separated fields to return (default: entity-specific)
            count: Max results (1-500)
            start: Starting offset for pagination
            sort: Sort field with direction (e.g., "-dateAdded" for descending)

        Returns:
            List of matching entities
        """
        if fields is None:
            fields = DEFAULT_FIELDS.get(entity, "id")

        params = {
            "query": query,
            "fields": fields,
            "count": min(count, 500),
            "start": start,
        }

        if sort:
            params["sort"] = sort

        result = self._request("GET", f"/search/{entity}", params)
        return result.get("data", [])

    def query(
        self,
        entity: str,
        where: str,
        fields: str | None = None,
        count: int = 20,
        start: int = 0,
        order_by: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query entities using JPQL-like syntax.

        Args:
            entity: Entity type (JobOrder, Candidate, etc.)
            where: WHERE clause (e.g., "status='Active' AND salary > 50000")
            fields: Comma-separated fields to return
            count: Max results (1-500)
            start: Starting offset for pagination
            order_by: Order by clause (e.g., "-dateAdded")

        Returns:
            List of matching entities
        """
        if fields is None:
            fields = DEFAULT_FIELDS.get(entity, "id")

        params = {
            "where": where,
            "fields": fields,
            "count": min(count, 500),
            "start": start,
        }

        if order_by:
            params["orderBy"] = order_by

        result = self._request("GET", f"/query/{entity}", params)
        return result.get("data", [])

    def get(
        self, entity: str, entity_id: int, fields: str | None = None
    ) -> dict[str, Any]:
        """Get a single entity by ID.

        Args:
            entity: Entity type (JobOrder, Candidate, etc.)
            entity_id: Entity ID
            fields: Comma-separated fields to return

        Returns:
            Entity data
        """
        if fields is None:
            fields = DEFAULT_FIELDS.get(entity, "*")

        params = {"fields": fields}
        result = self._request("GET", f"/entity/{entity}/{entity_id}", params)
        return result.get("data", {})

    def get_meta(self, entity: str) -> dict[str, Any]:
        """Get metadata/schema for an entity type.

        Args:
            entity: Entity type (JobOrder, Candidate, etc.)

        Returns:
            Entity metadata including available fields
        """
        params = {"fields": "*"}
        return self._request("GET", f"/meta/{entity}", params)


class BullhornAPIError(Exception):
    """Raised when Bullhorn API request fails."""

    pass
