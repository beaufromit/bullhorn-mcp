"""Tests for dynamic tool description enrichment at startup."""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from bullhorn_mcp.descriptions import (
    build_entity_section,
    enrich_tool_descriptions,
    PICKLIST_FIELDS_TO_EXPAND,
    TOOL_ENTITY_MAP,
    SUPPORTED_ENTITIES,
    select_fields,
    GENERIC_DISCOVERY_TOOLS,
    MAX_FIELDS_PER_ENTITY,
)
from bullhorn_mcp.auth import AuthenticationError


SAMPLE_FIELDS = [
    {"name": "id", "label": "Candidate ID", "type": "ID", "required": False},
    {"name": "firstName", "label": "First Name", "type": "STRING", "required": True},
    {"name": "occupation", "label": "Occupation", "type": "STRING", "required": False},
    {
        "name": "status",
        "label": "Status",
        "type": "STRING",
        "required": False,
        "options": [
            {"value": "Active", "label": "Active"},
            {"value": "Passively Looking", "label": "Passively Looking"},
            {"value": "Inactive", "label": "Inactive"},
        ],
    },
    {
        "name": "source",
        "label": "Source",
        "type": "STRING",
        "required": False,
        "options": [
            {"value": "Web", "label": "Web"},
            {"value": "Referral", "label": "Referral"},
        ],
    },
    {
        "name": "category",
        "label": "Category",
        "type": "TO_ONE",
        "required": False,
        "options": [
            {"value": "IT", "label": "IT"},
            {"value": "Finance", "label": "Finance"},
        ],
    },
    # A picklist field NOT in PICKLIST_FIELDS_TO_EXPAND
    {
        "name": "preferredContact",
        "label": "Preferred Contact",
        "type": "STRING",
        "required": False,
        "options": [
            {"value": "Phone", "label": "Phone"},
            {"value": "Email", "label": "Email"},
        ],
    },
]


class TestBuildEntitySection:
    def test_basic_fields_rendered(self):
        fields = [
            {"name": "firstName", "label": "First Name", "type": "STRING", "required": False},
            {"name": "lastName", "label": "Last Name", "type": "STRING", "required": True},
        ]
        result = build_entity_section("Candidate", fields)

        assert "### Candidate fields" in result
        assert "`firstName`" in result
        assert "(STRING)" in result
        assert "First Name" in result
        assert "`lastName`" in result
        assert "[required]" in result

    def test_label_omitted_when_same_as_name(self):
        fields = [{"name": "occupation", "label": "occupation", "type": "STRING", "required": False}]
        result = build_entity_section("Candidate", fields)

        # label matches name — should not appear twice
        assert result.count("occupation") == 1

    def test_includes_picklist_options_for_status(self):
        status_field = {
            "name": "status",
            "label": "Status",
            "type": "STRING",
            "required": False,
            "options": [
                {"value": "Active", "label": "Active"},
                {"value": "Inactive", "label": "Inactive"},
            ],
        }
        result = build_entity_section("Candidate", [status_field])

        assert "Valid values:" in result
        assert "Active" in result
        assert "Inactive" in result

    def test_includes_picklist_options_for_all_expand_fields(self):
        for field_name in PICKLIST_FIELDS_TO_EXPAND:
            field = {
                "name": field_name,
                "label": field_name.title(),
                "type": "STRING",
                "required": False,
                "options": [{"value": "X", "label": "X"}],
            }
            result = build_entity_section("Entity", [field])
            assert "Valid values:" in result, f"Expected options for {field_name}"

    def test_omits_options_for_non_expand_picklist(self):
        field = {
            "name": "preferredContact",
            "label": "Preferred Contact",
            "type": "STRING",
            "required": False,
            "options": [{"value": "Phone", "label": "Phone"}],
        }
        assert "preferredContact" not in PICKLIST_FIELDS_TO_EXPAND
        result = build_entity_section("Candidate", [field])

        assert "Valid values:" not in result

    def test_field_without_options_no_valid_values(self):
        field = {"name": "status", "label": "Status", "type": "STRING", "required": False}
        result = build_entity_section("Candidate", [field])

        assert "Valid values:" not in result

    def test_entity_name_in_header(self):
        result = build_entity_section("ClientCorporation", [])
        assert "### ClientCorporation fields" in result

    def test_full_sample_renders_without_error(self):
        result = build_entity_section("Candidate", SAMPLE_FIELDS)
        assert "### Candidate fields" in result
        assert "`occupation`" in result
        assert "`status`" in result
        assert "Active" in result
        assert "Passively Looking" in result
        # preferredContact is a picklist not in PICKLIST_FIELDS_TO_EXPAND
        assert result.count("Valid values:") == 3  # status, source, category


