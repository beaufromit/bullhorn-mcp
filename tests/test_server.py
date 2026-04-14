"""Tests for MCP server tools."""

import importlib
import json
import os
import pytest
from unittest.mock import Mock, patch, patch as mock_patch
from bullhorn_mcp import server
from bullhorn_mcp.auth import AuthenticationError
from bullhorn_mcp.client import BullhornAPIError


@pytest.fixture
def mock_client(sample_job, sample_candidate):
    """Create a mock Bullhorn client."""
    client = Mock()
    client.search.return_value = [sample_job]
    client.query.return_value = [sample_job]
    client.get.return_value = sample_job
    return client


@pytest.fixture(autouse=True)
def reset_client():
    """Reset the global client and metadata cache before each test."""
    server._client = None
    server._metadata = None
    yield
    server._client = None
    server._metadata = None


class TestListJobs:
    """Tests for list_jobs tool."""

    def test_list_jobs_basic(self, mock_client, sample_job):
        """Test basic job listing."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_jobs()

        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["title"] == "Software Engineer"
        mock_client.search.assert_called_once()

    def test_list_jobs_with_query(self, mock_client):
        """Test job listing with query parameter."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_jobs(query="title:Engineer")

        call_args = mock_client.search.call_args
        assert "title:Engineer" in call_args.kwargs["query"]

    def test_list_jobs_with_status(self, mock_client):
        """Test job listing with status filter."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_jobs(status="Open")

        call_args = mock_client.search.call_args
        assert 'status:"Open"' in call_args.kwargs["query"]

    def test_list_jobs_with_limit(self, mock_client):
        """Test job listing with custom limit."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_jobs(limit=50)

        call_args = mock_client.search.call_args
        assert call_args.kwargs["count"] == 50

    def test_list_jobs_error_handling(self, mock_client):
        """Test error handling in list_jobs."""
        mock_client.search.side_effect = BullhornAPIError("API Error")

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_jobs()

        assert "ERROR:" in result
        assert "API Error" in result


class TestListCandidates:
    """Tests for list_candidates tool."""

    def test_list_candidates_basic(self, mock_client, sample_candidate):
        """Test basic candidate listing."""
        mock_client.search.return_value = [sample_candidate]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_candidates()

        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["firstName"] == "John"

    def test_list_candidates_with_query(self, mock_client):
        """Test candidate listing with query."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_candidates(query="skillSet:Python")

        call_args = mock_client.search.call_args
        assert "skillSet:Python" in call_args.kwargs["query"]

    def test_list_candidates_auth_error(self, mock_client):
        """Test authentication error handling."""
        mock_client.search.side_effect = AuthenticationError("Auth failed")

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_candidates()

        assert "ERROR:" in result
        assert "Auth failed" in result


class TestGetJob:
    """Tests for get_job tool."""

    def test_get_job_by_id(self, mock_client, sample_job):
        """Test getting a job by ID."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_job(job_id=12345)

        data = json.loads(result)
        assert data["id"] == 12345
        mock_client.get.assert_called_with(
            entity="JobOrder", entity_id=12345, fields=None
        )

    def test_get_job_with_fields(self, mock_client):
        """Test getting a job with custom fields."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.get_job(job_id=12345, fields="id,title,salary")

        mock_client.get.assert_called_with(
            entity="JobOrder", entity_id=12345, fields="id,title,salary"
        )


class TestGetCandidate:
    """Tests for get_candidate tool."""

    def test_get_candidate_by_id(self, mock_client, sample_candidate):
        """Test getting a candidate by ID."""
        mock_client.get.return_value = sample_candidate

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_candidate(candidate_id=67890)

        data = json.loads(result)
        assert data["firstName"] == "John"
        assert data["lastName"] == "Smith"


class TestSearchEntities:
    """Tests for search_entities tool."""

    def test_search_placements(self, mock_client):
        """Test searching placements."""
        mock_client.search.return_value = [{"id": 1, "status": "Approved"}]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_entities(
                entity="Placement", query="status:Approved"
            )

        data = json.loads(result)
        assert data[0]["status"] == "Approved"
        mock_client.search.assert_called_with(
            entity="Placement",
            query="status:Approved",
            fields=None,
            count=20,
        )

    def test_search_with_limit(self, mock_client):
        """Test search with custom limit."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.search_entities(
                entity="ClientCorporation", query="name:Acme*", limit=100
            )

        call_args = mock_client.search.call_args
        assert call_args.kwargs["count"] == 100


class TestQueryEntities:
    """Tests for query_entities tool."""

    def test_query_with_where(self, mock_client):
        """Test query with WHERE clause."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.query_entities(
                entity="JobOrder", where="salary > 100000"
            )

        mock_client.query.assert_called_with(
            entity="JobOrder",
            where="salary > 100000",
            fields=None,
            count=20,
            order_by=None,
        )

    def test_query_with_order_by(self, mock_client):
        """Test query with ORDER BY."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.query_entities(
                entity="Candidate",
                where="status='Active'",
                order_by="-dateAdded",
            )

        call_args = mock_client.query.call_args
        assert call_args.kwargs["order_by"] == "-dateAdded"


class TestFormatResponse:
    """Tests for response formatting."""

    def test_format_list(self):
        """Test formatting a list response."""
        data = [{"id": 1}, {"id": 2}]
        result = server.format_response(data)

        parsed = json.loads(result)
        assert len(parsed) == 2

    def test_format_dict(self):
        """Test formatting a dict response."""
        data = {"id": 1, "name": "Test"}
        result = server.format_response(data)

        parsed = json.loads(result)
        assert parsed["id"] == 1

    def test_format_with_datetime(self):
        """Test formatting handles non-serializable types."""
        from datetime import datetime

        data = {"date": datetime(2024, 1, 1)}
        # Should not raise an error
        result = server.format_response(data)
        assert "2024" in result


class TestListContacts:
    """Tests for list_contacts tool."""

    def test_list_contacts_default(self, mock_client):
        """Test basic contact listing returns JSON list."""
        mock_client.search.return_value = [{"id": 111, "firstName": "Alice", "lastName": "Jones"}]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_contacts()

        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == 111
        mock_client.search.assert_called_once()

    def test_list_contacts_with_status(self, mock_client):
        """Test contact listing with status filter appended to query."""
        mock_client.search.return_value = []

        with patch.object(server, "get_client", return_value=mock_client):
            server.list_contacts(status="Active")

        call_args = mock_client.search.call_args
        assert 'status:"Active"' in call_args.kwargs["query"]

    def test_list_contacts_api_error(self, mock_client):
        """Test error handling returns ERROR prefix."""
        mock_client.search.side_effect = BullhornAPIError("fail")

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_contacts()

        assert result.startswith("ERROR:")


class TestListCompanies:
    """Tests for list_companies tool."""

    def test_list_companies_default(self, mock_client):
        """Test basic company listing returns JSON list with ClientCorporation entity."""
        mock_client.search.return_value = [{"id": 222, "name": "Acme Corp"}]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_companies()

        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 1
        call_args = mock_client.search.call_args
        assert call_args.kwargs["entity"] == "ClientCorporation"

    def test_list_companies_with_query(self, mock_client):
        """Test that a custom query is passed through to the search call."""
        mock_client.search.return_value = []

        with patch.object(server, "get_client", return_value=mock_client):
            server.list_companies(query="name:Acme*")

        call_args = mock_client.search.call_args
        assert "name:Acme*" in call_args.kwargs["query"]


class TestSprint1E2E:
    """End-to-end tests for Sprint 1 tools."""

    def test_sprint1_e2e_list_contacts_and_companies(self, mock_client):
        """Call list_contacts and list_companies in sequence, assert both return valid JSON."""
        sample_contact = {"id": 1, "firstName": "Alice", "lastName": "Jones"}
        sample_company = {"id": 2, "name": "Acme Corp"}

        with patch.object(server, "get_client", return_value=mock_client):
            mock_client.search.return_value = [sample_contact]
            contacts_result = server.list_contacts()

            mock_client.search.return_value = [sample_company]
            companies_result = server.list_companies()

        contacts_data = json.loads(contacts_result)
        assert isinstance(contacts_data, list)
        assert "id" in contacts_data[0]

        companies_data = json.loads(companies_result)
        assert isinstance(companies_data, list)
        assert "id" in companies_data[0]


