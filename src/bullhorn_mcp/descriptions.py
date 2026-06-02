"""Dynamic tool description enrichment from Bullhorn /meta at server startup.

Called once inside main() before mcp.run() to append live field summaries to
each tool's description. Falls back gracefully to static docstrings on failure.
"""

import logging

from .client import BullhornClient
from .metadata import BullhornMetadata

logger = logging.getLogger(__name__)

# All entity types to fetch /meta for at startup.
SUPPORTED_ENTITIES: list[str] = [
    "Candidate",
    "ClientContact",
    "ClientCorporation",
    "JobOrder",
    "JobSubmission",
    "Note",
    "Placement",
    "UserMessage",
    "CorporateUser",
]

# Picklist field names whose options[] are inlined as "Valid values: ..." in
# descriptions. Conservative set — keeps descriptions compact.
PICKLIST_FIELDS_TO_EXPAND: set[str] = {
    "status",
    "employmentType",
    "category",
    "type",
    "source",
}

# Maps each MCP tool name to the entity types whose field summary should be
# appended to its description. Single-entity tools name one entity; generic
# tools (search_entities, query_entities, update_record) name all.
TOOL_ENTITY_MAP: dict[str, list[str]] = {
    "list_jobs": ["JobOrder"],
    "list_candidates": ["Candidate"],
    "list_contacts": ["ClientContact"],
    "list_companies": ["ClientCorporation"],
    "get_job": ["JobOrder"],
    "get_candidate": ["Candidate"],
    "get_company": ["ClientCorporation"],
    "get_contact": ["ClientContact"],
    "search_entities": SUPPORTED_ENTITIES,
    "query_entities": SUPPORTED_ENTITIES,
    "create_company": ["ClientCorporation"],
    "create_contact": ["ClientContact"],
    "create_job": ["JobOrder"],
    "create_candidate": ["Candidate"],
    "update_job": ["JobOrder"],
    "update_record": SUPPORTED_ENTITIES,
    "add_note": ["Note"],
    "get_notes_for_entity": ["Note"],
    "search_notes": ["Note"],
    "find_duplicate_companies": ["ClientCorporation"],
    "find_duplicate_contacts": ["ClientContact", "ClientCorporation"],
    "find_duplicate_candidates": ["Candidate"],
    "parse_cv": ["Candidate"],
    "parse_cv_text": ["Candidate"],
    "create_candidate_from_cv": ["Candidate"],
    "attach_cv": ["Candidate"],
    "bulk_import": ["ClientCorporation", "ClientContact"],
    "shortlist_candidate": ["JobSubmission"],
    "shortlist_candidates": ["JobSubmission"],
    "search_emails": ["UserMessage"],
    "get_entity_fields": SUPPORTED_ENTITIES,
}


def build_entity_section(entity: str, fields: list[dict]) -> str:
    """Render a compact field-reference section for one entity.

    Args:
        entity: Entity type name (e.g. "Candidate")
        fields: Field dicts from BullhornMetadata.get_fields()

    Returns:
        Formatted multi-line string, e.g.:
            ### Candidate fields
            - `occupation` (STRING) — Occupation [Valid values: ...]
            ...
    """
    lines = [f"### {entity} fields"]
    for f in fields:
        name = f.get("name", "")
        ftype = f.get("type", "")
        label = f.get("label", "")
        required = f.get("required", False)

        line = f"- `{name}` ({ftype})"
        if label and label != name:
            line += f" — {label}"
        if required:
            line += " [required]"
        if name in PICKLIST_FIELDS_TO_EXPAND and f.get("options"):
            values = [str(o.get("value", "")) for o in f["options"] if o.get("value")]
            if values:
                line += f" [Valid values: {', '.join(values)}]"
        lines.append(line)
    return "\n".join(lines)


async def enrich_tool_descriptions(mcp, client: BullhornClient) -> BullhornMetadata:
    """Fetch /meta for each supported entity and append field summaries to tools.

    Runs once inside main() before mcp.run(). Per-entity and per-tool failures
    are caught and logged so one bad entity or tool name never blocks the rest.

    Returns the BullhornMetadata instance so main() can store it as the server's
    runtime metadata cache, avoiding a second round of /meta fetches.

    Args:
        mcp: The FastMCP server instance (tools already registered).
        client: Authenticated BullhornClient (first network call happens here).
    """
    metadata = BullhornMetadata(client)

    entity_sections: dict[str, str] = {}
    for entity in SUPPORTED_ENTITIES:
        try:
            fields = metadata.get_fields(entity)
            entity_sections[entity] = build_entity_section(entity, fields)
            logger.debug("Loaded metadata for %s (%d fields)", entity, len(fields))
        except Exception as exc:
            logger.warning("Could not load metadata for %s: %s", entity, exc)

    if not entity_sections:
        logger.warning("No entity metadata loaded — tool descriptions will use static fallbacks")
        return metadata

    for tool_name, entities in TOOL_ENTITY_MAP.items():
        sections = [entity_sections[e] for e in entities if e in entity_sections]
        if not sections:
            continue
        appended = "\n\n## Field reference (auto-populated at startup)\n" + "\n\n".join(sections)
        try:
            tool = await mcp.get_tool(tool_name)
            tool.description = (tool.description or "") + appended
        except Exception as exc:
            logger.warning("Could not enrich description for tool %s: %s", tool_name, exc)

    return metadata
