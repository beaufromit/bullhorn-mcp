"""Bullhorn CRM MCP Server - Query and manage CRM data via AI assistants."""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from importlib import resources as _pkg_resources
from typing import Any
from urllib.parse import urlparse
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from fastmcp import FastMCP
from fastmcp.apps.config import UI_EXTENSION_ID, AppConfig, ResourceCSP
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from fastmcp.server.dependencies import get_context

from .config import BullhornConfig
from .auth import BullhornAuth, AuthenticationError
from .client import BullhornClient, BullhornAPIError, DEFAULT_FIELDS
from .metadata import BullhornMetadata
from .candidate_config import get_candidate_defaults, get_candidate_required, get_mcp_source
from .joborder_config import get_joborder_defaults, get_joborder_required
from .shortlist_config import get_shortlist_status
from .fuzzy import score_company_match, categorize_score, score_contact_match
from .bulk import BulkImporter
from .identity import resolve_caller, resolve_caller_sub, IdentityResolutionError
from .descriptions import enrich_tool_descriptions
from . import match_log
from .duplicate_retrieval import match_candidates
from .duplicates import CandidateProfile, profile_from_fields, profile_from_parse
from .perplexity import search_people, PerplexityError
from .uploads import (
    ALLOWED_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    UploadError,
    upload_store,
)
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


def _match_caller(client: BullhornClient):
    """Who the match log records: the CorporateUser id, else the Entra sub, else None. Never raises."""
    try:
        return resolve_caller(client)["id"]
    except Exception:  # noqa: BLE001 - the log must never block a tool
        pass
    try:
        return resolve_caller_sub()
    except Exception:  # noqa: BLE001
        return None


def _run_match_check(client: BullhornClient, profile: CandidateProfile, errors: list[str] | None = None) -> dict | None:
    """The one Candidate match check (CR44), or None when it could not run (non-fatal).

    ``errors`` collects the failure text so a create path can warn about it.
    """
    try:
        return match_candidates(client, profile, caller=_match_caller(client))
    except Exception as exc:  # noqa: BLE001 - AuthenticationError, BullhornAPIError or a retrieval bug
        _logger.warning("Candidate match check could not run: %s", exc)
        if errors is not None:
            errors.append(str(exc))
        return None


def _log_match_outcome(client: BullhornClient, match_check_id: str | None, outcome: str, candidate_id: int | None) -> None:
    """Log an outcome under a match_check_id (D12). No id, nothing logged. Never raises."""
    if not match_check_id:
        return
    try:
        match_log.log_outcome(match_check_id, outcome, candidate_id, caller=_match_caller(client))
    except Exception as exc:  # noqa: BLE001
        _logger.warning("match log: outcome not logged: %s", exc)


def _is_guaranteed(match: dict) -> bool:
    return any(str(f).startswith("guaranteed_match:") for f in match.get("flags") or [])


def _match_summary(match: dict) -> str:
    reasons = "; ".join(b.get("reason", "") for b in match.get("breakdown") or [] if b.get("reason"))
    text = f"{match.get('name')} (Candidate {match.get('candidate_id')}) {match.get('percentage')}% {match.get('band')}"
    return f"{text}: {reasons}" if reasons else text


def _duplicate_policy(result: dict | None, hint: str) -> dict | None:
    """D9: the stop response for a create, or None when the create may go ahead.

    A high band or a guaranteed identifier gives ``duplicate_found``; otherwise any
    uncertain match gives ``possible_duplicates``. ``hint`` may hold ``{candidate_id}``
    and ``{match_check_id}`` placeholders. A deleted match alone never stops.
    """
    if not result:
        return None
    matches = result.get("matches") or []
    strong = [m for m in matches if m.get("band") == "high" or _is_guaranteed(m)]
    uncertain = [m for m in matches if m.get("band") == "uncertain"]
    if strong:
        kind, listed = "duplicate_found", strong
        intro = "This Candidate looks like one already on file"
    elif uncertain:
        kind, listed = "possible_duplicates", matches
        intro = "This Candidate may already be on file"
    else:
        return None
    check_id = result.get("match_check_id")
    top = listed[0]
    return {
        kind: True,
        "match_check_id": check_id,
        "matches": matches,
        "deleted_matches": result.get("deleted_matches") or [],
        "flags": result.get("flags") or [],
        "message": f"{intro}. Nothing was created. " + " | ".join(_match_summary(m) for m in listed),
        "hint": hint.replace("{candidate_id}", str(top.get("candidate_id"))).replace("{match_check_id}", str(check_id)),
    }


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
        "display labels. For CV files, call request_cv_upload first; never pass file "
        "contents in a tool argument."
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


def _iso_to_epoch_ms(date_str: str) -> int:
    """Convert an ISO-8601 date string (YYYY-MM-DD) to UTC midnight epoch milliseconds.

    Args:
        date_str: Date in YYYY-MM-DD format

    Returns:
        Epoch milliseconds (int) representing UTC midnight on that date

    Raises:
        ValueError: If the string cannot be parsed as YYYY-MM-DD
    """
    from datetime import datetime, timezone
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


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


def _note_action_clause(note_action: str) -> tuple[str | None, dict | None]:
    """Build the nested Lucene clause filtering a parent entity by note action.

    Note fields are reachable as nested fields on the parent entity's index
    (``notes.action``), which returns PARENT records rather than notes. The value
    must be double-quoted or a multi-word action silently matches nothing, so the
    quoting is done here rather than left to the caller.

    Validation is best-effort: when the Note.action picklist is unavailable the
    clause is still built, because blocking a working search on a failed metadata
    call would turn a degraded server into an unusable one.

    Args:
        note_action: A Note.action picklist value, e.g. "BD Call".

    Returns:
        ``(clause, None)`` on success, or ``(None, error_dict)`` if the value is
        rejected.
    """
    value = note_action.strip()
    if not value:
        return None, {
            "error": "invalid_note_action",
            "message": "note_action must be a non-empty Note action value.",
        }
    if '"' in value or "'" in value:
        return None, {
            "error": "invalid_note_action",
            "message": (
                "note_action must not contain quote characters. Pass the bare "
                'action value, e.g. note_action="BD Call".'
            ),
        }

    valid_actions = _load_valid_note_actions(get_metadata())
    if valid_actions is not None:
        # Lucene matches note actions case-insensitively, so accept any casing
        # and normalise to the picklist's own spelling.
        by_lower = {a.lower(): a for a in valid_actions}
        if value.lower() not in by_lower:
            return None, {
                "error": "invalid_note_action",
                "message": (
                    f"'{value}' is not a valid Note action for this Bullhorn instance."
                ),
                "valid_actions": sorted(valid_actions),
            }
        value = by_lower[value.lower()]

    return f'notes.action:"{value}"', None


def _and_clause(search_query: str, clause: str) -> str:
    """AND a clause onto a Lucene query, parenthesising the existing query."""
    return f"({search_query}) AND {clause}" if search_query else clause


@mcp.tool()
def list_jobs(
    query: str | None = None,
    status: str | None = None,
    note_action: str | None = None,
    limit: int = 20,
    start: int = 0,
    fields: str | None = None,
) -> str:
    """List and filter job orders from Bullhorn CRM.

    Filtering by note fields: note fields are searchable as nested fields on this
    entity's own index, which is the reliable way to answer "which jobs have a note
    like X". Results are PARENT records, deduplicated, never notes — a job with
    three "BD Call" notes is returned once, so the total is a job count, not a note
    count; for the notes themselves use get_notes_for_entity. Prefer the
    note_action parameter, which validates the value and quotes it. In a raw query,
    multi-word values MUST be double-quoted: notes.action:"BD Call" matches,
    notes.action:BD Call matches nothing. Verified paths: notes.action,
    notes.comments, notes.dateAdded (range style [20260721000000 TO 20260729000000]),
    notes.commentingPerson.id. notes.isDeleted is unsupported and matches nothing;
    the top-level isDeleted filter on the job itself still applies.

    Args:
        query: Lucene search query (e.g., "title:Engineer AND isOpen:1")
        status: Filter by job status
        note_action: Return only jobs carrying at least one note with this action
            (e.g. "BD Call"). Validated against the live Note.action picklist.
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
        - list_jobs(note_action="BD Call", status="Accepting Candidates")
        - list_jobs(limit=500, start=500) - Get records 501-1000
    """
    try:
        client = get_client()

        # Build search query
        search_query = query or ""
        if status:
            search_query = _and_clause(search_query, f'status:"{status}"')
        if note_action:
            clause, err = _note_action_clause(note_action)
            if err:
                return format_response(err)
            search_query = _and_clause(search_query, clause)

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
    note_action: str | None = None,
    limit: int = 20,
    start: int = 0,
    fields: str | None = None,
) -> str:
    """List and filter candidates from Bullhorn CRM.

    Filtering by note fields: note fields are searchable as nested fields on this
    entity's own index, which is the reliable way to answer "which candidates have
    a note like X". Results are PARENT records, deduplicated, never notes — a
    candidate with three "Agent added" notes is returned once, so the total is a
    candidate count, not a note count; for the notes themselves use
    get_notes_for_entity. Prefer the note_action parameter, which validates the
    value and quotes it. In a raw query, multi-word values MUST be double-quoted:
    notes.action:"Agent added" matches, notes.action:Agent added matches nothing.
    Verified paths: notes.action, notes.comments, notes.dateAdded (range style
    [20260721000000 TO 20260729000000]), notes.commentingPerson.id.
    notes.isDeleted is unsupported and matches nothing; the top-level isDeleted
    filter on the candidate itself still applies.

    Args:
        query: Lucene search query (e.g., "lastName:Smith" or "skillSet:Python")
        status: Filter by candidate status
        note_action: Return only candidates carrying at least one note with this
            action (e.g. "BD Call"). Validated against the live Note.action picklist.
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
        - list_candidates(note_action="Agent added", status="Active")
        - list_candidates(limit=500, start=500) - Get records 501-1000
    """
    try:
        client = get_client()

        # Build search query
        search_query = query or ""
        if status:
            search_query = _and_clause(search_query, f'status:"{status}"')
        if note_action:
            clause, err = _note_action_clause(note_action)
            if err:
                return format_response(err)
            search_query = _and_clause(search_query, clause)

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
    note_action: str | None = None,
    limit: int = 20,
    start: int = 0,
    fields: str | None = None,
) -> str:
    """List and filter client contacts from Bullhorn CRM.

    Filtering by note fields: note fields are searchable as nested fields on this
    entity's own index, which is the reliable way to answer "which contacts have a
    note like X". Results are PARENT records, deduplicated, never notes — a contact
    with three "BD Call" notes is returned once, so the total is a contact count,
    not a note count; for the notes themselves use get_notes_for_entity. Prefer the
    note_action parameter, which validates the value and quotes it. In a raw query,
    multi-word values MUST be double-quoted: notes.action:"BD Call" matches,
    notes.action:BD Call matches nothing. Verified paths: notes.action,
    notes.comments, notes.dateAdded (range style [20260721000000 TO 20260729000000]),
    notes.commentingPerson.id. notes.isDeleted is unsupported and matches nothing;
    the top-level isDeleted filter on the contact itself still applies.

    Args:
        query: Lucene search query (e.g., "lastName:Smith" or "occupation:Manager")
        status: Filter by contact status (e.g., "Active")
        note_action: Return only contacts carrying at least one note with this
            action (e.g. "BD Call"). Validated against the live Note.action picklist.
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
        - list_contacts(note_action="BD Call", status="Active") - Contacts with a BD Call note
        - list_contacts(limit=500, start=500) - Get records 501-1000
    """
    try:
        client = get_client()

        # Build search query
        search_query = query or ""
        if status:
            search_query = _and_clause(search_query, f'status:"{status}"')
        if note_action:
            clause, err = _note_action_clause(note_action)
            if err:
                return format_response(err)
            search_query = _and_clause(search_query, clause)

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


# Default field sets for list_placements.
# Mirrors DEFAULT_FIELDS["Placement"] in client.py — kept in sync deliberately.
_PLACEMENT_DEFAULT_FIELDS = DEFAULT_FIELDS["Placement"]
_PCR_DEFAULT_FIELDS = (
    "id,requestType,requestStatus,status,dateBegin,dateEnd,requestCustomDate1,dateAdded,"
    "placement(id,status,dateBegin,dateEnd,"
    "candidate(id,name),jobOrder(id,title),clientCorporation(id,name))"
)