class TestEnrichToolDescriptions:
    def _make_mock_mcp(self, tool_names: list[str]) -> Mock:
        """Return a mock mcp whose get_tool returns a simple object per name."""
        tools = {}
        for name in tool_names:
            t = Mock()
            t.description = f"Static description for {name}."
            tools[name] = t

        async def get_tool(name):
            return tools[name]

        mcp = Mock()
        mcp.get_tool = get_tool
        return mcp, tools

    def _make_mock_client(self, fields_by_entity: dict) -> Mock:
        """Return a mock BullhornClient whose get_meta responds per entity."""
        client = Mock()
        client.get_meta.side_effect = lambda entity: {
            "entity": entity,
            "fields": fields_by_entity.get(entity, []),
        }
        return client

    @pytest.mark.asyncio
    async def test_appends_to_existing_description(self):
        mcp, tools = self._make_mock_mcp(["list_candidates"])
        client = self._make_mock_client({"Candidate": SAMPLE_FIELDS})

        await enrich_tool_descriptions(mcp, client)

        desc = tools["list_candidates"].description
        assert desc.startswith("Static description for list_candidates.")
        assert "## Field reference" in desc
        assert "### Candidate fields" in desc

    @pytest.mark.asyncio
    async def test_original_text_preserved(self):
        mcp, tools = self._make_mock_mcp(["list_jobs"])
        client = self._make_mock_client({"JobOrder": SAMPLE_FIELDS})

        await enrich_tool_descriptions(mcp, client)

        assert tools["list_jobs"].description.startswith("Static description for list_jobs.")

    @pytest.mark.asyncio
    async def test_graceful_on_meta_failure_for_one_entity(self):
        """One entity failing /meta should not block others."""
        # Only Candidate and ClientContact are in TOOL_ENTITY_MAP for single-entity tools.
        # We'll make Candidate fail and ClientContact succeed.
        client = Mock()

        def get_meta(entity):
            if entity == "Candidate":
                raise Exception("Network timeout")
            return {"entity": entity, "fields": SAMPLE_FIELDS}

        client.get_meta.side_effect = get_meta

        mcp, tools = self._make_mock_mcp(["list_candidates", "list_contacts"])

        await enrich_tool_descriptions(mcp, client)

        # list_contacts (ClientContact) should be enriched
        assert "## Field reference" in tools["list_contacts"].description
        # list_candidates should keep its static description (Candidate failed)
        assert "## Field reference" not in tools["list_candidates"].description

    @pytest.mark.asyncio
    async def test_graceful_on_auth_failure(self):
        """AuthenticationError from /meta fetch is caught, server still starts."""
        client = Mock()
        client.get_meta.side_effect = AuthenticationError("Token expired")

        mcp, tools = self._make_mock_mcp(["list_candidates"])

        # Should not raise
        await enrich_tool_descriptions(mcp, client)

        # Description unchanged
        assert tools["list_candidates"].description == "Static description for list_candidates."

    @pytest.mark.asyncio
    async def test_graceful_on_get_tool_failure(self):
        """Unknown tool name in TOOL_ENTITY_MAP is handled without raising."""
        client = self._make_mock_client({"Candidate": SAMPLE_FIELDS})

        mcp = Mock()
        mcp.get_tool = AsyncMock(side_effect=Exception("Tool not found"))

        # Should not raise
        await enrich_tool_descriptions(mcp, client)

    @pytest.mark.asyncio
    async def test_search_entities_includes_all_supported_entities(self):
        """search_entities description should reference all SUPPORTED_ENTITIES."""
        # Build a client that returns at least an id field for each entity
        simple_field = [{"name": "id", "label": "ID", "type": "ID", "required": False}]
        client = self._make_mock_client({e: simple_field for e in SUPPORTED_ENTITIES})

        mcp, tools = self._make_mock_mcp(["search_entities"])

        await enrich_tool_descriptions(mcp, client)

        desc = tools["search_entities"].description
        for entity in SUPPORTED_ENTITIES:
            assert f"### {entity} fields" in desc, f"Expected section for {entity}"

    @pytest.mark.asyncio
    async def test_empty_field_list_still_renders_header(self):
        """An entity with no fields still produces a header (edge case)."""
        client = self._make_mock_client({"Candidate": []})
        mcp, tools = self._make_mock_mcp(["list_candidates"])

        await enrich_tool_descriptions(mcp, client)

        assert "### Candidate fields" in tools["list_candidates"].description

    @pytest.mark.asyncio
    async def test_generic_tool_gets_compact_with_pointer(self):
        """update_record is in GENERIC_DISCOVERY_TOOLS -- its description must contain the
        get_entity_fields pointer and must NOT contain 'Valid values:' (compact level)."""
        assert "update_record" in GENERIC_DISCOVERY_TOOLS
        fields = [
            {"name": "status", "label": "Status", "type": "STRING", "required": False,
             "options": [{"value": "Active", "label": "Active"}]},
        ]
        client = self._make_mock_client({e: fields for e in SUPPORTED_ENTITIES})
        mcp, tools = self._make_mock_mcp(["update_record"])

        await enrich_tool_descriptions(mcp, client)

        desc = tools["update_record"].description
        assert "get_entity_fields" in desc
        assert "Valid values:" not in desc

    @pytest.mark.asyncio
    async def test_entity_tool_gets_full_with_picklist(self):
        """list_candidates is NOT in GENERIC_DISCOVERY_TOOLS -- its description must contain
        [required] and Valid values: when the Candidate meta has such fields."""
        assert "list_candidates" not in GENERIC_DISCOVERY_TOOLS
        fields = [
            {"name": "firstName", "label": "First Name", "type": "STRING", "required": True},
            {"name": "status", "label": "Status", "type": "STRING", "required": False,
             "options": [{"value": "Active", "label": "Active"}]},
        ]
        client = self._make_mock_client({"Candidate": fields})
        mcp, tools = self._make_mock_mcp(["list_candidates"])

        await enrich_tool_descriptions(mcp, client)

        desc = tools["list_candidates"].description
        assert "[required]" in desc
        assert "Valid values:" in desc

    @pytest.mark.asyncio
    async def test_no_entity_section_exceeds_cap(self):
        """With 60 fields per entity, each rendered section must have at most MAX_FIELDS_PER_ENTITY bullets."""
        # Build 60 distinct fields per entity; all are required so they qualify for inclusion.
        many_fields = [
            {"name": f"field{i}", "label": f"Field {i}", "type": "STRING", "required": True}
            for i in range(60)
        ]
        client = self._make_mock_client({e: many_fields for e in SUPPORTED_ENTITIES})
        mcp, tools = self._make_mock_mcp(["list_candidates"])

        await enrich_tool_descriptions(mcp, client)

        desc = tools["list_candidates"].description
        bullet_count = desc.count("\n- `")
        assert bullet_count <= MAX_FIELDS_PER_ENTITY

    def test_generic_tool_static_docstring_mentions_get_entity_fields(self):
        """All 4 GENERIC_DISCOVERY_TOOLS must have 'get_entity_fields' in their static docstrings.

        Uses ast.parse on server.py to inspect the raw docstring before any runtime enrichment.
        """
        import ast
        import pathlib

        server_path = pathlib.Path(__file__).parent.parent / "src" / "bullhorn_mcp" / "server.py"
        tree = ast.parse(server_path.read_text())

        # Collect function-def docstrings by function name.
        docstrings: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                doc = ast.get_docstring(node)
                if doc:
                    docstrings[node.name] = doc

        # The 4 generic tools registered as MCP tools.
        generic_tools = {"search_entities", "query_entities", "update_record", "get_entity_fields"}
        for tool_name in generic_tools:
            assert tool_name in docstrings, f"No docstring found for {tool_name}"
            assert "get_entity_fields" in docstrings[tool_name], (
                f"Static docstring for {tool_name!r} does not mention get_entity_fields"
            )


