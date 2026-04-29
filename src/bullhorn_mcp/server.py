"""Bullhorn CRM MCP Server - Query and manage CRM data via AI assistants."""

import json
import logging
import os
from typing import Any
from fastmcp import FastMCP
from fastmcp.server.auth.oidc_proxy import OIDCProxy

from .config import BullhornConfig
from .auth import BullhornAuth, AuthenticationError
from .client import BullhornClient, BullhornAPIError
from .metadata import BullhornMetadata, FIELD_ALIASES
from .fuzzy import score_company_match, categorize_score, score_contact_match
from .bulk import BulkImporter
from .identity import resolve_caller, IdentityResolutionError
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


def _company_name_search_query(company_name: str) -> str:
    """Build a company search query broad enough for local fuzzy matching."""
    stripped = company_name.strip()
    if not stripped:
        return "isDeleted:0"

    first_term = stripped.split()[0]
    # Acronyms like BNY need candidates such as "Bank of New York Mellon" to be
    # returned before local fuzzy scoring can identify the abbreviation match.
    if first_term.isupper() and first_term.isalpha() and 2 <= len(first_term) <= 6:
        return f"name:{first_term[0]}*"

    return f"name:{first_term}*"


JOB_REQUIRED_BUSINESS_FIELDS = (
    "title",
    "source",
    "grade",
    "fee",
    "salary",
    "website_sector_range",
    "website_salary_range",
    "website_location",
)


def _validate_job_reference(field_name: str, value: Any) -> dict | None:
    """Return an error dict if a JobOrder relationship reference is malformed."""
    if not isinstance(value, dict) or "id" not in value:
        return {
            "error": f"{field_name}_required",
            "message": f"{field_name} must be an object containing an id.",
        }
    return None


def _missing_job_required_fields(fields: dict) -> list[str]:
    """Return required JobOrder business fields that were not supplied."""
    missing = []
    for field in JOB_REQUIRED_BUSINESS_FIELDS:
        value = fields.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def _validate_job_fields_known(metadata: BullhornMetadata, fields: dict) -> dict | None:
    """Ensure structured JobOrder create keys resolved to known fields."""
    known_fields = {field["name"] for field in metadata.get_fields("JobOrder")}
    known_fields.update(FIELD_ALIASES.get("JobOrder", {}).values())
    unknown_fields = [field for field in fields if field not in known_fields]

    if unknown_fields:
        return {
            "error": "unknown_job_fields",
            "message": (
                "These JobOrder fields could not be resolved from Bullhorn metadata "
                "or confirmed aliases."
            ),
            "fields": unknown_fields,
        }
    return None


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
        search_query = query or "isDeleted:0"
        if status:
            search_query = f"({search_query}) AND status:\"{status}\""

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
        search_query = query or "isDeleted:0"
        if status:
            search_query = f"({search_query}) AND status:\"{status}\""

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
        search_query = query or "isDeleted:0"
        if status:
            search_query = f"({search_query}) AND status:\"{status}\""

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
        search_query = query or "isDeleted:0"
        if status:
            search_query = f"({search_query}) AND status:\"{status}\""

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
    clientCorporation: dict | None = None,
    clientContact: dict | None = None,
    title: str | None = None,
    source: Any | None = None,
    grade: Any | None = None,
    fee: Any | None = None,
    salary: Any | None = None,
    website_sector_range: Any | None = None,
    website_salary_range: Any | None = None,
    website_location: Any | None = None,
    publicDescription: str | None = None,
    description: str | None = None,
    owner: dict | str | None = None,
    status: str = "Accepting Candidates",
    isOpen: bool = True,
    customText12: Any = 0,
    extra_fields: dict | None = None,
) -> str:
    """Create a new JobOrder record in Bullhorn CRM.

    Args:
        clientCorporation: Bullhorn company reference, {"id": int}.
        clientContact: Bullhorn client contact reference, {"id": int}.
        title: Job title.
        source: Source field value.
        grade: Grade field value.
        fee: Fee field value.
        salary: Salary field value.
        website_sector_range: Website sector range field value.
        website_salary_range: Website salary range field value.
        website_location: Website location field value.
        publicDescription: Optional public-facing job description.
        description: Optional internal job description.
        owner: Optional Bullhorn owner reference or resolvable consultant name.
        status: Job status, default "Accepting Candidates".
        isOpen: Open flag, default True.
        customText12: Local "Publish on website" field, default 0.
        extra_fields: Optional additional JobOrder fields validated against metadata.

    Returns:
        JSON object with changedEntityId, changeType, and full created JobOrder data.

    Examples:
        - create_job(clientCorporation={"id": 12345}, clientContact={"id": 67890},
                     title="Senior Software Engineer", source="Email",
                     grade="Senior", fee=25000, salary=90000,
                     website_sector_range="Technology",
                     website_salary_range="80000-100000",
                     website_location="London")
    """
    try:
        client = get_client()
        metadata = get_metadata()

        for field_name, value in (
            ("clientCorporation", clientCorporation),
            ("clientContact", clientContact),
        ):
            error = _validate_job_reference(field_name, value)
            if error is not None:
                return format_response(error)

        if extra_fields is not None and not isinstance(extra_fields, dict):
            return format_response({
                "error": "invalid_extra_fields",
                "message": "extra_fields must be a dictionary when provided.",
            })

        payload = {
            "clientCorporation": clientCorporation,
            "clientContact": clientContact,
            "title": title,
            "source": source,
            "grade": grade,
            "fee": fee,
            "salary": salary,
            "website_sector_range": website_sector_range,
            "website_salary_range": website_salary_range,
            "website_location": website_location,
            "status": status if status is not None else "Accepting Candidates",
            "isOpen": isOpen if isOpen is not None else True,
            "customText12": customText12 if customText12 is not None else 0,
        }

        missing_fields = _missing_job_required_fields(payload)
        if missing_fields:
            return format_response({
                "error": "required_fields_missing",
                "message": "Missing required JobOrder business fields.",
                "fields": missing_fields,
            })

        if publicDescription is not None:
            payload["publicDescription"] = publicDescription
        if description is not None:
            payload["description"] = description

        if owner is None:
            try:
                caller = resolve_caller(client)
                resolved_owner = {"id": caller["id"]}
            except IdentityResolutionError as e:
                return format_response({
                    "error": "identity_resolution_failed",
                    "message": str(e),
                    "hint": "Provide an explicit 'owner' field or check that your email matches a Bullhorn CorporateUser.",
                })
        else:
            owner_result = client.resolve_owner(owner)
            if isinstance(owner_result, list):
                return format_response({
                    "error": "owner_ambiguous",
                    "matches": owner_result,
                    "message": "Multiple users found. Specify owner by ID.",
                })
            resolved_owner = owner_result

        if extra_fields:
            payload.update(extra_fields)

        payload["owner"] = resolved_owner

        resolved = metadata.resolve_fields("JobOrder", payload)
        unknown_error = _validate_job_fields_known(metadata, resolved)
        if unknown_error is not None:
            return format_response(unknown_error)

        result = client.create("JobOrder", resolved)
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
        # Use first word of name as broad search term to cast a wide net
        broad_term = name.split()[0] if name.strip() else name
        results = client.search(
            "ClientCorporation",
            query=f"name:{broad_term}*",
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
                query=_company_name_search_query(company_name),
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
