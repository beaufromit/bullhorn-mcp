"""Bullhorn CRM MCP Server - Query and manage CRM data via AI assistants."""

import asyncio
import base64
import hmac
import json
import logging
import os
import re
import time
from typing import Any
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from fastmcp import FastMCP
from fastmcp.server.auth.oidc_proxy import OIDCProxy

from .config import BullhornConfig
from .auth import BullhornAuth, AuthenticationError
from .client import BullhornClient, BullhornAPIError, DEFAULT_FIELDS
from .metadata import BullhornMetadata
from .candidate_config import get_candidate_defaults, get_candidate_required, get_mcp_source
from .joborder_config import get_joborder_defaults, get_joborder_required
from .shortlist_config import get_shortlist_status
from .fuzzy import score_company_match, categorize_score, score_contact_match
from .bulk import BulkImporter
from .identity import resolve_caller, IdentityResolutionError
from .descriptions import enrich_tool_descriptions
from dotenv import load_dotenv
load_dotenv()

_logger = logging.getLogger(__name__)


def _strip_contact_title(fields: dict, entity: str) -> tuple[dict, list[str]]:
    """Strip readonly/wrong-entity fields from write payloads; return a warnings list."""
    warnings = []
    if entity == "ClientContact" and "title" in fields:
        fields = dict(fields)
        del fields["title"]
        msg = "Field 'title' was stripped from the ClientContact payload. Use 'occupation' for job title or 'namePrefix' for salutation."
        _logger.warning(msg)
        warnings.append(msg)
    if entity == "Candidate":
        fields = dict(fields)
        if "title" in fields:
            del fields["title"]
            msg = "Field 'title' was stripped from the Candidate payload. Use 'occupation' for job title — Candidate has no title field."
            _logger.warning(msg)
            warnings.append(msg)
    if entity in ("Candidate", "ClientContact") and "name" in fields:
        fields = dict(fields)
        del fields["name"]
        msg = (
            f"Field 'name' was ignored on the {entity} payload — "
            "it is computed by the MCP from firstName + lastName to keep them in sync."
        )
        _logger.warning(msg)
        warnings.append(msg)
    return fields, warnings


def _compute_person_name(fields: dict) -> str | None:
    """Return computed name from firstName + lastName, or None if neither is present."""
    first = str(fields.get("firstName") or "").strip()
    last = str(fields.get("lastName") or "").strip()
    combined = f"{first} {last}".strip()
    return combined or None


def _check_candidate_duplicates(
    client: BullhornClient,
    first_name: str,
    last_name: str,
    email: str | None,
) -> dict | None:
    """Search for duplicate Candidates by name and optional email.

    Returns a match dict (confidence, category, record) if best score >= 0.50,
    or None if no duplicate found. Returns None on search failure (non-fatal).
    """
    query_parts = []
    if email:
        query_parts.append(f'email:"{email}"')
    if first_name:
        query_parts.append(f'firstName:"{first_name}"')
    if last_name:
        query_parts.append(f'lastName:"{last_name}"')
    if not query_parts:
        return None

    query = " OR ".join(query_parts)
    try:
        results = client.search(
            "Candidate",
            query=query,
            fields="id,firstName,lastName,email,phone,occupation,companyName,dateAdded",
            count=50,
        )
    except (AuthenticationError, BullhornAPIError):
        return None

    best_score = 0.0
    best_match = None
    for record in results:
        # Email exact match short-circuits to the highest possible score
        if email and (record.get("email") or "").lower().strip() == email.lower().strip():
            score = 1.0
        else:
            score = score_contact_match(first_name, last_name, record)
        if score > best_score:
            best_score = score
            best_match = record

    if best_score >= 0.50 and best_match is not None:
        return {
            "confidence": round(best_score, 4),
            "category": categorize_score(best_score),
            "record": best_match,
        }
    return None


def _truncate_against_meta(metadata: BullhornMetadata, entity: str, fields: dict) -> dict:
    """Clip string field values that exceed their /meta maxLength limit.

    Non-string values and fields not in metadata are passed through unchanged.
    """
    try:
        meta_fields = {f["name"]: f for f in metadata.get_fields(entity)}
    except Exception:
        return fields

    result = {}
    for key, value in fields.items():
        if isinstance(value, str) and key in meta_fields:
            max_len = meta_fields[key].get("maxLength") or meta_fields[key].get("max_length")
            if max_len and isinstance(max_len, int) and len(value) > max_len:
                value = value[:max_len]
        result[key] = value
    return result


def _company_broad_query(company_name: str) -> str:
    """Build a broad Lucene name query for fuzzy company matching."""
    stripped = company_name.strip()
    if not stripped:
        return ""
    first_term = stripped.split()[0]
    # Acronyms like BNY need candidates such as "Bank of New York Mellon" to be
    # returned before local fuzzy scoring can identify the abbreviation match.
    if first_term.isupper() and first_term.isalpha() and 2 <= len(first_term) <= 6:
        return f"name:{first_term[0]}*"
    return f"name:{first_term}*"


# Read transport configuration at module load so FastMCP receives the right host/port.
# MCP_TRANSPORT: "stdio" (default, backward-compatible) or "http" (hosted deployment).
# PORT: HTTP listen port (default 8000). Ignored in stdio mode.
# HOST: HTTP bind address override. Defaults to 0.0.0.0 for http mode, 127.0.0.1 for stdio.
_transport_mode = os.environ.get("MCP_TRANSPORT", "stdio")
_port = int(os.environ.get("PORT", 8000))
_default_host = "0.0.0.0" if _transport_mode == "http" else "127.0.0.1"
_host = os.environ.get("HOST", _default_host)


def _build_auth() -> OIDCProxy | None:
    """Configure Entra OAuth when running in HTTP mode.

    In stdio mode, returns None — no auth required.
    In HTTP mode, all four Entra env vars must be present or the server
    refuses to start. This makes it impossible to accidentally run an
    unprotected HTTP endpoint.
    """
    if _transport_mode != "http":
        return None

    tenant_id = os.environ.get("ENTRA_TENANT_ID")
    client_id = os.environ.get("ENTRA_CLIENT_ID")
    client_secret = os.environ.get("ENTRA_CLIENT_SECRET")
    base_url = os.environ.get("MCP_BASE_URL")

    missing = [
        name for name, val in {
            "ENTRA_TENANT_ID": tenant_id,
            "ENTRA_CLIENT_ID": client_id,
            "ENTRA_CLIENT_SECRET": client_secret,
            "MCP_BASE_URL": base_url,
        }.items() if not val
    ]

    if missing:
        raise ValueError(
            f"HTTP transport requires Entra OAuth. Missing env vars: {', '.join(missing)}"
        )
    
    return OIDCProxy(
        config_url=f"https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration",
        client_id=client_id,
        client_secret=client_secret,
        base_url=base_url,
        required_scopes=["openid", "profile", "email"],
        forward_resource=False,
        audience=client_id,
        verify_id_token=True,
        extra_authorize_params={
            "scope": "openid profile email offline_access",
        },
    )


# Initialize MCP server
mcp = FastMCP(
    "Bullhorn CRM",
    auth=_build_auth(),
    instructions=(
        "Query and manage Bullhorn CRM data — jobs, candidates, contacts, companies, "
        "and placements. Supports field metadata resolution between API names and "
        "display labels."
    ),
)

# Global instances (initialized on first use)
_client: BullhornClient | None = None
_metadata: BullhornMetadata | None = None
_shortlist_status_validated: bool = False
_valid_note_actions: set[str] | None = None


def get_client() -> BullhornClient:
    """Get or create the Bullhorn API client."""
    global _client
    if _client is None:
        config = BullhornConfig.from_env()
        auth = BullhornAuth(config)
        _client = BullhornClient(auth)
    return _client


def get_metadata() -> BullhornMetadata:
    """Get or create the Bullhorn metadata resolver."""
    global _metadata
    if _metadata is None:
        _metadata = BullhornMetadata(get_client())
    return _metadata


def format_response(data: list | dict) -> str:
    """Format API response as readable JSON."""
    return json.dumps(data, indent=2, default=str)


def _paginate_envelope(meta: dict, start: int, count: int) -> dict:
    """Build the user-facing pagination envelope from a *_with_meta client result."""
    total = meta.get("total")
    data = meta["data"]
    returned = len(data)
    if total is None:
        has_more = returned == count
        next_start = start + returned if has_more else None
    else:
        has_more = (start + returned) < total
        next_start = start + returned if has_more else None
    return {
        "data": data,
        "pagination": {
            "total": total,
            "start": start,
            "count": returned,
            "has_more": has_more,
            "next_start": next_start,
        },
    }


