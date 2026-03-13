"""Bullhorn CRM MCP Server - Query and manage CRM data via AI assistants."""

import json
from mcp.server.fastmcp import FastMCP

from .config import BullhornConfig
from .auth import BullhornAuth, AuthenticationError
from .client import BullhornClient, BullhornAPIError
from .metadata import BullhornMetadata
from .fuzzy import score_company_match, categorize_score, score_contact_match
from .bulk import BulkImporter

# Initialize MCP server
mcp = FastMCP(
    "Bullhorn CRM",
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
        query: Lucene search query (e.g., "lastName:Smith" or "title:Manager")
        status: Filter by contact status (e.g., "Active")
        limit: Maximum number of results (1-500, default 20)
        fields: Comma-separated fields to return

    Returns:
        JSON array of client contacts

    Examples:
        - list_contacts() - Get recent contacts
        - list_contacts(query="lastName:Smith") - Find contacts named Smith
        - list_contacts(query="title:Manager AND clientCorporation.name:Acme")
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
        resolved = get_metadata().resolve_fields("ClientCorporation", fields)
        result = client.create("ClientCorporation", resolved)
        return format_response(result)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def create_contact(fields: dict) -> str:
    """Create a new ClientContact record in Bullhorn CRM, linked to a company.

    Args:
        fields: Dictionary of field names (or display labels) and values.
                Required keys: owner, clientCorporation (with an id).
                owner accepts either {"id": 12345} or a consultant name string
                such as "Maryrose Lyons" (resolved to a Bullhorn CorporateUser ID).
                clientCorporation must be {"id": <company_id>}.
                Example: {
                    "firstName": "Jane", "lastName": "Doe", "name": "Jane Doe",
                    "email": "jane@acme.com", "occupation": "VP Engineering",
                    "clientCorporation": {"id": 98765},
                    "owner": "Maryrose Lyons"
                }

    Returns:
        JSON object with changedEntityId, changeType, and full data of the created record.
        If owner resolves to multiple users, returns disambiguation JSON instead of creating.

    Examples:
        - create_contact({"firstName": "Jane", "lastName": "Doe", "name": "Jane Doe",
                          "clientCorporation": {"id": 98765}, "owner": {"id": 12345}})
        - create_contact({"firstName": "John", "lastName": "Smith",
                          "clientCorporation": {"id": 1}, "owner": "Maryrose Lyons"})
    """
    try:
        client = get_client()

        if "owner" not in fields:
            return format_response({"error": "owner_required", "message": "owner is required to create a ClientContact."})

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
        result = client.create("ClientContact", resolved)
        return format_response(result)

    except ValueError as e:
        return format_response({"error": "owner_not_found", "message": str(e)})
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
        - update_record("ClientContact", 54321, {"title": "CTO"})
        - update_record("ClientCorporation", 98765, {"status": "Active Account"})
        - update_record("ClientContact", 54321, {"Consultant": {"id": 99}})
    """
    try:
        client = get_client()
        resolved = get_metadata().resolve_fields(entity, fields)

        # Guard: reject company reassignment (check after resolution so label bypass is blocked)
        if entity == "ClientContact" and "clientCorporation" in resolved:
            return format_response({
                "error": "company_reassignment_not_supported",
                "message": "Company reassignment is not supported. Changing a ClientContact's associated ClientCorporation is not allowed.",
            })

        result = client.update(entity, entity_id, resolved)
        return format_response(result)

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
    client_corporation_id: int,
) -> str:
    """Check whether a contact already exists at a given company in Bullhorn.

    Args:
        first_name: Contact's first name
        last_name: Contact's last name
        client_corporation_id: Bullhorn ClientCorporation ID to scope the search

    Returns:
        JSON object: {"query": {...}, "matches": [...], "exact_match": bool}
        Partial matches (same name, different email) are flagged with "partial_match": true.

    Examples:
        - find_duplicate_contacts("John", "Smith", 123)
    """
    try:
        client = get_client()
        results = client.search(
            "ClientContact",
            query=f"clientCorporation.id:{client_corporation_id}",
            fields="id,firstName,lastName,email,phone,clientCorporation",
            count=100,
        )

        query_email_map: dict[int, str] = {}  # not used for scoring but for partial flag
        matches = []
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
                if query_full == cand_full and record.get("email"):
                    match_entry["partial_match"] = True
                matches.append(match_entry)

        matches.sort(key=lambda m: m["confidence"], reverse=True)
        exact_match = bool(matches and matches[0]["category"] == "exact")

        return format_response({
            "query": {"firstName": first_name, "lastName": last_name,
                      "clientCorporation": {"id": client_corporation_id}},
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
        importer = BulkImporter(get_client(), get_metadata())
        result = importer.process(companies, contacts)
        return format_response(result)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
