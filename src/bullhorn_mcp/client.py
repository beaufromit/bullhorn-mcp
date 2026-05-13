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
    "ClientContact": "id,firstName,lastName,email,phone,status,dateAdded,clientCorporation,owner",
    "JobSubmission": (
        "id,status,dateAdded,"
        "candidate(id,firstName,lastName),"
        "jobOrder(id,title),"
        "sendingUser(id,firstName,lastName)"
    ),
    "UserMessage": (
        "id,subject,smtpSendDate,smtpReceiveDate,dateAdded,"
        "externalFrom,externalTo,externalCC,externalBCC,"
        "sender(id,firstName,lastName,email),"
        "toRecipients(id,firstName,lastName,email),"
        "ccRecipients(id,firstName,lastName,email),"
        "messageFiles(id,name,contentType,fileSize,fileExtension,isExternal),"
        "threadID"
    ),
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

    def _guess_content_type(self, format: str) -> str:
        """Return a MIME type for a known CV file format."""
        return {
            "pdf": "application/pdf",
            "doc": "application/msword",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "html": "text/html",
            "text": "text/plain",
            "txt": "text/plain",
        }.get(format.lower(), "application/octet-stream")

    def _request_multipart(
        self,
        method: str,
        endpoint: str,
        files: dict,
        params: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """Make an authenticated multipart request to Bullhorn API."""
        session = self.auth.session

        url = f"{session.rest_url}{endpoint}"
        headers = {"BhRestToken": session.bh_rest_token}

        with httpx.Client(timeout=httpx.Timeout(timeout)) as client:
            response = client.request(method, url, files=files, params=params, headers=headers)

            if response.status_code == 401:
                self.auth._refresh_session()
                session = self.auth.session
                headers = {"BhRestToken": session.bh_rest_token}
                response = client.request(method, url, files=files, params=params, headers=headers)

            if response.status_code not in (200, 201):
                raise BullhornAPIError(
                    f"API request failed: {response.status_code} - {response.text}"
                )

            return response.json()

    def parse_resume_file(
        self, file_bytes: bytes, filename: str, format: str = "pdf"
    ) -> dict[str, Any]:
        """Parse a binary CV file via Bullhorn's resume parser.

        Args:
            file_bytes: Raw file bytes (PDF, DOC, DOCX, HTML, text)
            filename: Original filename (used in the multipart upload)
            format: File format hint (pdf, doc, docx, html, text)

        Returns:
            Parsed resume data: candidate, candidateEducation, candidateWorkHistory, skillList
        """
        content_type = self._guess_content_type(format)
        files = {"resume": (filename, file_bytes, content_type)}
        params = {"format": format, "populateDescription": "true"}
        return self._request_multipart("POST", "/resume/parseToCandidate", files=files, params=params)

    def parse_resume_text(
        self, content: str, content_type: str = "text/plain"
    ) -> dict[str, Any]:
        """Parse pasted CV text via Bullhorn's JSON resume parser.

        Args:
            content: Plain text or HTML CV content
            content_type: MIME type of the content (text/plain or text/html)

        Returns:
            Parsed resume data: candidate, candidateEducation, candidateWorkHistory, skillList
        """
        body = {"resume": content, "type": content_type, "format": "text"}
        return self._request("POST", "/resume/parseToCandidateViaJson", json=body)

    def attach_file(
        self,
        entity: str,
        entity_id: int,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        external_id: str | None = None,
        file_type: str | None = None,
    ) -> dict[str, Any]:
        """Attach a file to an entity record via Bullhorn's raw file upload.

        Args:
            entity: Entity type (e.g. Candidate)
            entity_id: Entity ID
            file_bytes: Raw file bytes
            filename: Filename used in Bullhorn
            content_type: MIME type of the file
            external_id: Optional externalID for the file attachment
            file_type: Optional fileType (e.g. "CV")

        Returns:
            File attachment metadata from Bullhorn
        """
        files = {"file": (filename, file_bytes, content_type)}
        params: dict[str, Any] = {}
        if external_id is not None:
            params["externalID"] = external_id
        if file_type is not None:
            params["fileType"] = file_type
        return self._request_multipart(
            "PUT",
            f"/file/{entity}/{entity_id}/raw",
            files=files,
            params=params or None,
        )

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
        extra_params: dict[str, Any] | None = None,
        exclude_deleted: bool = True,
    ) -> list[dict[str, Any]]:
        """Search entities using Lucene query syntax.

        Args:
            entity: Entity type (JobOrder, Candidate, etc.)
            query: Lucene query string (e.g., "isOpen:1 AND title:Engineer")
            fields: Comma-separated fields to return (default: entity-specific)
            count: Max results (1-500)
            start: Starting offset for pagination
            sort: Sort field with direction (e.g., "-dateAdded" for descending)
            extra_params: Additional query-string params to merge in (e.g.,
                ``{"entityId": 123}`` for UserMessage mailbox scoping).
            exclude_deleted: When True (default), appends ``AND isDeleted:0`` to
                filter out soft-deleted records. Pass False only when deleted
                records are explicitly needed.

        Returns:
            List of matching entities
        """
        if exclude_deleted:
            query = f"({query}) AND isDeleted:0" if query else "isDeleted:0"

        if fields is None:
            fields = DEFAULT_FIELDS.get(entity, "id")

        params: dict[str, Any] = {
            "query": query,
            "fields": fields,
            "count": min(count, 500),
            "start": start,
        }

        if sort:
            params["sort"] = sort

        if extra_params:
            params.update(extra_params)

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
        exclude_deleted: bool = True,
    ) -> list[dict[str, Any]]:
        """Query entities using JPQL-like syntax.

        Args:
            entity: Entity type (JobOrder, Candidate, etc.)
            where: WHERE clause (e.g., "status='Active' AND salary > 50000")
            fields: Comma-separated fields to return
            count: Max results (1-500)
            start: Starting offset for pagination
            order_by: Order by clause (e.g., "-dateAdded")
            exclude_deleted: When True (default), appends ``AND isDeleted=false``
                to filter out soft-deleted records. Pass False only when deleted
                records are explicitly needed.

        Returns:
            List of matching entities
        """
        if exclude_deleted:
            where = f"({where}) AND isDeleted=false" if where else "isDeleted=false"

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

    def add_note(
        self,
        entity: str,
        entity_id: int,
        action: str,
        comments: str,
        commenting_person_id: int | None = None,
    ) -> dict[str, Any]:
        """Add a Note entity linked to a Bullhorn record.

        Args:
            entity: One of "Candidate", "ClientContact", "ClientCorporation",
                "JobOrder", "Placement", "Lead", or "Opportunity"
            entity_id: ID of the entity to attach the note to
            action: Note action type (e.g. "General Note")
            comments: Note body text
            commenting_person_id: CorporateUser ID of the note author.
                When provided, sets commentingPerson on the Note.

        Returns:
            Dict with changedEntityId, changeType, and full Note record data

        Raises:
            ValueError: If entity is not one of the supported types
        """
        _ENTITY_FIELD: dict[str, tuple[str, Any]] = {
            "Candidate": ("personReference", {"id": entity_id}),
            "ClientContact": ("personReference", {"id": entity_id}),
            "ClientCorporation": ("clientCorporation", {"id": entity_id}),
            "JobOrder": ("jobOrder", {"id": entity_id}),
            "Placement": ("placements", [{"id": entity_id}]),
            "Lead": ("leads", [{"id": entity_id}]),
            "Opportunity": ("opportunities", [{"id": entity_id}]),
        }

        if entity not in _ENTITY_FIELD:
            supported = ", ".join(sorted(_ENTITY_FIELD))
            raise ValueError(f"add_note does not support entity '{entity}'. Supported: {supported}")

        payload: dict[str, Any] = {"action": action, "comments": comments}
        field_name, field_value = _ENTITY_FIELD[entity]
        payload[field_name] = field_value

        if commenting_person_id is not None:
            payload["commentingPerson"] = {"id": commenting_person_id}

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