@mcp.tool()
def list_jobs(
    query: str | None = None,
    status: str | None = None,
    limit: int = 20,
    start: int = 0,
    fields: str | None = None,
) -> str:
    """List and filter job orders from Bullhorn CRM.

    Args:
        query: Lucene search query (e.g., "title:Engineer AND isOpen:1")
        status: Filter by job status
        limit: Maximum number of results (1-500, default 20)
        start: Pagination offset — index of the first record to return (default 0).
               Use with limit to page through results: start=0 limit=500 for page 1,
               start=500 limit=500 for page 2, etc.
        fields: Comma-separated fields to return

    Returns:
        JSON object with ``data`` (array of job orders) and ``pagination``
        (``total``, ``start``, ``count``, ``has_more``, ``next_start``).
        When ``has_more`` is true, call again with ``start=<next_start>``
        to fetch the next page.

    Examples:
        - list_jobs() - Get recent jobs
        - list_jobs(query="isOpen:1") - Get open jobs
        - list_jobs(query="title:Software AND employmentType:Direct Hire", limit=10)
        - list_jobs(status="Accepting Candidates")
        - list_jobs(limit=500, start=500) - Get records 501-1000
    """
    try:
        client = get_client()

        # Build search query
        search_query = query or ""
        if status:
            search_query = f"({search_query}) AND status:\"{status}\"" if search_query else f"status:\"{status}\""

        meta = client.search_with_meta(
            entity="JobOrder",
            query=search_query,
            fields=fields,
            count=limit,
            start=start,
            sort="-dateAdded",
        )

        return format_response(_paginate_envelope(meta, start, limit))

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def list_candidates(
    query: str | None = None,
    status: str | None = None,
    limit: int = 20,
    start: int = 0,
    fields: str | None = None,
) -> str:
    """List and filter candidates from Bullhorn CRM.

    Args:
        query: Lucene search query (e.g., "lastName:Smith" or "skillSet:Python")
        status: Filter by candidate status
        limit: Maximum number of results (1-500, default 20)
        start: Pagination offset — index of the first record to return (default 0).
               Use with limit to page through results: start=0 limit=500 for page 1,
               start=500 limit=500 for page 2, etc.
        fields: Comma-separated fields to return

    Returns:
        JSON object with ``data`` (array of candidates) and ``pagination``
        (``total``, ``start``, ``count``, ``has_more``, ``next_start``).
        When ``has_more`` is true, call again with ``start=<next_start>``
        to fetch the next page.

    Examples:
        - list_candidates() - Get recent candidates
        - list_candidates(query="skillSet:Python") - Find Python developers
        - list_candidates(query="lastName:Smith AND status:Active")
        - list_candidates(status="Active", limit=50)
        - list_candidates(limit=500, start=500) - Get records 501-1000
    """
    try:
        client = get_client()

        # Build search query
        search_query = query or ""
        if status:
            search_query = f"({search_query}) AND status:\"{status}\"" if search_query else f"status:\"{status}\""

        meta = client.search_with_meta(
            entity="Candidate",
            query=search_query,
            fields=fields,
            count=limit,
            start=start,
            sort="-dateAdded",
        )

        return format_response(_paginate_envelope(meta, start, limit))

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def list_contacts(
    query: str | None = None,
    status: str | None = None,
    limit: int = 20,
    start: int = 0,
    fields: str | None = None,
) -> str:
    """List and filter client contacts from Bullhorn CRM.

    Args:
        query: Lucene search query (e.g., "lastName:Smith" or "occupation:Manager")
        status: Filter by contact status (e.g., "Active")
        limit: Maximum number of results (1-500, default 20)
        start: Pagination offset — index of the first record to return (default 0).
               Use with limit to page through results: start=0 limit=500 for page 1,
               start=500 limit=500 for page 2, etc.
        fields: Comma-separated fields to return

    Returns:
        JSON object with ``data`` (array of client contacts) and ``pagination``
        (``total``, ``start``, ``count``, ``has_more``, ``next_start``).
        When ``has_more`` is true, call again with ``start=<next_start>``
        to fetch the next page.

    Examples:
        - list_contacts() - Get recent contacts
        - list_contacts(query="lastName:Smith") - Find contacts named Smith
        - list_contacts(query="occupation:Manager AND clientCorporation.name:Acme")
        - list_contacts(status="Active", limit=50)
        - list_contacts(limit=500, start=500) - Get records 501-1000
    """
    try:
        client = get_client()

        # Build search query
        search_query = query or ""
        if status:
            search_query = f"({search_query}) AND status:\"{status}\"" if search_query else f"status:\"{status}\""

        meta = client.search_with_meta(
            entity="ClientContact",
            query=search_query,
            fields=fields,
            count=limit,
            start=start,
            sort="-dateAdded",
        )

        return format_response(_paginate_envelope(meta, start, limit))

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def list_companies(
    query: str | None = None,
    status: str | None = None,
    limit: int = 20,
    start: int = 0,
    fields: str | None = None,
) -> str:
    """List and filter client companies from Bullhorn CRM.

    Args:
        query: Lucene search query (e.g., "name:Acme*" or "phone:555*")
        status: Filter by company status (e.g., "Active")
        limit: Maximum number of results (1-500, default 20)
        start: Pagination offset — index of the first record to return (default 0).
               Use with limit to page through results: start=0 limit=500 for page 1,
               start=500 limit=500 for page 2, etc.
        fields: Comma-separated fields to return

    Returns:
        JSON object with ``data`` (array of client companies) and ``pagination``
        (``total``, ``start``, ``count``, ``has_more``, ``next_start``).
        When ``has_more`` is true, call again with ``start=<next_start>``
        to fetch the next page.

    Examples:
        - list_companies() - Get recent companies
        - list_companies(query="name:Acme*") - Find companies starting with Acme
        - list_companies(status="Active", limit=50)
        - list_companies(limit=500, start=500) - Get records 501-1000
    """
    try:
        client = get_client()

        # Build search query
        search_query = query or ""
        if status:
            search_query = f"({search_query}) AND status:\"{status}\"" if search_query else f"status:\"{status}\""

        meta = client.search_with_meta(
            entity="ClientCorporation",
            query=search_query,
            fields=fields,
            count=limit,
            start=start,
            sort="-dateAdded",
        )

        return format_response(_paginate_envelope(meta, start, limit))

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def get_job(job_id: int, fields: str | None = None) -> str:
    """Get details for a specific job order by ID.

    Args:
        job_id: The JobOrder ID
        fields: Comma-separated fields to return (default: all common fields)

    Returns:
        JSON object with job details.

    Note on notes: the JobOrder record's notes association returns IDs only unless
    expanded as notes(id,action,comments,...) in fields. For any non-trivial notes
    read, use get_notes_for_entity("JobOrder", job_id) instead.
    """
    try:
        client = get_client()
        result = client.get(entity="JobOrder", entity_id=job_id, fields=fields)
        return format_response(result)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def get_candidate(candidate_id: int, fields: str | None = None) -> str:
    """Get details for a specific candidate by ID.

    Args:
        candidate_id: The Candidate ID
        fields: Comma-separated fields to return (default: all common fields)

    Returns:
        JSON object with candidate details.

    Note on notes: the Candidate record's notes association returns IDs only unless
    expanded as notes(id,action,comments,...) in fields. For any non-trivial notes
    read, use get_notes_for_entity("Candidate", candidate_id) instead.
    """
    try:
        client = get_client()
        result = client.get(entity="Candidate", entity_id=candidate_id, fields=fields)
        return format_response(result)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def get_company(company_id: int, fields: str | None = None) -> str:
    """Get details for a specific client company (ClientCorporation) by ID.

    Args:
        company_id: The ClientCorporation ID
        fields: Comma-separated fields to return (default: id,name,status,phone,address,dateAdded)

    Returns:
        JSON object with company details.

    Note on notes: use get_notes_for_entity("ClientCorporation", company_id) for company notes.
    """
    try:
        client = get_client()
        result = client.get(entity="ClientCorporation", entity_id=company_id, fields=fields)
        return format_response(result)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def search_entities(
    entity: str,
    query: str,
    limit: int = 20,
    start: int = 0,
    fields: str | None = None,
) -> str:
    """Search any Bullhorn entity type using Lucene query syntax.

    Soft-deleted records (isDeleted=true) are excluded by default.

    Args:
        entity: Entity type (JobOrder, Candidate, Placement, ClientCorporation, ClientContact, etc.)
        query: Lucene search query
        limit: Maximum number of results (1-500, default 20)
        start: Pagination offset — index of the first record to return (default 0).
               Use with limit to page through results: start=0 limit=500 for page 1,
               start=500 limit=500 for page 2, etc.
        fields: Comma-separated fields to return

    Returns:
        JSON object with ``data`` (array of matching entities) and ``pagination``
        (``total``, ``start``, ``count``, ``has_more``, ``next_start``).
        When ``has_more`` is true, call again with ``start=<next_start>``
        to fetch the next page.

    Examples:
        - search_entities(entity="Placement", query="status:Approved")
        - search_entities(entity="ClientCorporation", query="name:Acme*")
        - search_entities(entity="JobSubmission", query="jobOrder.id:12345")
        - search_entities(entity="Candidate", query="status:Active", limit=500, start=500)

    Note on entity="Note": /search/Note runs Lucene over the comments text field only.
    Filtering by subject-entity ID (e.g. personReference.id:N, jobOrder.id:N) is unreliable
    and should not be used to fetch notes for a specific record. Use get_notes_for_entity
    for record-scoped reads. Use search_notes for full-text keyword search across all notes.
    """
    try:
        client = get_client()

        meta = client.search_with_meta(
            entity=entity,
            query=query,
            fields=fields,
            count=limit,
            start=start,
        )

        return format_response(_paginate_envelope(meta, start, limit))

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def query_entities(
    entity: str,
    where: str,
    limit: int = 20,
    start: int = 0,
    fields: str | None = None,
    order_by: str | None = None,
) -> str:
    """Query Bullhorn entities using SQL-like WHERE syntax.

    Soft-deleted records (isDeleted=true) are excluded by default.

    Args:
        entity: Entity type (JobOrder, Candidate, etc.)
        where: WHERE clause (e.g., "salary > 100000 AND status='Active'")
        limit: Maximum number of results (1-500, default 20)
        start: Pagination offset — index of the first record to return (default 0).
               Use with limit to page through results: start=0 limit=500 for page 1,
               start=500 limit=500 for page 2, etc.
        fields: Comma-separated fields to return
        order_by: Sort order (e.g., "-dateAdded" for newest first)

    Returns:
        JSON object with ``data`` (array of matching entities) and ``pagination``
        (``total``, ``start``, ``count``, ``has_more``, ``next_start``).
        When ``has_more`` is true, call again with ``start=<next_start>``
        to fetch the next page.

    Examples:
        - query_entities(entity="JobOrder", where="salary > 100000")
        - query_entities(entity="Candidate", where="status='Active'", order_by="-dateAdded")
        - query_entities(entity="Placement", where="status='Approved'", limit=500, start=500)

    Note: entity="Note" is not supported — Bullhorn does not expose /query/Note.
    Use get_notes_for_entity for record-scoped reads or search_notes for full-text search.
    """
    if entity == "Note":
        return format_response({
            "error": "entity_not_queryable",
            "message": (
                "Note does not support /query in Bullhorn. "
                "Use get_notes_for_entity(entity, entity_id) to fetch all notes on a record, "
                "or search_notes(query) to search note content by keyword."
            ),
        })

    try:
        client = get_client()

        meta = client.query_with_meta(
            entity=entity,
            where=where,
            fields=fields,
            count=limit,
            start=start,
            order_by=order_by,
        )

        return format_response(_paginate_envelope(meta, start, limit))

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def search_emails(
    person_id: int,
    user: str | dict | None = None,
    since: str | None = None,
    until: str | None = None,
    subject_contains: str | None = None,
    include_body: bool = False,
    limit: int = 20,
    start: int = 0,
    fields: str | None = None,
) -> str:
    """Search Bullhorn email messages (UserMessage) for a person's mailbox.

    Returns emails sent to or from a Candidate or ClientContact, optionally
    filtered to those that also involve a specific recruiter (CorporateUser),
    a date range, or a subject substring. Sorted most-recent-first by
    smtpReceiveDate.

    Args:
        person_id: ID of the Candidate or ClientContact whose mailbox to
            search. CorporateUser ids are not accepted here — to filter by
            recruiter, put them on the ``user`` argument instead. Resolve
            names to ids first via list_candidates / list_contacts /
            search_entities.
        user: Optional CorporateUser filter. Accepts {"id": N} or a name
            string (resolved via /query/CorporateUser). If a name matches
            multiple users, returns disambiguation JSON instead of running
            the search. If omitted, defaults to the authenticated user when
            running in HTTP/Entra mode; otherwise no user filter is applied.
        since: ISO-8601 date lower bound on smtpSendDate (e.g., "2024-01-01").
        until: ISO-8601 date upper bound on smtpSendDate.
        subject_contains: Substring to match in subject. Caller is
            responsible for any Lucene escaping.
        include_body: If True, also returns the email body in the
            ``comments`` field (HTML, can be large). Off by default to keep
            responses small for bulk searches.
        limit: Maximum number of results (1-500, default 20).
        start: Pagination offset — index of the first record to return (default 0).
        fields: Override the default field selection.

    Returns:
        JSON object with ``data`` (array of UserMessage records) and ``pagination``
        (``total``, ``start``, ``count``, ``has_more``, ``next_start``).
        Each record's nested sender and recipients carry an auto-populated
        ``_subtype`` of "Candidate", "ClientContact", or "CorporateUser".
        Attachments are listed in ``messageFiles`` as metadata only — content
        download is not yet supported (pending Bullhorn support resolution).
        When ``has_more`` is true, call again with ``start=<next_start>`` for the
        next page.

    Examples:
        - search_emails(person_id=34389, limit=10)
        - search_emails(person_id=34389, user="Andrew Wynne", since="2020-01-01")
        - search_emails(person_id=34389, user={"id": 24}, include_body=True, limit=5)
    """
    try:
        client = get_client()

        # Resolve user filter to a CorporateUser id (or skip).
        user_id: int | None = None
        if user is not None:
            owner_result = client.resolve_owner(user)
            if isinstance(owner_result, list):
                return format_response({
                    "error": "user_ambiguous",
                    "matches": owner_result,
                    "message": "Multiple users matched. Specify user by ID.",
                })
            user_id = owner_result["id"]
        else:
            try:
                caller = resolve_caller(client)
                user_id = caller["id"]
            except IdentityResolutionError:
                # No JWT (stdio mode) or no matching CorporateUser —
                # search without a user filter rather than failing.
                user_id = None

        # Build Lucene query.
        clauses = [f"(sender.id:{person_id} OR recipients.id:{person_id})"]
        if user_id is not None:
            clauses.append(f"(sender.id:{user_id} OR recipients.id:{user_id})")
        if since or until:
            lo = since if since else "*"
            hi = until if until else "*"
            clauses.append(f"smtpSendDate:[{lo} TO {hi}]")
        if subject_contains:
            clauses.append(f"subject:({subject_contains})")
        query = " AND ".join(clauses)

        # Append ``comments`` only when the caller wants the body.
        resolved_fields = fields if fields is not None else DEFAULT_FIELDS["UserMessage"]
        if include_body:
            resolved_fields = f"{resolved_fields},comments"

        meta = client.search_with_meta(
            entity="UserMessage",
            query=query,
            fields=resolved_fields,
            count=limit,
            start=start,
            sort="-smtpReceiveDate",
        )

        return format_response(_paginate_envelope(meta, start, limit))

    except ValueError as e:
        # resolve_owner raises ValueError when no CorporateUser matches.
        return format_response({"error": "user_not_found", "message": str(e)})
    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def create_company(fields: dict) -> str:
    """Create a new ClientCorporation record in Bullhorn CRM.

    Args:
        fields: Dictionary of field names (or display labels) and values for the new company.
                Field labels are resolved to API names automatically (e.g. "Industry" → "industryList").
                Optional: owner (auto-populated from authenticated user if absent).
                Example: {"name": "Acme Holdings Ltd", "status": "Prospect", "phone": "+1 555 0100"}

    Returns:
        JSON object with changedEntityId, changeType, and full data of the created record.

    Examples:
        - create_company({"name": "Acme Corp", "status": "Prospect"})
        - create_company({"name": "Globex", "status": "Active Account", "phone": "+1 212 555 0100",
                          "address": {"city": "New York", "state": "NY"}})
    """
    try:
        client = get_client()
        if "owner" not in fields:
            try:
                caller = resolve_caller(client)
                fields = dict(fields)  # don't mutate input
                fields["owner"] = {"id": caller["id"]}
            except IdentityResolutionError as e:
                return format_response({
                    "error": "identity_resolution_failed",
                    "message": str(e),
                    "hint": "Provide an explicit 'owner' field or check that your email matches a Bullhorn CorporateUser.",
                })
        resolved = get_metadata().resolve_fields("ClientCorporation", fields)
        result = client.create("ClientCorporation", resolved)
        return format_response(result)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def create_contact(fields: dict, force: bool = False) -> str:
    """Create a new ClientContact record in Bullhorn CRM, linked to a company.

    Args:
        fields: Dictionary of field names (or display labels) and values.
                Required keys: clientCorporation (with an id). Optional: owner (auto-populated from authenticated user if absent).
                owner accepts either {"id": 12345} or a consultant name string
                such as "Maryrose Lyons" (resolved to a Bullhorn CorporateUser ID).
                clientCorporation must be {"id": <company_id>}.
                Example: {
                    "firstName": "Jane", "lastName": "Doe",
                    "email": "jane@acme.com", "occupation": "VP Engineering",
                    "clientCorporation": {"id": 98765},
                    "owner": "Maryrose Lyons"
                }
                'name' is computed by the MCP from firstName + lastName — do not send.
        force: If True, skip duplicate detection and create regardless. Default False.

    Returns:
        JSON object with changedEntityId, changeType, and full data of the created record.
        If owner resolves to multiple users, returns disambiguation JSON instead of creating.
        If a duplicate contact is found, returns duplicate_found JSON instead of creating
        (unless force=True).

    Examples:
        - create_contact({"firstName": "Jane", "lastName": "Doe",
                          "clientCorporation": {"id": 98765}, "owner": {"id": 12345}})
        - create_contact({"firstName": "John", "lastName": "Smith",
                          "clientCorporation": {"id": 1}, "owner": "Maryrose Lyons"})
        - create_contact({"firstName": "John", "lastName": "Smith",
                          "clientCorporation": {"id": 1}, "owner": {"id": 99}}, force=True)
    """
    try:
        client = get_client()

        if "owner" not in fields:
            try:
                caller = resolve_caller(client)
                fields = dict(fields)  # don't mutate input
                fields["owner"] = {"id": caller["id"]}
            except IdentityResolutionError as e:
                return format_response({
                    "error": "identity_resolution_failed",
                    "message": str(e),
                    "hint": "Provide an explicit 'owner' field or check that your email matches a Bullhorn CorporateUser.",
                })

        if "clientCorporation" not in fields:
            return format_response({"error": "clientCorporation_required", "message": "clientCorporation is required to create a ClientContact."})

        owner_result = client.resolve_owner(fields["owner"])

        if isinstance(owner_result, list):
            return format_response({
                "error": "owner_ambiguous",
                "matches": owner_result,
                "message": "Multiple users found. Specify owner by ID.",
            })

        contact_fields = dict(fields)
        contact_fields["owner"] = owner_result

        resolved = get_metadata().resolve_fields("ClientContact", contact_fields)
        resolved, warnings = _strip_contact_title(resolved, "ClientContact")

        computed = _compute_person_name(resolved)
        if computed:
            resolved["name"] = computed

        if not force:
            corp_id = resolved.get("clientCorporation", {}).get("id")
            first_name = resolved.get("firstName", "")
            last_name = resolved.get("lastName", "")

            if corp_id and (first_name or last_name):
                try:
                    existing = client.search(
                        "ClientContact",
                        query=f"clientCorporation.id:{corp_id}",
                        fields="id,firstName,lastName,email,phone,clientCorporation",
                        count=100,
                    )
                    candidates = existing
                except (AuthenticationError, BullhornAPIError):
                    candidates = []  # dedup search failure is non-fatal; proceed with create

                best_score = 0.0
                best_match = None
                for candidate in candidates:
                    score = score_contact_match(first_name, last_name, candidate)
                    if score > best_score:
                        best_score = score
                        best_match = candidate

                if best_score >= 0.50 and best_match is not None:
                    category = categorize_score(best_score)
                    return format_response({
                        "duplicate_found": True,
                        "match": {
                            "confidence": round(best_score, 4),
                            "category": category,
                            "record": best_match,
                        },
                        "message": (
                            "A contact matching this name already exists at this company. "
                            "Use update_record to modify the existing record, or set force=True to create regardless."
                        ),
                    })

        result = client.create("ClientContact", resolved)
        response = format_response(result)
        if warnings:
            data = json.loads(response)
            data["warnings"] = warnings
            return json.dumps(data, indent=2)
        return response

    except ValueError as e:
        return format_response({"error": "owner_not_found", "message": str(e)})
    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def create_job(
    clientCorporation: dict,
    clientContact: dict,
    title: str,
    fields: dict | None = None,
) -> str:
    """Create a new JobOrder record in Bullhorn CRM.

    Args:
        clientCorporation: Bullhorn company reference, {"id": int}. Required.
        clientContact: Bullhorn client contact reference, {"id": int}. Required.
        title: Job title string. Required.
        fields: Optional dict of additional JobOrder field names or display labels
                to values. Accepts API names, metadata labels, and configured aliases
                (BULLHORN_JOBORDER_ALIASES). Owner defaults to the authenticated
                caller's Bullhorn CorporateUser when absent. Instance-specific
                defaults (BULLHORN_JOBORDER_DEFAULTS) are applied before caller
                values, so caller values always win.

    Returns:
        JSON object with changedEntityId, changeType, and full created JobOrder data.

    Examples:
        - create_job(
              clientCorporation={"id": 12345},
              clientContact={"id": 67890},
              title="Senior Software Engineer",
              fields={
                  "source": "Email",
                  "salary": 90000,
                  "publicDescription": "Public-facing job description...",
              }
          )
    """
    if not isinstance(clientCorporation, dict) or "id" not in clientCorporation:
        return format_response({
            "error": "clientCorporation_required",
            "message": "clientCorporation must be an object containing an id.",
        })
    if not isinstance(clientContact, dict) or "id" not in clientContact:
        return format_response({
            "error": "clientContact_required",
            "message": "clientContact must be an object containing an id.",
        })
    if not isinstance(title, str) or not title.strip():
        return format_response({
            "error": "title_required",
            "message": "title must be a non-empty string.",
        })

    try:
        client = get_client()
        metadata = get_metadata()

        caller_fields = dict(fields) if fields else {}
        caller_fields["clientCorporation"] = clientCorporation
        caller_fields["clientContact"] = clientContact
        caller_fields["title"] = title

        # Owner fallback — identical pattern to create_contact
        if "owner" not in caller_fields:
            try:
                caller = resolve_caller(client)
                caller_fields["owner"] = {"id": caller["id"]}
            except IdentityResolutionError as e:
                return format_response({
                    "error": "identity_resolution_failed",
                    "message": str(e),
                    "hint": "Provide an explicit 'owner' field or check that your email matches a Bullhorn CorporateUser.",
                })
        else:
            owner_result = client.resolve_owner(caller_fields["owner"])
            if isinstance(owner_result, list):
                return format_response({
                    "error": "owner_ambiguous",
                    "matches": owner_result,
                    "message": "Multiple users found. Specify owner by ID.",
                })
            caller_fields["owner"] = owner_result

        resolved_caller = metadata.resolve_fields("JobOrder", caller_fields)
        resolved_defaults = metadata.resolve_fields("JobOrder", get_joborder_defaults())
        merged = {**resolved_defaults, **resolved_caller}

        # Validate env-defined required fields (beyond the hardcoded three above)
        env_required = get_joborder_required()
        if env_required:
            required_resolved = metadata.resolve_fields("JobOrder", {k: None for k in env_required})
            missing = [
                k for k in required_resolved
                if k not in merged or merged[k] is None or merged[k] == ""
            ]
            if missing:
                return format_response({
                    "error": "required_fields_missing",
                    "message": "Missing required JobOrder fields configured for this instance.",
                    "fields": missing,
                })

        result = client.create("JobOrder", merged)
        return format_response(result)

    except ValueError as e:
        return format_response({"error": "owner_not_found", "message": str(e)})
    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def update_job(job_id: int, fields: dict) -> str:
    """Update fields on an existing JobOrder record.

    Args:
        job_id: Bullhorn JobOrder ID to update.
        fields: Dictionary of JobOrder field names or display labels to update.

    Returns:
        JSON object with changedEntityId, changeType, and full updated JobOrder data.

    Examples:
        - update_job(12345, {"published description": "Updated public copy"})
        - update_job(12345, {"publish on website": 0, "title": "Senior Engineer"})
    """
    try:
        client = get_client()
        resolved = get_metadata().resolve_fields("JobOrder", fields)
        result = client.update("JobOrder", job_id, resolved)
        return format_response(result)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def update_record(entity: str, entity_id: int, fields: dict) -> str:
    """Update fields on an existing ClientCorporation or ClientContact record.

    Args:
        entity: "ClientContact" or "ClientCorporation"
        entity_id: Bullhorn ID of the record to update
        fields: Dictionary of field names (or display labels) and new values.
                Field labels are resolved to API names automatically.
                Company reassignment (changing clientCorporation on a ClientContact) is not supported.

    Returns:
        JSON object with changedEntityId, changeType, and full updated record.

    Examples:
        - update_record("ClientContact", 54321, {"occupation": "CTO"})
        - update_record("ClientCorporation", 98765, {"status": "Active Account"})
        - update_record("ClientContact", 54321, {"Consultant": {"id": 99}})
    """
    try:
        # CR10 owner stamping intentionally does not apply here — update_record modifies existing records only.
        client = get_client()
        resolved = get_metadata().resolve_fields(entity, fields)

        # Guard: reject company reassignment (check after resolution so label bypass is blocked)
        if entity == "ClientContact" and "clientCorporation" in resolved:
            return format_response({
                "error": "company_reassignment_not_supported",
                "message": "Company reassignment is not supported. Changing a ClientContact's associated ClientCorporation is not allowed.",
            })

        resolved, warnings = _strip_contact_title(resolved, entity)

        # Recompute name when firstName or lastName changes on person entities
        if entity in ("Candidate", "ClientContact") and ("firstName" in resolved or "lastName" in resolved):
            if "firstName" in resolved and "lastName" in resolved:
                computed = _compute_person_name(resolved)
            else:
                current = client.get(entity, entity_id, fields="firstName,lastName")
                computed = _compute_person_name({**current, **resolved})
            if computed:
                resolved["name"] = computed

        result = client.update(entity, entity_id, resolved)
        response = format_response(result)
        if warnings:
            data = json.loads(response)
            data["warnings"] = warnings
            return json.dumps(data, indent=2)
        return response

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


