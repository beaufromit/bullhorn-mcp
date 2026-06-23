"""Dynamic tool description enrichment from Bullhorn /meta at server startup.

Called once inside main() before mcp.run() to append live field summaries to
each tool's description. Falls back gracefully to static docstrings on failure.
"""

import logging
import re

from .client import BullhornClient, DEFAULT_FIELDS
from .metadata import BullhornMetadata

logger = logging.getLogger(__name__)

# Maximum number of fields to include in a full entity section.
MAX_FIELDS_PER_ENTITY: int = 40

# Regex matching Bullhorn generated custom-field names (e.g. customText1,
# customInt3, customObject5). Used by select_fields() to include them only when
# they carry a human-readable label different from the field name itself.
_CUSTOM_FIELD_RE: re.Pattern[str] = re.compile(
    r"^custom(?:Text|Int|Float|Date|Big)\d+$|^customObject"
)

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
    "Tearsheet",
]

# Picklist field names whose options[] are inlined as "Valid values: ..." in
# descriptions. Conservative set -- keeps descriptions compact.
PICKLIST_FIELDS_TO_EXPAND: set[str] = {
    "status",
    "employmentType",
    "category",
    "type",
    "source",
}

# Tools that work across many entity types. They get compact per-entity sections
# rather than full ones to avoid overwhelming the context window.
GENERIC_DISCOVERY_TOOLS: set[str] = {
    "search_entities",
    "query_entities",
    "update_record",
    "get_entity_fields",
}

# Maps each MCP tool name to the entity types whose field summary should be
# appended to its description. Single-entity tools name one entity; generic
# tools (search_entities, query_entities, update_record) name all.
TOOL_ENTITY_MAP: dict[str, list[str]] = {
    "list_jobs": ["JobOrder"],
    "list_candidates": ["Candidate"],
    "list_contacts": ["ClientContact"],
    "list_companies": ["ClientCorporation"],
    "list_placements": ["Placement"],
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
    "get_job_submissions": ["JobSubmission"],
    "shortlist_candidate": ["JobSubmission"],
    "shortlist_candidates": ["JobSubmission"],
    "search_emails": ["UserMessage"],
    "get_entity_fields": SUPPORTED_ENTITIES,
    "list_tearsheets": ["Tearsheet"],
    "get_tearsheet": ["Tearsheet"],
    "create_tearsheet": ["Tearsheet"],
    "add_to_tearsheet": ["Tearsheet"],
    "remove_from_tearsheet": ["Tearsheet"],
}


def select_fields(entity: str, meta_fields: list[dict]) -> list[dict]:
    """Return a curated, de-duped, capped list of fields for an entity section.

    Selection priority:
      1. Fields listed in DEFAULT_FIELDS for the entity (base name before "(" is
         used to strip association-syntax qualifiers such as "candidate(id,name)").
      2. Fields marked required in meta_fields.
      3. Fields whose name appears in PICKLIST_FIELDS_TO_EXPAND.
      4. Custom fields (name matches _CUSTOM_FIELD_RE) that carry a human-readable
         label different from the field name.

    De-duplication is by field name, first-occurrence wins. The resulting list is
    capped at MAX_FIELDS_PER_ENTITY entries.

    Args:
        entity: Entity type name (e.g. "Candidate").
        meta_fields: Field dicts from BullhornMetadata.get_fields().

    Returns:
        Ordered list of field dicts, at most MAX_FIELDS_PER_ENTITY entries.
    """
    # Build a lookup from name -> field dict for fast access.
    by_name: dict[str, dict] = {f.get("name", ""): f for f in meta_fields if f.get("name")}

    # Step 1: DEFAULT_FIELDS for the entity, parsed to plain field names.
    default_str = DEFAULT_FIELDS.get(entity, "")
    default_names: list[str] = []
    for token in default_str.split(","):
        token = token.strip()
        if not token:
            continue
        # Strip association syntax: "candidate(id,name)" -> "candidate"
        base = token.split("(")[0].strip()
        if base:
            default_names.append(base)

    seen: set[str] = set()
    selected: list[dict] = []

    def _add(name: str) -> None:
        if name in seen or name not in by_name:
            return
        seen.add(name)
        selected.append(by_name[name])

    for name in default_names:
        _add(name)

    # Step 2: required fields.
    for f in meta_fields:
        if f.get("required"):
            _add(f.get("name", ""))

    # Step 3: picklist fields that are in PICKLIST_FIELDS_TO_EXPAND.
    for f in meta_fields:
        name = f.get("name", "")
        if name in PICKLIST_FIELDS_TO_EXPAND:
            _add(name)

    # Step 4: named custom fields with a human-readable label.
    for f in meta_fields:
        name = f.get("name", "")
        label = f.get("label", "")
        if _CUSTOM_FIELD_RE.match(name) and label and label != name:
            _add(name)

    return selected[:MAX_FIELDS_PER_ENTITY]