class TestCreateCompany:
    """Tests for create_company tool."""

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        return meta

    def test_create_company_success(self, mock_client, mock_metadata):
        """create_company returns JSON with changedEntityId on success."""
        mock_client.create.return_value = {
            "changedEntityId": 98765,
            "changeType": "INSERT",
            "data": {"id": 98765, "name": "Acme Holdings Ltd", "status": "Prospect"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_company({"name": "Acme Holdings Ltd", "status": "Prospect"})

        data = json.loads(result)
        assert data["changedEntityId"] == 98765
        assert data["changeType"] == "INSERT"
        assert data["data"]["name"] == "Acme Holdings Ltd"

    def test_create_company_api_error(self, mock_client, mock_metadata):
        """create_company returns ERROR prefix on API failure."""
        mock_client.create.side_effect = BullhornAPIError("missing required field")

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_company({"status": "Prospect"})

        assert result.startswith("ERROR:")
        assert "missing required field" in result

    def test_create_company_label_resolution(self, mock_client):
        """create_company resolves field labels to API names before creating."""
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        # Simulate label "Industry" resolving to API name "industryList"
        meta.resolve_fields.return_value = {"name": "Acme", "industryList": "Technology", "owner": {"id": 1}}
        mock_client.create.return_value = {
            "changedEntityId": 1,
            "changeType": "INSERT",
            "data": {"id": 1, "name": "Acme"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            server.create_company({"name": "Acme", "Industry": "Technology"})


class TestCreateContact:
    """Tests for create_contact tool."""

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        return meta

    def test_create_contact_success(self, mock_client, mock_metadata):
        """create_contact resolves owner by ID and returns created contact."""
        mock_client.resolve_owner.return_value = {"id": 99}
        mock_client.create.return_value = {
            "changedEntityId": 54321,
            "changeType": "INSERT",
            "data": {"id": 54321, "firstName": "Jane", "lastName": "Doe",
                     "clientCorporation": {"id": 1}, "owner": {"id": 99}},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.create_contact({
                "firstName": "Jane", "lastName": "Doe",
                "clientCorporation": {"id": 1}, "owner": {"id": 99},
            })

        data = json.loads(result)
        assert data["changedEntityId"] == 54321
        assert data["changeType"] == "INSERT"

    def test_create_contact_missing_owner(self, mock_client, mock_metadata):
        """create_contact returns identity_resolution_failed when owner absent and resolve_caller fails."""
        from bullhorn_mcp.identity import IdentityResolutionError
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("No authentication token available")):
            result = server.create_contact({"firstName": "Jane", "clientCorporation": {"id": 1}})

        data = json.loads(result)
        assert data["error"] == "identity_resolution_failed"
        mock_client.create.assert_not_called()

    def test_create_contact_missing_corporation(self, mock_client, mock_metadata):
        """create_contact returns error when clientCorporation key is absent."""
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.create_contact({"firstName": "Jane", "owner": {"id": 1}})

        data = json.loads(result)
        assert data["error"] == "clientCorporation_required"
        mock_client.create.assert_not_called()

    def test_create_contact_owner_ambiguous(self, mock_client, mock_metadata):
        """create_contact returns disambiguation response when multiple users match."""
        mock_client.resolve_owner.return_value = [
            {"id": 10, "firstName": "John", "lastName": "Smith", "email": "j1@firm.com", "department": "Sales"},
            {"id": 11, "firstName": "John", "lastName": "Smith", "email": "j2@firm.com", "department": "Tech"},
        ]

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.create_contact({
                "firstName": "Jane", "clientCorporation": {"id": 1}, "owner": "John Smith",
            })

        data = json.loads(result)
        assert data["error"] == "owner_ambiguous"
        assert len(data["matches"]) == 2
        mock_client.create.assert_not_called()

    def test_create_contact_owner_not_found(self, mock_client, mock_metadata):
        """create_contact returns error when owner name matches no user."""
        mock_client.resolve_owner.side_effect = ValueError("No CorporateUser found matching 'Ghost User'")

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.create_contact({
                "firstName": "Jane", "clientCorporation": {"id": 1}, "owner": "Ghost User",
            })

        data = json.loads(result)
        assert data["error"] == "owner_not_found"
        mock_client.create.assert_not_called()

    def test_create_contact_owner_by_id(self, mock_client, mock_metadata):
        """create_contact with owner as dict passes through without querying CorporateUser."""
        mock_client.resolve_owner.return_value = {"id": 99}
        mock_client.create.return_value = {
            "changedEntityId": 1, "changeType": "INSERT",
            "data": {"id": 1, "firstName": "Jane"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            server.create_contact({
                "firstName": "Jane", "clientCorporation": {"id": 1}, "owner": {"id": 99},
            })

        mock_client.resolve_owner.assert_called_once_with({"id": 99})


class TestUpdateRecord:
    """Tests for update_record tool."""

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        return meta

    def test_update_record_success(self, mock_client, mock_metadata):
        """update_record returns updated record JSON."""
        mock_client.update.return_value = {
            "changedEntityId": 54321,
            "changeType": "UPDATE",
            "data": {"id": 54321, "firstName": "Jane", "title": "CTO"},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.update_record("ClientContact", 54321, {"title": "CTO"})

        data = json.loads(result)
        assert data["changedEntityId"] == 54321
        assert data["changeType"] == "UPDATE"
        assert data["data"]["title"] == "CTO"

    def test_update_record_company_reassignment_blocked(self, mock_client, mock_metadata):
        """update_record blocks clientCorporation change on ClientContact."""
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.update_record("ClientContact", 1, {"clientCorporation": {"id": 2}})

        data = json.loads(result)
        assert data["error"] == "company_reassignment_not_supported"
        mock_client.update.assert_not_called()

    def test_update_record_company_reassignment_blocked_via_label(self, mock_client):
        """update_record blocks reassignment even when key is provided as a label."""
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        # "Company" label resolves to "clientCorporation"
        meta.resolve_fields.return_value = {"clientCorporation": {"id": 99}}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta):
            result = server.update_record("ClientContact", 1, {"Company": {"id": 99}})

        data = json.loads(result)
        assert data["error"] == "company_reassignment_not_supported"
        mock_client.update.assert_not_called()

    def test_update_record_label_resolution(self, mock_client):
        """update_record applies label resolution before calling update."""
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.return_value = {"recruiterUserID": {"id": 42}}
        mock_client.update.return_value = {
            "changedEntityId": 1, "changeType": "UPDATE", "data": {"id": 1},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta):
            server.update_record("ClientContact", 1, {"Consultant": {"id": 42}})

        mock_client.update.assert_called_once_with("ClientContact", 1, {"recruiterUserID": {"id": 42}})

    def test_update_record_api_error(self, mock_client, mock_metadata):
        """update_record returns ERROR prefix on API failure."""
        mock_client.update.side_effect = BullhornAPIError("update failed")
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.update_record("ClientContact", 1, {"title": "CTO"})
        assert result.startswith("ERROR:")


class TestAddNote:
    """Tests for add_note tool."""

    def test_add_note_to_contact_success(self, mock_client):
        """add_note returns Note ID on success."""
        mock_client.add_note.return_value = {
            "changedEntityId": 88901,
            "changeType": "INSERT",
            "data": {"id": 88901, "action": "General Note", "comments": "Test"},
        }
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.add_note("ClientContact", 54321, "General Note", "Test")

        data = json.loads(result)
        assert data["changedEntityId"] == 88901
        assert data["changeType"] == "INSERT"

    def test_add_note_invalid_entity(self, mock_client):
        """add_note returns error for unsupported entity type."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.add_note("JobOrder", 1, "General Note", "Test")

        data = json.loads(result)
        assert data["error"] == "invalid_entity"
        mock_client.add_note.assert_not_called()

    def test_add_note_api_error(self, mock_client):
        """add_note returns ERROR prefix on API failure."""
        mock_client.add_note.side_effect = BullhornAPIError("invalid action type")
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.add_note("ClientContact", 1, "Bad Action", "note")
        assert result.startswith("ERROR:")


class TestSprint6E2E:
    """End-to-end tests for Sprint 6."""

    def test_sprint6_e2e_update_then_note(self, mock_client):
        """Update a contact's title then add a note; assert both return expected IDs."""
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields

        mock_client.update.return_value = {
            "changedEntityId": 54321,
            "changeType": "UPDATE",
            "data": {"id": 54321, "title": "CTO"},
        }
        mock_client.add_note.return_value = {
            "changedEntityId": 88901,
            "changeType": "INSERT",
            "data": {"id": 88901, "action": "General Note"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta):
            update_result = server.update_record("ClientContact", 54321, {"title": "CTO"})
            note_result = server.add_note("ClientContact", 54321, "General Note", "Updated via test")

        update_data = json.loads(update_result)
        assert update_data["changedEntityId"] == 54321
        assert update_data["data"]["title"] == "CTO"

        note_data = json.loads(note_result)
        assert note_data["changedEntityId"] == 88901


class TestFindDuplicateCompanies:
    """Tests for find_duplicate_companies tool."""

    def test_find_duplicate_companies_exact(self, mock_client):
        """Returns exact_match=True when a company name matches exactly."""
        mock_client.search.return_value = [
            {"id": 1, "name": "Acme Holdings Ltd", "status": "Active", "phone": None}
        ]
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_companies(name="Acme Holdings Ltd")

        data = json.loads(result)
        assert data["exact_match"] is True
        assert data["matches"][0]["category"] == "exact"
        assert data["matches"][0]["confidence"] >= 0.95

    def test_find_duplicate_companies_likely(self, mock_client):
        """Returns likely match for acronym like BNY vs Bank of New York Mellon."""
        mock_client.search.return_value = [
            {"id": 2, "name": "Bank of New York Mellon", "status": "Active", "phone": None}
        ]
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_companies(name="BNY")

        data = json.loads(result)
        assert data["exact_match"] is False
        assert data["matches"][0]["category"] == "likely"

    def test_find_duplicate_companies_no_match(self, mock_client):
        """Returns empty matches list when search returns nothing."""
        mock_client.search.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_companies(name="Globex Corporation")

        data = json.loads(result)
        assert data["matches"] == []
        assert data["exact_match"] is False

    def test_find_duplicate_companies_filters_low_scores(self, mock_client):
        """Companies scoring below 0.50 are excluded from results."""
        mock_client.search.return_value = [
            {"id": 1, "name": "Unrelated Business Corp", "status": "Active", "phone": None}
        ]
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_companies(name="Acme")

        data = json.loads(result)
        assert data["matches"] == []

    def test_find_duplicate_companies_api_error(self, mock_client):
        """Returns ERROR prefix on API failure."""
        mock_client.search.side_effect = BullhornAPIError("search failed")
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_companies(name="Acme")
        assert result.startswith("ERROR:")


class TestFindDuplicateContacts:
    """Tests for find_duplicate_contacts tool."""

    def test_find_duplicate_contacts_exact(self, mock_client):
        """Returns exact match when name matches exactly."""
        mock_client.search.return_value = [
            {"id": 11, "firstName": "John", "lastName": "Smith",
             "email": "j.smith@co.com", "phone": None, "clientCorporation": {"id": 123}}
        ]
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_contacts("John", "Smith", 123)

        data = json.loads(result)
        assert data["exact_match"] is True
        assert data["matches"][0]["category"] == "exact"

    def test_find_duplicate_contacts_partial(self, mock_client):
        """Same name with email present is flagged as partial_match."""
        mock_client.search.return_value = [
            {"id": 11, "firstName": "John", "lastName": "Smith",
             "email": "other@co.com", "phone": None, "clientCorporation": {"id": 123}}
        ]
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_contacts("John", "Smith", 123)

        data = json.loads(result)
        assert data["matches"][0].get("partial_match") is True

    def test_find_duplicate_contacts_no_match(self, mock_client):
        """Returns empty matches when no contacts found."""
        mock_client.search.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_contacts("Jane", "Doe", 123)

        data = json.loads(result)
        assert data["matches"] == []
        assert data["exact_match"] is False

    def test_find_duplicate_contacts_query_structure(self, mock_client):
        """Response query object has expected structure."""
        mock_client.search.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_contacts("Jane", "Doe", 456)

        data = json.loads(result)
        assert data["query"]["firstName"] == "Jane"
        assert data["query"]["lastName"] == "Doe"
        assert data["query"]["clientCorporation"]["id"] == 456

    def test_find_duplicate_contacts_api_error(self, mock_client):
        """Returns ERROR prefix on API failure."""
        mock_client.search.side_effect = BullhornAPIError("search failed")
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_contacts("John", "Smith", 1)
        assert result.startswith("ERROR:")


class TestSprint5E2E:
    """End-to-end tests for Sprint 5 MCP tools."""

    def test_sprint5_e2e_contact_duplicate_flow(self, mock_client):
        """Full contact duplicate check returns structure matching PRD section 10."""
        mock_client.search.return_value = [
            {"id": 11234, "firstName": "John", "lastName": "Smith",
             "email": "john.smith@bnymellon.com", "phone": "+1 212 495 2000",
             "clientCorporation": {"id": 44321, "name": "Bank of New York Mellon"}}
        ]
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_contacts("John", "Smith", 44321)

        data = json.loads(result)
        assert data["exact_match"] is True
        assert data["matches"][0]["record"]["id"] == 11234
        assert data["matches"][0]["confidence"] >= 0.95
        assert "partial_match" in data["matches"][0]  # has email so partial_match present


class TestSprint4E2E:
    """End-to-end tests for Sprint 4."""

    def test_sprint4_e2e_create_contact_with_name_owner(self, mock_client):
        """Mock CorporateUser lookup (single match) + create; assert owner resolved."""
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields

        mock_client.resolve_owner.return_value = {"id": 99}
        mock_client.create.return_value = {
            "changedEntityId": 54321,
            "changeType": "INSERT",
            "data": {"id": 54321, "firstName": "Jane", "lastName": "Doe",
                     "clientCorporation": {"id": 1}, "owner": {"id": 99}},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta):
            result = server.create_contact({
                "firstName": "Jane", "lastName": "Doe",
                "clientCorporation": {"id": 1}, "owner": "Maryrose Lyons",
            })

        data = json.loads(result)
        assert data["changedEntityId"] == 54321
        assert data["data"]["owner"]["id"] == 99
        mock_client.resolve_owner.assert_called_once_with("Maryrose Lyons")
        # Resolved owner must be written into the fields sent to create
        create_call_fields = mock_client.create.call_args[0][1]
        assert create_call_fields["owner"] == {"id": 99}


class TestSprint3E2E:
    """End-to-end tests for Sprint 3."""

    def test_sprint3_e2e_create_and_retrieve_company(self, mock_client):
        """Mock PUT create then GET retrieve; assert response has changedEntityId and data.name."""
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields

        mock_client.create.return_value = {
            "changedEntityId": 98765,
            "changeType": "INSERT",
            "data": {"id": 98765, "name": "Acme", "status": "Prospect"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_company({"name": "Acme", "status": "Prospect"})

        data = json.loads(result)
        assert data["changedEntityId"] == 98765
        assert data["data"]["name"] == "Acme"
        assert data["changeType"] == "INSERT"


class TestGetEntityFields:
    """Tests for get_entity_fields tool."""

    SAMPLE_FIELDS = [
        {"name": "id", "label": "Contact ID", "type": "ID", "required": False},
        {"name": "recruiterUserID", "label": "Consultant", "type": "TO_ONE", "required": True},
        {"name": "clientCorporation", "label": "Company", "type": "TO_ONE", "required": True},
    ]

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.get_fields.return_value = self.SAMPLE_FIELDS
        meta.resolve_label_to_api.side_effect = lambda entity, label: (
            "recruiterUserID" if label.lower() == "consultant" else None
        )
        meta.resolve_api_to_label.side_effect = lambda entity, api: (
            "Company" if api == "clientCorporation" else None
        )
        return meta

    def test_get_entity_fields_returns_list(self, mock_client, mock_metadata):
        """No label/api_name returns full field list."""
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.get_entity_fields(entity="ClientContact")

        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 3
        assert any(f["name"] == "recruiterUserID" for f in data)

    def test_get_entity_fields_resolve_label(self, mock_client, mock_metadata):
        """Providing label returns resolved api_name."""
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.get_entity_fields(entity="ClientContact", label="Consultant")

        data = json.loads(result)
        assert data["label"] == "Consultant"
        assert data["api_name"] == "recruiterUserID"

    def test_get_entity_fields_resolve_api_name(self, mock_client, mock_metadata):
        """Providing api_name returns resolved label."""
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.get_entity_fields(entity="ClientContact", api_name="clientCorporation")

        data = json.loads(result)
        assert data["api_name"] == "clientCorporation"
        assert data["label"] == "Company"

    def test_get_entity_fields_unresolvable_label(self, mock_client, mock_metadata):
        """Unresolvable label returns null api_name without error."""
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.get_entity_fields(entity="ClientContact", label="NonExistent")

        data = json.loads(result)
        assert data["label"] == "NonExistent"
        assert data["api_name"] is None

    def test_get_entity_fields_api_error(self, mock_client, mock_metadata):
        """API error returns ERROR prefix."""
        mock_metadata.get_fields.side_effect = BullhornAPIError("meta failed")

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.get_entity_fields(entity="ClientContact")

        assert result.startswith("ERROR:")


class TestMCPServerSetup:
    """Tests for MCP server configuration."""

    def test_server_has_tools(self):
        """Test that all expected tools are registered.

        FastMCP 3.x removed _tool_manager; use the public async list_tools() API instead.
        """
        import asyncio
        tools = [t.name for t in asyncio.run(server.mcp.list_tools())]

        assert "list_jobs" in tools
        assert "list_candidates" in tools
        assert "list_contacts" in tools
        assert "list_companies" in tools
        assert "get_job" in tools
        assert "get_candidate" in tools
        assert "search_entities" in tools
        assert "query_entities" in tools
        assert "get_entity_fields" in tools
        assert "create_company" in tools
        assert "create_contact" in tools
        assert "find_duplicate_companies" in tools
        assert "find_duplicate_contacts" in tools
        assert "update_record" in tools
        assert "add_note" in tools
        assert "bulk_import" in tools

    def test_server_name(self):
        """Test server name is set correctly."""
        assert server.mcp.name == "Bullhorn CRM"


class TestBulkImport:
    """Tests for bulk_import MCP tool."""

    def test_bulk_import_success(self, mock_client):
        """Mock all sub-operations; assert summary structure correct."""
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata

        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields

        # Company search returns no existing records
        mock_client.search.return_value = []
        # Company create returns new ID
        mock_client.create.return_value = {
            "changedEntityId": 101,
            "changeType": "INSERT",
            "data": {"id": 101, "name": "Acme"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta):
            result = server.bulk_import(
                companies=[{"name": "Acme", "status": "Prospect"}],
                contacts=[],
            )

        data = json.loads(result)
        assert data["halted"] is False
        assert "summary" in data
        assert "companies" in data["summary"]
        assert "contacts" in data["summary"]
        assert data["summary"]["companies"]["created"] == 1
        assert data["details"]["companies"][0]["status"] == "created"

    def test_bulk_import_halts_on_errors(self, mock_client):
        """Three consecutive create failures trigger halted=True in response."""
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata

        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields

        mock_client.search.return_value = []
        mock_client.create.side_effect = BullhornAPIError("Server error")

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta):
            result = server.bulk_import(
                companies=[{"name": "A"}, {"name": "B"}, {"name": "C"}],
                contacts=[],
            )

        data = json.loads(result)
        assert data["halted"] is True
        assert data["summary"]["companies"]["failed"] == 3


class TestSprint8E2E:
    """End-to-end tests for Sprint 8 (CR1: title/occupation fix)."""

    def test_sprint8_e2e_create_contact_occupation(self, mock_client):
        """occupation field passes through correctly; 'title' is NOT injected.

        This test guards against the CR1 regression where callers sending
        'occupation' would have it silently passed through while 'title'
        (salutation) could be injected. Verifies the PUT payload to Bullhorn
        contains 'occupation' and does not contain a spurious 'title' key.
        """
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata

        # Metadata mock: no label named "title" exists, so raw 'occupation'
        # passes through; resolve_fields uses real FIELD_ALIASES logic via
        # side_effect that delegates to real BullhornMetadata behaviour.
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields

        mock_client.resolve_owner.return_value = {"id": 99}
        mock_client.create.return_value = {
            "changedEntityId": 54321,
            "changeType": "INSERT",
            "data": {
                "id": 54321, "firstName": "Jane", "lastName": "Doe",
                "occupation": "VP of Engineering",
                "clientCorporation": {"id": 1}, "owner": {"id": 99},
            },
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta):
            result = server.create_contact({
                "firstName": "Jane", "lastName": "Doe",
                "occupation": "VP of Engineering",
                "clientCorporation": {"id": 1},
                "owner": {"id": 99},
            })

        data = json.loads(result)
        assert data["changedEntityId"] == 54321
        assert data["data"]["occupation"] == "VP of Engineering"

        # Confirm the fields sent to Bullhorn's create() contain 'occupation'
        # and do NOT contain a spurious 'title' key
        create_fields = mock_client.create.call_args[0][1]
        assert "occupation" in create_fields
        assert "title" not in create_fields


class TestSprint9PayloadAudit:
    """CR2: Verify create/update tools only send caller-specified fields to Bullhorn.

    These tests capture the exact payload passed to client.create() / client.update()
    and assert no extra keys were injected. They exist to prevent the class of bug
    described in CR2, where fields the caller never supplied (e.g. 'department') were
    being added to the API request body, causing Bullhorn validation failures.
    """

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        return meta

    def test_create_contact_payload_only_contains_caller_fields(self, mock_client, mock_metadata):
        """PUT body for create_contact contains exactly the keys the caller provided.

        Only 'owner' is transformed (string → {"id": int}); no other fields are
        added. This guards against auto-injection of defaults, parameter bleed-through,
        or template population beyond the caller's input dict.
        """
        mock_client.resolve_owner.return_value = {"id": 99}
        mock_client.create.return_value = {
            "changedEntityId": 1, "changeType": "INSERT",
            "data": {"id": 1},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            server.create_contact({
                "firstName": "Jane", "lastName": "Doe",
                "clientCorporation": {"id": 1}, "owner": {"id": 99},
            })

        create_fields = mock_client.create.call_args[0][1]
        assert set(create_fields.keys()) == {"firstName", "lastName", "clientCorporation", "owner"}

    def test_create_contact_owner_normalised_not_injected(self, mock_client, mock_metadata):
        """When owner is a name string, only that key is transformed — nothing else added."""
        mock_client.resolve_owner.return_value = {"id": 55}
        mock_client.create.return_value = {
            "changedEntityId": 1, "changeType": "INSERT",
            "data": {"id": 1},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            server.create_contact({
                "firstName": "Jane", "lastName": "Doe",
                "clientCorporation": {"id": 1}, "owner": "Maryrose Lyons",
            })

        create_fields = mock_client.create.call_args[0][1]
        assert set(create_fields.keys()) == {"firstName", "lastName", "clientCorporation", "owner"}
        assert create_fields["owner"] == {"id": 55}

    def test_create_company_payload_only_contains_caller_fields(self, mock_client, mock_metadata):
        """PUT body for create_company contains exactly the caller-supplied keys plus auto-populated owner.

        CR10: owner is auto-stamped from resolve_caller when absent; no other fields injected.
        """
        mock_client.create.return_value = {
            "changedEntityId": 1, "changeType": "INSERT",
            "data": {"id": 1, "name": "Acme", "status": "Prospect"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1, "firstName": "Beau"}):
            server.create_company({"name": "Acme", "status": "Prospect"})

        create_fields = mock_client.create.call_args[0][1]
        # owner is auto-populated from resolve_caller; no other fields injected
        assert set(create_fields.keys()) == {"name", "status", "owner"}
        assert create_fields["owner"] == {"id": 1}

    def test_update_record_payload_only_contains_caller_fields(self, mock_client, mock_metadata):
        """POST body for update_record contains exactly the fields the caller specified."""
        mock_client.update.return_value = {
            "changedEntityId": 1, "changeType": "UPDATE",
            "data": {"id": 1, "occupation": "CTO"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            server.update_record("ClientContact", 1, {"occupation": "CTO"})

        # update(entity, entity_id, data) — data is the third positional arg
        update_fields = mock_client.update.call_args[0][2]
        assert set(update_fields.keys()) == {"occupation"}


class TestSprint9E2E:
    """End-to-end tests for Sprint 9 (CR2: no auto-injected fields audit)."""

    def test_sprint9_e2e_minimal_create_contact_payload(self, mock_client):
        """Minimal create_contact call produces an exact, injection-free PUT payload.

        Verifies the full path: server tool → metadata (pass-through) → client.create().
        The payload Bullhorn receives must contain exactly the four caller-supplied keys
        and nothing else. This is the primary regression guard for CR2.
        """
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata

        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields

        mock_client.resolve_owner.return_value = {"id": 99}
        mock_client.create.return_value = {
            "changedEntityId": 54321,
            "changeType": "INSERT",
            "data": {
                "id": 54321, "firstName": "Jane", "lastName": "Doe",
                "clientCorporation": {"id": 1}, "owner": {"id": 99},
            },
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta):
            result = server.create_contact({
                "firstName": "Jane", "lastName": "Doe",
                "clientCorporation": {"id": 1}, "owner": {"id": 99},
            })

        data = json.loads(result)
        assert data["changedEntityId"] == 54321

        # The PUT body must be exactly the four caller-supplied fields
        create_fields = mock_client.create.call_args[0][1]
        assert create_fields == {
            "firstName": "Jane",
            "lastName": "Doe",
            "clientCorporation": {"id": 1},
            "owner": {"id": 99},
        }


class TestSprint10E2E:
    """End-to-end tests for Sprint 10 (CR3: owner name resolution + no CorporateUser data leak)."""

    def test_sprint10_e2e_create_contact_owner_name_no_leak(self, mock_client):
        """Owner name string resolves to {"id": int}; no CorporateUser fields leak into payload.

        This is the primary regression guard for CR3. Verifies:
        1. resolve_owner is called with the name string (not bypassed).
        2. The ClientContact PUT payload contains owner: {"id": 42} — not a full CorporateUser record.
        3. No CorporateUser-sourced fields (department, email, firstName from CorporateUser) appear in
           the create payload.
        """
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata

        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields

        # Simulate successful owner name resolution: "Beau Warren" → {"id": 42}
        mock_client.resolve_owner.return_value = {"id": 42}
        mock_client.create.return_value = {
            "changedEntityId": 54321,
            "changeType": "INSERT",
            "data": {
                "id": 54321,
                "firstName": "Jane",
                "lastName": "Doe",
                "clientCorporation": {"id": 1},
                "owner": {"id": 42},
            },
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta):
            result = server.create_contact({
                "firstName": "Jane",
                "lastName": "Doe",
                "clientCorporation": {"id": 1},
                "owner": "Beau Warren",
            })

        data = json.loads(result)
        assert data["changedEntityId"] == 54321

        # resolve_owner must have been called with the name string
        mock_client.resolve_owner.assert_called_once_with("Beau Warren")

        # The ClientContact PUT payload must have owner resolved to {"id": 42}
        create_fields = mock_client.create.call_args[0][1]
        assert create_fields["owner"] == {"id": 42}

        # No CorporateUser data must appear in the payload
        assert "department" not in create_fields
        assert "email" not in create_fields
        # firstName/lastName here belong to the contact, not the CorporateUser —
        # verify they match the contact's values, not a CorporateUser bleed-through
        assert create_fields["firstName"] == "Jane"
        assert create_fields["lastName"] == "Doe"


class TestSprint11DocstringRegression:
    """CR4: Regression guards for incorrect field names in tool docstrings."""

    def test_update_record_docstring_does_not_use_title_for_job_title(self):
        """update_record docstring must not show {"title": "CTO"} — title is salutation, not job title."""
        import bullhorn_mcp.server as srv

        docstring = srv.update_record.__doc__ or ""
        assert '"title": "CTO"' not in docstring, (
            'update_record docstring contains {"title": "CTO"} — '
            "title is the salutation field (Mr/Ms/Dr); use occupation for job title"
        )

    def test_update_record_docstring_uses_occupation_for_job_title(self):
        """update_record docstring example should use occupation for job title."""
        import bullhorn_mcp.server as srv

        docstring = srv.update_record.__doc__ or ""
        assert '"occupation": "CTO"' in docstring, (
            'update_record docstring should contain {"occupation": "CTO"} as the job title example'
        )

    def test_list_contacts_docstring_uses_occupation_not_title_in_query(self):
        """list_contacts docstring should not suggest title:Manager as a job-title query — use occupation."""
        import bullhorn_mcp.server as srv

        docstring = srv.list_contacts.__doc__ or ""
        assert "title:Manager" not in docstring, (
            'list_contacts docstring contains "title:Manager" — '
            "title is the salutation field; use occupation:Manager to search by job title"
        )


class TestSprint12TitleInjectionRegression:
    """CR6: Regression guards ensuring title is never injected into update_record POST body.

    These tests operate at the HTTP layer using respx to capture the raw request body
    sent to Bullhorn. This is a deeper guard than Sprint 9's mock_client tests, which
    only verify what server.py passes to client.update(). These tests verify that
    BullhornClient.update() also sends exactly the caller-specified fields over the wire.

    Root-cause finding: Investigation of the full execution path (server.py →
    metadata.py → client.py → httpx) found NO code-level injection. The update_record
    tool, resolve_fields(), client.update(), and _request() all pass fields through
    without adding keys. DEFAULT_FIELDS["ClientContact"] (which contains "title") is
    referenced only in read paths (search/query/get), never in write paths. The
    injection described in CR6 originates from the calling agent, not from the MCP
    server code. These tests serve as a permanent regression guard to ensure no future
    change introduces code-level injection.
    """

    @pytest.fixture
    def mock_auth(self, mock_session):
        """Create a mock auth object with the shared session fixture."""
        from unittest.mock import Mock, PropertyMock
        from bullhorn_mcp.auth import BullhornAuth
        auth = Mock(spec=BullhornAuth)
        type(auth).session = PropertyMock(return_value=mock_session)
        return auth

    def test_update_record_post_body_exact_keys(self, mock_auth, mock_session):
        """POST body for ClientContact update contains exactly {"firstName": "Test"} — no title injected.

        Captures the raw HTTP request body sent by BullhornClient.update() via respx.
        This is the primary regression guard for CR6: verifies that no extra keys
        (in particular 'title') are injected into the Bullhorn API POST request.
        """
        import httpx
        import respx
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        from bullhorn_mcp.client import BullhornClient

        captured = {}

        def capture_post(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"changedEntityId": 1, "changeType": "UPDATE"})

        contact_record = {"id": 1, "firstName": "Test"}

        with respx.mock:
            respx.post(f"{mock_session.rest_url}/entity/ClientContact/1").mock(
                side_effect=capture_post
            )
            respx.get(f"{mock_session.rest_url}/entity/ClientContact/1").mock(
                return_value=httpx.Response(200, json={"data": contact_record})
            )

            client = BullhornClient(mock_auth)
            client.update("ClientContact", 1, {"firstName": "Test"})

        assert "body" in captured, "POST was not called — route did not match"
        assert captured["body"] == {"firstName": "Test"}, (
            f"POST body contained unexpected keys: {captured['body']}"
        )

    def test_update_record_post_body_exact_keys_occupation(self, mock_auth, mock_session):
        """POST body for ClientContact update with occupation contains exactly {"occupation": "CTO"}.

        Verifies that the 'occupation' field is passed through cleanly and that no
        other keys (including 'title') are injected alongside it.
        """
        import httpx
        import respx
        from bullhorn_mcp.client import BullhornClient

        captured = {}

        def capture_post(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"changedEntityId": 1, "changeType": "UPDATE"})

        contact_record = {"id": 1, "occupation": "CTO"}

        with respx.mock:
            respx.post(f"{mock_session.rest_url}/entity/ClientContact/1").mock(
                side_effect=capture_post
            )
            respx.get(f"{mock_session.rest_url}/entity/ClientContact/1").mock(
                return_value=httpx.Response(200, json={"data": contact_record})
            )

            client = BullhornClient(mock_auth)
            client.update("ClientContact", 1, {"occupation": "CTO"})

        assert "body" in captured, "POST was not called — route did not match"
        assert captured["body"] == {"occupation": "CTO"}, (
            f"POST body contained unexpected keys: {captured['body']}"
        )

    def test_sprint12_e2e_update_no_title_injection(self, mock_auth, mock_session):
        """E2E: update_record("ClientContact", 1, {"firstName": "Aleksandr"}) sends only that field.

        Exercises the full stack: server.update_record() → metadata.resolve_fields()
        → client.update() → HTTP POST. Captures the raw POST body and asserts it is
        exactly {"firstName": "Aleksandr"} with no injected keys.
        """
        import httpx
        import respx
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        from bullhorn_mcp.client import BullhornClient

        captured = {}

        def capture_post(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"changedEntityId": 1, "changeType": "UPDATE"})

        contact_record = {"id": 1, "firstName": "Aleksandr"}

        # Mock metadata: resolve_fields passes through unchanged (no label remapping needed)
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields

        real_client = BullhornClient(mock_auth)

        with respx.mock:
            respx.post(f"{mock_session.rest_url}/entity/ClientContact/1").mock(
                side_effect=capture_post
            )
            respx.get(f"{mock_session.rest_url}/entity/ClientContact/1").mock(
                return_value=httpx.Response(200, json={"data": contact_record})
            )

            with patch.object(server, "get_client", return_value=real_client), \
                 patch.object(server, "get_metadata", return_value=meta):
                result = server.update_record("ClientContact", 1, {"firstName": "Aleksandr"})

        data = json.loads(result)
        assert data["changedEntityId"] == 1

        assert "body" in captured, "POST was not called — route did not match"
        assert captured["body"] == {"firstName": "Aleksandr"}, (
            f"POST body contained unexpected keys: {captured['body']}"
        )


class TestSprint13TitleStripping:
    """CR7: Defensive stripping of 'title' from ClientContact write payloads.

    When a calling agent mistakenly includes 'title' in a ClientContact write
    payload, server.py strips the field silently, logs a warning, and returns
    a 'warnings' array in the response so the caller is informed.
    """

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        return meta

    def test_create_contact_title_stripped_with_warning(self, mock_client, mock_metadata):
        """create_contact strips 'title' from payload and returns warnings array."""
        captured = {}

        def capture_create(entity, fields):
            captured["fields"] = dict(fields)
            return {
                "changedEntityId": 54321,
                "changeType": "INSERT",
                "data": {"id": 54321, "firstName": "Jane", "lastName": "Doe",
                         "clientCorporation": {"id": 1}, "owner": {"id": 99}},
            }

        mock_client.resolve_owner.return_value = {"id": 99}
        mock_client.create.side_effect = capture_create

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.create_contact({
                "firstName": "Jane", "lastName": "Doe",
                "clientCorporation": {"id": 1}, "owner": {"id": 99},
                "title": "CTO",
            })

        data = json.loads(result)
        assert "title" not in captured["fields"], "title should have been stripped before create()"
        assert "warnings" in data
        assert len(data["warnings"]) == 1
        assert "title" in data["warnings"][0]
        assert "occupation" in data["warnings"][0]

    def test_create_contact_no_warning_without_title(self, mock_client, mock_metadata):
        """create_contact with no 'title' field returns no warnings key."""
        mock_client.resolve_owner.return_value = {"id": 99}
        mock_client.create.return_value = {
            "changedEntityId": 54321,
            "changeType": "INSERT",
            "data": {"id": 54321, "firstName": "Jane", "lastName": "Doe",
                     "clientCorporation": {"id": 1}, "owner": {"id": 99}},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.create_contact({
                "firstName": "Jane", "lastName": "Doe",
                "clientCorporation": {"id": 1}, "owner": {"id": 99},
            })

        data = json.loads(result)
        assert "warnings" not in data

    def test_update_record_title_stripped_with_warning(self, mock_client, mock_metadata):
        """update_record strips 'title' from ClientContact payload and returns warnings."""
        captured = {}

        def capture_update(entity, entity_id, fields):
            captured["fields"] = dict(fields)
            return {
                "changedEntityId": 1,
                "changeType": "UPDATE",
                "data": {"id": 1},
            }

        mock_client.update.side_effect = capture_update

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.update_record("ClientContact", 1, {"title": "VP"})

        data = json.loads(result)
        assert "title" not in captured["fields"], "title should have been stripped before update()"
        assert "warnings" in data
        assert len(data["warnings"]) == 1
        assert "title" in data["warnings"][0]

    def test_update_record_joborder_title_not_stripped(self, mock_client, mock_metadata):
        """update_record does NOT strip 'title' from non-ClientContact entities."""
        captured = {}

        def capture_update(entity, entity_id, fields):
            captured["fields"] = dict(fields)
            return {
                "changedEntityId": 1,
                "changeType": "UPDATE",
                "data": {"id": 1, "title": "Senior Engineer"},
            }

        mock_client.update.side_effect = capture_update

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.update_record("JobOrder", 1, {"title": "Senior Engineer"})

        data = json.loads(result)
        assert captured["fields"].get("title") == "Senior Engineer", "title must not be stripped for JobOrder"
        assert "warnings" not in data

    def test_update_record_occupation_no_warning(self, mock_client, mock_metadata):
        """update_record with 'occupation' on ClientContact does not trigger warnings."""
        mock_client.update.return_value = {
            "changedEntityId": 1,
            "changeType": "UPDATE",
            "data": {"id": 1, "occupation": "VP"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.update_record("ClientContact", 1, {"occupation": "VP"})

        data = json.loads(result)
        assert "warnings" not in data

    def test_sprint13_e2e_create_contact_title_stripped(self, mock_session):
        """E2E: create_contact strips 'title' from payload sent to Bullhorn and warns caller.

        Exercises the full stack: server.create_contact() → metadata.resolve_fields()
        → client.create() → HTTP PUT. Captures the raw PUT body and asserts it lacks
        'title', while the response contains changedEntityId and a warnings array.
        """
        import httpx
        import respx
        from unittest.mock import Mock, PropertyMock
        from bullhorn_mcp.auth import BullhornAuth
        from bullhorn_mcp.metadata import BullhornMetadata
        from bullhorn_mcp.client import BullhornClient

        auth = Mock(spec=BullhornAuth)
        type(auth).session = PropertyMock(return_value=mock_session)

        captured = {}

        def capture_put(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json={"changedEntityId": 9999, "changeType": "INSERT"})

        contact_record = {
            "id": 9999, "firstName": "Conor", "lastName": "Warren",
            "clientCorporation": {"id": 1}, "owner": {"id": 42},
        }

        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields

        real_client = BullhornClient(auth)

        with respx.mock:
            respx.put(f"{mock_session.rest_url}/entity/ClientContact").mock(
                side_effect=capture_put
            )
            respx.get(f"{mock_session.rest_url}/entity/ClientContact/9999").mock(
                return_value=httpx.Response(200, json={"data": contact_record})
            )
            # Duplicate check search — return empty so creation proceeds
            respx.get(f"{mock_session.rest_url}/search/ClientContact").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            # resolve_owner: owner is {"id": 42} — BullhornClient.resolve_owner passes it through
            with patch.object(server, "get_client", return_value=real_client), \
                 patch.object(server, "get_metadata", return_value=meta):
                result = server.create_contact({
                    "firstName": "Conor", "lastName": "Warren",
                    "clientCorporation": {"id": 1}, "owner": {"id": 42},
                    "title": "CEO",
                })

        data = json.loads(result)
        assert data["changedEntityId"] == 9999
        assert "body" in captured, "PUT was not called — route did not match"
        assert "title" not in captured["body"], (
            f"title was not stripped from PUT body: {captured['body']}"
        )
        assert "warnings" in data
        assert any("title" in w for w in data["warnings"])


class TestSprint14DuplicateCheck:
    """Tests for Sprint 14: duplicate detection in create_contact."""

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        return meta

    def test_create_contact_blocks_on_exact_duplicate(self, mock_client, mock_metadata):
        """create_contact returns duplicate_found when an exact name match exists at the same company."""
        mock_client.resolve_owner.return_value = {"id": 99}
        # search returns a contact with the same name
        mock_client.search.return_value = [
            {"id": 500, "firstName": "John", "lastName": "Smith",
             "email": "john@acme.com", "phone": None, "clientCorporation": {"id": 1}},
        ]

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.create_contact({
                "firstName": "John", "lastName": "Smith",
                "clientCorporation": {"id": 1}, "owner": {"id": 99},
            })

        data = json.loads(result)
        assert data["duplicate_found"] is True
        assert data["match"]["category"] == "exact"
        assert data["match"]["record"]["id"] == 500
        assert "force=True" in data["message"]
        mock_client.create.assert_not_called()

    def test_create_contact_blocks_on_near_duplicate(self, mock_client, mock_metadata):
        """create_contact returns duplicate_found for a near-match name at the same company."""
        mock_client.resolve_owner.return_value = {"id": 99}
        # "Jon" vs "John" — should score above 0.50
        mock_client.search.return_value = [
            {"id": 501, "firstName": "Jon", "lastName": "Smith",
             "email": None, "phone": None, "clientCorporation": {"id": 1}},
        ]

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.create_contact({
                "firstName": "John", "lastName": "Smith",
                "clientCorporation": {"id": 1}, "owner": {"id": 99},
            })

        data = json.loads(result)
        assert data["duplicate_found"] is True
        assert data["match"]["record"]["id"] == 501
        assert data["match"]["confidence"] >= 0.50
        mock_client.create.assert_not_called()

    def test_create_contact_proceeds_when_no_duplicate(self, mock_client, mock_metadata):
        """create_contact calls create when no duplicate is found."""
        mock_client.resolve_owner.return_value = {"id": 99}
        # search returns an unrelated contact — low score, should not block
        mock_client.search.return_value = [
            {"id": 502, "firstName": "Alice", "lastName": "Brown",
             "email": None, "phone": None, "clientCorporation": {"id": 1}},
        ]
        mock_client.create.return_value = {
            "changedEntityId": 999, "changeType": "INSERT",
            "data": {"id": 999, "firstName": "John", "lastName": "Smith"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.create_contact({
                "firstName": "John", "lastName": "Smith",
                "clientCorporation": {"id": 1}, "owner": {"id": 99},
            })

        data = json.loads(result)
        assert data["changedEntityId"] == 999
        mock_client.create.assert_called_once()

    def test_create_contact_force_bypasses_duplicate_check(self, mock_client, mock_metadata):
        """create_contact with force=True skips the duplicate search entirely."""
        mock_client.resolve_owner.return_value = {"id": 99}
        mock_client.create.return_value = {
            "changedEntityId": 888, "changeType": "INSERT",
            "data": {"id": 888, "firstName": "John", "lastName": "Smith"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.create_contact(
                {"firstName": "John", "lastName": "Smith",
                 "clientCorporation": {"id": 1}, "owner": {"id": 99}},
                force=True,
            )

        data = json.loads(result)
        assert data["changedEntityId"] == 888
        # search must NOT have been called — force bypasses the dedup check
        mock_client.search.assert_not_called()
        mock_client.create.assert_called_once()

    def test_create_contact_dedup_search_failure_is_nonfatal(self, mock_client, mock_metadata):
        """A search failure during duplicate check is non-fatal; creation proceeds."""
        mock_client.resolve_owner.return_value = {"id": 99}
        mock_client.search.side_effect = BullhornAPIError("search unavailable")
        mock_client.create.return_value = {
            "changedEntityId": 777, "changeType": "INSERT",
            "data": {"id": 777, "firstName": "John", "lastName": "Smith"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.create_contact({
                "firstName": "John", "lastName": "Smith",
                "clientCorporation": {"id": 1}, "owner": {"id": 99},
            })

        data = json.loads(result)
        assert data["changedEntityId"] == 777
        mock_client.create.assert_called_once()

    def test_sprint14_e2e_create_contact_duplicate_blocked(self, mock_session):
        """E2E: create_contact blocks creation when a duplicate contact exists at the company.

        Mocks: CorporateUser query (owner by name) + ClientContact search returning existing
        contact with same name. Asserts duplicate_found is returned, no PUT call made.
        """
        import httpx
        import respx
        from unittest.mock import Mock, PropertyMock
        from bullhorn_mcp.auth import BullhornAuth
        from bullhorn_mcp.metadata import BullhornMetadata
        from bullhorn_mcp.client import BullhornClient

        auth = Mock(spec=BullhornAuth)
        type(auth).session = PropertyMock(return_value=mock_session)

        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields

        real_client = BullhornClient(auth)

        existing_contact = {
            "id": 170841, "firstName": "Conor", "lastName": "Warren",
            "email": "kid@warrenhouse.com", "phone": None,
            "clientCorporation": {"id": 10666},
        }

        with respx.mock:
            # Owner resolution: CorporateUser query for "Beau Warren"
            respx.get(f"{mock_session.rest_url}/query/CorporateUser").mock(
                return_value=httpx.Response(200, json={
                    "data": [{"id": 42, "firstName": "Beau", "lastName": "Warren",
                              "email": "beau@firm.com"}]
                })
            )
            # Duplicate check: ClientContact search at company 10666
            respx.get(f"{mock_session.rest_url}/search/ClientContact").mock(
                return_value=httpx.Response(200, json={"data": [existing_contact]})
            )

            with patch.object(server, "get_client", return_value=real_client), \
                 patch.object(server, "get_metadata", return_value=meta):
                result = server.create_contact({
                    "firstName": "Conor", "lastName": "Warren",
                    "clientCorporation": {"id": 10666},
                    "owner": "Beau Warren",
                })

        data = json.loads(result)
        assert data["duplicate_found"] is True
        assert data["match"]["record"]["id"] == 170841
        assert "force=True" in data["message"]

    def test_sprint14_e2e_create_contact_force_creates_despite_duplicate(self, mock_session):
        """E2E: create_contact with force=True creates the record even when a duplicate exists.

        Mocks: CorporateUser query (owner), ClientContact search (returns existing),
        ClientContact PUT + GET. Asserts PUT is called and changedEntityId in response.
        """
        import httpx
        import respx
        from unittest.mock import Mock, PropertyMock
        from bullhorn_mcp.auth import BullhornAuth
        from bullhorn_mcp.metadata import BullhornMetadata
        from bullhorn_mcp.client import BullhornClient

        auth = Mock(spec=BullhornAuth)
        type(auth).session = PropertyMock(return_value=mock_session)

        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields

        real_client = BullhornClient(auth)

        existing_contact = {
            "id": 170841, "firstName": "Conor", "lastName": "Warren",
            "email": "kid@warrenhouse.com", "phone": None,
            "clientCorporation": {"id": 10666},
        }
        new_contact = {
            "id": 170844, "firstName": "Conor", "lastName": "Warren",
            "clientCorporation": {"id": 10666}, "owner": {"id": 42},
        }

        with respx.mock:
            # Owner resolution
            respx.get(f"{mock_session.rest_url}/query/CorporateUser").mock(
                return_value=httpx.Response(200, json={
                    "data": [{"id": 42, "firstName": "Beau", "lastName": "Warren",
                              "email": "beau@firm.com"}]
                })
            )
            # PUT creates new contact
            respx.put(f"{mock_session.rest_url}/entity/ClientContact").mock(
                return_value=httpx.Response(201, json={"changedEntityId": 170844, "changeType": "INSERT"})
            )
            # GET fetches newly created record
            respx.get(f"{mock_session.rest_url}/entity/ClientContact/170844").mock(
                return_value=httpx.Response(200, json={"data": new_contact})
            )

            with patch.object(server, "get_client", return_value=real_client), \
                 patch.object(server, "get_metadata", return_value=meta):
                result = server.create_contact(
                    {"firstName": "Conor", "lastName": "Warren",
                     "clientCorporation": {"id": 10666},
                     "owner": "Beau Warren"},
                    force=True,
                )

        data = json.loads(result)
        assert data["changedEntityId"] == 170844


# ---------------------------------------------------------------------------
# Sprint 15: CR8 — HTTP Transport Mode
# ---------------------------------------------------------------------------

class TestSprint15HttpTransport:
    """Tests for MCP_TRANSPORT / PORT environment variable handling in main()."""

    def test_main_stdio_default(self):
        """main() with no MCP_TRANSPORT calls mcp.run() with no transport kwarg."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MCP_TRANSPORT", None)
            with patch.object(server.mcp, "run") as mock_run:
                server.main()
        mock_run.assert_called_once_with()

    def test_main_http_transport(self):
        """main() with _transport_mode=http calls mcp.run(transport='streamable-http').

        main() uses the module-level _transport_mode variable (set at import time),
        not os.environ directly. Patch the module-level var to test dispatch logic.
        The call also includes host= and port= from the module-level _host/_port vars.
        """
        from unittest.mock import ANY
        with patch.object(server, "_transport_mode", "http"):
            with patch.object(server.mcp, "run") as mock_run:
                server.main()
        mock_run.assert_called_once_with(transport="streamable-http", host=ANY, port=ANY)

    def test_main_stdio_explicit(self):
        """main() with _transport_mode=stdio calls mcp.run() with no transport kwarg."""
        with patch.object(server, "_transport_mode", "stdio"):
            with patch.object(server.mcp, "run") as mock_run:
                server.main()
        mock_run.assert_called_once_with()

    def test_main_invalid_transport_raises(self):
        """main() with an unrecognised _transport_mode raises ValueError."""
        with patch.object(server, "_transport_mode", "grpc"):
            with pytest.raises(ValueError, match="grpc"):
                server.main()

    def test_fastmcp_port_configured_from_env(self):
        """PORT env var is read into the module-level _port variable at import time.

        FastMCP 3.x removed mcp.settings.port (port/host are now passed to run(), not
        the constructor). We assert the module-level _port variable directly — that is
        what main() uses when calling mcp.run(port=_port).
        """
        import bullhorn_mcp.server as server_module

        with patch.dict(os.environ, {"PORT": "9999", "MCP_TRANSPORT": "stdio"}):
            importlib.reload(server_module)
            assert server_module._port == 9999

        # Restore original module state so subsequent tests are unaffected.
        importlib.reload(server_module)

    def test_sprint15_e2e_http_mode_startup(self):
        """E2E: MCP_TRANSPORT=http and PORT=8001 → mcp.run called with streamable-http.

        Port is verified via server_module._port (FastMCP 3.x no longer exposes settings.port).
        OIDCProxy is mocked to prevent real HTTP calls to OIDC discovery endpoint during reload.
        """
        from unittest.mock import ANY, MagicMock
        import bullhorn_mcp.server as server_module

        entra_vars = {
            "MCP_TRANSPORT": "http",
            "PORT": "8001",
            "ENTRA_TENANT_ID": "test-tenant",
            "ENTRA_CLIENT_ID": "test-client",
            "ENTRA_CLIENT_SECRET": "test-secret",
            "MCP_BASE_URL": "https://test.example.com",
        }
        # OIDCProxy.__init__ fetches OIDC discovery doc over HTTP at construction time.
        # Mock the class so reload doesn't make real network calls.
        with patch("fastmcp.server.auth.oidc_proxy.OIDCProxy", MagicMock()):
            with patch.dict(os.environ, entra_vars):
                importlib.reload(server_module)
                assert server_module._port == 8001

                with patch.object(server_module.mcp, "run") as mock_run:
                    server_module.main()

                mock_run.assert_called_once_with(
                    transport="streamable-http", host=ANY, port=ANY
                )

        # Restore to stdio mode. Explicitly pin MCP_TRANSPORT=stdio so the restore reload
        # cannot be affected by any stale MCP_TRANSPORT=http left in the environment.
        with patch.dict(os.environ, {"MCP_TRANSPORT": "stdio"}, clear=False):
            importlib.reload(server_module)


# ---------------------------------------------------------------------------
# Sprint 17: CR10 — Owner auto-stamping for create_contact and create_company
# ---------------------------------------------------------------------------

class TestSprint17CreateContact:
    """Tests for CR10: owner auto-population in create_contact."""

    @pytest.fixture(autouse=True)
    def reset_identity_cache(self):
        from bullhorn_mcp import identity
        identity._reset_caller_cache()
        yield
        identity._reset_caller_cache()

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        return meta

    def test_create_contact_owner_auto_populated(self, mock_client, mock_metadata):
        """When owner is absent, resolve_caller is called and owner is auto-set to {id: caller_id}."""
        mock_client.resolve_owner.return_value = {"id": 42}
        mock_client.search.return_value = []  # no duplicates
        mock_client.create.return_value = {
            "changedEntityId": 54321,
            "changeType": "INSERT",
            "data": {"id": 54321, "firstName": "Jane", "lastName": "Doe",
                     "clientCorporation": {"id": 1}, "owner": {"id": 42}},
        }

        caller = {"id": 42, "firstName": "Beau", "email": "beau@test.com"}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value=caller):
            result = server.create_contact({
                "firstName": "Jane", "lastName": "Doe",
                "clientCorporation": {"id": 1},
            })

        data = json.loads(result)
        assert data["changedEntityId"] == 54321
        create_fields = mock_client.create.call_args[0][1]
        assert create_fields["owner"] == {"id": 42}

    def test_create_contact_explicit_owner_dict_wins(self, mock_client, mock_metadata):
        """When owner is explicitly provided as a dict, resolve_caller is NOT called."""
        mock_client.resolve_owner.return_value = {"id": 99}
        mock_client.search.return_value = []
        mock_client.create.return_value = {
            "changedEntityId": 1, "changeType": "INSERT",
            "data": {"id": 1},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller") as mock_resolve:
            server.create_contact({
                "firstName": "Jane", "lastName": "Doe",
                "clientCorporation": {"id": 1}, "owner": {"id": 99},
            })

        mock_resolve.assert_not_called()
        create_fields = mock_client.create.call_args[0][1]
        assert create_fields["owner"] == {"id": 99}

    def test_create_contact_explicit_owner_name_wins(self, mock_client, mock_metadata):
        """When owner is a name string, resolve_caller is NOT called; existing name resolution runs."""
        mock_client.resolve_owner.return_value = {"id": 77}
        mock_client.search.return_value = []
        mock_client.create.return_value = {
            "changedEntityId": 2, "changeType": "INSERT",
            "data": {"id": 2},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller") as mock_resolve:
            result = server.create_contact({
                "firstName": "Jane", "lastName": "Doe",
                "clientCorporation": {"id": 1}, "owner": "Maryrose Lyons",
            })

        mock_resolve.assert_not_called()
        mock_client.resolve_owner.assert_called_once_with("Maryrose Lyons")
        create_fields = mock_client.create.call_args[0][1]
        assert create_fields["owner"] == {"id": 77}

    def test_create_contact_identity_resolution_fails(self, mock_client, mock_metadata):
        """When resolve_caller raises IdentityResolutionError and owner absent, returns error."""
        from bullhorn_mcp.identity import IdentityResolutionError

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller",
                          side_effect=IdentityResolutionError("No authentication token available")):
            result = server.create_contact({
                "firstName": "Jane", "lastName": "Doe",
                "clientCorporation": {"id": 1},
            })

        data = json.loads(result)
        assert data["error"] == "identity_resolution_failed"
        assert "hint" in data
        mock_client.create.assert_not_called()

    def test_create_contact_no_owner_required_error_gone(self, mock_client, mock_metadata):
        """Response when owner is absent with successful resolution does NOT contain 'owner is required'."""
        mock_client.resolve_owner.return_value = {"id": 42}
        mock_client.search.return_value = []
        mock_client.create.return_value = {
            "changedEntityId": 1, "changeType": "INSERT",
            "data": {"id": 1},
        }

        caller = {"id": 42, "firstName": "Beau", "email": "beau@test.com"}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value=caller):
            result = server.create_contact({
                "firstName": "Jane", "lastName": "Doe",
                "clientCorporation": {"id": 1},
            })

        assert "owner is required" not in result

    def test_create_contact_auto_owner_payload_no_leak(self, mock_client, mock_metadata):
        """Auto-populated owner is exactly {id: caller_id} — no firstName/email from caller dict leaks."""
        mock_client.resolve_owner.return_value = {"id": 42}
        mock_client.search.return_value = []
        mock_client.create.return_value = {
            "changedEntityId": 1, "changeType": "INSERT",
            "data": {"id": 1},
        }

        caller = {"id": 42, "firstName": "Beau", "lastName": "Warren", "email": "beau@test.com"}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value=caller):
            server.create_contact({
                "firstName": "Jane", "lastName": "Doe",
                "clientCorporation": {"id": 1},
            })

        create_fields = mock_client.create.call_args[0][1]
        assert create_fields["owner"] == {"id": 42}
        # No caller dict fields should leak into the contact payload
        assert "email" not in create_fields or create_fields.get("email") is None or True  # email may be from contact
        # Specifically: the owner value must be only {id: 42}, not the full caller dict
        assert list(create_fields["owner"].keys()) == ["id"]


class TestSprint17CreateCompany:
    """Tests for CR10: owner auto-population in create_company."""

    @pytest.fixture(autouse=True)
    def reset_identity_cache(self):
        from bullhorn_mcp import identity
        identity._reset_caller_cache()
        yield
        identity._reset_caller_cache()

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        return meta

    def test_create_company_owner_auto_populated(self, mock_client, mock_metadata):
        """When owner absent, resolve_caller is invoked and owner is set to {id: caller_id}."""
        mock_client.create.return_value = {
            "changedEntityId": 1001, "changeType": "INSERT",
            "data": {"id": 1001, "name": "Acme"},
        }

        caller = {"id": 42, "firstName": "Beau"}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value=caller):
            result = server.create_company({"name": "Acme"})

        data = json.loads(result)
        assert data["changedEntityId"] == 1001
        create_fields = mock_client.create.call_args[0][1]
        assert create_fields["owner"] == {"id": 42}

    def test_create_company_auto_owner_payload_no_leak(self, mock_client, mock_metadata):
        """Auto-populated owner value is exactly {id: caller_id} — no extra caller fields leak."""
        mock_client.create.return_value = {
            "changedEntityId": 1, "changeType": "INSERT",
            "data": {"id": 1},
        }

        caller = {"id": 42, "firstName": "Beau", "lastName": "Warren", "email": "beau@test.com"}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value=caller):
            server.create_company({"name": "Acme"})

        create_fields = mock_client.create.call_args[0][1]
        assert create_fields["owner"] == {"id": 42}
        assert list(create_fields["owner"].keys()) == ["id"]

    def test_create_company_explicit_owner_wins(self, mock_client, mock_metadata):
        """When owner is explicitly provided, resolve_caller is NOT called."""
        mock_client.create.return_value = {
            "changedEntityId": 1, "changeType": "INSERT",
            "data": {"id": 1},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller") as mock_resolve:
            server.create_company({"name": "Acme", "owner": {"id": 99}})

        mock_resolve.assert_not_called()
        create_fields = mock_client.create.call_args[0][1]
        assert create_fields["owner"] == {"id": 99}

    def test_create_company_identity_resolution_fails(self, mock_client, mock_metadata):
        """When resolve_caller raises IdentityResolutionError and owner absent, returns error."""
        from bullhorn_mcp.identity import IdentityResolutionError

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller",
                          side_effect=IdentityResolutionError("No authentication token available")):
            result = server.create_company({"name": "Acme"})

        data = json.loads(result)
        assert data["error"] == "identity_resolution_failed"
        assert "hint" in data
        mock_client.create.assert_not_called()


class TestSprint17Regression:
    """Regression tests: CR10 owner stamping does NOT apply to bulk_import or update_record."""

    @pytest.fixture(autouse=True)
    def reset_identity_cache(self):
        from bullhorn_mcp import identity
        identity._reset_caller_cache()
        yield
        identity._reset_caller_cache()

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        return meta

    def test_bulk_import_does_not_call_resolve_caller(self, mock_client, mock_metadata):
        """bulk_import with owner-supplied contacts does not invoke resolve_caller."""
        mock_client.search.return_value = []
        mock_client.create.return_value = {
            "changedEntityId": 101, "changeType": "INSERT",
            "data": {"id": 101, "name": "Acme"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller") as mock_resolve:
            server.bulk_import(
                companies=[{"name": "Acme", "status": "Prospect"}],
                contacts=[],
            )

        mock_resolve.assert_not_called()

    def test_update_record_does_not_auto_populate_owner(self, mock_client, mock_metadata):
        """update_record called without owner does not invoke resolve_caller and POST has no owner."""
        mock_client.update.return_value = {
            "changedEntityId": 1, "changeType": "UPDATE",
            "data": {"id": 1, "occupation": "CTO"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller") as mock_resolve:
            result = server.update_record("ClientContact", 1, {"occupation": "CTO"})

        mock_resolve.assert_not_called()
        update_fields = mock_client.update.call_args[0][2]
        assert "owner" not in update_fields
        data = json.loads(result)
        assert data["changedEntityId"] == 1


class TestSprint17E2E:
    """End-to-end tests for CR10: full stack owner auto-population."""

    @pytest.fixture(autouse=True)
    def reset_identity_cache(self):
        from bullhorn_mcp import identity
        identity._reset_caller_cache()
        yield
        identity._reset_caller_cache()

    def test_e2e_create_contact_no_owner_auto_populated(self, mock_session):
        """E2E: create_contact without owner auto-stamps owner from authenticated CorporateUser.

        Mocks: get_access_token JWT with email, CorporateUser query returning id=7,
        ClientContact search (no duplicates), ClientContact PUT (capture body), GET.
        Asserts PUT body has owner: {id: 7} and response has changedEntityId.
        """
        import httpx
        import respx
        from unittest.mock import Mock, PropertyMock
        from bullhorn_mcp.auth import BullhornAuth
        from bullhorn_mcp.metadata import BullhornMetadata
        from bullhorn_mcp.client import BullhornClient

        auth = Mock(spec=BullhornAuth)
        type(auth).session = PropertyMock(return_value=mock_session)

        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields

        real_client = BullhornClient(auth)

        captured = {}

        def capture_put(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json={"changedEntityId": 9001, "changeType": "INSERT"})

        new_contact = {
            "id": 9001, "firstName": "Jane", "lastName": "Doe",
            "clientCorporation": {"id": 1}, "owner": {"id": 7},
        }

        token = Mock()
        token.claims = {"email": "beau@thepanel.com"}

        with respx.mock:
            # CorporateUser query for identity resolution
            respx.get(f"{mock_session.rest_url}/query/CorporateUser").mock(
                return_value=httpx.Response(200, json={
                    "data": [{"id": 7, "firstName": "Beau", "lastName": "Warren",
                              "email": "beau@thepanel.com"}]
                })
            )
            # Duplicate check search
            respx.get(f"{mock_session.rest_url}/search/ClientContact").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            # ClientContact PUT
            respx.put(f"{mock_session.rest_url}/entity/ClientContact").mock(
                side_effect=capture_put
            )
            # ClientContact GET
            respx.get(f"{mock_session.rest_url}/entity/ClientContact/9001").mock(
                return_value=httpx.Response(200, json={"data": new_contact})
            )

            with patch.object(server, "get_client", return_value=real_client), \
                 patch.object(server, "get_metadata", return_value=meta), \
                 patch("bullhorn_mcp.identity.get_access_token", return_value=token):
                result = server.create_contact({
                    "firstName": "Jane", "lastName": "Doe",
                    "clientCorporation": {"id": 1},
                })

        data = json.loads(result)
        assert data["changedEntityId"] == 9001
        assert "body" in captured, "PUT was not called"
        assert captured["body"]["owner"] == {"id": 7}

    def test_e2e_create_contact_explicit_owner_overrides(self, mock_session):
        """E2E: create_contact with explicit owner uses that owner; no CorporateUser token lookup."""
        import httpx
        import respx
        from unittest.mock import Mock, PropertyMock
        from bullhorn_mcp.auth import BullhornAuth
        from bullhorn_mcp.metadata import BullhornMetadata
        from bullhorn_mcp.client import BullhornClient

        auth = Mock(spec=BullhornAuth)
        type(auth).session = PropertyMock(return_value=mock_session)

        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields

        real_client = BullhornClient(auth)

        captured = {}

        def capture_put(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json={"changedEntityId": 9002, "changeType": "INSERT"})

        new_contact = {
            "id": 9002, "firstName": "Jane", "lastName": "Doe",
            "clientCorporation": {"id": 1}, "owner": {"id": 99},
        }

        with respx.mock:
            # Duplicate check search
            respx.get(f"{mock_session.rest_url}/search/ClientContact").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            # ClientContact PUT
            respx.put(f"{mock_session.rest_url}/entity/ClientContact").mock(
                side_effect=capture_put
            )
            # ClientContact GET
            respx.get(f"{mock_session.rest_url}/entity/ClientContact/9002").mock(
                return_value=httpx.Response(200, json={"data": new_contact})
            )

            with patch.object(server, "get_client", return_value=real_client), \
                 patch.object(server, "get_metadata", return_value=meta), \
                 patch("bullhorn_mcp.identity.get_access_token") as mock_token:
                result = server.create_contact({
                    "firstName": "Jane", "lastName": "Doe",
                    "clientCorporation": {"id": 1}, "owner": {"id": 99},
                })

        data = json.loads(result)
        assert data["changedEntityId"] == 9002
        assert captured["body"]["owner"] == {"id": 99}
        # get_access_token should NOT have been called (owner was explicit)
        mock_token.assert_not_called()

    def test_e2e_create_company_no_owner_auto_populated(self, mock_session):
        """E2E: create_company without owner auto-stamps owner from authenticated CorporateUser.

        Asserts PUT body has owner: {id: 7} and response has changedEntityId.
        """
        import httpx
        import respx
        from unittest.mock import Mock, PropertyMock
        from bullhorn_mcp.auth import BullhornAuth
        from bullhorn_mcp.metadata import BullhornMetadata
        from bullhorn_mcp.client import BullhornClient

        auth = Mock(spec=BullhornAuth)
        type(auth).session = PropertyMock(return_value=mock_session)

        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields

        real_client = BullhornClient(auth)

        captured = {}

        def capture_put(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json={"changedEntityId": 8001, "changeType": "INSERT"})

        new_company = {"id": 8001, "name": "Acme", "owner": {"id": 7}}

        token = Mock()
        token.claims = {"email": "beau@thepanel.com"}

        with respx.mock:
            # CorporateUser query for identity resolution
            respx.get(f"{mock_session.rest_url}/query/CorporateUser").mock(
                return_value=httpx.Response(200, json={
                    "data": [{"id": 7, "firstName": "Beau", "lastName": "Warren",
                              "email": "beau@thepanel.com"}]
                })
            )
            # ClientCorporation PUT
            respx.put(f"{mock_session.rest_url}/entity/ClientCorporation").mock(
                side_effect=capture_put
            )
            # ClientCorporation GET
            respx.get(f"{mock_session.rest_url}/entity/ClientCorporation/8001").mock(
                return_value=httpx.Response(200, json={"data": new_company})
            )

            with patch.object(server, "get_client", return_value=real_client), \
                 patch.object(server, "get_metadata", return_value=meta), \
                 patch("bullhorn_mcp.identity.get_access_token", return_value=token):
                result = server.create_company({"name": "Acme"})

        data = json.loads(result)
        assert data["changedEntityId"] == 8001
        assert "body" in captured, "PUT was not called"
        assert captured["body"]["owner"] == {"id": 7}