@mcp.tool()
def list_placements(
    record_type: str = "new",
    since: str | None = None,
    until: str | None = None,
    status: str | None = None,
    query: str | None = None,
    limit: int = 20,
    start: int = 0,
    fields: str | None = None,
    order_by: str | None = None,
) -> str:
    """List placements and/or contract extensions from Bullhorn CRM.

    This tool handles two distinct start-event types that must never be
    combined, because they live in different entities and use different date
    fields:

    | record_type   | Entity                 | "Start" date field   |
    |---------------|------------------------|----------------------|
    | "new"         | Placement              | dateBegin            |
    | "extensions"  | PlacementChangeRequest | requestCustomDate1   |

    Use ``since``/``until`` to filter by that start date.  Placement 10982
    is a good example: its ``dateBegin`` is Jun 2023 (the original start),
    but it has 34 Contract Extension change requests each with their own
    ``requestCustomDate1`` stepping forward monthly.  Querying
    ``record_type="new", since="2024-01-01"`` correctly excludes it;
    ``record_type="extensions", since="2024-01-01"`` returns its recent
    extensions.

    Args:
        record_type: Which start events to return.
            "new"        -- new Placement starts (Placement.dateBegin).
            "extensions" -- Contract Extension events
                           (PlacementChangeRequest.requestCustomDate1).
            "both"       -- both, returned as separate top-level keys
                           "new" and "extensions"; never merged.
        since: ISO-8601 date lower bound (YYYY-MM-DD, inclusive) applied to
            the start date field for the chosen record_type.
        until: ISO-8601 date upper bound (YYYY-MM-DD, inclusive) applied to
            the start date field.
        status: Filter by Placement.status (e.g. "Approved"). Applies to
            "new" only; ignored for "extensions".
        query: Optional extra raw SQL WHERE fragment appended to the
            generated clause (e.g. "employmentType='Daily Rate'").
        limit: Maximum records per type (1-500, default 20).
        start: Pagination offset.  When record_type="both", applies
            independently to each type.
        fields: Comma-separated fields to return.  Overrides the default
            field set for the chosen type(s).
        order_by: Sort field.  Defaults to "-dateBegin" for "new" and
            "-requestCustomDate1" for "extensions".

    Returns:
        For "new" or "extensions": JSON object with ``data`` (rows tagged
        with ``record_type``) and ``pagination``
        (total, start, count, has_more, next_start).
        For "both": JSON object with top-level keys "new" and "extensions",
        each containing a full data+pagination envelope.

    Examples:
        - list_placements()
          -- recent new placements
        - list_placements(record_type="new", since="2025-01-01")
          -- placements that genuinely started in 2025 (extensions excluded)
        - list_placements(record_type="extensions", since="2025-01-01")
          -- Contract Extensions with a start date in 2025
        - list_placements(record_type="both", since="2024-06-01", until="2025-06-17")
          -- both new placements and extensions that started in the period
        - list_placements(record_type="new", status="Approved", limit=50)
        - list_placements(limit=500, start=500)
          -- page 2 of new placements
    """
    _VALID_RECORD_TYPES = {"new", "extensions", "both"}
    if record_type not in _VALID_RECORD_TYPES:
        return format_response({
            "error": "invalid_record_type",
            "message": (
                f"record_type must be one of: {', '.join(sorted(_VALID_RECORD_TYPES))}. "
                f"Got: {record_type!r}"
            ),
        })

    # Parse since/until to epoch ms.
    since_ms: int | None = None
    until_ms: int | None = None
    if since is not None:
        try:
            since_ms = _iso_to_epoch_ms(since)
        except ValueError:
            return format_response({
                "error": "invalid_date",
                "message": f"since must be YYYY-MM-DD. Got: {since!r}",
            })
    if until is not None:
        try:
            # Include the full until day: add 86400000 ms (one day) to midnight.
            until_ms = _iso_to_epoch_ms(until) + 86_400_000
        except ValueError:
            return format_response({
                "error": "invalid_date",
                "message": f"until must be YYYY-MM-DD. Got: {until!r}",
            })
    if status is not None and "'" in status:
        return format_response({
            "error": "invalid_status",
            "message": f"status must not contain single quotes. Got: {status!r}",
        })

    try:
        client = get_client()

        def _build_placement_where() -> str:
            clauses = []
            if since_ms is not None:
                clauses.append(f"dateBegin >= {since_ms}")
            if until_ms is not None:
                clauses.append(f"dateBegin < {until_ms}")
            if status is not None:
                clauses.append(f"status='{status}'")
            if query:
                clauses.append(f"({query})")
            return " AND ".join(clauses) if clauses else "id IS NOT NULL"

        def _build_pcr_where() -> str:
            clauses = ["requestType='Contract Extension'"]
            if since_ms is not None:
                clauses.append(f"requestCustomDate1 >= {since_ms}")
            if until_ms is not None:
                clauses.append(f"requestCustomDate1 < {until_ms}")
            if query:
                clauses.append(f"({query})")
            return " AND ".join(clauses)

        def _fetch_new() -> dict:
            eff_order = order_by or "-dateBegin"
            eff_fields = fields or _PLACEMENT_DEFAULT_FIELDS
            meta = client.query_with_meta(
                entity="Placement",
                where=_build_placement_where(),
                fields=eff_fields,
                count=limit,
                start=start,
                order_by=eff_order,
            )
            for row in meta["data"]:
                row["record_type"] = "new"
            return _paginate_envelope(meta, start, limit)

        def _fetch_extensions() -> dict:
            eff_order = order_by or "-requestCustomDate1"
            eff_fields = fields or _PCR_DEFAULT_FIELDS
            meta = client.query_with_meta(
                entity="PlacementChangeRequest",
                where=_build_pcr_where(),
                fields=eff_fields,
                count=limit,
                start=start,
                order_by=eff_order,
            )
            for row in meta["data"]:
                row["record_type"] = "extension"
            return _paginate_envelope(meta, start, limit)

        if record_type == "new":
            return format_response(_fetch_new())
        if record_type == "extensions":
            return format_response(_fetch_extensions())
        # both
        return format_response({
            "new": _fetch_new(),
            "extensions": _fetch_extensions(),
        })

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
def get_contact(contact_id: int, fields: str | None = None) -> str:
    """Get details for a specific client contact by ID.

    Args:
        contact_id: The ClientContact ID
        fields: Comma-separated fields to return
                (default: id,firstName,lastName,name,email,phone,occupation,
                 status,clientCorporation,owner,dateAdded)

    Returns:
        JSON object with contact details.

    Note on notes: use get_notes_for_entity("ClientContact", contact_id) for contact notes.
    """
    try:
        client = get_client()
        result = client.get(entity="ClientContact", entity_id=contact_id, fields=fields)
        return format_response(result)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def list_tearsheets(
    query: str | None = None,
    limit: int = 20,
    start: int = 0,
    fields: str | None = None,
) -> str:
    """List tearsheets (hotlists) from Bullhorn.

    Args:
        query: Lucene query to filter tearsheets (e.g. 'name:CFO*' or 'owner.id:123')
        limit: Maximum number of results (1-500, default 20)
        start: Pagination offset (default 0)
        fields: Comma-separated fields to return
                (default: id,name,description,owner,dateAdded)

    Returns:
        JSON object with ``data`` (array of tearsheets) and ``pagination``.

    Examples:
        - list_tearsheets() - All tearsheets
        - list_tearsheets(query="name:CFO*") - Tearsheets whose name starts with CFO
        - list_tearsheets(query="owner.id:99") - Tearsheets owned by CorporateUser 99
    """
    try:
        client = get_client()
        meta = client.search_with_meta(
            entity="Tearsheet",
            query=query or "",
            fields=fields,
            count=limit,
            start=start,
            sort="-dateAdded",
        )
        return format_response(_paginate_envelope(meta, start, limit))
    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def get_tearsheet(
    tearsheet_id: int,
    candidate_limit: int = 200,
    candidate_fields: str | None = None,
) -> str:
    """Get a tearsheet and its candidate members by ID.

    Args:
        tearsheet_id: The Tearsheet ID
        candidate_limit: Maximum number of candidate members to return (default 200)
        candidate_fields: Comma-separated fields to return for each candidate
                          (default: id,firstName,lastName,email,occupation,status)

    Returns:
        JSON object with tearsheet metadata and a ``candidates`` key containing
        ``data`` (array of candidates) and ``pagination``.
    """
    try:
        client = get_client()
        default_candidate_fields = "id,firstName,lastName,email,occupation,status"

        tearsheet = client.get("Tearsheet", tearsheet_id)
        members_meta = client.get_association_with_meta(
            entity="Tearsheet",
            entity_id=tearsheet_id,
            association="candidates",
            fields=candidate_fields or default_candidate_fields,
            count=candidate_limit,
            start=0,
        )
        tearsheet["candidates"] = _paginate_envelope(members_meta, 0, candidate_limit)
        return format_response(tearsheet)
    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def create_tearsheet(
    name: str,
    description: str | None = None,
    owner: int | None = None,
) -> str:
    """Create a new tearsheet (hotlist) in Bullhorn.

    Args:
        name: Name of the tearsheet
        description: Optional description
        owner: Bullhorn CorporateUser ID to assign as owner.
               If omitted, the authenticated user is resolved automatically.

    Returns:
        JSON object with changedEntityId, changeType, and the created tearsheet record.
    """
    try:
        client = get_client()
        payload: dict[str, Any] = {"name": name}
        if description:
            payload["description"] = description

        if owner is not None:
            payload["owner"] = {"id": owner}
        else:
            try:
                caller = resolve_caller(client)
                payload["owner"] = {"id": caller["id"]}
            except IdentityResolutionError:
                return format_response({
                    "error": "identity_resolution_failed",
                    "message": "Could not resolve authenticated user to a Bullhorn CorporateUser. Provide owner explicitly.",
                })

        result = client.create("Tearsheet", payload)
        return format_response(result)
    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def add_to_tearsheet(tearsheet_id: int, candidate_ids: list[int]) -> str:
    """Add one or more candidates to a tearsheet.

    Args:
        tearsheet_id: The Tearsheet ID
        candidate_ids: List of Candidate IDs to add

    Returns:
        JSON object confirming the operation and listing the added candidate IDs.

    Examples:
        - add_to_tearsheet(tearsheet_id=55, candidate_ids=[101, 102, 103])
    """
    if not candidate_ids:
        return format_response({
            "error": "invalid_argument",
            "message": "candidate_ids must be a non-empty list.",
        })
    try:
        client = get_client()
        client.add_association("Tearsheet", tearsheet_id, "candidates", candidate_ids)
        return format_response({
            "tearsheet_id": tearsheet_id,
            "added": candidate_ids,
            "count": len(candidate_ids),
        })
    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def remove_from_tearsheet(tearsheet_id: int, candidate_ids: list[int]) -> str:
    """Remove one or more candidates from a tearsheet.

    Args:
        tearsheet_id: The Tearsheet ID
        candidate_ids: List of Candidate IDs to remove

    Returns:
        JSON object confirming the operation and listing the removed candidate IDs.

    Examples:
        - remove_from_tearsheet(tearsheet_id=55, candidate_ids=[101, 102])
    """
    if not candidate_ids:
        return format_response({
            "error": "invalid_argument",
            "message": "candidate_ids must be a non-empty list.",
        })
    try:
        client = get_client()
        client.remove_association("Tearsheet", tearsheet_id, "candidates", candidate_ids)
        return format_response({
            "tearsheet_id": tearsheet_id,
            "removed": candidate_ids,
            "count": len(candidate_ids),
        })
    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def get_job_submissions(
    job_id: int,
    status: str | None = None,
    limit: int = 20,
    start: int = 0,
    fields: str | None = None,
) -> str:
    """Get all candidate submissions (pipeline) for a specific job.

    Args:
        job_id: The JobOrder ID to fetch submissions for
        status: Filter by submission status (e.g., "Shortlisted", "Interviewing",
                "Offered", "Placed"). Omit to return all statuses.
        limit: Maximum number of results (1-500, default 20)
        start: Pagination offset (default 0). Use with limit to page through results.
        fields: Comma-separated fields to return
                (default: id,candidate(id,firstName,lastName,email),
                 status,dateAdded,sendingUser(id,name))

    Returns:
        JSON object with ``data`` (array of job submissions) and ``pagination``
        (``total``, ``start``, ``count``, ``has_more``, ``next_start``).
        When ``has_more`` is true, call again with ``start=<next_start>``
        to fetch the next page.

    Examples:
        - get_job_submissions(job_id=12345) — All submissions for job 12345
        - get_job_submissions(job_id=12345, status="Shortlisted") — Shortlisted only
        - get_job_submissions(job_id=12345, limit=50, start=0) — First 50 results
    """
    if status is not None and "'" in status:
        return format_response({
            "error": "invalid_status",
            "message": f"status must not contain single quotes. Got: {status!r}",
        })

    try:
        client = get_client()

        where = f"jobOrder.id={job_id}"
        if status:
            where += f" AND status='{status}'"

        default_fields = "id,candidate(id,firstName,lastName,email),status,dateAdded,sendingUser(id,name)"
        meta = client.query_with_meta(
            entity="JobSubmission",
            where=where,
            fields=fields or default_fields,
            count=limit,
            start=start,
        )

        return format_response(_paginate_envelope(meta, start, limit))

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

    Filtering by note fields (Candidate, ClientContact, JobOrder): note fields are
    searchable as nested fields on the PARENT entity's index and return parent
    records, deduplicated, never notes. This is the reliable way to answer "which
    records have a note like X", and it combines freely with parent filters:
    search_entities(entity="ClientContact", query='notes.action:"BD Call" AND status:Active').
    Multi-word values MUST be double-quoted: notes.action:"BD Call" matches,
    notes.action:BD Call matches nothing at all. Verified paths: notes.action,
    notes.comments, notes.dateAdded (range style [20260721000000 TO 20260729000000]),
    notes.commentingPerson.id. notes.isDeleted is unsupported and matches nothing.
    The list_contacts / list_candidates / list_jobs tools expose this as a
    validated note_action parameter, which is easier to get right.

    On entity="Note": /search/Note returns no documents for any query on this
    account, so it cannot be used to find notes, and filtering by subject-entity ID
    (e.g. personReference.id:N) is unreliable regardless. When that is detected the
    response carries a ``warnings`` key and the empty ``data`` says nothing about
    whether matching notes exist. Use get_notes_for_entity for a single record's
    notes, or the nested pattern above to find records.

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

    For the full field list of any entity, call get_entity_fields(entity="<Entity>").
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

        envelope = _paginate_envelope(meta, start, limit)

        # entity="Note" reaches the same /search/Note route as search_notes'
        # Lucene branch, so an empty result here is ambiguous in exactly the same
        # way: either "no matches" or "this route returns no documents at all".
        # Probe once so the route is never rendered as a factual answer about the
        # caller's data.
        if (
            (entity or "").strip().lower() == "note"
            and not envelope["data"]
            and not envelope["pagination"]["total"]
            and client.note_search_returns_results() is False
        ):
            envelope["warnings"] = [_NOTE_INDEX_EMPTY_WARNING]

        return format_response(envelope)

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

    For the full field list of any entity, call get_entity_fields(entity="<Entity>").
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
            extra_params={"entityId": person_id},
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
    """Update fields on an existing ClientCorporation, ClientContact, or Candidate record.

    Args:
        entity: "ClientContact", "ClientCorporation", or "Candidate"
        entity_id: Bullhorn ID of the record to update
        fields: Dictionary of field names (or display labels) and new values.
                Field labels are resolved to API names automatically.
                Company reassignment (changing clientCorporation on a ClientContact) is not supported.
                For ClientContact and Candidate: 'title' is stripped with a warning — use
                'occupation' for job title. Candidate has no 'title' field at all.

    Returns:
        JSON object with changedEntityId, changeType, and full updated record.

    Examples:
        - update_record("ClientContact", 54321, {"occupation": "CTO"})
        - update_record("ClientCorporation", 98765, {"status": "Active Account"})
        - update_record("ClientContact", 54321, {"Consultant": {"id": 99}})
        - update_record("Candidate", 11234, {"occupation": "Head of Engineering", "dateAvailable": 1735689600000})

    For the full field list of any entity, call get_entity_fields(entity="<Entity>").
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
# reject clientCorporation (CR25), so both tools share one field list. Alias,
# not a separate literal, so search_notes and get_notes_for_entity can never
# drift apart and always return the same note shape.
_NOTE_SEARCH_DEFAULT_FIELDS = _NOTE_DEFAULT_FIELDS

# Attached to search_notes results when the match-all probe confirms the Lucene
# /search/Note route returns nothing on this account, so that an empty result is
# never mistaken for a factual answer about the caller's data. States observed
# behaviour and names the working routes; it does not diagnose Bullhorn.
_NOTE_INDEX_EMPTY_WARNING = (
    "The Lucene /search/Note route returns no documents for any query on this "
    "account, so this empty result does not mean no matching notes exist. Routes "
    "that do return note data: (1) list_contacts / list_candidates / list_jobs "
    'with note_action="<action>", to find the parent records carrying a given '
    'note action; (2) a nested query such as notes.action:"BD Call" via '
    "search_entities on the parent entity; (3) search_notes with entity_filter, "
    "or get_notes_for_entity(entity, entity_id), for a single record's notes."
)


def _note_association(entity: str) -> str:
    """Return the note association name to read for an entity.

    On ClientCorporation, "notes" is the scalar "Company Comments" text field,
    not an association, so the association endpoint 500s with "Unknown entity:
    String" (CR40). Company notes are the notes of the company's contacts,
    read via "clientContactNotes" instead.
    """
    return "clientContactNotes" if entity == "ClientCorporation" else "notes"


def _strip_cc_telemetry(comments: str) -> tuple[str, list[str]]:
    """Remove click-to-call tags from a note comments string.

    Returns (cleaned_comments, list_of_removed_tags).
    """
    full_matches = [m.group(0) for m in _CC_TAG_RE.finditer(comments)]
    cleaned = _CC_TAG_RE.sub("", comments).strip()
    return cleaned, full_matches


@mcp.tool()
def add_note(entity: str, entity_id: int, action: str, comments: str, person_id: int | None = None) -> str:
    """Add a Note to a Bullhorn record.

    Candidate, ClientContact and Lead notes attach to the record itself.
    JobOrder, Placement and Opportunity notes attach to the logged-in
    consultant, not the record's client contact or candidate, so job notes do
    not pile up on a contact's timeline. Pass person_id to attach one of those
    notes to a specific person instead. ClientCorporation is not a note
    target: Bullhorn has no company-level note, so calling this with
    entity="ClientCorporation" writes nothing and instead returns the
    company's non-archived contacts (up to 50, contacts_truncated is true if
    there are more). Add the note to one of those contacts, or use
    update_record to set the company's "Company Comments" field.

    Args:
        entity: One of "Candidate", "ClientContact", "JobOrder", "Placement",
            "Lead", or "Opportunity"
        entity_id: Bullhorn ID of the record to attach the note to
        action: Note action type, must match a valid action in your Bullhorn instance (e.g. "General Note")
        comments: Note body text
        person_id: Optional Bullhorn person ID. For JobOrder, Placement and
            Opportunity, attaches the note to this person instead of the
            logged-in consultant. Ignored for Candidate, ClientContact and Lead.

    Returns:
        JSON object with changedEntityId, changeType, and full Note record data.

    Examples:
        - add_note("Candidate", 11111, "General Note", "Strong fit for senior roles")
        - add_note("ClientContact", 54321, "General Note", "Discovered via weekly scan")
        - add_note("JobOrder", 22222, "General Note", "Role put on hold pending budget approval")
        - add_note("Placement", 33333, "General Note", "Candidate started, all good")
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

        if entity == "ClientCorporation":
            contacts = client.query(
                "ClientContact",
                f"clientCorporation.id={entity_id} AND status<>'Archive'",
                fields="id,firstName,lastName,occupation,email",
                count=51,
                order_by="lastName",
            )
            contacts_truncated = len(contacts) > 50
            contacts = contacts[:50]
            return format_response({
                "error": "company_notes_live_on_contacts",
                "message": (
                    "Bullhorn has no company-level note. Add the note to one of "
                    'the company\'s contacts with add_note(entity="ClientContact", '
                    'entity_id=<contact id>, ...) instead, or use update_record to '
                    'set the company\'s "Company Comments" field.'
                ),
                "contacts": contacts,
                "contacts_truncated": contacts_truncated,
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

        person_reference_id = None
        if entity in {"JobOrder", "Placement", "Opportunity"}:
            if person_id is not None:
                person_reference_id = person_id
            elif commenting_person_id is not None:
                person_reference_id = commenting_person_id
            else:
                record = client.get(entity, entity_id, fields="id,owner(id)")
                owner_id = (record.get("owner") or {}).get("id")
                if owner_id is None:
                    return format_response({
                        "error": "no_linked_person",
                        "message": (
                            f"Could not resolve a person for this {entity} note: "
                            "the caller's identity did not resolve and the record "
                            "has no owner. Pass person_id explicitly."
                        ),
                    })
                person_reference_id = owner_id

        result = client.add_note(
            entity, entity_id, action, comments,
            commenting_person_id=commenting_person_id,
            person_reference_id=person_reference_id,
        )
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
def create_candidate(
    fields: dict,
    force: bool = False,
    work_history: list | None = None,
    education: list | None = None,
    skills: list | None = None,
    primary_skills: list | None = None,
    match_check_id: str | None = None,
) -> str:
    """Create a new Candidate record in Bullhorn CRM.

    For a candidate found on LinkedIn or through people_search_perplexity, also pass
    their work_history, education and skills; they are written after the Candidate and
    the response lists what was written. For a CV file use create_candidate_from_cv.
    Runs a duplicate check first. A likely or possible duplicate stops the create
    (duplicate_found / possible_duplicates): show the consultant who, the percentage
    and the reasons, and only create anyway (force=True) if they say so.

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
        work_history: Optional CandidateWorkHistory entries, e.g.
                [{"companyName": "Acme", "title": "Engineer", "startDate": <epoch ms>, "endDate": null}]
        education: Optional CandidateEducation entries, e.g.
                [{"school": "UCD", "major": "Accounting", "graduationDate": <epoch ms>}]
        skills: Optional free-text skill names, added to skillSet.
        primary_skills: Optional Bullhorn Skill ids to link as primarySkills.
        match_check_id: The match_check_id of the find_duplicate_candidates call this create follows;
                with force=True it records the outcome under that check.

    Returns:
        JSON object with changedEntityId, changeType, and full data of the created record,
        plus "written" (child records with their new ids, skills) when any list was passed.
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
                return _required_fields_missing_response(missing, "fields", from_cv=False)

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

        check = None
        if not force:
            check_errors: list[str] = []
            check = _run_match_check(client, profile_from_fields(resolved, work_history, education), check_errors)
            if check is None:
                warnings.append(f"Duplicate check could not run: {check_errors[0] if check_errors else 'unknown error'}")
            stop = _duplicate_policy(check, (
                "Use update_record on Candidate {candidate_id} to change the existing record. To create a new "
                "Candidate anyway, call create_candidate again with force=True and match_check_id='{match_check_id}'."
            ))
            if stop is not None:
                return format_response(stop)

        has_children = any(x is not None for x in (work_history, education, skills, primary_skills))
        skill_names, primary_ids = _normalize_skills(skills, primary_skills)
        skill_set_written: list[str] = []
        if skill_names:
            # Names go in the create payload (CR43 P4), merged with any skillSet given.
            resolved["skillSet"], skill_set_written = _merge_skill_set(resolved.get("skillSet"), skill_names)

        result = client.create("Candidate", resolved)
        if force:
            _log_match_outcome(client, match_check_id, "created_with_force", result.get("changedEntityId"))
        elif check is not None:
            _log_match_outcome(client, check["match_check_id"], "created_new", result.get("changedEntityId"))
        if not has_children:
            if warnings:
                data = json.loads(format_response(result))
                data["warnings"] = warnings
                return json.dumps(data, indent=2)
            return format_response(result)

        # The Candidate exists from here on: nothing below may hide its id (CR43 goal 5).
        data = json.loads(format_response(result))
        candidate_id = result["changedEntityId"]
        written: dict = {"work_history": [], "education": [], "skill_set": skill_set_written, "primary_skills": []}
        try:
            children, child_warnings = _write_candidate_children(
                client, metadata, candidate_id, work_history or [], education or [], [], primary_ids, "", [],
            )
            written.update({k: v for k, v in children.items() if k != "skill_set"})
            warnings.extend(child_warnings)
        except Exception as exc:
            _logger.exception("create_candidate: failure after Candidate %s was created", candidate_id)
            data["error"] = f"Candidate {candidate_id} was created, but writing its child records failed: {exc}"
        data["written"] = written
        if warnings:
            data["warnings"] = warnings
        return json.dumps(data, indent=2, default=str)

    except ValueError as e:
        return format_response({"error": "owner_not_found", "message": str(e)})
    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def find_duplicate_candidates(
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
    phones: list | None = None,
    linkedin_url: str | None = None,
    current_company: str | None = None,
    work_history: list | None = None,
    education: list | None = None,
    upload_id: str | None = None,
) -> str:
    """Check whether a Candidate is already in Bullhorn, weighing every signal given.

    Give as much as you know: name, email, phones, LinkedIn URL, current employer,
    work history, education. Or give upload_id to use the stored parse of a CV and
    pass only corrections. Show the consultant EVERY match: who (name and id), the
    percentage, the band and the reasons from its breakdown. Matches are ranked;
    deleted_matches are removed records, shown for information only. Pass the
    returned match_check_id to create_candidate, create_candidate_from_cv or
    attach_cv so the outcome is recorded. Nothing is written to Bullhorn.

    Args:
        first_name: First name
        last_name: Last name
        email: Email address
        phones: Phone numbers (list of strings)
        linkedin_url: LinkedIn profile URL
        current_company: Current employer name
        work_history: Entries with companyName, title, startDate, endDate (epoch ms)
        education: Entries with school, degree, graduationDate (epoch ms)
        upload_id: A received CV upload whose stored parse is the base profile; the other arguments override it
    """
    try:
        client = get_client()
        profile = CandidateProfile()
        if upload_id is not None:
            upload, error = _load_received_upload(upload_id)
            if error:
                return error
            profile = profile_from_parse(_parse_upload(client, upload))
        if first_name is not None:
            profile.first_name = first_name.strip() or None
        if last_name is not None:
            profile.last_name = last_name.strip() or None
        if email is not None:
            profile.emails = [email.strip()] if email.strip() else []
        if phones is not None:
            profile.phones = [str(p).strip() for p in phones if str(p).strip()]
        if linkedin_url is not None:
            profile.linkedin_url = linkedin_url.strip() or None
        if current_company is not None:
            profile.current_company = current_company.strip() or None
        if work_history is not None or education is not None:
            given = profile_from_fields({}, work_history, education)
            if work_history is not None:
                profile.work_history = given.work_history
            if education is not None:
                profile.education = given.education

        if not (
            profile.first_name or profile.last_name or profile.emails or profile.phones
            or profile.linkedin_url or profile.current_company or profile.work_history
        ):
            return format_response({
                "error": "query_required",
                "message": (
                    "Provide at least one of: a name, email, phones, linkedin_url, current_company, "
                    "work_history, or an upload_id."
                ),
            })

        return format_response(match_candidates(client, profile, caller=_match_caller(client)))

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


# --- CR41: CV upload tickets --------------------------------------------------
# CV bytes never travel in a tool argument. request_cv_upload mints a single-use
# URL, the file is POSTed there out of band (curl in Cowork, or the in-chat upload
# box), and the CV tools take the resulting upload_id. Uploads are bound to the
# Entra `sub`, so they need HTTP mode (stdio has no token and no upload listener).

_UPLOAD_BOX_URI = "ui://bullhorn/cv-upload-box.html"


def _uploads_unavailable() -> str | None:
    """Return the stdio-mode error JSON, or None when uploads are available."""
    if _transport_mode != "http":
        return format_response({
            "error": "uploads_require_http_mode",
            "message": (
                "CV file uploads need the hosted (HTTP) server. This server runs in "
                "stdio mode, which has no upload endpoint. Use parse_cv_text or "
                "create_candidate_from_cv(content=...) with pasted CV text instead."
            ),
        })
    return None


def _upload_url(token: str) -> str:
    return f"{os.environ.get('MCP_BASE_URL', '').rstrip('/')}/upload/{token}"


def _client_supports_ui() -> bool:
    """True when the connected client advertised MCP Apps support at initialize."""
    try:
        return bool(get_context().client_supports_extension(UI_EXTENSION_ID))
    except Exception:
        return False


def _upload_error(e: UploadError) -> str:
    hints = {
        "upload_not_found": "Call request_cv_upload to start a new upload.",
        "upload_expired": "The upload expired. Call request_cv_upload again and resend the file.",
        "upload_already_used": "This upload has already been used. Call request_cv_upload for a new one.",
        "unsupported_file_type": "Allowed CV types: " + ", ".join(sorted(ALLOWED_EXTENSIONS)) + ".",
        "too_many_uploads": "Use or finish the uploads already started; unused ones expire after 15 minutes.",
        "upload_in_use": "Wait for the other call on this upload to finish, then check get_cv_upload(upload_id).",
    }
    body = {"error": e.code, "message": str(e)}
    if e.code in hints:
        body["hint"] = hints[e.code]
    return format_response(body)


def _load_received_upload(
    upload_id: str, claim: bool = False, attached_ok_for: int | None = None
) -> tuple[dict | None, str | None]:
    """Fetch a received upload for the caller. Returns ``(record, None)`` or ``(None, error_json)``.

    The record keeps its bytes; the caller must call ``upload_store.mark_attached``
    after a successful Bullhorn attach so the bytes are dropped (NFR-9). The record
    also carries ``owner_sub`` so ``_parse_upload`` can store the parse on it.

    With ``claim=True`` (calls that write) the upload is reserved before its status is
    read, so an overlapping call on the same upload gets ``upload_in_use`` and a
    call that waited for another's attach sees ``attached``. On success the caller
    must ``upload_store.release(upload_id)`` in a ``finally``; on error it is
    already released.

    ``attached_ok_for=<candidate_id>`` (attach_cv, CR43 P2): an upload already
    attached to that same Candidate is returned (without bytes) while its stored
    parse lives, so an attach_cv confirm call can follow the call that attached the
    file. Attached to any other Candidate it is still ``upload_already_attached``.
    """
    unavailable = _uploads_unavailable()
    if unavailable:
        return None, unavailable
    try:
        sub = resolve_caller_sub()
    except IdentityResolutionError as e:
        return None, format_response({"error": "identity_resolution_failed", "message": str(e)})
    try:
        if claim:
            # A failed claim holds nothing, so there is nothing to release; releasing
            # here would free a claim another call holds on the same upload_id.
            upload_store.claim(upload_id, sub)
    except UploadError as e:
        return None, _upload_error(e)
    try:
        rec = upload_store.get(upload_id, sub)
    except UploadError as e:
        if claim:
            upload_store.release(upload_id)
        return None, _upload_error(e)
    rec["owner_sub"] = sub
    status = rec["status"]
    if status == "received":
        return rec, None
    if (
        status == "attached"
        and attached_ok_for is not None
        and rec.get("attached_candidate_id") == attached_ok_for
        and rec.get("parsed") is not None
    ):
        return rec, None
    if claim:
        upload_store.release(upload_id)
    if status == "pending":
        return None, format_response({
            "error": "upload_pending",
            "message": f"No file has been received for upload '{upload_id}' yet.",
            "hint": (
                "Send the file to the upload_url from request_cv_upload (or the upload box), "
                "then check get_cv_upload(upload_id) shows status 'received'."
            ),
        })
    if status == "attached":
        return None, format_response({
            "error": "upload_already_attached",
            "message": f"Upload '{upload_id}' is already attached in Bullhorn and its file was deleted here.",
            "hint": "Call request_cv_upload and resend the file to use it again.",
        })
    return None, format_response({
        "error": "upload_expired",
        "message": f"Upload '{upload_id}' has expired and its file was deleted.",
        "hint": "Call request_cv_upload again and resend the file.",
    })


# --- CR43: reviewed CV flow helpers --------------------------------------------
# The parser drafts, Claude checks the draft against the CV and corrects it, and
# the server writes Claude's version (FR-15 Amendment 2). These helpers are shared
# by create_candidate_from_cv, attach_cv and create_candidate so all three write
# child records and skills the same way.

# Keys shown back to Claude for each written child record.
_WORK_HISTORY_KEYS = ("companyName", "title", "startDate", "endDate")
_EDUCATION_KEYS = ("school", "degree", "major", "certification", "graduationDate", "startDate", "endDate")


def _parse_upload(client: BullhornClient, upload: dict) -> dict:
    """Return the upload's stored parse, or parse its bytes once and store the result.

    One parser call per upload whatever runs after it (parse_cv, create, attach), so
    the write uses exactly the parse Claude reviewed (CR43 goal 1, A1).
    """
    if upload.get("parsed") is not None:
        return upload["parsed"]
    parsed = client.parse_resume_file(upload["data"], upload["filename"], upload["format"])
    try:
        upload_store.set_parsed(upload["upload_id"], upload["owner_sub"], parsed)
    except UploadError:
        # The record went (expired or purged) mid-call; this call can still use the parse.
        _logger.warning("Could not store the parse on upload %s", upload["upload_id"])
    upload["parsed"] = parsed
    return parsed


def _split_parsed_skills(parsed: dict) -> tuple[list[str], list[int]]:
    """Split a parse into ``(free-text skill names, primary skill ids)``.

    Live shape (CR43): ``skillList`` is a list of strings and ``primarySkills`` is
    ``[{name, id}]``. A dict in ``skillList`` gives its ``name`` and a bare id in
    ``primarySkills`` is accepted, so an unexpected shape cannot crash the write
    (CR19 assumed ``skillList`` was ``[{id, name}]`` and crashed on strings).
    Names are de-duplicated case-insensitively, ids exactly; order is kept.
    """
    names: list[str] = []
    seen: set[str] = set()
    for skill in parsed.get("skillList") or []:
        name = skill.get("name") if isinstance(skill, dict) else skill
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        if name.lower() not in seen:
            seen.add(name.lower())
            names.append(name)
    ids: list[int] = []
    for entry in parsed.get("primarySkills") or []:
        sid = entry.get("id") if isinstance(entry, dict) else entry
        if isinstance(sid, str) and sid.strip().isdigit():
            sid = int(sid.strip())
        if isinstance(sid, int) and not isinstance(sid, bool) and sid not in ids:
            ids.append(sid)
    return names, ids


def _normalize_skills(skills: list | None, primary_skills: list | None) -> tuple[list[str], list[int]]:
    """Normalize Claude's ``skills`` / ``primary_skills`` arguments like a parse."""
    return _split_parsed_skills({"skillList": skills or [], "primarySkills": primary_skills or []})


def _skill_set_names(skill_set: object) -> set[str]:
    """Lower-cased names already in a comma-separated ``skillSet``."""
    if not isinstance(skill_set, str):
        return set()
    return {part.strip().lower() for part in skill_set.split(",") if part.strip()}


def _merge_skill_set(existing: object, names: list[str]) -> tuple[str, list[str]]:
    """Append the names not already in ``existing``. Returns ``(new skillSet, names added)``."""
    present = _skill_set_names(existing)
    added = [n for n in names if n.lower() not in present]
    base = existing.strip() if isinstance(existing, str) else ""
    return ", ".join(filter(None, [base] + added)), added


def _cv_response_view(parsed: dict) -> dict:
    """The parse as Claude sees it: everything it reviews, without the HTML description.

    The description can be ~48k characters (CR42) and is always written from the
    stored parse, so only its length is shown.
    """
    candidate = dict(parsed.get("candidate") or {})
    description = candidate.pop("description", None)
    return {
        "confidenceScore": parsed.get("confidenceScore"),
        "candidate": candidate,
        "description_length": len(description) if isinstance(description, str) else 0,
        "candidateWorkHistory": parsed.get("candidateWorkHistory") or [],
        "candidateEducation": parsed.get("candidateEducation") or [],
        "skillList": parsed.get("skillList") or [],
        "primarySkills": parsed.get("primarySkills") or [],
    }


def _write_candidate_children(
    client: BullhornClient,
    metadata: BullhornMetadata,
    candidate_id: int,
    work_history: list,
    education: list,
    skill_names: list[str],
    primary_skill_ids: list[int],
    existing_skillset: object,
    existing_primary_ids: list[int],
) -> tuple[dict, list[str]]:
    """Write work history, education and skills to an existing Candidate.

    Every item is best-effort: a failure becomes a warning and the rest carry on.
    Skill names not already in ``existing_skillset`` are appended in one skillSet
    update. Ids not in ``existing_primary_ids`` are linked with one association PUT:
    a ``primarySkills`` value in an entity update returns 200 with an
    ATTEMPT_TO_SET_TO_MANY warning and writes nothing (CR43 A2, live 2026-10-02),
    so an association response with ``messages`` or without ``changeType:
    ASSOCIATE`` is reported as a failure, never as linked.

    Returns ``(written, warnings)``; ``written`` lists each child with its new id,
    the names appended and the ids linked, plus what was skipped as already present.
    """
    warnings: list[str] = []
    written: dict = {"work_history": [], "education": [], "skill_set": [], "primary_skills": []}

    for entity, entries, key, keys in (
        ("CandidateWorkHistory", work_history, "work_history", _WORK_HISTORY_KEYS),
        ("CandidateEducation", education, "education", _EDUCATION_KEYS),
    ):
        label = "Work history" if key == "work_history" else "Education"
        for entry in entries:
            try:
                if not isinstance(entry, dict):
                    raise ValueError(f"expected an object, got {type(entry).__name__}")
                payload = {k: v for k, v in entry.items() if k != "id"}
                payload["candidate"] = {"id": candidate_id}
                payload = _truncate_against_meta(metadata, entity, payload)
                r = client.create(entity, payload)
                written[key].append(
                    {"id": r["changedEntityId"], **{k: payload[k] for k in keys if payload.get(k) is not None}}
                )
            except Exception as exc:
                warnings.append(f"{label} entry failed: {exc}")

    present = _skill_set_names(existing_skillset)
    new_names = [n for n in skill_names if n.lower() not in present]
    skipped_names = [n for n in skill_names if n.lower() in present]
    if new_names:
        try:
            combined, _ = _merge_skill_set(existing_skillset, new_names)
            client.update("Candidate", candidate_id, {"skillSet": combined})
            written["skill_set"] = new_names
        except Exception as exc:
            warnings.append(f"skillSet update failed: {exc}")

    to_link = [i for i in primary_skill_ids if i not in existing_primary_ids]
    skipped_ids = [i for i in primary_skill_ids if i in existing_primary_ids]
    if to_link:
        try:
            r = client.add_association("Candidate", candidate_id, "primarySkills", to_link)
            if (r or {}).get("messages") or (r or {}).get("changeType") != "ASSOCIATE":
                warnings.append(f"primarySkills link not confirmed by Bullhorn, nothing linked: {r}")
            else:
                written["primary_skills"] = to_link
        except Exception as exc:
            warnings.append(f"primarySkills link failed: {exc}")

    if skipped_names or skipped_ids:
        written["already_present"] = {"skill_set": skipped_names, "primary_skills": skipped_ids}
    return written, warnings


def _required_fields_missing_response(missing: list, retry_arg: str, from_cv: bool) -> str:
    """``required_fields_missing`` with a hint on how to retry (CR43 goal 8)."""
    hint = f"Call again with the missing fields added to {retry_arg}."
    if "companyName" in missing:
        source = "from the CV (the most recent work history entry)" if from_cv else "you were given"
        hint += f" For companyName use the candidate's current employer {source}."
    return format_response({
        "error": "required_fields_missing",
        "message": "Missing required Candidate fields configured for this instance.",
        "fields": missing,
        "hint": hint,
    })


def _text_key(*parts: object) -> tuple:
    """De-dup key: text trimmed and lower-cased, None and blank equal, other values as is."""
    return tuple(
        (p.strip().lower() if isinstance(p, str) else ("" if p is None else p)) for p in parts
    )


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


# Fields that say which qualification an education entry is.
_EDUCATION_IDENTITY = ("school", "degree", "major", "certification")
# Two entries are only compared if they share one of these. A shared ``degree``
# alone does not count: on this tenant it is mostly a generic level or grade
# ("bachelors", "unspecified", "first class honours"), so it says little on its own.
_EDUCATION_MATCH_ON = frozenset({"school", "major", "certification", "credential"})
# Fields that name the qualification itself, as opposed to where it was taken.
_EDUCATION_QUALIFICATION = ("degree", "major", "certification", "credential")


def _education_view(entry: dict) -> dict:
    """Normalized filled fields of an education entry, for matching.

    A certification-only entry and a degree-only entry are both reduced to one
    ``credential`` field: before the parser used ``certification``, this tenant
    stored certifications as a bare ``degree`` ("ACCA", "PMP"; 550 of 1,000
    records sampled from 2024), so the same certification arrives in either field.
    """
    view = {
        k: (v.strip().lower() if isinstance(v, str) else v)
        for k in _EDUCATION_KEYS
        if not _is_blank(v := entry.get(k))
    }
    identity = [k for k in _EDUCATION_IDENTITY if k in view]
    if identity in (["degree"], ["certification"]):
        view["credential"] = view.pop(identity[0])
    return view


def _education_matches(a: dict, b: dict) -> bool:
    """True when two education entries describe the same qualification.

    Every field filled on both sides must agree, and at least one of school, major,
    certification or the credential must be filled on both (a shared generic
    degree alone matched "First Class Honours, Econometrics" to "University of
    Delhi, First Class Honours" in the live replay). A field filled on one side
    only does not block the match, because a record and a new CV often differ in
    detail (a major or graduationDate on one and not the other). But when both
    sides name a qualification (degree, major, certification), they must share
    one value: a BComm and a later diploma or MSc at the same school are two
    entries (CR43 review M1), while "ACA" as a degree on one side and as a
    certification on the other is one. Different certifications never match.
    Live sample (2026-10-02, 2,000 recent records): ``startDate``/``endDate`` are
    never filled and half the entries are certification-only, which is why exact
    matching on the old school/degree/startDate/endDate key wrongly merged them.
    """
    va, vb = _education_view(a), _education_view(b)
    shared = va.keys() & vb.keys()
    if not shared & _EDUCATION_MATCH_ON:
        return False
    if not all(va[k] == vb[k] for k in shared):
        return False
    qa = {va[k] for k in _EDUCATION_QUALIFICATION if k in va}
    qb = {vb[k] for k in _EDUCATION_QUALIFICATION if k in vb}
    return not (qa and qb) or bool(qa & qb)


def _new_cv_children(existing_wh: list, existing_edu: list, work_history: list, education: list) -> tuple[list, list]:
    """Work history and education entries not on the record and not repeated earlier in the same list.

    Work history matches on its key fields, education on ``_education_matches``.
    Non-dict entries pass through so the write reports them as failed.
    """
    wh_keys = {_text_key(*(r.get(k) for k in _WORK_HISTORY_KEYS)) for r in existing_wh}
    new_wh = []
    for e in work_history:
        if isinstance(e, dict):
            key = _text_key(*(e.get(k) for k in _WORK_HISTORY_KEYS))
            if key in wh_keys:
                continue
            wh_keys.add(key)
        new_wh.append(e)
    seen_edu = [r for r in existing_edu if isinstance(r, dict)]
    new_edu = []
    for e in education:
        if isinstance(e, dict):
            if any(_education_matches(e, r) for r in seen_edu):
                continue
            seen_edu.append(e)
        new_edu.append(e)
    return new_wh, new_edu


def _plan_cv_update(
    existing: dict,
    proposed_fields: dict,
    fields_to_update: list | None,
    existing_wh: list,
    existing_edu: list,
    work_history: list,
    education: list,
    skill_names: list[str],
    primary_ids: list[int],
    existing_skillset: object,
    existing_primary_ids: list[int],
) -> dict:
    """Split a CV update into additions (written now) and overwrites (need confirm=True).

    Pure. A field is an addition when the record holds None or blank, an overwrite
    when it holds a different value, and skipped when equal after trimming or when
    the proposed value is blank (a blank parse never clears a field).
    ``fields_to_update`` limits which fields are considered. A description
    overwrite shows only both lengths (CR43 A6). Work history and education are
    de-duplicated against the record (work history by its key fields, education by
    ``_education_matches``), so a confirm call after the additions call adds nothing
    twice; skills already listed or linked are skipped.
    """
    if fields_to_update is not None:
        proposed_fields = {k: v for k, v in proposed_fields.items() if k in fields_to_update}

    add_fields: dict = {}
    overwrites: list[dict] = []
    for field, proposed in proposed_fields.items():
        if _is_blank(proposed):
            continue
        current = existing.get(field)
        if _is_blank(current):
            add_fields[field] = proposed
            continue
        same = (
            current.strip() == proposed.strip()
            if isinstance(current, str) and isinstance(proposed, str)
            else current == proposed
        )
        if same:
            continue
        if field == "description":
            overwrites.append({
                "field": field,
                "current_length": len(str(current)),
                "proposed_length": len(str(proposed)),
            })
        else:
            overwrites.append({"field": field, "current": current, "proposed": proposed})

    new_wh, new_edu = _new_cv_children(existing_wh, existing_edu, work_history, education)

    present = _skill_set_names(existing_skillset)
    return {
        "additions": {
            "fields": add_fields,
            "work_history": new_wh,
            "education": new_edu,
            "skill_names": [n for n in skill_names if n.lower() not in present],
            "primary_skill_ids": [i for i in primary_ids if i not in existing_primary_ids],
        },
        "overwrites": overwrites,
        "already_present": {
            "work_history": len(work_history) - len(new_wh),
            "education": len(education) - len(new_edu),
            "skill_set": [n for n in skill_names if n.lower() in present],
            "primary_skills": [i for i in primary_ids if i in existing_primary_ids],
        },
    }


@mcp.tool()
def request_cv_upload(filename: str, candidate_id: int | None = None) -> str:
    """Start a CV file upload. Call this before parse_cv, create_candidate_from_cv or attach_cv.

    Returns an upload_id, a single-use upload_url (15 minutes) and next_steps to follow.
    Never pass file contents in a tool argument.

    Args:
        filename: The CV's original name exactly as the user attached it (e.g. "Jane_Doe_CV.pdf").
        candidate_id: Optional existing Candidate the CV is for.
    """
    unavailable = _uploads_unavailable()
    if unavailable:
        return unavailable
    try:
        sub = resolve_caller_sub()
    except IdentityResolutionError as e:
        return format_response({"error": "identity_resolution_failed", "message": str(e)})
    try:
        upload_id, token, expires_at = upload_store.create(sub, filename, candidate_id)
    except UploadError as e:
        return _upload_error(e)

    upload_url = _upload_url(token)
    use_step = (
        f"Then call get_cv_upload(upload_id='{upload_id}') and check status is 'received'. "
        f"Then call parse_cv(upload_id='{upload_id}') and review the parse against the CV itself: "
        "fix names, the current employer (companyName), job titles with the employer merged in, "
        "dates (an ongoing role has no endDate) and skills that are not in the CV. "
        f"Then call create_candidate_from_cv(upload_id='{upload_id}', <your corrections>) for a new "
        f"candidate, or attach_cv(candidate_id=..., upload_id='{upload_id}', <your corrections>) for an "
        "existing one, and tell the user exactly what was written."
    )
    if _client_supports_ui():
        fallback = (
            f"If curl fails or you cannot run shell commands, call "
            f"show_cv_upload_box(upload_id='{upload_id}') so the user can drop the file into the chat."
        )
    else:
        fallback = (
            "If curl fails or you cannot run shell commands, tell the user the file could not "
            "be sent and stop. Do not paste, retype or base64-encode the file."
        )
    return format_response({
        "upload_id": upload_id,
        "upload_url": upload_url,
        "expires_at": expires_at.isoformat(timespec="seconds"),
        "max_bytes": MAX_UPLOAD_BYTES,
        "next_steps": [
            (
                "If the CV is a file in your environment and you can run shell commands, send it "
                "(use its full path on disk, which may carry an extra prefix; the original name is kept): "
                f"curl -sS -X POST -F file=@\"<full path to the attached file>\" {upload_url}"
            ),
            use_step,
            fallback,
        ],
    })


@mcp.tool()
def get_cv_upload(upload_id: str) -> str:
    """Check a CV upload's status: pending, received, attached or expired.

    Args:
        upload_id: The id returned by request_cv_upload.
    """
    unavailable = _uploads_unavailable()
    if unavailable:
        return unavailable
    try:
        sub = resolve_caller_sub()
    except IdentityResolutionError as e:
        return format_response({"error": "identity_resolution_failed", "message": str(e)})
    try:
        rec = upload_store.get(upload_id, sub)
    except UploadError as e:
        return _upload_error(e)
    result = {
        "upload_id": rec["upload_id"],
        "status": rec["status"],
        "filename": rec["filename"],
        "size": rec["size"],
        "candidate_id": rec["candidate_id"],
    }
    if rec["status"] == "attached":
        result["file_id"] = rec["file_id"]
    return format_response(result)


def _upload_box_app_config(base_url: str | None) -> AppConfig:
    """MCP Apps metadata for the upload box resource.

    ``connectDomains`` lets the sandboxed iframe fetch our upload route. Claude
    serves each server's apps from ``{sha256(server url)[:32]}.claudemcpcontent.com``;
    the server url is the MCP endpoint, ``{MCP_BASE_URL}/mcp``. Both are derived
    from MCP_BASE_URL so a different deployment needs no code change. With no
    base URL (stdio) nothing is declared, and the box cannot upload anyway.
    """
    if not base_url:
        return AppConfig(prefers_border=True)
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    server_url = f"{base_url.rstrip('/')}/mcp"
    domain = hashlib.sha256(server_url.encode("utf-8")).hexdigest()[:32] + ".claudemcpcontent.com"
    return AppConfig(csp=ResourceCSP(connect_domains=[origin]), domain=domain, prefers_border=True)


@mcp.resource(
    _UPLOAD_BOX_URI,
    name="cv_upload_box",
    description="In-chat CV upload box (MCP App).",
    app=_upload_box_app_config(os.environ.get("MCP_BASE_URL")),
)
def cv_upload_box_resource() -> str:
    """Serve the upload box HTML (packaged beside this module)."""
    return _pkg_resources.files("bullhorn_mcp").joinpath("upload_box.html").read_text(encoding="utf-8")


@mcp.tool(app=AppConfig(resource_uri=_UPLOAD_BOX_URI))
def show_cv_upload_box(upload_id: str) -> str:
    """Show an upload box in the chat for a pending CV upload, when curl could not send the file.

    Afterwards wait for the user to say the file is uploaded, then call get_cv_upload.

    Args:
        upload_id: The id returned by request_cv_upload.
    """
    unavailable = _uploads_unavailable()
    if unavailable:
        return unavailable
    try:
        sub = resolve_caller_sub()
    except IdentityResolutionError as e:
        return format_response({"error": "identity_resolution_failed", "message": str(e)})
    try:
        rec = upload_store.get(upload_id, sub)
        if rec["status"] == "received":
            # The file is already here; starting over would mean resending it.
            return format_response({
                "error": "upload_already_received",
                "message": f"Upload '{upload_id}' has already received its file, so no upload box is needed.",
                "hint": (
                    f"Carry on with create_candidate_from_cv(upload_id='{upload_id}') for a new "
                    f"candidate, or attach_cv(candidate_id=..., upload_id='{upload_id}') for an existing one."
                ),
            })
        # The store keeps only token hashes, so the box gets a fresh token for the
        # same ticket; the old URL stops working.
        token, expires_at = upload_store.reissue_token(upload_id, sub)
    except UploadError as e:
        return _upload_error(e)
    return format_response({
        "upload_id": upload_id,
        "upload_url": _upload_url(token),
        "filename": rec["filename"],
        "expires_at": expires_at.isoformat(timespec="seconds"),
        "max_bytes": MAX_UPLOAD_BYTES,
        "allowed_extensions": [rec["extension"]],
        "message": (
            "An upload box is now shown in the chat. Wait for the user to drop the file, "
            f"then call get_cv_upload(upload_id='{upload_id}')."
        ),
    })


@mcp.tool()
def parse_cv(upload_id: str) -> str:
    """Parse an uploaded CV for you to review before anything is written. Step 1 of the CV flow.

    Bullhorn's parser makes mistakes. Check what it returns against the CV itself and
    note your corrections: names, the current employer (companyName, often left empty),
    job titles with the employer merged in, dates (an ongoing role has no endDate),
    education, and skills that are not in the CV. Then call create_candidate_from_cv
    (new candidate) or attach_cv (existing candidate) with the same upload_id and your
    corrections. The parse is kept with the upload, so the write uses exactly this
    parse and the file is not parsed again. Nothing is written to Bullhorn here.
    Also runs the duplicate check (duplicate_check, with a match_check_id): show the
    consultant every match with who, the percentage and the reasons.

    Args:
        upload_id: The id from request_cv_upload, once get_cv_upload shows 'received'.

    Returns:
        JSON {"parsed": {confidenceScore, candidate, description_length,
        candidateWorkHistory, candidateEducation, skillList, primarySkills},
        "duplicate_check": null | {match_check_id, matches, ...}}. The HTML
        description is left out (only its length is shown); it is always written
        from the stored parse.
    """
    upload, error = _load_received_upload(upload_id)
    if error:
        return error
    try:
        client = get_client()
        # The upload keeps its file and now its parse: create or attach needs both.
        parsed = _parse_upload(client, upload)

        dup = _run_match_check(client, profile_from_parse(parsed))
        return format_response({"parsed": _cv_response_view(parsed), "duplicate_check": dup})

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def parse_cv_text(
    content: str,
    content_type: str = "text/plain",
) -> str:
    """Parse pasted CV text for you to review. Nothing is written to Bullhorn.

    Check the result against the CV text and pass your corrections to
    create_candidate_from_cv(content=..., ...). Pasted text is not stored, so that
    call parses it again. Also runs the duplicate check (duplicate_check, with a match_check_id):
    show the consultant every match with who, the percentage and the reasons.

    Args:
        content: Plain text or HTML CV content
        content_type: MIME type: "text/plain" (default) or "text/html"

    Returns:
        JSON {"parsed": {...same view as parse_cv...}, "duplicate_check": null | {match_check_id, matches, ...}}.
    """
    try:
        client = get_client()
        parsed = client.parse_resume_text(content, content_type)

        dup = _run_match_check(client, profile_from_parse(parsed))
        return format_response({"parsed": _cv_response_view(parsed), "duplicate_check": dup})

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def create_candidate_from_cv(
    upload_id: str | None = None,
    content: str | None = None,
    content_type: str = "text/plain",
    force: bool = False,
    fields_override: dict | None = None,
    work_history: list | None = None,
    education: list | None = None,
    skills: list | None = None,
    primary_skills: list | None = None,
    match_check_id: str | None = None,
) -> str:
    """Create a new Candidate from a CV, written with your corrections to the parse.

    Call parse_cv first and check the parse against the CV. Pass what you corrected:
    fields_override for Candidate fields, and work_history, education, skills or
    primary_skills to replace that whole parsed list (an omitted list uses the parse,
    an empty list writes none). In one call this writes the Candidate, its work
    history, education, skillSet and primarySkills, and attaches the CV file (file
    mode). Nothing is shown for confirmation first: tell the user exactly what the
    response says was written. Stops on a likely or possible duplicate unless force=True:
    show the consultant who, the percentage and the reasons, and offer attach_cv.
    Exactly one of upload_id (file, from request_cv_upload) or content (text) is needed.

    Args:
        upload_id: The id from request_cv_upload, once get_cv_upload shows 'received' (file mode)
        content: Plain text or HTML CV content (text mode)
        content_type: MIME type for text mode. Default: text/plain
        force: Skip duplicate check and create regardless. Default False.
        fields_override: Corrected or extra Candidate fields; they win over the parse.
                         The description always comes from the parse.
        work_history: Corrected CandidateWorkHistory entries (replaces the parsed list).
        education: Corrected CandidateEducation entries (replaces the parsed list).
        skills: Corrected free-text skill names for skillSet (replaces parsed skillList).
        primary_skills: Corrected Bullhorn Skill ids to link (replaces parsed primarySkills).
        match_check_id: The match_check_id from parse_cv or find_duplicate_candidates; with force=True
                        it records the outcome under that check.

    Returns:
        {"created": true, "candidate_id", "written": {fields, description_length,
        work_history, education, skill_set, primary_skills, file}, "warnings",
        "duplicate_check", and "cv_attach_retry" when the file was not attached}.
        If a duplicate is found: {"duplicate_found" or "possible_duplicates": true, "matches", "parsed", "hint"}.
    """
    is_binary = upload_id is not None
    is_text = content is not None

    if not is_binary and not is_text:
        return format_response({
            "error": "input_required",
            "message": "Provide either upload_id (from request_cv_upload) for a CV file or content for CV text.",
        })
    if is_binary and is_text:
        return format_response({
            "error": "ambiguous_input",
            "message": "Provide either upload_id or content, not both.",
        })

    corrections = (fields_override, work_history, education, skills, primary_skills, match_check_id)
    if not is_binary:
        return _create_candidate_from_cv(None, None, content, content_type, force, *corrections)
    upload, error = _load_received_upload(upload_id, claim=True)
    if error:
        return error
    try:
        return _create_candidate_from_cv(upload, upload_id, None, content_type, force, *corrections)
    finally:
        upload_store.release(upload_id)


def _create_candidate_from_cv(
    upload: dict | None,
    upload_id: str | None,
    content: str | None,
    content_type: str,
    force: bool,
    fields_override: dict | None,
    work_history: list | None,
    education: list | None,
    skills: list | None,
    primary_skills: list | None,
    match_check_id: str | None = None,
) -> str:
    """Body of create_candidate_from_cv once the input is checked and any upload claimed."""
    try:
        client = get_client()
        metadata = get_metadata()

        if upload is not None:
            parsed = _parse_upload(client, upload)
        else:
            parsed = client.parse_resume_text(content, content_type)

        warnings: list[str] = []
        candidate_data = dict(parsed.get("candidate") or {})
        if fields_override:
            override = dict(fields_override)
            if "description" in override:
                # CR43 goal 2: the description is the parser's rendering of the CV itself.
                override.pop("description")
                warnings.append("fields_override 'description' was ignored: the description always comes from the parsed CV.")
            candidate_data.update(override)

        # Claude's lists replace the parsed ones; an omitted list uses the parse.
        if work_history is None:
            work_history = parsed.get("candidateWorkHistory") or []
        if education is None:
            education = parsed.get("candidateEducation") or []
        parsed_names, parsed_ids = _split_parsed_skills(parsed)
        given_names, given_ids = _normalize_skills(skills, primary_skills)
        skill_names = given_names if skills is not None else parsed_names
        primary_ids = given_ids if primary_skills is not None else parsed_ids
        # An entry repeated in one list is written once, as in attach_cv.
        work_history, education = _new_cv_children([], [], work_history, education)

        # The check runs on the corrected names and email (CR43 P5).
        dup = None
        if not force:
            check_errors: list[str] = []
            dup = _run_match_check(client, profile_from_fields(candidate_data, work_history, education), check_errors)
            if dup is None:
                warnings.append(f"Duplicate check could not run: {check_errors[0] if check_errors else 'unknown error'}")
            upload_ref = f"upload_id='{upload_id}', " if upload_id else ""
            stop = _duplicate_policy(dup, (
                "To add this CV to the existing record call attach_cv(candidate_id={candidate_id}, "
                + upload_ref
                + "match_check_id='{match_check_id}'). To create a new Candidate anyway, call "
                "create_candidate_from_cv again with force=True and match_check_id='{match_check_id}'."
            ))
            if stop is not None:
                stop["parsed"] = _cv_response_view(parsed)
                return format_response(stop)

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
        warnings.extend(strip_warnings)
        skill_set_written: list[str] = []
        if skill_names:
            # Names go in the create payload, one write fewer (CR43 P4).
            resolved["skillSet"], skill_set_written = _merge_skill_set(resolved.get("skillSet"), skill_names)
        resolved = _truncate_against_meta(metadata, "Candidate", resolved)
        if skill_set_written:
            # Report only the names that survived the skillSet maxLength clip.
            kept = _skill_set_names(resolved.get("skillSet"))
            skill_set_written = [n for n in skill_set_written if n.lower() in kept]

        env_required = get_candidate_required()
        if env_required:
            required_resolved = metadata.resolve_fields("Candidate", {k: None for k in env_required})
            missing = [k for k in required_resolved if k not in resolved or resolved[k] is None or resolved[k] == ""]
            if missing:
                return _required_fields_missing_response(missing, "fields_override", from_cv=True)

        computed = _compute_person_name(resolved)
        if computed:
            resolved["name"] = computed

        create_result = client.create("Candidate", resolved)
        candidate_id = create_result["changedEntityId"]

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"

    # The Candidate exists from here on. No failure below, of any type, may hide its
    # id (CR43 goal 5): T40.8 lost Candidate 173063's id to an AttributeError here.
    description = resolved.get("description")
    written: dict = {
        "fields": {k: v for k, v in resolved.items() if k != "description"},
        "description_length": len(description) if isinstance(description, str) else 0,
        "work_history": [],
        "education": [],
        "skill_set": skill_set_written,
        "primary_skills": [],
        "file": None,
    }
    result: dict = {"created": True, "candidate_id": candidate_id, "written": written}
    if force:
        _log_match_outcome(client, match_check_id, "created_with_force", candidate_id)
    elif dup is not None:
        _log_match_outcome(client, dup["match_check_id"], "created_new", candidate_id)
    if upload is not None:
        # Everything from this CV is written below with Claude's corrections; a later
        # attach_cv for this Candidate must only attach the file, never replay the
        # raw parse over those corrections.
        upload_store.mark_created(upload_id, candidate_id)
    try:
        children, child_warnings = _write_candidate_children(
            client, metadata, candidate_id, work_history, education, [], primary_ids, "", [],
        )
        written.update({k: v for k, v in children.items() if k != "skill_set"})
        warnings.extend(child_warnings)

        # Attach CV file (file mode only). On success the upload's bytes are dropped
        # at once (NFR-9); on failure they are kept so the user can retry.
        if upload is not None:
            try:
                content_mime = client._guess_content_type(upload["format"])
                file_attachment = client.attach_file(
                    "Candidate", candidate_id, upload["data"], upload["filename"], content_mime, file_type="CV"
                )
                written["file"] = {"file_id": (file_attachment or {}).get("fileId"), "name": upload["filename"]}
                upload_store.mark_attached(upload_id, written["file"]["file_id"], candidate_id)
            except Exception as exc:
                warnings.append(f"CV file attachment failed: {exc}")
    except Exception as exc:
        _logger.exception("create_candidate_from_cv: failure after Candidate %s was created", candidate_id)
        result["error"] = f"Candidate {candidate_id} was created, but a later step failed: {exc}"

    if warnings:
        result["warnings"] = warnings
    result["duplicate_check"] = dup
    if upload is not None and written["file"] is None:
        # The Candidate exists now. Calling this tool again would flag it as a
        # duplicate, and force=True would create a second one, so point the
        # retry at attach_cv on the new record instead.
        result["cv_attach_retry"] = {
            "message": (
                f"Candidate {candidate_id} was created but the CV file was not attached. "
                "Do not call create_candidate_from_cv again for this CV. To retry the "
                "attachment, make the call below (the upload is kept until it expires). "
                "It only attaches the file: everything else was written above."
            ),
            "next_call": f"attach_cv(candidate_id={candidate_id}, upload_id='{upload_id}')",
        }
    return format_response(result)


@mcp.tool()
def attach_cv(
    candidate_id: int,
    upload_id: str,
    fields_to_update: list | None = None,
    fields_override: dict | None = None,
    work_history: list | None = None,
    education: list | None = None,
    skills: list | None = None,
    primary_skills: list | None = None,
    confirm: bool = False,
    match_check_id: str | None = None,
) -> str:
    """Attach a CV to an existing Candidate and add what the CV has that the record lacks.

    Call parse_cv first and check the parse against the CV. Corrections work as in
    create_candidate_from_cv (an omitted list uses the parse, an empty list adds none).
    Additions are written straight away: the CV file, new work history and education,
    skill names not yet in skillSet, skill ids not yet linked, and fields that are
    empty on the record. A field that already holds a different value is NOT changed:
    it comes back in pending_overwrites. If a consultant is present, show those to
    them and only after they say yes call again with the same arguments and
    confirm=True; that writes exactly the overwrites and repeats nothing. With no
    consultant present (automation), pass confirm=True on the first call.
    Tell the user exactly what the response says was written.

    Args:
        candidate_id: Bullhorn Candidate ID of the existing record.
        upload_id: The id from request_cv_upload, once get_cv_upload shows 'received'.
        fields_to_update: Optional list of Candidate field names to consider. Omitted:
                          every parsed field (plus fields_override).
        fields_override: Corrected or extra Candidate field values; they win over the parse.
                         The description always comes from the parse.
        work_history: Corrected CandidateWorkHistory entries (replaces the parsed list).
        education: Corrected CandidateEducation entries (replaces the parsed list).
        skills: Corrected free-text skill names (replaces parsed skillList).
        primary_skills: Corrected Bullhorn Skill ids (replaces parsed primarySkills).
        confirm: True writes the overwrites too. Default False.
        match_check_id: The match_check_id from the duplicate check that led here; the outcome is recorded under it.

    Returns:
        {"committed": true, "candidate_id", "written": {fields, work_history, education,
        skill_set, primary_skills, file}, "already_present", "pending_overwrites"
        (without confirm), "overwritten" (with confirm), "warnings"}. On a failure
        after the first write: also "partial": true and "error".
    """
    # Every call can write (additions apply at once), so every call claims (CR43 P1).
    upload, error = _load_received_upload(upload_id, claim=True, attached_ok_for=candidate_id)
    if error:
        return error
    try:
        hinted = upload["candidate_id"]
        if hinted is not None and hinted != candidate_id:
            return format_response({
                "error": "upload_candidate_mismatch",
                "message": (
                    f"Upload '{upload_id}' was started for Candidate {hinted}, "
                    f"not Candidate {candidate_id}. Nothing was changed."
                ),
                "hint": (
                    f"If the CV is for Candidate {hinted}, call attach_cv(candidate_id={hinted}, "
                    f"upload_id='{upload_id}'). Otherwise call request_cv_upload with the right "
                    "candidate_id (or none) and resend the file."
                ),
            })
        return _attach_cv(
            candidate_id, upload, upload_id, fields_to_update, fields_override,
            work_history, education, skills, primary_skills, confirm, match_check_id,
        )
    finally:
        upload_store.release(upload_id)


# Fields attach_cv never plans from the parse: identity, the computed name, the
# salutation, and skillSet (appended through the skills logic, never replaced).
_ATTACH_SKIP_FIELDS = frozenset({"id", "name", "title", "skillSet"})
_ATTACH_BASE_FIELDS = "id,firstName,lastName,email,phone,mobile,occupation,companyName,skillSet,status,dateAdded,description"


def _attach_cv(
    candidate_id: int,
    upload: dict,
    upload_id: str,
    fields_to_update: list | None,
    fields_override: dict | None,
    work_history: list | None,
    education: list | None,
    skills: list | None,
    primary_skills: list | None,
    confirm: bool,
    match_check_id: str | None = None,
) -> str:
    """Body of attach_cv once the upload is loaded and claimed."""
    if upload.get("created_candidate_id") == candidate_id:
        corrections = (fields_to_update, fields_override, work_history, education, skills, primary_skills)
        return _attach_created_cv_file(
            candidate_id, upload, upload_id, any(c is not None for c in corrections), match_check_id,
        )
    warnings: list[str] = []
    try:
        client = get_client()
        metadata = get_metadata()

        parsed = _parse_upload(client, upload)
        candidate_fields = dict(parsed.get("candidate") or {})
        if fields_override:
            override = metadata.resolve_fields("Candidate", dict(fields_override))
            if "description" in override:
                override.pop("description")
                warnings.append("fields_override 'description' was ignored: the description always comes from the parsed CV.")
            candidate_fields.update(override)
        proposed_fields = {
            k: v for k, v in candidate_fields.items()
            if k not in _ATTACH_SKIP_FIELDS and isinstance(v, (str, int, float, bool))
        }
        # Clip before planning, so a value written clipped by the additions call is
        # equal on the confirm call instead of coming back as an overwrite.
        proposed_fields = _truncate_against_meta(metadata, "Candidate", proposed_fields)
        if fields_to_update is not None:
            # Labels resolve as in fields_override ("Job Title" -> occupation).
            api_names = {f: next(iter(metadata.resolve_fields("Candidate", {f: None}))) for f in fields_to_update}
            fields_to_update = list(dict.fromkeys(api_names.values()))
            # The warning names fields as the caller sent them.
            unknown = [f for f, api in api_names.items() if api not in proposed_fields]
            if unknown:
                warnings.append(f"fields_to_update not in the parse or fields_override, ignored: {unknown}")

        if work_history is None:
            work_history = parsed.get("candidateWorkHistory") or []
        if education is None:
            education = parsed.get("candidateEducation") or []
        parsed_names, parsed_ids = _split_parsed_skills(parsed)
        given_names, given_ids = _normalize_skills(skills, primary_skills)
        skill_names = given_names if skills is not None else parsed_names
        primary_ids = given_ids if primary_skills is not None else parsed_ids

        # Fetch every field the plan compares, or an unfetched filled field would
        # look empty and be written as an "addition" over the real value.
        fetch = list(dict.fromkeys(_ATTACH_BASE_FIELDS.split(",") + list(proposed_fields)))
        existing = client.get("Candidate", candidate_id, fields=",".join(fetch))

        try:
            existing_wh = client.query(
                "CandidateWorkHistory",
                where=f"candidate.id={candidate_id}",
                fields="id," + ",".join(_WORK_HISTORY_KEYS),
                count=500,
            )
        except Exception:
            existing_wh = []
        try:
            existing_edu = client.query(
                "CandidateEducation",
                where=f"candidate.id={candidate_id}",
                fields="id," + ",".join(_EDUCATION_KEYS),
                count=500,
            )
        except Exception:
            existing_edu = []
        existing_primary_ids: list[int] = []
        if primary_ids:
            try:
                linked = client.get_association("Candidate", candidate_id, "primarySkills", fields="id", count=500)
                existing_primary_ids = [r["id"] for r in linked if isinstance(r, dict) and "id" in r]
            except Exception:
                existing_primary_ids = []

        plan = _plan_cv_update(
            existing, proposed_fields, fields_to_update, existing_wh, existing_edu,
            work_history, education, skill_names, primary_ids,
            existing.get("skillSet"), existing_primary_ids,
        )
    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"

    additions = plan["additions"]
    overwrites = plan["overwrites"]
    written: dict = {"fields": [], "work_history": [], "education": [], "skill_set": [], "primary_skills": [], "file": None}
    result: dict = {"committed": True, "candidate_id": candidate_id, "written": written}

    # From the first write on, no failure may lose what was already written.
    try:
        field_payload = dict(additions["fields"])
        if confirm:
            for change in overwrites:
                field_payload[change["field"]] = proposed_fields[change["field"]]
        if field_payload:
            field_payload = _truncate_against_meta(metadata, "Candidate", field_payload)
            field_payload, strip_warns = _strip_contact_title(field_payload, "Candidate")
            warnings.extend(strip_warns)
            if "firstName" in field_payload or "lastName" in field_payload:
                computed = _compute_person_name({**existing, **field_payload})
                if computed:
                    field_payload["name"] = computed
            client.update("Candidate", candidate_id, field_payload)
            written["fields"] = list(field_payload.keys())

        children, child_warnings = _write_candidate_children(
            client, metadata, candidate_id,
            additions["work_history"], additions["education"],
            additions["skill_names"], additions["primary_skill_ids"],
            existing.get("skillSet"), existing_primary_ids,
        )
        written.update({k: v for k, v in children.items() if k != "already_present"})
        warnings.extend(child_warnings)

        if upload["status"] == "received":
            # Drop the bytes once Bullhorn has the file (NFR-9); the parse stays on
            # the tombstone so a confirm call can follow. On failure the bytes are
            # kept and the same call can be repeated: nothing above is written twice.
            try:
                content_mime = client._guess_content_type(upload["format"])
                file_attachment = client.attach_file(
                    "Candidate", candidate_id, upload["data"], upload["filename"], content_mime, file_type="CV"
                )
                written["file"] = {"file_id": (file_attachment or {}).get("fileId"), "name": upload["filename"]}
                upload_store.mark_attached(upload_id, written["file"]["file_id"], candidate_id)
            except Exception as exc:
                warnings.append(
                    f"CV file attachment failed: {exc}. Retry with attach_cv(candidate_id={candidate_id}, "
                    f"upload_id='{upload_id}'); the upload is kept until it expires."
                )
        else:
            written["file"] = {"file_id": upload.get("file_id"), "name": upload["filename"], "already_attached": True}
    except Exception as exc:
        _logger.exception("attach_cv: failure part way through writing Candidate %s", candidate_id)
        result["partial"] = True
        result["error"] = f"Writing to Candidate {candidate_id} stopped part way: {exc}"

    _log_attached(match_check_id, candidate_id, written)
    already = plan["already_present"]
    if any(already.values()):
        result["already_present"] = already
    if confirm:
        result["overwritten"] = [c["field"] for c in overwrites if c["field"] in written["fields"]]
    elif overwrites:
        result["pending_overwrites"] = overwrites
        result["hint"] = (
            "These fields already hold a different value and were NOT changed. Show them to the "
            "consultant; only after they say yes, call attach_cv again with the same arguments "
            "and confirm=True. Nothing above will be added twice."
        )
    if warnings:
        result["warnings"] = warnings
    return format_response(result)


def _log_attached(match_check_id: str | None, candidate_id: int, written: dict) -> None:
    """D12: log ``attached_to`` under the given match_check_id after a call that wrote something."""
    file_info = written.get("file") or {}
    wrote = any(written.get(k) for k in ("fields", "work_history", "education", "skill_set", "primary_skills")) or (
        bool(file_info) and not file_info.get("already_attached")
    )
    if wrote:
        _log_match_outcome(get_client(), match_check_id, "attached_to", candidate_id)


def _attach_created_cv_file(
    candidate_id: int, upload: dict, upload_id: str, had_corrections: bool, match_check_id: str | None = None,
) -> str:
    """attach_cv for the Candidate create_candidate_from_cv made from this upload: the file only.

    The create already wrote the fields, work history, education and skills with
    Claude's corrections. Planning again from the stored parse would add the raw
    parser entries next to the corrected ones and offer to revert the corrected
    fields (CR43 review C1), so nothing but the file is written here.
    """
    warnings: list[str] = []
    if had_corrections:
        warnings.append(
            "Corrections were ignored: this Candidate was created from this CV and already holds "
            "what was written then. Use update_record to change it."
        )
    written: dict = {"fields": [], "work_history": [], "education": [], "skill_set": [], "primary_skills": [], "file": None}
    result: dict = {"committed": True, "candidate_id": candidate_id, "written": written}
    if upload["status"] != "received":
        written["file"] = {"file_id": upload.get("file_id"), "name": upload["filename"], "already_attached": True}
    else:
        try:
            client = get_client()
            content_mime = client._guess_content_type(upload["format"])
            file_attachment = client.attach_file(
                "Candidate", candidate_id, upload["data"], upload["filename"], content_mime, file_type="CV"
            )
            written["file"] = {"file_id": (file_attachment or {}).get("fileId"), "name": upload["filename"]}
            upload_store.mark_attached(upload_id, written["file"]["file_id"], candidate_id)
        except Exception as exc:
            warnings.append(
                f"CV file attachment failed: {exc}. Retry with attach_cv(candidate_id={candidate_id}, "
                f"upload_id='{upload_id}'); the upload is kept until it expires."
            )
    _log_attached(match_check_id, candidate_id, written)
    if warnings:
        result["warnings"] = warnings
    return format_response(result)


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

    Returns all fields for any supported entity — use to discover field names before calling update_record, search_entities, query_entities, or create tools.
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
    For entity="ClientCorporation", this returns the notes of the company's
    contacts (Bullhorn has no company-level note).

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
            _note_association(entity),
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

    When entity_filter is provided the search runs against that record's notes
    directly and is reliable. Without entity_filter it uses Bullhorn's Lucene
    /search/Note route, which on this account returns no documents for any query,
    including phrases present in thousands of notes. When that is detected the
    response carries a ``warnings`` key, and an empty ``data`` says nothing about
    whether matching notes exist. Routes that do return data:
      - list_contacts / list_candidates / list_jobs with note_action="<action>",
        to find the PARENT records carrying a given note action
      - a nested query such as notes.action:"BD Call" via search_entities on the
        parent entity (multi-word values must be double-quoted)
      - entity_filter below, or get_notes_for_entity, for one record's notes

    Args:
        query: Keyword to search for in note comments (case-insensitive substring
            when entity_filter is provided; Lucene syntax when searching globally)
        entity_filter: Optional dict to narrow results to notes attached to a
            specific record. Format: {"type": "Candidate", "id": 169020}.
            Supported types: Candidate, ClientContact, ClientCorporation,
            JobOrder, Placement, Lead, Opportunity.
            When provided, fetches all notes for that record and keyword-filters
            them locally — reliable regardless of Lucene index configuration.
            For type="ClientCorporation" this searches the notes of the
            company's contacts (Bullhorn has no company-level note).
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
        warnings: list[str] = []

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
                _note_association(filter_type),
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

            # An empty result from this route is ambiguous: it means either "no
            # matches" or "this route does not return documents on this account".
            # Probe once to tell the two apart, so an unusable route is never
            # rendered as a factual answer about the caller's data.
            if not notes and not pagination["total"]:
                if client.note_search_returns_results() is False:
                    warnings.append(_NOTE_INDEX_EMPTY_WARNING)

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

        response: dict = {"data": cleaned_notes, "pagination": pagination}
        if warnings:
            response["warnings"] = warnings
        return format_response(response)

    except (AuthenticationError, BullhornAPIError) as e:
        return f"ERROR: {e}"


_PERPLEXITY_MAX_QUERIES = 5
_PERPLEXITY_SNIPPET_CHARS = 300


@mcp.tool()
def people_search_perplexity(
    queries: list[str],
    max_results: int = 10,
) -> str:
    """Searches a dedicated index for individual profiles and employee data. Returns information including names, job titles, companies, and profile URLs. Use this tool ONLY when the user specifically wants individual employee lookups, career history, or people who match work-related criteria (e.g., listing employees at a company by location). This tool is strongest for sourcing or mapping multiple people who match criteria: population-shaped queries (role plus location or sector) return many precise matches. For a single specific named individual or a company's specific office-holder, prefer a general web search first and fall back to this tool if the results are unsatisfactory. Results are a snapshot and may not reflect a person's current role.

    There is no paging: to see more people, re-call with a higher max_results or vary the query.

    Args:
        queries: 1 to 5 search queries, e.g. ["financial controller Dublin"].
            Results across all queries come back as one merged, ranked list.
        max_results: Total results across all queries (1-50, default 10)
    """
    # CR38: external source, isolated from Bullhorn. Validate before any HTTP call.
    if not queries:
        return format_response({
            "error": "queries_required",
            "message": "Provide at least one query.",
        })
    if len(queries) > _PERPLEXITY_MAX_QUERIES:
        return format_response({
            "error": "too_many_queries",
            "message": f"At most {_PERPLEXITY_MAX_QUERIES} queries per call. Got: {len(queries)}",
        })
    if any(not isinstance(q, str) or not q.strip() for q in queries):
        return format_response({
            "error": "blank_query",
            "message": "Every query must be a non-empty string.",
        })
    max_results = max(1, min(50, max_results))

    # Read at call time, never at import: a missing key must not stop the server.
    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        return format_response({
            "error": "perplexity_key_not_configured",
            "message": "PERPLEXITY_API_KEY is not set on the server.",
        })

    try:
        raw = search_people(api_key, queries, max_results=max_results)
    except PerplexityError as e:
        return format_response({"error": "perplexity_error", "message": str(e)})

    results = []
    for item in raw:
        snippet = item.get("snippet")
        if not isinstance(snippet, str):
            snippet = ""
        if len(snippet) > _PERPLEXITY_SNIPPET_CHARS:
            snippet = snippet[:_PERPLEXITY_SNIPPET_CHARS].rstrip() + "..."
        row = {
            "title": item.get("title"),
            "url": item.get("url"),
            "snippet": snippet,
            "last_updated": item.get("last_updated"),
        }
        # People mode usually omits date; only surface it when present.
        if item.get("date"):
            row["date"] = item["date"]
        results.append(row)

    return format_response({
        "queries": queries,
        "count": len(results),
        "note": (
            "Results are a single merged, ranked list across all queries, capped at "
            "max_results total. Source: Perplexity people index (external, not Bullhorn)."
        ),
        "results": results,
    })


# CR41: POST /upload/{token}. The token is the only authorisation (the route sits
# outside Entra, like the CR27 upload route it replaces). It stores bytes in the in-memory
# upload store and never calls Bullhorn: every Bullhorn write stays inside an MCP
# tool, where the caller's Entra identity is available. Never log the token.

# Multipart overhead allowance on top of the 10 MB file cap.
_UPLOAD_BODY_LIMIT = MAX_UPLOAD_BYTES + 64 * 1024


class _InMemoryMultiPartParser(MultiPartParser):
    """Starlette's parser spools file parts above 1 MB to a temp file on disk.

    NFR-9 says received files are held in memory only, so the spool threshold is
    raised above the capped body size and the file part never rolls to disk.
    """

    spool_max_size = _UPLOAD_BODY_LIMIT + 1


def _cors_origin(request: Request) -> str | None:
    """Return the Origin to echo back when it is the Claude MCP App sandbox, else None."""
    origin = request.headers.get("origin")
    if not origin:
        return None
    parsed = urlparse(origin)
    host = parsed.hostname or ""
    if parsed.scheme == "https" and host.endswith(".claudemcpcontent.com"):
        return origin
    return None


def _upload_json(request: Request, body: dict, status_code: int) -> JSONResponse:
    response = JSONResponse(body, status_code=status_code)
    origin = _cors_origin(request)
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    return response


async def _read_capped_body(request: Request) -> bytes | None:
    """Read the request body, or return None as soon as it exceeds the limit."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > _UPLOAD_BODY_LIMIT:
        return None
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _UPLOAD_BODY_LIMIT:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


async def _upload_handler(request: Request) -> Response:
    """Handle POST /upload/{token}: receive one CV file (multipart field ``file``)."""
    if request.method == "OPTIONS":
        origin = _cors_origin(request)
        if not origin:
            return Response(status_code=403)
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Max-Age": "600",
                "Vary": "Origin",
            },
        )

    token = request.path_params.get("token", "")
    too_large = {
        "error": "file_too_large",
        "message": f"The file is larger than the {MAX_UPLOAD_BYTES} byte (10 MB) limit.",
    }
    try:
        # Refuse a dead ticket before reading up to 10 MB of body.
        upload_store.check_token(token)

        if not request.headers.get("content-type", "").startswith("multipart/form-data"):
            return _upload_json(request, {
                "error": "missing_file",
                "message": "Send the CV as multipart/form-data in a field named 'file'.",
            }, 400)

        body = await _read_capped_body(request)
        if body is None:
            return _upload_json(request, too_large, 413)

        async def _body_stream():
            yield body

        try:
            form = await _InMemoryMultiPartParser(
                request.headers, _body_stream(), max_files=1, max_fields=10
            ).parse()
        except MultiPartException as exc:
            return _upload_json(request, {"error": "invalid_multipart", "message": str(exc)}, 400)

        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            return _upload_json(request, {
                "error": "missing_file",
                "message": "Send the CV as multipart/form-data in a field named 'file'.",
            }, 400)
        data = await upload.read()
        result = upload_store.redeem(token, upload.filename, data)
    except UploadError as e:
        _logger.info("cv upload rejected: %s", e.code)
        return _upload_json(request, {"error": e.code, "message": str(e)}, e.http_status)

    _logger.info("cv upload received upload_id=%s size=%s", result["upload_id"], result["size"])
    return _upload_json(request, result, 200)


mcp.custom_route("/upload/{token}", methods=["POST", "OPTIONS"])(_upload_handler)


class _RedactUploadTokenFilter(logging.Filter):
    """Blank the token in uvicorn access-log lines for ``/upload/{token}``.

    A rejected file does not use up a ticket, so a token copied from a log would
    stay redeemable for up to 15 minutes. uvicorn logs the path as the third arg.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) \
                and args[2].startswith("/upload/"):
            record.args = args[:2] + ("/upload/<redacted>",) + args[3:]
        return True


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
        access_logger = logging.getLogger("uvicorn.access")
        if not any(isinstance(f, _RedactUploadTokenFilter) for f in access_logger.filters):
            access_logger.addFilter(_RedactUploadTokenFilter())
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
