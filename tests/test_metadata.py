"""Tests for BullhornMetadata field metadata and label resolution."""

import pytest
from unittest.mock import Mock
from bullhorn_mcp.metadata import BullhornMetadata


# Sample meta API response for ClientContact
SAMPLE_META_RESPONSE = {
    "entity": "ClientContact",
    "label": "Contact",
    "fields": [
        {"name": "id", "label": "Contact ID", "type": "ID", "required": False},
        {"name": "firstName", "label": "First Name", "type": "STRING", "required": True},
        {"name": "lastName", "label": "Last Name", "type": "STRING", "required": True},
        {"name": "email", "label": "Email", "type": "STRING", "required": False},
        {"name": "recruiterUserID", "label": "Consultant", "type": "TO_ONE", "required": True},
        {"name": "clientCorporation", "label": "Company", "type": "TO_ONE", "required": True},
        {"name": "customText1", "label": "Custom Text 1", "type": "STRING", "required": False},
    ],
}


@pytest.fixture
def mock_client():
    client = Mock()
    client.get_meta.return_value = SAMPLE_META_RESPONSE
    return client


@pytest.fixture
def metadata(mock_client):
    return BullhornMetadata(mock_client)


class TestGetFields:
    def test_get_fields_parses_response(self, metadata):
        """Returns a list of dicts with expected keys."""
        fields = metadata.get_fields("ClientContact")

        assert isinstance(fields, list)
        assert len(fields) == 7

        consultant_field = next(f for f in fields if f["name"] == "recruiterUserID")
        assert consultant_field == {
            "name": "recruiterUserID",
            "label": "Consultant",
            "type": "TO_ONE",
            "required": True,
        }

    def test_get_fields_caches_result(self, metadata, mock_client):
        """Second call uses cache, not a second HTTP request."""
        metadata.get_fields("ClientContact")
        metadata.get_fields("ClientContact")

        mock_client.get_meta.assert_called_once()

    def test_get_fields_different_entities_cached_separately(self, metadata, mock_client):
        """Separate entities each trigger their own meta request."""
        mock_client.get_meta.return_value = {"fields": [{"name": "id", "label": "ID", "type": "ID", "required": False}]}
        metadata.get_fields("ClientContact")
        metadata.get_fields("ClientCorporation")

        assert mock_client.get_meta.call_count == 2

    def test_get_fields_excludes_fields_without_name(self, mock_client):
        """Fields missing a name key are excluded from results."""
        mock_client.get_meta.return_value = {
            "fields": [
                {"name": "id", "label": "ID", "type": "ID", "required": False},
                {"label": "No Name Field", "type": "STRING"},  # should be excluded
            ]
        }
        metadata = BullhornMetadata(mock_client)
        fields = metadata.get_fields("ClientContact")
        assert len(fields) == 1
        assert fields[0]["name"] == "id"


class TestResolveLabelToApi:
    def test_resolve_label_to_api(self, metadata):
        """'Consultant' resolves to 'recruiterUserID'."""
        assert metadata.resolve_label_to_api("ClientContact", "Consultant") == "recruiterUserID"

    def test_resolve_label_case_insensitive(self, metadata):
        """Resolution is case-insensitive."""
        assert metadata.resolve_label_to_api("ClientContact", "consultant") == "recruiterUserID"
        assert metadata.resolve_label_to_api("ClientContact", "CONSULTANT") == "recruiterUserID"

    def test_resolve_label_not_found_returns_none(self, metadata):
        """Unknown label returns None."""
        assert metadata.resolve_label_to_api("ClientContact", "NonExistentLabel") is None


class TestResolveApiToLabel:
    def test_resolve_api_to_label(self, metadata):
        """'clientCorporation' resolves to 'Company'."""
        assert metadata.resolve_api_to_label("ClientContact", "clientCorporation") == "Company"

    def test_resolve_api_not_found_returns_none(self, metadata):
        """Unknown API name returns None."""
        assert metadata.resolve_api_to_label("ClientContact", "nonExistentField") is None


class TestResolveFields:
    def test_resolve_fields_label_key(self, metadata):
        """A label key is replaced with its API name."""
        result = metadata.resolve_fields("ClientContact", {"Consultant": {"id": 42}})
        assert "recruiterUserID" in result
        assert result["recruiterUserID"] == {"id": 42}
        assert "Consultant" not in result

    def test_resolve_fields_api_key_passes_through(self, metadata):
        """An existing API name key passes through unchanged."""
        result = metadata.resolve_fields("ClientContact", {"firstName": "Alice"})
        assert result["firstName"] == "Alice"

    def test_resolve_fields_mixed_keys(self, metadata):
        """Dict with one label and one API name both resolve correctly."""
        result = metadata.resolve_fields(
            "ClientContact",
            {"Consultant": {"id": 42}, "firstName": "Alice"},
        )
        assert result["recruiterUserID"] == {"id": 42}
        assert result["firstName"] == "Alice"

    def test_resolve_fields_unknown_key_passes_through(self, metadata):
        """Unknown keys (not a label or API name) pass through unchanged."""
        result = metadata.resolve_fields("ClientContact", {"unknownField": "value"})
        assert result["unknownField"] == "value"


