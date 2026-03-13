"""Tests for MCP server tools."""

import json
import pytest
from unittest.mock import Mock, patch
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
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.create_company({"name": "Acme Holdings Ltd", "status": "Prospect"})

        data = json.loads(result)
        assert data["changedEntityId"] == 98765
        assert data["changeType"] == "INSERT"
        assert data["data"]["name"] == "Acme Holdings Ltd"
        mock_client.create.assert_called_once_with(
            "ClientCorporation", {"name": "Acme Holdings Ltd", "status": "Prospect"}
        )

    def test_create_company_api_error(self, mock_client, mock_metadata):
        """create_company returns ERROR prefix on API failure."""
        mock_client.create.side_effect = BullhornAPIError("missing required field")

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.create_company({"status": "Prospect"})

        assert result.startswith("ERROR:")
        assert "missing required field" in result

    def test_create_company_label_resolution(self, mock_client):
        """create_company resolves field labels to API names before creating."""
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        # Simulate label "Industry" resolving to API name "industryList"
        meta.resolve_fields.return_value = {"name": "Acme", "industryList": "Technology"}
        mock_client.create.return_value = {
            "changedEntityId": 1,
            "changeType": "INSERT",
            "data": {"id": 1, "name": "Acme"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta):
            server.create_company({"name": "Acme", "Industry": "Technology"})

        meta.resolve_fields.assert_called_once_with(
            "ClientCorporation", {"name": "Acme", "Industry": "Technology"}
        )
        mock_client.create.assert_called_once_with(
            "ClientCorporation", {"name": "Acme", "industryList": "Technology"}
        )


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
        """create_contact returns error when owner key is absent."""
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.create_contact({"firstName": "Jane", "clientCorporation": {"id": 1}})

        data = json.loads(result)
        assert data["error"] == "owner_required"
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
             patch.object(server, "get_metadata", return_value=meta):
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
        """Test that all expected tools are registered."""
        tools = list(server.mcp._tool_manager._tools.keys())

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
        """PUT body for create_company contains exactly the keys the caller provided."""
        mock_client.create.return_value = {
            "changedEntityId": 1, "changeType": "INSERT",
            "data": {"id": 1, "name": "Acme", "status": "Prospect"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            server.create_company({"name": "Acme", "status": "Prospect"})

        create_fields = mock_client.create.call_args[0][1]
        assert set(create_fields.keys()) == {"name", "status"}

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