_NOTE_TARGET_ENTITIES = {
    "Candidate",
    "ClientContact",
    "ClientCorporation",
    "JobOrder",
    "Placement",
    "Lead",
    "Opportunity",
}

# Bullhorn phone-integration click-to-call tag: [cc:<uuid>,<number>,<number>,inbound|outbound]
_CC_TAG_RE = re.compile(
    r"\[cc:[a-f0-9-]+,[^,\]]*,[^,\]]*(,inbound|,outbound)?\]",
    re.IGNORECASE,
)

# Maps _NOTE_TARGET_ENTITIES members to the subject-reference field name on a
# Note record (mirrors the write-side _ENTITY_FIELD map in client.add_note).
_NOTE_ENTITY_SUBJECT_FIELD: dict[str, str] = {
    "Candidate": "personReference",
    "ClientContact": "personReference",
    "ClientCorporation": "clientCorporation",
    "JobOrder": "jobOrder",
    "Placement": "placements",
    "Lead": "leads",
    "Opportunity": "opportunities",
}

_NOTE_DEFAULT_FIELDS = (
    "id,action,comments,dateAdded,"
    "commentingPerson(id,firstName,lastName),"
    "personReference(id,firstName,lastName),"
    "jobOrder(id,title),"
    "placements(id),"
    "leads(id),"
    "opportunities(id),"
    "isDeleted"
)