class TestConstants:
    def test_all_tool_entity_map_entities_in_supported(self):
        """Every entity referenced in TOOL_ENTITY_MAP is in SUPPORTED_ENTITIES."""
        supported = set(SUPPORTED_ENTITIES)
        for tool, entities in TOOL_ENTITY_MAP.items():
            for entity in entities:
                assert entity in supported, (
                    f"Tool {tool!r} references entity {entity!r} "
                    f"which is not in SUPPORTED_ENTITIES"
                )

    def test_picklist_fields_not_empty(self):
        assert len(PICKLIST_FIELDS_TO_EXPAND) > 0

    def test_supported_entities_has_core_five(self):
        core = {"Candidate", "ClientContact", "ClientCorporation", "JobOrder", "JobSubmission"}
        assert core.issubset(set(SUPPORTED_ENTITIES))


class TestSelectFields:
    """Tests for select_fields() field curation logic."""

    def test_includes_default_fields_in_order(self):
        """DEFAULT_FIELDS for Candidate starts with id,firstName -- id must come before firstName."""
        # Provide meta with both fields present.
        meta_fields = [
            {"name": "id", "label": "ID", "type": "ID", "required": False},
            {"name": "firstName", "label": "First Name", "type": "STRING", "required": False},
            {"name": "lastName", "label": "Last Name", "type": "STRING", "required": False},
        ]
        result = select_fields("Candidate", meta_fields)
        names = [f["name"] for f in result]
        assert "id" in names
        assert "firstName" in names
        assert names.index("id") < names.index("firstName")

    def test_includes_required_fields(self):
        """A field marked required=True that is not in DEFAULT_FIELDS is still included."""
        meta_fields = [
            {"name": "customRequiredField", "label": "Some Required Field", "type": "STRING", "required": True},
        ]
        result = select_fields("Candidate", meta_fields)
        names = [f["name"] for f in result]
        assert "customRequiredField" in names

    def test_includes_picklist_fields(self):
        """employmentType is in PICKLIST_FIELDS_TO_EXPAND; it must be included for Note entity."""
        assert "employmentType" in PICKLIST_FIELDS_TO_EXPAND
        meta_fields = [
            {"name": "employmentType", "label": "Employment Type", "type": "STRING", "required": False,
             "options": [{"value": "Contract", "label": "Contract"}]},
        ]
        result = select_fields("Note", meta_fields)
        names = [f["name"] for f in result]
        assert "employmentType" in names

    def test_includes_configured_custom_field(self):
        """A custom field with a human-readable label different from its name is included."""
        meta_fields = [
            {"name": "customText41", "label": "Candidate Source - This Placement", "type": "STRING", "required": False},
        ]
        result = select_fields("Candidate", meta_fields)
        names = [f["name"] for f in result]
        assert "customText41" in names

    def test_excludes_unconfigured_custom_field(self):
        """A custom field whose label equals its name (unconfigured) is excluded."""
        meta_fields = [
            {"name": "customText40", "label": "customText40", "type": "STRING", "required": False},
        ]
        result = select_fields("Candidate", meta_fields)
        names = [f["name"] for f in result]
        assert "customText40" not in names

    def test_deduplicates_field_qualifying_under_two_rules(self):
        """A field that qualifies under both DEFAULT_FIELDS and PICKLIST_FIELDS_TO_EXPAND appears once."""
        # status is in Candidate DEFAULT_FIELDS AND in PICKLIST_FIELDS_TO_EXPAND.
        meta_fields = [
            {"name": "status", "label": "Status", "type": "STRING", "required": False,
             "options": [{"value": "Active", "label": "Active"}]},
        ]
        result = select_fields("Candidate", meta_fields)
        names = [f["name"] for f in result]
        assert names.count("status") == 1

    def test_respects_cap_priority_order(self):
        """With >MAX_FIELDS_PER_ENTITY candidates, required and DEFAULT fields are kept; excess custom fields trimmed."""
        # Build enough junk custom fields to force trimming.
        meta_fields = []
        # Add a required field not in DEFAULT_FIELDS.
        meta_fields.append({"name": "requiredField", "label": "Required Field", "type": "STRING", "required": True})
        # Add a DEFAULT_FIELDS field for Candidate.
        meta_fields.append({"name": "id", "label": "ID", "type": "ID", "required": False})
        # Fill up with many custom fields with human-readable labels.
        for i in range(60):
            meta_fields.append({
                "name": f"customText{i + 1}",
                "label": f"Human Label {i + 1}",
                "type": "STRING",
                "required": False,
            })
        result = select_fields("Candidate", meta_fields)
        assert len(result) <= MAX_FIELDS_PER_ENTITY
        names = [f["name"] for f in result]
        # High-priority fields must survive the cap.
        assert "id" in names
        assert "requiredField" in names

    def test_no_default_fields_entry_falls_through(self):
        """Note has no DEFAULT_FIELDS entry; rules 2-4 still add required/picklist/custom fields."""
        from bullhorn_mcp.client import DEFAULT_FIELDS
        assert "Note" not in DEFAULT_FIELDS

        meta_fields = [
            {"name": "commentingPerson", "label": "Commenting Person", "type": "TO_ONE", "required": True},
            {"name": "employmentType", "label": "Employment Type", "type": "STRING", "required": False,
             "options": [{"value": "Contract", "label": "Contract"}]},
            {"name": "customText5", "label": "My Custom Note Label", "type": "STRING", "required": False},
        ]
        result = select_fields("Note", meta_fields)
        names = [f["name"] for f in result]
        assert "commentingPerson" in names
        assert "employmentType" in names
        assert "customText5" in names

    def test_composite_default_fields_parsed_to_base(self):
        """Placement DEFAULT_FIELDS contains 'candidate(id,name)'; select_fields parses to 'candidate'."""
        meta_fields = [
            {"name": "candidate", "label": "Candidate", "type": "TO_ONE", "required": False},
        ]
        result = select_fields("Placement", meta_fields)
        names = [f["name"] for f in result]
        assert "candidate" in names


