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


class TestSprint2E2E:
    def test_sprint2_e2e_full_resolution_cycle(self, metadata):
        """Full round-trip: get fields, resolve label->api, resolve api->label."""
        fields = metadata.get_fields("ClientContact")
        assert any(f["name"] == "recruiterUserID" for f in fields)

        api_name = metadata.resolve_label_to_api("ClientContact", "Consultant")
        assert api_name == "recruiterUserID"

        label = metadata.resolve_api_to_label("ClientContact", api_name)
        assert label == "Consultant"