# /search/Note and the /entity/{Entity}/{id}/notes association endpoint both
# reject clientCorporation — keep these fields in sync with _NOTE_DEFAULT_FIELDS.
_NOTE_SEARCH_DEFAULT_FIELDS = (
    "id,action,comments,dateAdded,"
    "commentingPerson(id,firstName,lastName),"
    "personReference(id,firstName,lastName),"
    "jobOrder(id,title),"
    "placements(id),"
    "leads(id),"
    "opportunities(id),"
    "isDeleted"
)


def _strip_cc_telemetry(comments: str) -> tuple[str, list[str]]:
    """Remove click-to-call tags from a note comments string.

    Returns (cleaned_comments, list_of_removed_tags).
    """
    full_matches = [m.group(0) for m in _CC_TAG_RE.finditer(comments)]
    cleaned = _CC_TAG_RE.sub("", comments).strip()
    return cleaned, full_matches


@mcp.tool()
def add_note(entity: str, entity_id: int, action: str, comments: str) -> str:
    """Add a Note to a Bullhorn record.

    Args:
        entity: One of "Candidate", "ClientContact", "ClientCorporation",
            "JobOrder", "Placement", "Lead", or "Opportunity"
        entity_id: Bullhorn ID of the record to attach the note to
        action: Note action type — must match a valid action in your Bullhorn instance (e.g. "General Note")
        comments: Note body text

    Returns:
        JSON object with changedEntityId, changeType, and full Note record data.

    Examples:
        - add_note("Candidate", 11111, "General Note", "Strong fit for senior roles")
        - add_note("ClientContact", 54321, "General Note", "Discovered via weekly scan")
        - add_note("ClientCorporation", 98765, "General Note", "PE-backed, growing headcount")
        - add_note("JobOrder", 22222, "General Note", "Role put on hold pending budget approval")
        - add_note("Placement", 33333, "General Note", "Candidate started — all good")
    """
    try:
        client = get_client()

        if entity not in _NOTE_TARGET_ENTITIES:
            return format_response({
                "error": "invalid_entity",
                "message": (
                    f"add_note does not support entity '{entity}'. "
                    f"Supported: {', '.join(sorted(_NOTE_TARGET_ENTITIES))}."
                ),
            })

        valid_actions = _load_valid_note_actions(get_metadata())
        if valid_actions is not None and action not in valid_actions:
            return format_response({
                "error": "invalid_action",
                "message": f"'{action}' is not a valid Note action for this Bullhorn instance.",
                "valid_actions": sorted(valid_actions),
            })

        commenting_person_id = None
        try:
            caller = resolve_caller(client)
            commenting_person_id = caller["id"]
        except IdentityResolutionError:
            pass

        result = client.add_note(entity, entity_id, action, comments, commenting_person_id=commenting_person_id)
        return format_response(result)

    except (AuthenticationError, BullhornAPIError, ValueError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def find_duplicate_companies(
    name: str,
    website: str | None = None,
    phone: str | None = None,
) -> str:
    """Check whether a company already exists in Bullhorn using fuzzy name matching.

    Args:
        name: Company name to search for
        website: Optional website for additional context (not used in matching currently)
        phone: Optional phone for additional context (not used in matching currently)

    Returns:
        JSON object: {"query": name, "matches": [...], "exact_match": bool}
        Each match includes confidence score, category (exact/likely/possible), and record fields.

    Examples:
        - find_duplicate_companies(name="BNY") - Returns "Bank of New York Mellon" as likely match
        - find_duplicate_companies(name="Acme Holdings Ltd") - Returns exact match if exists
    """
    try:
        client = get_client()
        results = client.search(
            "ClientCorporation",
            query=_company_broad_query(name),
            fields="id,name,status,phone",
            count=50,
        )

        matches = []
        for record in results:
            score = score_company_match(name, record.get("name", ""))
            if score >= 0.50:
                matches.append({
                    "confidence": round(score, 4),
                    "category": categorize_score(score),
                    "record": record,
                })

        matches.sort(key=lambda m: m["confidence"], reverse=True)
        exact_match = bool(matches and matches[0]["category"] == "exact")

        return format_response({"query": name, "matches": matches, "exact_match": exact_match})

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def find_duplicate_contacts(
    first_name: str,
    last_name: str,
    client_corporation_id: int | None = None,
    company_name: str | None = None,
    email: str | None = None,
) -> str:
    """Check whether a contact already exists at a given company in Bullhorn.

    Args:
        first_name: Contact's first name
        last_name: Contact's last name
        client_corporation_id: Bullhorn ClientCorporation ID to scope the search
        company_name: Company name to resolve when client_corporation_id is not provided
        email: Optional input email; same-name contacts with different emails are partial matches

    Returns:
        JSON object: {"query": {...}, "matches": [...], "exact_match": bool}
        Partial matches (same name, different email) are flagged with "partial_match": true.

    Examples:
        - find_duplicate_contacts("John", "Smith", 123)
        - find_duplicate_contacts("John", "Smith", company_name="Acme Ltd")
    """
    try:
        client = get_client()
        resolved_company_id = client_corporation_id
        resolved_company: dict | None = None

        if resolved_company_id is None:
            if not company_name:
                return format_response({
                    "error": "company_reference_required",
                    "message": "Provide either client_corporation_id or company_name.",
                })

            companies = client.search(
                "ClientCorporation",
                query=_company_broad_query(company_name),
                fields="id,name,status,phone",
                count=50,
            )

            company_matches = []
            for company in companies:
                score = score_company_match(company_name, company.get("name", ""))
                if score >= 0.75:
                    company_matches.append((score, company))

            company_matches.sort(key=lambda match: match[0], reverse=True)
            if not company_matches:
                return format_response({
                    "error": "company_not_found",
                    "message": f"No likely ClientCorporation match found for '{company_name}'.",
                    "company_name": company_name,
                })

            best_company_score, resolved_company = company_matches[0]
            resolved_company_id = resolved_company.get("id")
            if resolved_company_id is None:
                return format_response({
                    "error": "company_missing_id",
                    "message": f"Resolved ClientCorporation for '{company_name}' did not include an id.",
                    "company": resolved_company,
                })
            resolved_company = {
                **resolved_company,
                "confidence": round(best_company_score, 4),
                "category": categorize_score(best_company_score),
            }

        results = client.search(
            "ClientContact",
            query=f"clientCorporation.id:{resolved_company_id}",
            fields="id,firstName,lastName,email,phone,clientCorporation",
            count=100,
        )

        matches = []
        query_email = email.lower().strip() if email else None
        for record in results:
            score = score_contact_match(first_name, last_name, record)
            if score >= 0.50:
                match_entry: dict = {
                    "confidence": round(score, 4),
                    "category": categorize_score(score),
                    "record": record,
                }
                # Flag as partial if same name but email is present and differs
                query_full = f"{first_name} {last_name}".lower().strip()
                cand_full = f"{record.get('firstName', '')} {record.get('lastName', '')}".lower().strip()
                candidate_email = (record.get("email") or "").lower().strip()
                if (
                    query_full == cand_full
                    and query_email
                    and candidate_email
                    and candidate_email != query_email
                ):
                    match_entry["partial_match"] = True
                matches.append(match_entry)

        matches.sort(key=lambda m: m["confidence"], reverse=True)
        exact_match = bool(matches and matches[0]["category"] == "exact")

        return format_response({
            "query": {
                "firstName": first_name,
                "lastName": last_name,
                "email": email,
                "clientCorporation": {"id": resolved_company_id},
                "company_name": company_name,
            },
            "resolved_company": resolved_company,
            "matches": matches,
            "exact_match": exact_match,
        })

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def create_candidate(fields: dict, force: bool = False) -> str:
    """Create a new Candidate record in Bullhorn CRM.

    Args:
        fields: Dictionary of field names (or display labels) and values.
                Required keys: firstName, lastName.
                Optional: occupation (job title), companyName (free text, NOT clientCorporation),
                email, mobile, phone, skillSet, source, status, owner.
                owner accepts {"id": int} or a consultant name string.
                'title' is not a valid Candidate field — use 'occupation' for job title.
                'clientCorporation' is not valid — use 'companyName' (free text).
                'name' is auto-computed from firstName + lastName — do not send.
                Example: {
                    "firstName": "Jane", "lastName": "Doe",
                    "occupation": "Senior Engineer", "companyName": "Acme Corp",
                    "email": "jane@example.com", "mobile": "555-0001",
                    "source": "LinkedIn"
                }
        force: If True, skip duplicate detection and create regardless. Default False.

    Returns:
        JSON object with changedEntityId, changeType, and full data of the created record.
        If a duplicate is found, returns duplicate_found JSON instead (unless force=True).
        If owner resolves to multiple users, returns disambiguation JSON instead of creating.

    Examples:
        - create_candidate({"firstName": "Jane", "lastName": "Doe", "occupation": "Engineer"})
        - create_candidate({"firstName": "John", "lastName": "Smith", "email": "j@x.com"}, force=True)
    """
    try:
        client = get_client()

        if "clientCorporation" in fields:
            return format_response({
                "error": "clientCorporation_not_valid",
                "message": "Candidate does not have a clientCorporation field. Use 'companyName' (free text) for the current employer.",
            })

        fields = dict(fields)

        if "owner" not in fields:
            try:
                caller = resolve_caller(client)
                fields["owner"] = {"id": caller["id"]}
            except IdentityResolutionError as e:
                return format_response({
                    "error": "identity_resolution_failed",
                    "message": str(e),
                    "hint": "Provide an explicit 'owner' field or check that your email matches a Bullhorn CorporateUser.",
                })

        if not fields.get("firstName") or not str(fields["firstName"]).strip():
            return format_response({"error": "firstName_required", "message": "firstName is required to create a Candidate."})
        if not fields.get("lastName") or not str(fields["lastName"]).strip():
            return format_response({"error": "lastName_required", "message": "lastName is required to create a Candidate."})

        metadata = get_metadata()
        defaults = get_candidate_defaults()
        resolved_input = metadata.resolve_fields("Candidate", fields)
        merged = {**metadata.resolve_fields("Candidate", defaults), **resolved_input}

        owner_result = client.resolve_owner(merged["owner"])
        if isinstance(owner_result, list):
            return format_response({
                "error": "owner_ambiguous",
                "matches": owner_result,
                "message": "Multiple users found. Specify owner by ID.",
            })
        merged["owner"] = owner_result

        # Stamp source with configured MCP value if not already set
        if not merged.get("source"):
            merged["source"] = get_mcp_source()

        # Validate tenant-configured required fields
        env_required = get_candidate_required()
        if env_required:
            required_resolved = metadata.resolve_fields("Candidate", {k: None for k in env_required})
            missing = [k for k in required_resolved if k not in merged or merged[k] is None or merged[k] == ""]
            if missing:
                return format_response({
                    "error": "required_fields_missing",
                    "message": "Missing required Candidate fields configured for this instance.",
                    "fields": missing,
                })

        resolved = metadata.resolve_fields("Candidate", merged)

        # Guard after resolution so label bypass is blocked (mirrors update_record pattern)
        if "clientCorporation" in resolved:
            return format_response({
                "error": "clientCorporation_not_valid",
                "message": "Candidate does not have a clientCorporation field. Use 'companyName' (free text) for the current employer.",
            })

        resolved, warnings = _strip_contact_title(resolved, "Candidate")

        computed = _compute_person_name(resolved)
        if computed:
            resolved["name"] = computed

        if not force:
            first_name = str(resolved.get("firstName", ""))
            last_name = str(resolved.get("lastName", ""))
            email = resolved.get("email")
            dup = _check_candidate_duplicates(client, first_name, last_name, email)
            if dup is not None:
                return format_response({
                    "duplicate_found": True,
                    "match": dup,
                    "message": (
                        "A Candidate matching this name or email already exists. "
                        "Use update_record to modify the existing record, or set force=True to create regardless."
                    ),
                })

        result = client.create("Candidate", resolved)
        if warnings:
            data = json.loads(format_response(result))
            data["warnings"] = warnings
            return json.dumps(data, indent=2)
        return format_response(result)

    except ValueError as e:
        return format_response({"error": "owner_not_found", "message": str(e)})
    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def find_duplicate_candidates(
    first_name: str,
    last_name: str,
    email: str | None = None,
) -> str:
    """Check whether a Candidate already exists in Bullhorn using name and optional email.

    Args:
        first_name: Candidate's first name
        last_name: Candidate's last name
        email: Optional email for exact-match detection (highest signal)

    Returns:
        JSON object: {"query": {...}, "matches": [...], "exact_match": bool}
        Each match includes confidence score, category (exact/likely/possible), and record fields.

    Examples:
        - find_duplicate_candidates("Jane", "Doe")
        - find_duplicate_candidates("Jane", "Doe", email="jane@example.com")
    """
    try:
        client = get_client()

        query_parts = []
        if email:
            query_parts.append(f'email:"{email}"')
        if first_name:
            query_parts.append(f'firstName:"{first_name}"')
        if last_name:
            query_parts.append(f'lastName:"{last_name}"')

        if not query_parts:
            return format_response({"error": "query_required", "message": "Provide at least one of: first_name, last_name, email."})

        results = client.search(
            "Candidate",
            query=" OR ".join(query_parts),
            fields="id,firstName,lastName,email,phone,occupation,companyName,dateAdded",
            count=50,
        )

        matches = []
        for record in results:
            if email and (record.get("email") or "").lower().strip() == email.lower().strip():
                score = 1.0
            else:
                score = score_contact_match(first_name, last_name, record)
            if score >= 0.50:
                matches.append({
                    "confidence": round(score, 4),
                    "category": categorize_score(score),
                    "record": record,
                })

        matches.sort(key=lambda m: m["confidence"], reverse=True)
        exact_match = bool(matches and matches[0]["category"] == "exact")

        return format_response({
            "query": {"firstName": first_name, "lastName": last_name, "email": email},
            "matches": matches,
            "exact_match": exact_match,
        })

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def parse_cv(
    file_b64: str,
    filename: str,
    format: str = "pdf",
) -> str:
    """Parse a binary CV file and return the extracted fields without saving anything.

    The CV is sent to Bullhorn's resume parser (POST /resume/parseToCandidate).
    Nothing is written to Bullhorn — this is a preview-only operation.
    Also runs a duplicate candidate check on the parsed name and email.

    Args:
        file_b64: Base64-encoded CV file bytes (PDF, DOC, DOCX, HTML, or text)
        filename: Original filename (e.g. "jane_doe_cv.pdf")
        format: File format hint: pdf, doc, docx, html, text. Default: pdf

    Returns:
        JSON object:
        {
            "parsed": {
                "candidate": {...},
                "candidateEducation": [...],
                "candidateWorkHistory": [...],
                "skillList": [...]
            },
            "duplicate_check": null | {"confidence": ..., "category": ..., "record": {...}}
        }

    Examples:
        - parse_cv(file_b64="...", filename="cv.pdf")
        - parse_cv(file_b64="...", filename="resume.docx", format="docx")
    """
    try:
        client = get_client()
        try:
            file_bytes = base64.b64decode(file_b64)
        except Exception as e:
            return format_response({"error": "invalid_base64", "message": f"Could not decode file_b64: {e}"})

        parsed = client.parse_resume_file(file_bytes, filename, format)

        candidate_data = parsed.get("candidate", {})
        first_name = candidate_data.get("firstName", "")
        last_name = candidate_data.get("lastName", "")
        email = candidate_data.get("email")

        dup = _check_candidate_duplicates(client, first_name, last_name, email)

        return format_response({"parsed": parsed, "duplicate_check": dup})

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def parse_cv_text(
    content: str,
    content_type: str = "text/plain",
) -> str:
    """Parse pasted CV text and return the extracted fields without saving anything.

    The text is sent to Bullhorn's JSON resume parser (POST /resume/parseToCandidateViaJson).
    Nothing is written to Bullhorn — this is a preview-only operation.
    Also runs a duplicate candidate check on the parsed name and email.

    Args:
        content: Plain text or HTML CV content
        content_type: MIME type: "text/plain" (default) or "text/html"

    Returns:
        JSON object:
        {
            "parsed": {
                "candidate": {...},
                "candidateEducation": [...],
                "candidateWorkHistory": [...],
                "skillList": [...]
            },
            "duplicate_check": null | {"confidence": ..., "category": ..., "record": {...}}
        }

    Examples:
        - parse_cv_text(content="Jane Doe\\nSenior Engineer\\njane@example.com\\n...")
        - parse_cv_text(content="<html>...</html>", content_type="text/html")
    """
    try:
        client = get_client()
        parsed = client.parse_resume_text(content, content_type)

        candidate_data = parsed.get("candidate", {})
        first_name = candidate_data.get("firstName", "")
        last_name = candidate_data.get("lastName", "")
        email = candidate_data.get("email")

        dup = _check_candidate_duplicates(client, first_name, last_name, email)

        return format_response({"parsed": parsed, "duplicate_check": dup})

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def create_candidate_from_cv(
    file_b64: str | None = None,
    filename: str | None = None,
    format: str = "pdf",
    content: str | None = None,
    content_type: str = "text/plain",
    force: bool = False,
    fields_override: dict | None = None,
) -> str:
    """Parse a CV and create a Candidate record in one operation.

    Supports two input modes:
    - Binary: provide file_b64 + filename (PDF, DOC, DOCX, HTML)
    - Text: provide content (plain text or HTML)
    Exactly one mode must be used.

    Flow: parse → duplicate check → create Candidate → write child records
    (education, work history, skills) → attach CV file (binary only).
    Child record failures are best-effort — warnings are included in the response.

    Args:
        file_b64: Base64-encoded CV bytes (binary mode)
        filename: Original filename for the CV (binary mode)
        format: File format hint: pdf, doc, docx, html, text. Default: pdf
        content: Plain text or HTML CV content (text mode)
        content_type: MIME type for text mode. Default: text/plain
        force: Skip duplicate check and create regardless. Default False.
        fields_override: Optional additional Candidate fields that override parsed values.

    Returns:
        If no duplicate: JSON with candidate_id, work_history_ids, education_ids,
        skills_added, file_attachment (null for text-only), and optional warnings.
        If duplicate found: JSON with duplicate_found, match, and parsed fields.

    Examples:
        - create_candidate_from_cv(file_b64="...", filename="cv.pdf")
        - create_candidate_from_cv(content="Jane Doe\\nEngineer...", content_type="text/plain")
        - create_candidate_from_cv(file_b64="...", filename="cv.pdf", force=True,
                                   fields_override={"source": "Referral"})
    """
    is_binary = file_b64 is not None and filename is not None
    is_text = content is not None

    if not is_binary and not is_text:
        return format_response({
            "error": "input_required",
            "message": "Provide either (file_b64 + filename) for binary input or content for text input.",
        })
    if is_binary and is_text:
        return format_response({
            "error": "ambiguous_input",
            "message": "Provide either binary (file_b64 + filename) or text (content), not both.",
        })

    try:
        client = get_client()
        metadata = get_metadata()
        file_bytes: bytes | None = None

        if is_binary:
            try:
                file_bytes = base64.b64decode(file_b64)
            except Exception as e:
                return format_response({"error": "invalid_base64", "message": f"Could not decode file_b64: {e}"})
            parsed = client.parse_resume_file(file_bytes, filename, format)
        else:
            parsed = client.parse_resume_text(content, content_type)

        candidate_data = dict(parsed.get("candidate", {}))
        first_name = candidate_data.get("firstName", "")
        last_name = candidate_data.get("lastName", "")
        email = candidate_data.get("email")

        if not force:
            dup = _check_candidate_duplicates(client, first_name, last_name, email)
            if dup is not None:
                return format_response({
                    "duplicate_found": True,
                    "match": dup,
                    "parsed": parsed,
                    "hint": (
                        "A matching Candidate already exists. "
                        "Use attach_cv to update the existing record and attach this CV, "
                        "or pass force=True to create a new record anyway."
                    ),
                })

        # Build candidate payload from parsed data + overrides
        if fields_override:
            candidate_data.update(fields_override)

        # Owner stamping
        if "owner" not in candidate_data:
            try:
                caller = resolve_caller(client)
                candidate_data["owner"] = {"id": caller["id"]}
            except IdentityResolutionError as e:
                return format_response({
                    "error": "identity_resolution_failed",
                    "message": str(e),
                    "hint": "Provide an explicit owner in fields_override or check that your email matches a Bullhorn CorporateUser.",
                })

        # Apply tenant defaults
        defaults = get_candidate_defaults()
        candidate_data = {**metadata.resolve_fields("Candidate", defaults), **candidate_data}

        # Stamp source with configured MCP value if not already set
        if not candidate_data.get("source"):
            candidate_data["source"] = get_mcp_source()

        resolved = metadata.resolve_fields("Candidate", candidate_data)
        resolved, strip_warnings = _strip_contact_title(resolved, "Candidate")
        resolved = _truncate_against_meta(metadata, "Candidate", resolved)

        env_required = get_candidate_required()
        if env_required:
            required_resolved = metadata.resolve_fields("Candidate", {k: None for k in env_required})
            missing = [k for k in required_resolved if k not in resolved or resolved[k] is None or resolved[k] == ""]
            if missing:
                return format_response({
                    "error": "required_fields_missing",
                    "message": "Missing required Candidate fields configured for this instance.",
                    "fields": missing,
                })

        computed = _compute_person_name(resolved)
        if computed:
            resolved["name"] = computed

        create_result = client.create("Candidate", resolved)
        candidate_id = create_result["changedEntityId"]

        warnings: list[str] = list(strip_warnings)
        work_history_ids: list[int] = []
        education_ids: list[int] = []
        skills_added: dict = {"matched_ids": [], "appended_to_skillset": []}

        # Write work history (best-effort)
        for entry in parsed.get("candidateWorkHistory", []):
            try:
                wh = dict(entry)
                wh["candidate"] = {"id": candidate_id}
                wh.pop("id", None)
                wh = _truncate_against_meta(metadata, "CandidateWorkHistory", wh)
                r = client.create("CandidateWorkHistory", wh)
                work_history_ids.append(r["changedEntityId"])
            except Exception as exc:
                warnings.append(f"Work history entry failed: {exc}")

        # Write education (best-effort)
        for entry in parsed.get("candidateEducation", []):
            try:
                edu = dict(entry)
                edu["candidate"] = {"id": candidate_id}
                edu.pop("id", None)
                edu = _truncate_against_meta(metadata, "CandidateEducation", edu)
                r = client.create("CandidateEducation", edu)
                education_ids.append(r["changedEntityId"])
            except Exception as exc:
                warnings.append(f"Education entry failed: {exc}")

        # Process skills (best-effort)
        matched_skill_ids: list[int] = []
        unmatched_skill_names: list[str] = []
        for skill in parsed.get("skillList", []):
            if skill.get("id"):
                matched_skill_ids.append(skill["id"])
            elif skill.get("name"):
                unmatched_skill_names.append(skill["name"])

        if matched_skill_ids:
            try:
                client.update(
                    "Candidate",
                    candidate_id,
                    {"primarySkills": {"data": [{"id": sid} for sid in matched_skill_ids]}},
                )
                skills_added["matched_ids"] = matched_skill_ids
            except Exception as exc:
                warnings.append(f"primarySkills update failed: {exc}")

        if unmatched_skill_names:
            try:
                existing = client.get("Candidate", candidate_id, fields="skillSet")
                existing_skillset = existing.get("skillSet") or ""
                combined = ", ".join(filter(None, [existing_skillset] + unmatched_skill_names))
                client.update("Candidate", candidate_id, {"skillSet": combined})
                skills_added["appended_to_skillset"] = unmatched_skill_names
            except Exception as exc:
                warnings.append(f"skillSet update failed: {exc}")

        # Attach CV file (binary mode only)
        file_attachment = None
        if is_binary and file_bytes is not None:
            try:
                content_mime = client._guess_content_type(format)
                file_attachment = client.attach_file(
                    "Candidate", candidate_id, file_bytes, filename, content_mime, file_type="CV"
                )
            except Exception as exc:
                warnings.append(f"CV file attachment failed: {exc}")

        result: dict = {
            "created": True,
            "candidate_id": candidate_id,
            "work_history_ids": work_history_ids,
            "education_ids": education_ids,
            "skills_added": skills_added,
            "file_attachment": file_attachment,
        }
        if warnings:
            result["warnings"] = warnings

        return format_response(result)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def attach_cv(
    candidate_id: int,
    file_b64: str,
    filename: str,
    format: str = "pdf",
    fields_to_update: list | None = None,
    include_work_history: bool = False,
    include_education: bool = False,
    include_skills: bool = False,
    force_all: bool = False,
) -> str:
    """Attach a CV to an existing Candidate, with per-field diff and confirmation.

    This tool uses a two-call confirmation flow:

    **Call 1 — preview** (omit fields_to_update, force_all=False):
    Parses the CV, fetches the existing Candidate, diffs the fields, and returns
    a preview of what would change. Nothing is written. The CV is not yet attached.

    **Call 2 — commit** (provide fields_to_update or force_all=True):
    Re-parses the CV, applies only the listed field updates, optionally writes
    new work history / education / skills entries, and attaches the CV file.

    Args:
        candidate_id: Bullhorn Candidate ID of the existing record.
        file_b64: Base64-encoded CV bytes (PDF, DOC, DOCX, HTML, or text).
        filename: Original filename for the CV.
        format: File format hint: pdf, doc, docx, html, text. Default: pdf.
        fields_to_update: List of Candidate field API names to apply from parsed data.
                          If None and force_all=False, returns preview only.
        include_work_history: If True (commit only), write new work history entries.
        include_education: If True (commit only), write new education entries.
        include_skills: If True (commit only), update skills from the CV.
        force_all: If True, apply every proposed field change and all sections
                   without an explicit list (commit shorthand).

    Returns:
        Preview: {"preview": true, "candidate_id": ..., "proposed_field_changes": [...],
                  "proposed_work_history": [...], "proposed_education": [...],
                  "proposed_skills": {...}, "message": "..."}
        Commit: {"committed": true, "candidate_id": ..., "fields_updated": [...],
                 "work_history_added": [...], "education_added": [...],
                 "skills_added": {...}, "file_attachment": {...}}

    Examples:
        - attach_cv(candidate_id=123, file_b64="...", filename="cv.pdf")
        - attach_cv(candidate_id=123, file_b64="...", filename="cv.pdf",
                    fields_to_update=["occupation", "email"], include_work_history=True)
        - attach_cv(candidate_id=123, file_b64="...", filename="cv.pdf", force_all=True)
    """
    try:
        client = get_client()
        metadata = get_metadata()

        try:
            file_bytes = base64.b64decode(file_b64)
        except Exception as e:
            return format_response({"error": "invalid_base64", "message": f"Could not decode file_b64: {e}"})

        parsed = client.parse_resume_file(file_bytes, filename, format)
        parsed_candidate = parsed.get("candidate", {})

        # Fetch current record (broad field set for diffing)
        existing = client.get(
            "Candidate",
            candidate_id,
            fields="id,firstName,lastName,email,phone,mobile,occupation,companyName,skillSet,status,dateAdded",
        )

        # --- DIFF scalar fields ---
        proposed_changes = []
        for field, proposed_val in parsed_candidate.items():
            if field in ("id", "name", "title") or not isinstance(proposed_val, (str, int, float, bool)):
                continue
            current_val = existing.get(field)
            if proposed_val != current_val:
                proposed_changes.append({
                    "field": field,
                    "current": current_val,
                    "proposed": proposed_val,
                })

        # --- Diff work history (match on companyName + title + dateBegin + dateEnd) ---
        existing_wh_keys: set = set()
        try:
            existing_wh = client.query(
                "CandidateWorkHistory",
                where=f"candidate.id={candidate_id}",
                fields="id,companyName,title,startDate,endDate",
            )
            existing_wh_keys = {
                (r.get("companyName", ""), r.get("title", ""), r.get("startDate"), r.get("endDate"))
                for r in existing_wh
            }
        except Exception:
            existing_wh = []

        proposed_wh = []
        for entry in parsed.get("candidateWorkHistory", []):
            key = (entry.get("companyName", ""), entry.get("title", ""), entry.get("startDate"), entry.get("endDate"))
            if key not in existing_wh_keys:
                proposed_wh.append(entry)

        # --- Diff education (match on school + degree + startDate + endDate) ---
        existing_edu_keys: set = set()
        try:
            existing_edu = client.query(
                "CandidateEducation",
                where=f"candidate.id={candidate_id}",
                fields="id,school,degree,startDate,endDate",
            )
            existing_edu_keys = {
                (r.get("school", ""), r.get("degree", ""), r.get("startDate"), r.get("endDate"))
                for r in existing_edu
            }
        except Exception:
            existing_edu = []

        proposed_edu = []
        for entry in parsed.get("candidateEducation", []):
            key = (entry.get("school", ""), entry.get("degree", ""), entry.get("startDate"), entry.get("endDate"))
            if key not in existing_edu_keys:
                proposed_edu.append(entry)

        # --- Skills ---
        matched_skills = [s for s in parsed.get("skillList", []) if s.get("id")]
        unmatched_skills = [s["name"] for s in parsed.get("skillList", []) if not s.get("id") and s.get("name")]
        proposed_skills = {"matched": matched_skills, "unmatched_to_skillset": unmatched_skills}

        is_preview = fields_to_update is None and not force_all

        if is_preview:
            return format_response({
                "preview": True,
                "candidate_id": candidate_id,
                "proposed_field_changes": proposed_changes,
                "proposed_work_history": proposed_wh,
                "proposed_education": proposed_edu,
                "proposed_skills": proposed_skills,
                "message": (
                    "Review the proposed changes. To commit, call attach_cv again with "
                    "fields_to_update=[...] listing only the field names you want applied. "
                    "Pass include_work_history=True / include_education=True / include_skills=True "
                    "to commit those sections. The CV file will be attached only on the commit call. "
                    "Or pass force_all=True to apply everything at once."
                ),
            })

        # --- COMMIT ---
        apply_fields = {c["field"] for c in proposed_changes} if force_all else set(fields_to_update or [])
        apply_wh = force_all or include_work_history
        apply_edu = force_all or include_education
        apply_skills = force_all or include_skills

        fields_updated: list[str] = []
        work_history_added: list[int] = []
        education_added: list[int] = []
        skills_committed: dict = {"matched_ids": [], "appended_to_skillset": []}
        warnings: list[str] = []

        if apply_fields:
            update_payload = {}
            for change in proposed_changes:
                if change["field"] in apply_fields:
                    update_payload[change["field"]] = change["proposed"]
            if update_payload:
                update_payload = _truncate_against_meta(metadata, "Candidate", update_payload)
                update_payload, strip_warns = _strip_contact_title(update_payload, "Candidate")
                warnings.extend(strip_warns)
                if "firstName" in update_payload or "lastName" in update_payload:
                    if "firstName" in update_payload and "lastName" in update_payload:
                        computed = _compute_person_name(update_payload)
                    else:
                        current = client.get("Candidate", candidate_id, fields="firstName,lastName")
                        computed = _compute_person_name({**current, **update_payload})
                    if computed:
                        update_payload["name"] = computed
                client.update("Candidate", candidate_id, update_payload)
                fields_updated = list(update_payload.keys())

        if apply_wh:
            for entry in proposed_wh:
                try:
                    wh = dict(entry)
                    wh["candidate"] = {"id": candidate_id}
                    wh.pop("id", None)
                    wh = _truncate_against_meta(metadata, "CandidateWorkHistory", wh)
                    r = client.create("CandidateWorkHistory", wh)
                    work_history_added.append(r["changedEntityId"])
                except Exception as exc:
                    warnings.append(f"Work history entry failed: {exc}")

        if apply_edu:
            for entry in proposed_edu:
                try:
                    edu = dict(entry)
                    edu["candidate"] = {"id": candidate_id}
                    edu.pop("id", None)
                    edu = _truncate_against_meta(metadata, "CandidateEducation", edu)
                    r = client.create("CandidateEducation", edu)
                    education_added.append(r["changedEntityId"])
                except Exception as exc:
                    warnings.append(f"Education entry failed: {exc}")

        if apply_skills:
            if matched_skills:
                try:
                    client.update(
                        "Candidate",
                        candidate_id,
                        {"primarySkills": {"data": [{"id": s["id"]} for s in matched_skills]}},
                    )
                    skills_committed["matched_ids"] = [s["id"] for s in matched_skills]
                except Exception as exc:
                    warnings.append(f"primarySkills update failed: {exc}")
            if unmatched_skills:
                try:
                    existing_rec = client.get("Candidate", candidate_id, fields="skillSet")
                    existing_ss = existing_rec.get("skillSet") or ""
                    combined = ", ".join(filter(None, [existing_ss] + unmatched_skills))
                    client.update("Candidate", candidate_id, {"skillSet": combined})
                    skills_committed["appended_to_skillset"] = unmatched_skills
                except Exception as exc:
                    warnings.append(f"skillSet update failed: {exc}")

        # Always attach the CV file on commit
        content_mime = client._guess_content_type(format)
        file_attachment = client.attach_file(
            "Candidate", candidate_id, file_bytes, filename, content_mime, file_type="CV"
        )

        result: dict = {
            "committed": True,
            "candidate_id": candidate_id,
            "fields_updated": fields_updated,
            "work_history_added": work_history_added,
            "education_added": education_added,
            "skills_added": skills_committed,
            "file_attachment": file_attachment,
        }
        if warnings:
            result["warnings"] = warnings
        return format_response(result)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def get_entity_fields(
    entity: str,
    label: str | None = None,
    api_name: str | None = None,
) -> str:
    """Query field metadata for a Bullhorn entity type, with optional label resolution.

    Args:
        entity: Entity type (e.g. ClientContact, ClientCorporation, JobOrder)
        label: Display label to resolve to its API field name (e.g. "Consultant")
        api_name: API field name to resolve to its display label (e.g. "recruiterUserID")

    Returns:
        If neither label nor api_name: JSON array of all fields with name, label, type, required.
        If label provided: JSON object with the resolved api_name (null if not found).
        If api_name provided: JSON object with the resolved label (null if not found).

    Examples:
        - get_entity_fields(entity="ClientContact") - List all fields
        - get_entity_fields(entity="ClientContact", label="Consultant") - Resolve label -> API name
        - get_entity_fields(entity="ClientContact", api_name="recruiterUserID") - Resolve API name -> label
    """
    try:
        metadata = get_metadata()

        if label is not None:
            resolved = metadata.resolve_label_to_api(entity, label)
            return format_response({"label": label, "api_name": resolved})

        if api_name is not None:
            resolved = metadata.resolve_api_to_label(entity, api_name)
            return format_response({"api_name": api_name, "label": resolved})

        fields = metadata.get_fields(entity)
        return format_response(fields)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def bulk_import(companies: list, contacts: list) -> str:
    """Import a batch of companies and contacts into Bullhorn CRM.

    Companies are processed first (with duplicate detection), then contacts
    (with company resolution, owner resolution, and duplicate detection).
    Halts after 3 consecutive create errors to surface systemic issues.

    Args:
        companies: List of company field dicts. Each must include "name".
                   Standard fields: name, status, phone, address, industry, etc.
                   Example: [{"name": "Acme Ltd", "status": "Prospect"}]
        contacts: List of contact field dicts. Required keys: owner.
                  Use "company_name" (str) to reference a company by name,
                  or "clientCorporation" ({"id": <int>}) to reference by ID.
                  owner accepts either {"id": int} or a consultant name string.
                  Example: [{"firstName": "Jane", "lastName": "Doe",
                             "company_name": "Acme Ltd", "owner": "Mary Lyons"}]

    Returns:
        JSON object: {
            "halted": bool,
            "summary": {
                "companies": {"created": int, "existing": int, "flagged": int, "failed": int},
                "contacts": {"created": int, "existing": int, "flagged": int, "failed": int}
            },
            "details": {"companies": [...], "contacts": [...]}
        }

    Examples:
        - bulk_import(
            companies=[{"name": "Acme", "status": "Prospect"}],
            contacts=[{"firstName": "Jane", "lastName": "Doe",
                       "company_name": "Acme", "owner": "Mary Lyons"}]
          )
    """
    try:
        # CR10 owner stamping intentionally does not apply here — bulk_import callers must supply owner explicitly per contact.
        importer = BulkImporter(get_client(), get_metadata())
        result = importer.process(companies, contacts)
        return format_response(result)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


def _load_valid_note_actions(metadata: BullhornMetadata) -> set[str] | None:
    """Load and cache valid Note action picklist values from Bullhorn metadata.

    Returns the set of valid values, or None if metadata is unavailable.
    """
    global _valid_note_actions
    if _valid_note_actions is not None:
        return _valid_note_actions
    try:
        fields_meta = metadata.get_fields("Note")
        action_field = next((f for f in fields_meta if f.get("name") == "action"), None)
        if action_field:
            options = action_field.get("options", [])
            values = {o.get("value") for o in options if o.get("value")}
            if values:
                _valid_note_actions = values
                return _valid_note_actions
    except Exception:
        pass
    return None


def _validate_shortlist_status_once(metadata: BullhornMetadata, configured_status: str) -> None:
    """Warn once per process if the configured shortlist status is not in the picklist."""
    global _shortlist_status_validated
    if _shortlist_status_validated:
        return
    _shortlist_status_validated = True
    try:
        fields_meta = metadata.get_fields("JobSubmission")
        status_field = next(
            (f for f in fields_meta if f.get("name") == "status"), None
        )
        if status_field:
            valid = [o.get("value") for o in status_field.get("options", [])]
            if valid and configured_status not in valid:
                _logger.warning(
                    "BULLHORN_SHORTLIST_STATUS=%r is not in the JobSubmission status "
                    "picklist for this instance. Valid values: %s",
                    configured_status,
                    valid,
                )
    except Exception:
        pass


def _shortlist_one(
    job_id: int,
    candidate_id: int,
    resolved_status: str,
    resolved_fields: dict,
    resolved_sending_user: dict | None,
    client: BullhornClient,
) -> dict:
    """Create one JobSubmission, checking for an existing record first.

    Returns a plain dict (not JSON string). Callers wrap with format_response.
    """
    existing = client.query(
        "JobSubmission",
        where=f"candidate.id={candidate_id} AND jobOrder.id={job_id}",
        fields="id,status,dateAdded,sendingUser",
    )
    if existing:
        return {"duplicate": True, "existing": existing[0]}

    payload: dict[str, Any] = {
        "candidate": {"id": candidate_id},
        "jobOrder": {"id": job_id},
        "status": resolved_status,
    }
    payload.update({k: v for k, v in resolved_fields.items() if k != "status"})

    if "dateWebResponse" not in payload:
        payload["dateWebResponse"] = int(time.time() * 1000)

    if resolved_sending_user is not None and "sendingUser" not in payload:
        payload["sendingUser"] = resolved_sending_user

    result = client.create("JobSubmission", payload)
    return {"duplicate": False, **result}


@mcp.tool()
def shortlist_candidate(
    job_id: int,
    candidate_id: int,
    status: str | None = None,
    fields: dict | None = None,
) -> str:
    """Shortlist a candidate to a job by creating a JobSubmission record in Bullhorn.

    Performs a duplicate pre-check: if a JobSubmission already exists for this
    (candidate, job) pair, returns the existing record with duplicate=true and
    does not create a second submission.

    The 'Added By' (sendingUser) is auto-stamped to the authenticated MCP user.
    In stdio mode where identity resolution is unavailable, it falls back to the
    API service account.

    Args:
        job_id: Bullhorn JobOrder ID.
        candidate_id: Bullhorn Candidate ID.
        status: JobSubmission status string. Defaults to BULLHORN_SHORTLIST_STATUS
                env var (default "Shortlisted"). Must match a configured status
                in your Bullhorn instance.
        fields: Optional dict of additional JobSubmission field names or labels.
                Accepts API names and metadata labels. Caller values win on conflict
                with auto-stamped fields (sendingUser, dateWebResponse).

    Returns:
        JSON object with changedEntityId, changeType, data, and duplicate flag.
        If duplicate=true, the existing record is returned under "existing" and
        no new record is created.

    Examples:
        - shortlist_candidate(job_id=10, candidate_id=20)
        - shortlist_candidate(job_id=10, candidate_id=20, status="Internal Review")
        - shortlist_candidate(job_id=10, candidate_id=20, fields={"source": "Web"})
    """
    if not isinstance(job_id, int) or job_id <= 0:
        return format_response({
            "error": "invalid_argument",
            "message": "job_id must be a positive integer.",
        })
    if not isinstance(candidate_id, int) or candidate_id <= 0:
        return format_response({
            "error": "invalid_argument",
            "message": "candidate_id must be a positive integer.",
        })

    try:
        resolved_status = status or get_shortlist_status()
        client = get_client()
        metadata = get_metadata()

        _validate_shortlist_status_once(metadata, resolved_status)

        resolved_fields = metadata.resolve_fields("JobSubmission", fields or {})

        sending_user: dict | None = None
        try:
            caller = resolve_caller(client)
            sending_user = {"id": caller["id"]}
        except IdentityResolutionError:
            _logger.warning(
                "Identity resolution unavailable; sendingUser will default to API service account."
            )

        result = _shortlist_one(
            job_id, candidate_id, resolved_status, resolved_fields, sending_user, client
        )
        return format_response(result)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def shortlist_candidates(
    job_id: int,
    candidate_ids: list[int],
    status: str | None = None,
    fields: dict | None = None,
) -> str:
    """Shortlist multiple candidates to the same job in one operation.

    Calls the same logic as shortlist_candidate for each candidate_id. Identity
    resolution runs once for the batch, not per candidate.

    Returns a structured response with per-candidate status ("created",
    "duplicate", or "error") and a summary count.

    Args:
        job_id: Bullhorn JobOrder ID.
        candidate_ids: List of Bullhorn Candidate IDs to shortlist.
        status: JobSubmission status string. Defaults to BULLHORN_SHORTLIST_STATUS
                env var (default "Shortlisted").
        fields: Optional dict of additional JobSubmission fields applied to
                every candidate in the batch.

    Returns:
        JSON object with job_id, results list, and summary counts.

    Examples:
        - shortlist_candidates(job_id=10, candidate_ids=[20, 21, 22])
        - shortlist_candidates(job_id=10, candidate_ids=[20, 21], status="Internal Review")
    """
    if not isinstance(job_id, int) or job_id <= 0:
        return format_response({
            "error": "invalid_argument",
            "message": "job_id must be a positive integer.",
        })

    try:
        resolved_status = status or get_shortlist_status()
        client = get_client()
        metadata = get_metadata()

        _validate_shortlist_status_once(metadata, resolved_status)

        resolved_fields = metadata.resolve_fields("JobSubmission", fields or {})

        sending_user: dict | None = None
        try:
            caller = resolve_caller(client)
            sending_user = {"id": caller["id"]}
        except IdentityResolutionError:
            _logger.warning(
                "Identity resolution unavailable; sendingUser will default to API service account."
            )

        results = []
        created = duplicates = errors = 0

        for cid in candidate_ids:
            try:
                if not isinstance(cid, int) or cid <= 0:
                    errors += 1
                    results.append({
                        "candidate_id": cid,
                        "status": "error",
                        "error": "candidate_id must be a positive integer.",
                    })
                    continue
                outcome = _shortlist_one(
                    job_id, cid, resolved_status, resolved_fields, sending_user, client
                )
                if outcome.get("duplicate"):
                    duplicates += 1
                    results.append({
                        "candidate_id": cid,
                        "status": "duplicate",
                        "submission_id": outcome["existing"]["id"],
                    })
                else:
                    created += 1
                    results.append({
                        "candidate_id": cid,
                        "status": "created",
                        "submission_id": outcome["changedEntityId"],
                    })
            except (AuthenticationError, BullhornAPIError) as e:
                errors += 1
                results.append({
                    "candidate_id": cid,
                    "status": "error",
                    "error": str(e),
                })

        return format_response({
            "job_id": job_id,
            "results": results,
            "summary": {"created": created, "duplicates": duplicates, "errors": errors},
        })

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def get_notes_for_entity(
    entity: str,
    entity_id: int,
    limit: int = 50,
    start: int = 0,
    fields: str | None = None,
    order_by: str = "-dateAdded",
    include_deleted: bool = False,
) -> str:
    """Fetch all notes attached to a specific Bullhorn record.

    This is the correct tool for "what are the notes on candidate X / job Y / contact Z".
    Do NOT use query_entities(entity="Note") — Note does not support /query. Do NOT
    rely on search_entities(entity="Note") to filter by record ID — Lucene by subject-entity
    ID is unreliable on /search/Note. Use this tool instead.

    Args:
        entity: One of "Candidate", "ClientContact", "ClientCorporation",
            "JobOrder", "Placement", "Lead", or "Opportunity"
        entity_id: Bullhorn ID of the record whose notes to fetch
        limit: Maximum number of notes (1-500, default 50)
        start: Pagination offset (default 0)
        fields: Comma-separated Note fields to return. Default includes id, action,
            comments, dateAdded, commentingPerson, personReference, jobOrder,
            clientCorporation, isDeleted.
        order_by: Sort field with optional leading "-" for descending (default "-dateAdded").
        include_deleted: If True, include soft-deleted notes. Default False.

    Returns:
        JSON object with ``data`` (array of note dicts) and ``pagination``
        (``total``, ``start``, ``count``, ``has_more``, ``next_start``).
        Click-to-call telemetry tags are stripped from the comments field and
        moved to a sibling ``call_metadata`` list. When ``has_more`` is true,
        call again with ``start=<next_start>`` for the next page.
        ``next_start`` is always the raw Bullhorn page offset; when
        ``include_deleted=False`` (the default), soft-deleted notes occupy
        Bullhorn offsets but are excluded from ``data``, so
        ``pagination.count`` may be less than ``next_start - start``.
        Always use ``next_start`` directly — do not compute it as
        ``start + count``.

    Examples:
        - get_notes_for_entity("Candidate", 169020) - All notes on a candidate
        - get_notes_for_entity("JobOrder", 12345, limit=10, order_by="dateAdded")
        - get_notes_for_entity("ClientContact", 54321, include_deleted=True)
    """
    try:
        client = get_client()

        if entity not in _NOTE_TARGET_ENTITIES:
            return format_response({
                "error": "invalid_entity",
                "message": (
                    f"get_notes_for_entity does not support entity '{entity}'. "
                    f"Supported: {', '.join(sorted(_NOTE_TARGET_ENTITIES))}."
                ),
            })

        resolved_fields = fields if fields is not None else _NOTE_DEFAULT_FIELDS
        meta = client.get_association_with_meta(
            entity,
            entity_id,
            "notes",
            fields=resolved_fields,
            count=limit,
            start=start,
            order_by=order_by,
        )

        raw_notes = meta["data"]
        # raw_page_count drives offset arithmetic so next_start always advances
        # past the current Bullhorn page (including any soft-deleted entries).
        raw_page_count = len(raw_notes)
        notes = raw_notes if include_deleted else [n for n in raw_notes if not n.get("isDeleted")]

        cleaned_notes = []
        for note in notes:
            note = dict(note)
            raw_comments = note.get("comments") or ""
            if raw_comments:
                cleaned, tags = _strip_cc_telemetry(raw_comments)
                note["comments"] = cleaned
                if tags:
                    note["call_metadata"] = tags
            cleaned_notes.append(note)

        total = meta.get("total")
        has_more = (start + raw_page_count) < total if total is not None else raw_page_count == limit
        next_start = start + raw_page_count if has_more else None
        return format_response({
            "data": cleaned_notes,
            "pagination": {
                "total": total,
                "start": start,
                "count": len(cleaned_notes),
                "has_more": has_more,
                "next_start": next_start,
            },
        })

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def search_notes(
    query: str,
    entity_filter: dict | None = None,
    limit: int = 20,
    start: int = 0,
    fields: str | None = None,
) -> str:
    """Search notes by content using Lucene full-text search.

    Use this tool when you want to find notes mentioning a phrase across the
    entire database (e.g. "visa sponsorship", "counter offer"). For fetching
    all notes on a specific record, use get_notes_for_entity instead — it is
    more reliable and efficient for that use case.

    When entity_filter is provided the search is performed against the entity's
    notes directly (reliable on all tenants). Without entity_filter, Bullhorn's
    Lucene index is used — this requires the Note search index to be enabled on
    your tenant; contact Bullhorn support to enable "Advanced Note Searching" if
    results are unexpectedly empty.

    Args:
        query: Keyword to search for in note comments (case-insensitive substring
            when entity_filter is provided; Lucene syntax when searching globally)
        entity_filter: Optional dict to narrow results to notes attached to a
            specific record. Format: {"type": "Candidate", "id": 169020}.
            Supported types: Candidate, ClientContact, ClientCorporation,
            JobOrder, Placement, Lead, Opportunity.
            When provided, fetches all notes for that record and keyword-filters
            them locally — reliable regardless of Lucene index configuration.
        limit: Maximum number of results (1-500, default 20)
        start: Pagination offset (default 0)
        fields: Comma-separated Note fields to return. Default includes id, action,
            comments, dateAdded, commentingPerson, personReference, jobOrder,
            placements, leads, opportunities, isDeleted. Note: clientCorporation
            is not available on /search/Note — use get_notes_for_entity if you
            need that field.

    Returns:
        JSON object with ``data`` (array of note dicts) and ``pagination``
        (``total``, ``start``, ``count``, ``has_more``, ``next_start``).
        Click-to-call telemetry tags are stripped from comments and moved to a
        ``call_metadata`` sibling field. When ``has_more`` is true, call again
        with ``start=<next_start>`` for the next page.

    Examples:
        - search_notes("visa sponsorship") - Find all notes mentioning visa sponsorship
        - search_notes("counter offer", entity_filter={"type": "Candidate", "id": 169020})
        - search_notes("references", limit=50)
    """
    stripped_query = (query or "").strip()
    if not stripped_query or stripped_query == "*":
        return format_response({
            "error": "invalid_query",
            "message": (
                "search_notes requires a non-empty keyword query. "
                "Bullhorn's /search/Note rejects bare '*'. "
                "To fetch all notes on a specific record use "
                "get_notes_for_entity(entity, entity_id) instead."
            ),
        })

    try:
        client = get_client()

        filter_type = (entity_filter or {}).get("type")
        filter_id = (entity_filter or {}).get("id")

        if filter_type in _NOTE_TARGET_ENTITIES and filter_id is not None:
            # Entity-scoped path: fetch all notes for the record via association
            # endpoint, then keyword-filter in Python. Reliable on all tenants
            # regardless of Lucene index configuration.
            resolved_fields = fields if fields is not None else _NOTE_DEFAULT_FIELDS
            all_notes = client.get_association(
                filter_type,
                filter_id,
                "notes",
                fields=resolved_fields,
                count=500,
            )
            all_notes = [n for n in all_notes if not n.get("isDeleted")]
            keyword = stripped_query.lower()
            matched = [
                n for n in all_notes
                if keyword in (n.get("comments") or "").lower()
            ]
            notes = matched[start: start + limit]
            total_matched = len(matched)
            has_more = (start + limit) < total_matched
            next_start = start + limit if has_more else None
            pagination: dict = {
                "total": total_matched,
                "start": start,
                "count": len(notes),
                "has_more": has_more,
                "next_start": next_start,
            }
        else:
            resolved_fields = fields if fields is not None else _NOTE_SEARCH_DEFAULT_FIELDS
            note_meta = client.search_with_meta(
                "Note",
                query=stripped_query,
                fields=resolved_fields,
                count=limit,
                start=start,
            )
            notes = note_meta["data"]
            envelope = _paginate_envelope(note_meta, start, limit)
            pagination = envelope["pagination"]

        # Strip CC telemetry
        cleaned_notes = []
        for note in notes:
            note = dict(note)
            raw_comments = note.get("comments") or ""
            if raw_comments:
                cleaned, tags = _strip_cc_telemetry(raw_comments)
                note["comments"] = cleaned
                if tags:
                    note["call_metadata"] = tags
            cleaned_notes.append(note)

        return format_response({"data": cleaned_notes, "pagination": pagination})

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


async def _upload_cv_handler(request: Request) -> Response:
    """Handle POST /upload-cv: accept a CV file and either parse+create or attach to a Candidate."""
    upload_secret = os.environ.get("UPLOAD_SECRET")
    if not upload_secret:
        return JSONResponse({"error": "upload_secret_not_configured"}, status_code=400)

    provided = request.headers.get("X-Upload-Secret", "")
    if not provided or not hmac.compare_digest(provided, upload_secret):
        _logger.warning(
            "upload-cv auth failure from %s",
            request.client.host if request.client else "?",
        )
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    form = await request.form()
    upload = form.get("file")
    filename = form.get("filename")
    fmt = form.get("format") or "pdf"
    candidate_id_raw = form.get("candidate_id")
    force_raw = form.get("force") or "false"

    if upload is None or not filename:
        return JSONResponse(
            {"error": "missing_field", "message": "file and filename are required"},
            status_code=400,
        )

    if hasattr(upload, "read"):
        file_bytes: bytes = await upload.read()
    else:
        file_bytes = bytes(upload)

    force = str(force_raw).lower() == "true"

    candidate_id: int | None = None
    if candidate_id_raw:
        try:
            candidate_id = int(candidate_id_raw)
        except (TypeError, ValueError):
            return JSONResponse({"error": "invalid_candidate_id"}, status_code=400)

    _logger.info("upload-cv attempt filename=%s candidate_id=%s", filename, candidate_id)

    try:
        if candidate_id is not None:
            client = get_client()
            content_mime = client._guess_content_type(fmt)
            result = await asyncio.to_thread(
                client.attach_file,
                "Candidate", candidate_id, file_bytes, str(filename), content_mime, None, "CV",
            )
            _logger.info("upload-cv success attach candidate_id=%s", candidate_id)
            return JSONResponse(result, status_code=200)
        else:
            file_b64 = base64.b64encode(file_bytes).decode()
            result_json = await asyncio.to_thread(
                create_candidate_from_cv,
                file_b64=file_b64,
                filename=str(filename),
                format=str(fmt),
                force=force,
            )
            try:
                parsed = json.loads(result_json)
                if "error" in parsed:
                    _logger.error(
                        "upload-cv create error filename=%s error=%s",
                        filename, parsed.get("error"),
                    )
                    return JSONResponse(parsed, status_code=500)
            except (json.JSONDecodeError, TypeError):
                pass
            _logger.info("upload-cv success create filename=%s", filename)
            return Response(content=result_json, media_type="application/json", status_code=200)
    except BullhornAPIError as exc:
        _logger.exception("upload-cv bullhorn error filename=%s", filename)
        return JSONResponse({"error": "bullhorn_error", "message": str(exc)}, status_code=500)
    except Exception as exc:
        _logger.exception("upload-cv internal error filename=%s", filename)
        return JSONResponse({"error": "internal_error", "message": str(exc)}, status_code=500)


mcp.custom_route("/upload-cv", methods=["POST"])(_upload_cv_handler)


def main():
    """Run the MCP server.

    Transport is controlled by the MCP_TRANSPORT environment variable:
    - "stdio" (default): stdio transport for local clients (Claude Desktop, Claude Code, etc.)
    - "http": streamable-http transport for hosted deployments accessible to web clients.
      Requires ENTRA_TENANT_ID, ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET, and MCP_BASE_URL
      to be set — the server will refuse to start in HTTP mode without them.

    HTTP port is controlled by PORT (default 8000).
    HTTP host is controlled by HOST (default 0.0.0.0 in http mode, 127.0.0.1 in stdio mode).
    All env vars are read at module import time — transport, host, and port are consistent.
    """
    global _metadata
    try:
        _metadata = asyncio.run(enrich_tool_descriptions(mcp, get_client()))
    except Exception as exc:
        _logger.warning("Could not enrich tool descriptions at startup: %s", exc)

    if _transport_mode == "http":
        _logger.info(
            "Starting Bullhorn MCP server in HTTP mode on %s:%s", _host, _port
        )
        mcp.run(transport="streamable-http", host=_host, port=_port)
    elif _transport_mode == "stdio":
        _logger.info("Starting Bullhorn MCP server in stdio mode")
        mcp.run()
    else:
        raise ValueError(
            f"Unknown MCP_TRANSPORT '{_transport_mode}'. Valid values: stdio, http"
        )


if __name__ == "__main__":
    main()