def build_entity_section(entity: str, fields: list[dict], level: str = "full") -> str:
    """Render a field-reference section for one entity.

    Args:
        entity: Entity type name (e.g. "Candidate").
        fields: Field dicts from BullhornMetadata.get_fields(). For "full" level
            the caller should pass the select_fields() result; for "compact" the
            DEFAULT_FIELDS subset is rendered (this function still accepts the
            full meta list and filters inline).
        level: "full" (default) -- curated list with type/label/required/picklist
            annotations; "compact" -- DEFAULT_FIELDS subset with type and label
            only, no picklist expansion and no [required] marker.

    Returns:
        Formatted multi-line string, e.g.:
            ### Candidate fields
            - `occupation` (STRING) -- Occupation [Valid values: ...]
            ...
    """
    lines = [f"### {entity} fields"]

    if level == "compact":
        # Render only the DEFAULT_FIELDS base names with minimal annotations.
        default_str = DEFAULT_FIELDS.get(entity, "")
        by_name: dict[str, dict] = {f.get("name", ""): f for f in fields if f.get("name")}
        for name in [t.split("(")[0].strip() for t in default_str.split(",") if t.strip()]:
            f = by_name.get(name)
            if not f:
                continue
            ftype = f.get("type", "")
            label = f.get("label", "")
            line = f"- `{name}` ({ftype})"
            if label and label != name:
                line += f" -- {label}"
            lines.append(line)
    else:
        # Full level: annotate with type, label, required, and picklist values.
        for f in fields:
            name = f.get("name", "")
            ftype = f.get("type", "")
            label = f.get("label", "")
            required = f.get("required", False)

            line = f"- `{name}` ({ftype})"
            if label and label != name:
                line += f" -- {label}"
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

    Generic discovery tools (search_entities, query_entities, update_record,
    get_entity_fields) receive compact per-entity sections plus a trailing
    pointer to get_entity_fields for the full list. All other tools receive full
    sections built from the select_fields() curated list.

    Returns the BullhornMetadata instance so main() can store it as the server's
    runtime metadata cache, avoiding a second round of /meta fetches.

    Args:
        mcp: The FastMCP server instance (tools already registered).
        client: Authenticated BullhornClient (first network call happens here).
    """
    metadata = BullhornMetadata(client)

    # Precompute both full and compact sections per entity.
    full_sections: dict[str, str] = {}
    compact_sections: dict[str, str] = {}

    for entity in SUPPORTED_ENTITIES:
        try:
            fields = metadata.get_fields(entity)
            curated = select_fields(entity, fields)
            full_sections[entity] = build_entity_section(entity, curated, level="full")
            compact_sections[entity] = build_entity_section(entity, fields, level="compact")
            logger.debug("Loaded metadata for %s (%d fields)", entity, len(fields))
        except Exception as exc:
            logger.warning("Could not load metadata for %s: %s", entity, exc)

    if not full_sections:
        logger.warning("No entity metadata loaded -- tool descriptions will use static fallbacks")
        return metadata

    _pointer = (
        '\nFor the full field list of any entity, call get_entity_fields(entity="<Entity>").'
    )

    for tool_name, entities in TOOL_ENTITY_MAP.items():
        is_generic = tool_name in GENERIC_DISCOVERY_TOOLS

        if is_generic:
            sections = [compact_sections[e] for e in entities if e in compact_sections]
        else:
            sections = [full_sections[e] for e in entities if e in full_sections]

        if not sections:
            continue

        appended = "\n\n## Field reference (auto-populated at startup)\n" + "\n\n".join(sections)
        if is_generic:
            appended += _pointer

        try:
            tool = await mcp.get_tool(tool_name)
            tool.description = (tool.description or "") + appended
        except Exception as exc:
            logger.warning("Could not enrich description for tool %s: %s", tool_name, exc)

    return metadata
