"""Bullhorn CRM MCP Server - Query and manage CRM data via AI assistants."""

import asyncio
import json
import logging
import os
import time
from typing import Any
from fastmcp import FastMCP
from fastmcp.server.auth.oidc_proxy import OIDCProxy

from .config import BullhornConfig
from .auth import BullhornAuth, AuthenticationError
from .client import BullhornClient, BullhornAPIError, DEFAULT_FIELDS
from .metadata import BullhornMetadata
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
    """Strip the 'title' key from ClientContact write payloads and return a warnings list."""
    warnings = []
    if entity == "ClientContact" and "title" in fields:
        fields = dict(fields)  # don't mutate input
        del fields["title"]
        msg = "Field 'title' was stripped from the ClientContact payload. Use 'occupation' for job title or 'namePrefix' for salutation."
        _logger.warning(msg)
        warnings.append(msg)
    return fields, warnings


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


@mcp.tool()
def list_jobs(
    query: str | None = None,
    status: str | None = None,
    limit: int = 20,
    fields: str | None = None,
) -> str:
    """List and filter job orders from Bullhorn CRM.

    Args:
        query: Lucene search query (e.g., "title:Engineer AND isOpen:1")
        status: Filter by job status
        limit: Maximum number of results (1-500, default 20)
        fields: Comma-separated fields to return

    Returns:
        JSON array of job orders

    Examples:
        - list_jobs() - Get recent jobs
        - list_jobs(query="isOpen:1") - Get open jobs
        - list_jobs(query="title:Software AND employmentType:Direct Hire", limit=10)
        - list_jobs(status="Accepting Candidates")
    """
    try:
        client = get_client()

        # Build search query
        search_query = query or ""
        if status:
            search_query = f"({search_query}) AND status:\"{status}\"" if search_query else f"status:\"{status}\""

        results = client.search(
            entity="JobOrder",
            query=search_query,
            fields=fields,
            count=limit,
            sort="-dateAdded",
        )

        return format_response(results)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def list_candidates(
    query: str | None = None,
    status: str | None = None,
    limit: int = 20,
    fields: str | None = None,
) -> str:
    """List and filter candidates from Bullhorn CRM.

    Args:
        query: Lucene search query (e.g., "lastName:Smith" or "skillSet:Python")
        status: Filter by candidate status
        limit: Maximum number of results (1-500, default 20)
        fields: Comma-separated fields to return

    Returns:
        JSON array of candidates

    Examples:
        - list_candidates() - Get recent candidates
        - list_candidates(query="skillSet:Python") - Find Python developers
        - list_candidates(query="lastName:Smith AND status:Active")
        - list_candidates(status="Active", limit=50)
    """
    try:
        client = get_client()

        # Build search query
        search_query = query or ""
        if status:
            search_query = f"({search_query}) AND status:\"{status}\"" if search_query else f"status:\"{status}\""

        results = client.search(
            entity="Candidate",
            query=search_query,
            fields=fields,
            count=limit,
            sort="-dateAdded",
        )

        return format_response(results)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def list_contacts(
    query: str | None = None,
    status: str | None = None,
    limit: int = 20,
    fields: str | None = None,
) -> str:
    """List and filter client contacts from Bullhorn CRM.

    Args:
        query: Lucene search query (e.g., "lastName:Smith" or "occupation:Manager")
        status: Filter by contact status (e.g., "Active")
        limit: Maximum number of results (1-500, default 20)
        fields: Comma-separated fields to return

    Returns:
        JSON array of client contacts

    Examples:
        - list_contacts() - Get recent contacts
        - list_contacts(query="lastName:Smith") - Find contacts named Smith
        - list_contacts(query="occupation:Manager AND clientCorporation.name:Acme")
        - list_contacts(status="Active", limit=50)
    """
    try:
        client = get_client()

        # Build search query
        search_query = query or ""
        if status:
            search_query = f"({search_query}) AND status:\"{status}\"" if search_query else f"status:\"{status}\""

        results = client.search(
            entity="ClientContact",
            query=search_query,
            fields=fields,
            count=limit,
            sort="-dateAdded",
        )

        return format_response(results)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def list_companies(
    query: str | None = None,
    status: str | None = None,
    limit: int = 20,
    fields: str | None = None,
) -> str:
    """List and filter client companies from Bullhorn CRM.

    Args:
        query: Lucene search query (e.g., "name:Acme*" or "phone:555*")
        status: Filter by company status (e.g., "Active")
        limit: Maximum number of results (1-500, default 20)
        fields: Comma-separated fields to return

    Returns:
        JSON array of client companies

    Examples:
        - list_companies() - Get recent companies
        - list_companies(query="name:Acme*") - Find companies starting with Acme
        - list_companies(status="Active", limit=50)
    """
    try:
        client = get_client()

        # Build search query
        search_query = query or ""
        if status:
            search_query = f"({search_query}) AND status:\"{status}\"" if search_query else f"status:\"{status}\""

        results = client.search(
            entity="ClientCorporation",
            query=search_query,
            fields=fields,
            count=limit,
            sort="-dateAdded",
        )

        return format_response(results)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def get_job(job_id: int, fields: str | None = None) -> str:
    """Get details for a specific job order by ID.

    Args:
        job_id: The JobOrder ID
        fields: Comma-separated fields to return (default: all common fields)

    Returns:
        JSON object with job details
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
        JSON object with candidate details
    """
    try:
        client = get_client()
        result = client.get(entity="Candidate", entity_id=candidate_id, fields=fields)
        return format_response(result)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def search_entities(
    entity: str,
    query: str,
    limit: int = 20,
    fields: str | None = None,
) -> str:
    """Search any Bullhorn entity type using Lucene query syntax.

    Soft-deleted records (isDeleted=true) are excluded by default.

    Args:
        entity: Entity type (JobOrder, Candidate, Placement, ClientCorporation, ClientContact, etc.)
        query: Lucene search query
        limit: Maximum number of results (1-500, default 20)
        fields: Comma-separated fields to return

    Returns:
        JSON array of matching entities

    Examples:
        - search_entities(entity="Placement", query="status:Approved")
        - search_entities(entity="ClientCorporation", query="name:Acme*")
        - search_entities(entity="JobSubmission", query="jobOrder.id:12345")
    """
    try:
        client = get_client()

        results = client.search(
            entity=entity,
            query=query,
            fields=fields,
            count=limit,
        )

        return format_response(results)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def query_entities(
    entity: str,
    where: str,
    limit: int = 20,
    fields: str | None = None,
    order_by: str | None = None,
) -> str:
    """Query Bullhorn entities using SQL-like WHERE syntax.

    Soft-deleted records (isDeleted=true) are excluded by default.

    Args:
        entity: Entity type (JobOrder, Candidate, etc.)
        where: WHERE clause (e.g., "salary > 100000 AND status='Active'")
        limit: Maximum number of results (1-500, default 20)
        fields: Comma-separated fields to return
        order_by: Sort order (e.g., "-dateAdded" for newest first)

    Returns:
        JSON array of matching entities

    Examples:
        - query_entities(entity="JobOrder", where="salary > 100000")
        - query_entities(entity="Candidate", where="status='Active'", order_by="-dateAdded")
    """
    try:
        client = get_client()

        results = client.query(
            entity=entity,
            where=where,
            fields=fields,
            count=limit,
            order_by=order_by,
        )

        return format_response(results)

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
    fields: str | None = None,
) -> str:
    """Search Bullhorn email messages (UserMessage) for a person's mailbox.

    Returns emails sent to or from a Candidate or ClientContact, optionally
    filtered to those that also involve a specific recruiter (CorporateUser),
    a date range, or a subject substring. Sorted most-recent-first by
    smtpSendDate.

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
        fields: Override the default field selection.

    Returns:
        JSON array of UserMessage records. Each record's nested sender and
        recipients carry an auto-populated ``_subtype`` of "Candidate",
        "ClientContact", or "CorporateUser". Attachments are listed in
        ``messageFiles`` as metadata only — content download is not yet
        supported (pending Bullhorn support resolution).

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

        results = client.search(
            entity="UserMessage",
            query=query,
            fields=resolved_fields,
            count=limit,
            sort="-smtpSendDate",
            extra_params={"entityId": person_id},
        )

        return format_response(results)

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
                    "firstName": "Jane", "lastName": "Doe", "name": "Jane Doe",
                    "email": "jane@acme.com", "occupation": "VP Engineering",
                    "clientCorporation": {"id": 98765},
                    "owner": "Maryrose Lyons"
                }
        force: If True, skip duplicate detection and create regardless. Default False.

    Returns:
        JSON object with changedEntityId, changeType, and full data of the created record.
        If owner resolves to multiple users, returns disambiguation JSON instead of creating.
        If a duplicate contact is found, returns duplicate_found JSON instead of creating
        (unless force=True).

    Examples:
        - create_contact({"firstName": "Jane", "lastName": "Doe", "name": "Jane Doe",
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
        result = client.update(entity, entity_id, resolved)
        response = format_response(result)
        if warnings:
            data = json.loads(response)
            data["warnings"] = warnings
            return json.dumps(data, indent=2)
        return response

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def add_note(entity: str, entity_id: int, action: str, comments: str) -> str:
    """Add a Note to a ClientContact or ClientCorporation record.

    Args:
        entity: "ClientContact" or "ClientCorporation"
        entity_id: Bullhorn ID of the record to attach the note to
        action: Note action type — must match a valid action in your Bullhorn instance (e.g. "General Note")
        comments: Note body text

    Returns:
        JSON object with changedEntityId, changeType, and full Note record data.

    Examples:
        - add_note("ClientContact", 54321, "General Note", "Discovered via weekly scan")
        - add_note("ClientCorporation", 98765, "General Note", "PE-backed, growing headcount")
    """
    try:
        client = get_client()

        if entity not in ("ClientContact", "ClientCorporation"):
            return format_response({
                "error": "invalid_entity",
                "message": f"add_note only supports ClientContact or ClientCorporation, got '{entity}'.",
            })

        result = client.add_note(entity, entity_id, action, comments)
        return format_response(result)

    except (AuthenticationError, BullhornAPIError) as e:
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