class TestSprint8FieldAliases:
    def test_resolve_fields_job_title_alias(self, metadata, mock_client):
        """'job title' resolves to 'occupation' via FIELD_ALIASES before metadata lookup.

        This alias exists because Bullhorn ClientContact has two fields that callers
        confuse: `title` (salutation: Mr/Ms/Dr) and `occupation` (job title). The alias
        ensures "job title" maps to the correct API field without requiring a metadata
        round-trip, since Bullhorn's meta API does not reliably label `occupation` as
        "Job Title".
        """
        result = metadata.resolve_fields("ClientContact", {"job title": "VP of Engineering"})
        assert result == {"occupation": "VP of Engineering"}
        # Alias is resolved before metadata, so no meta call is needed
        mock_client.get_meta.assert_not_called()

    def test_resolve_fields_job_title_alias_case_insensitive(self, metadata, mock_client):
        """Alias lookup is case-insensitive."""
        result = metadata.resolve_fields("ClientContact", {"Job Title": "Director"})
        assert result == {"occupation": "Director"}
        mock_client.get_meta.assert_not_called()

    def test_resolve_fields_title_passes_through(self, metadata):
        """'title' (salutation) passes through unchanged when no label matches it.

        Callers who genuinely want to set the salutation (Mr, Ms, Dr) should use
        the raw API name 'title'. This test confirms the alias does NOT intercept
        the raw key 'title' — only the natural-language phrase 'job title'.
        """
        # SAMPLE_META_RESPONSE has no label named "title", so it passes through as-is
        result = metadata.resolve_fields("ClientContact", {"title": "Mr"})
        assert result == {"title": "Mr"}

    def test_resolve_fields_alias_does_not_affect_other_entities(self, mock_client):
        """FIELD_ALIASES for ClientContact do not bleed into other entity types."""
        mock_client.get_meta.return_value = {"fields": [
            {"name": "id", "label": "ID", "type": "ID", "required": False},
        ]}
        meta = BullhornMetadata(mock_client)
        result = meta.resolve_fields("ClientCorporation", {"job title": "some value"})
        # No alias for ClientCorporation — falls through to metadata lookup which finds nothing
        assert result == {"job title": "some value"}


class TestSprint9FieldAudit:
    """CR2: Verify resolve_fields never injects keys beyond what the caller provides."""

    def test_resolve_fields_department_passes_through_unchanged(self, metadata):
        """'department' is not a valid ClientContact field — passes through as-is.

        CR2 identified 'department' being sent to Bullhorn during contact creation,
        causing API rejections. The correct ClientContact field for organisational
        grouping is 'division'. This test confirms resolve_fields does not silently
        map 'department' to anything — it passes through unchanged so Bullhorn
        returns a clear error to the caller rather than silently doing the wrong thing.
        If 'department' → 'division' becomes a confirmed real-world alias need, a
        FIELD_ALIASES entry should be added at that point (not speculatively).
        """
        # SAMPLE_META_RESPONSE has no label "department", so it passes through as-is
        result = metadata.resolve_fields("ClientContact", {"department": "Engineering"})
        assert result == {"department": "Engineering"}

    def test_resolve_fields_does_not_add_keys(self, metadata):
        """resolve_fields output has exactly the same number of keys as input.

        The function must never add keys that were not in the caller's input dict —
        regardless of what Bullhorn's metadata contains.
        """
        input_fields = {"firstName": "Jane", "lastName": "Doe"}
        result = metadata.resolve_fields("ClientContact", input_fields)
        assert set(result.keys()) == {"firstName", "lastName"}

    def test_resolve_fields_does_not_add_keys_for_corporation(self, mock_client):
        """Same key-count guarantee holds for ClientCorporation."""
        mock_client.get_meta.return_value = {"fields": [
            {"name": "name", "label": "Name", "type": "STRING", "required": True},
            {"name": "status", "label": "Status", "type": "STRING", "required": False},
            {"name": "phone", "label": "Phone", "type": "STRING", "required": False},
        ]}
        meta = BullhornMetadata(mock_client)
        input_fields = {"name": "Acme"}
        result = meta.resolve_fields("ClientCorporation", input_fields)
        assert set(result.keys()) == {"name"}


def test_resolve_fields_joborder_published_description_alias(metadata, mock_client):
    result = metadata.resolve_fields("JobOrder", {"published description": "External posting text"})
    assert result == {"publicDescription": "External posting text"}
    mock_client.get_meta.assert_not_called()


def test_resolve_fields_joborder_public_description_alias(metadata, mock_client):
    result = metadata.resolve_fields("JobOrder", {"public description": "External posting text"})
    assert result == {"publicDescription": "External posting text"}
    mock_client.get_meta.assert_not_called()


def test_resolve_fields_joborder_publish_on_website_alias(metadata, mock_client):
    result = metadata.resolve_fields("JobOrder", {"publish on website": "Yes"})
    assert result == {"customText12": "Yes"}
    mock_client.get_meta.assert_not_called()


def test_joborder_aliases_do_not_affect_client_contact(metadata):
    result = metadata.resolve_fields("ClientContact", {"published description": "External posting text"})
    assert result == {"published description": "External posting text"}


class TestSprint2E2E:
    def test_sprint2_e2e_full_resolution_cycle(self, metadata):
        """Full round-trip: get fields, resolve label->api, resolve api->label."""
        fields = metadata.get_fields("ClientContact")
        assert any(f["name"] == "recruiterUserID" for f in fields)

        api_name = metadata.resolve_label_to_api("ClientContact", "Consultant")
        assert api_name == "recruiterUserID"

        label = metadata.resolve_api_to_label("ClientContact", api_name)
        assert label == "Consultant"