class TestBuildEntitySectionLevels:
    """Tests for the level parameter of build_entity_section()."""

    def test_full_level_inlines_required_and_picklist(self):
        """level='full' renders [required] markers and Valid values: for picklist fields."""
        fields = [
            {"name": "firstName", "label": "First Name", "type": "STRING", "required": True},
            {"name": "status", "label": "Status", "type": "STRING", "required": False,
             "options": [{"value": "Active", "label": "Active"}, {"value": "Inactive", "label": "Inactive"}]},
        ]
        result = build_entity_section("Candidate", fields, level="full")
        assert "[required]" in result
        assert "Valid values:" in result

    def test_compact_level_omits_picklist_and_required(self):
        """level='compact' renders no [required] and no Valid values: lines."""
        fields = [
            {"name": "firstName", "label": "First Name", "type": "STRING", "required": True},
            {"name": "status", "label": "Status", "type": "STRING", "required": False,
             "options": [{"value": "Active", "label": "Active"}]},
        ]
        result = build_entity_section("Candidate", fields, level="compact")
        assert "[required]" not in result
        assert "Valid values:" not in result

    def test_compact_level_renders_default_fields_only(self):
        """level='compact' only renders fields present in DEFAULT_FIELDS for the entity.

        'occupation' is in Candidate DEFAULT_FIELDS; 'someOtherField' is not.
        """
        fields = [
            {"name": "occupation", "label": "Occupation", "type": "STRING", "required": False},
            {"name": "someOtherField", "label": "Some Other Field", "type": "STRING", "required": False},
        ]
        result = build_entity_section("Candidate", fields, level="compact")
        assert "`occupation`" in result
        assert "someOtherField" not in result

    def test_compact_level_still_has_header(self):
        """level='compact' still emits the ### <Entity> fields header."""
        result = build_entity_section("Candidate", [], level="compact")
        assert "### Candidate fields" in result

    def test_default_level_is_full(self):
        """Calling build_entity_section without level= should equal calling with level='full'."""
        fields = [
            {"name": "firstName", "label": "First Name", "type": "STRING", "required": True},
            {"name": "status", "label": "Status", "type": "STRING", "required": False,
             "options": [{"value": "Active", "label": "Active"}]},
        ]
        result_default = build_entity_section("Candidate", fields)
        result_full = build_entity_section("Candidate", fields, level="full")
        assert result_default == result_full
