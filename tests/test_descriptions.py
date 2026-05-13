"""Tests for dynamic tool description enrichment at startup."""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from bullhorn_mcp.descriptions import (
    build_entity_section,
    enrich_tool_descriptions,
    PICKLIST_FIELDS_TO_EXPAND,
    TOOL_ENTITY_MAP,
    SUPPORTED_ENTITIES,
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
