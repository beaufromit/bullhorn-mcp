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

    def update(self, entity: str, entity_id: int, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing entity in Bullhorn.

        Args:
            entity: Entity type (ClientCorporation, ClientContact, etc.)
            entity_id: ID of the entity to update
            data: Fields to update

        Returns:
            Dict with changedEntityId, changeType, and full updated record data
        """
        self._request("POST", f"/entity/{entity}/{entity_id}", json=data)
        record = self.get(entity, entity_id)
        return {"changedEntityId": entity_id, "changeType": "UPDATE", "data": record}

    def add_note(self, entity: str, entity_id: int, action: str, comments: str) -> dict[str, Any]:
        """Add a Note entity linked to a ClientContact or ClientCorporation.

        Args:
            entity: "ClientContact" or "ClientCorporation"
            entity_id: ID of the entity to attach the note to
            action: Note action type (e.g. "General Note")
            comments: Note body text

        Returns:
            Dict with changedEntityId, changeType, and full Note record data
        """
        payload: dict[str, Any] = {"action": action, "comments": comments}

        if entity == "ClientContact":
            payload["personReference"] = {"id": entity_id}
            payload["commentingPerson"] = {"id": entity_id}
        elif entity == "ClientCorporation":
            payload["clientCorporation"] = {"id": entity_id}

        result = self._request("PUT", "/entity/Note", json=payload)
        note_id = result["changedEntityId"]
        record = self.get("Note", note_id)
        return {"changedEntityId": note_id, "changeType": "INSERT", "data": record}

    def resolve_owner(self, owner: str | dict) -> dict | list:
        """Resolve an owner to a Bullhorn CorporateUser ID.

        Args:
            owner: Either {"id": int} (passed through) or a name string to search.

        Returns:
            {"id": int} if resolved to a single user, or a list of matching user
            dicts if multiple users match (caller must disambiguate).

        Raises:
            ValueError: If no CorporateUser matches the given name.
        """
        if isinstance(owner, dict):
            return owner

        results = self.query(
            entity="CorporateUser",
            where=f"name='{owner}'",
            fields="id,firstName,lastName,email",
        )

        if len(results) == 0:
            raise ValueError(f"No CorporateUser found matching '{owner}'")
        if len(results) == 1:
            return {"id": results[0]["id"]}
        return results

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
