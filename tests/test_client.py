"""Tests for Bullhorn API client."""

import time
import pytest
import httpx
import respx
from unittest.mock import Mock, PropertyMock
from bullhorn_mcp.auth import BullhornAuth, BullhornSession
from bullhorn_mcp.client import BullhornClient, BullhornAPIError, DEFAULT_FIELDS


@pytest.fixture
def mock_auth(mock_session):
    """Create a mock auth object with a valid session."""
    auth = Mock(spec=BullhornAuth)
    type(auth).session = PropertyMock(return_value=mock_session)
    return auth


class TestBullhornClient:
    """Tests for BullhornClient class."""

    @respx.mock
    def test_search_jobs(self, mock_auth, mock_session, sample_job):
        """Test searching for jobs."""
        respx.get(f"{mock_session.rest_url}/search/JobOrder").mock(
            return_value=httpx.Response(
                200,
                json={"data": [sample_job]},
            )
        )

        client = BullhornClient(mock_auth)
        results = client.search("JobOrder", "isOpen:1", count=10)

        assert len(results) == 1
        assert results[0]["id"] == 12345
        assert results[0]["title"] == "Software Engineer"

    @respx.mock
    def test_search_candidates(self, mock_auth, mock_session, sample_candidate):
        """Test searching for candidates."""
        respx.get(f"{mock_session.rest_url}/search/Candidate").mock(
            return_value=httpx.Response(
                200,
                json={"data": [sample_candidate]},
            )
        )

        client = BullhornClient(mock_auth)
        results = client.search("Candidate", "lastName:Smith")

        assert len(results) == 1
        assert results[0]["firstName"] == "John"
        assert results[0]["lastName"] == "Smith"

    @respx.mock
    def test_search_with_custom_fields(self, mock_auth, mock_session):
        """Test search with custom fields."""
        route = respx.get(f"{mock_session.rest_url}/search/JobOrder").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        client = BullhornClient(mock_auth)
        client.search("JobOrder", "isOpen:1", fields="id,title,salary")

        # Check that custom fields were passed
        assert "fields=id%2Ctitle%2Csalary" in str(route.calls[0].request.url)

    @respx.mock
    def test_search_with_sort(self, mock_auth, mock_session):
        """Test search with sort parameter."""
        route = respx.get(f"{mock_session.rest_url}/search/JobOrder").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        client = BullhornClient(mock_auth)
        client.search("JobOrder", "isOpen:1", sort="-dateAdded")

        assert "sort=-dateAdded" in str(route.calls[0].request.url)

    @respx.mock
    def test_search_count_limit(self, mock_auth, mock_session):
        """Test that count is limited to 500."""
        route = respx.get(f"{mock_session.rest_url}/search/JobOrder").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        client = BullhornClient(mock_auth)
        client.search("JobOrder", "isOpen:1", count=1000)  # Request more than max

        # Should be capped at 500
        assert "count=500" in str(route.calls[0].request.url)

    @respx.mock
    def test_query_entities(self, mock_auth, mock_session, sample_job):
        """Test querying entities with WHERE clause."""
        respx.get(f"{mock_session.rest_url}/query/JobOrder").mock(
            return_value=httpx.Response(
                200,
                json={"data": [sample_job]},
            )
        )

        client = BullhornClient(mock_auth)
        results = client.query("JobOrder", "salary > 100000")

        assert len(results) == 1
        assert results[0]["salary"] == 150000

    @respx.mock
    def test_query_with_order_by(self, mock_auth, mock_session):
        """Test query with orderBy parameter."""
        route = respx.get(f"{mock_session.rest_url}/query/JobOrder").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        client = BullhornClient(mock_auth)
        client.query("JobOrder", "isOpen=true", order_by="-dateAdded")

        assert "orderBy=-dateAdded" in str(route.calls[0].request.url)

    @respx.mock
    def test_get_entity_by_id(self, mock_auth, mock_session, sample_job):
        """Test getting a single entity by ID."""
        respx.get(f"{mock_session.rest_url}/entity/JobOrder/12345").mock(
            return_value=httpx.Response(
                200,
                json={"data": sample_job},
            )
        )

        client = BullhornClient(mock_auth)
        result = client.get("JobOrder", 12345)

        assert result["id"] == 12345
        assert result["title"] == "Software Engineer"

    @respx.mock
    def test_get_entity_with_custom_fields(self, mock_auth, mock_session):
        """Test getting entity with custom fields."""
        route = respx.get(f"{mock_session.rest_url}/entity/Candidate/67890").mock(
            return_value=httpx.Response(200, json={"data": {}})
        )

        client = BullhornClient(mock_auth)
        client.get("Candidate", 67890, fields="id,firstName,lastName,email")

        assert "fields=id%2CfirstName%2ClastName%2Cemail" in str(route.calls[0].request.url)

    @respx.mock
    def test_get_meta(self, mock_auth, mock_session):
        """Test getting entity metadata."""
        meta_response = {
            "entity": "JobOrder",
            "fields": [
                {"name": "id", "type": "Integer"},
                {"name": "title", "type": "String"},
            ],
        }
        respx.get(f"{mock_session.rest_url}/meta/JobOrder").mock(
            return_value=httpx.Response(200, json=meta_response)
        )

        client = BullhornClient(mock_auth)
        result = client.get_meta("JobOrder")

        assert result["entity"] == "JobOrder"
        assert len(result["fields"]) == 2

    @respx.mock
    def test_api_error_handling(self, mock_auth, mock_session):
        """Test handling of API errors."""
        respx.get(f"{mock_session.rest_url}/search/JobOrder").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        client = BullhornClient(mock_auth)

        with pytest.raises(BullhornAPIError) as exc_info:
            client.search("JobOrder", "isOpen:1")

        assert "500" in str(exc_info.value)

    @respx.mock
    def test_session_refresh_on_401(self, mock_auth, mock_session, sample_job):
        """Test that 401 triggers session refresh and retry."""
        # First call returns 401, second succeeds
        route = respx.get(f"{mock_session.rest_url}/search/JobOrder")
        route.side_effect = [
            httpx.Response(401, text="Unauthorized"),
            httpx.Response(200, json={"data": [sample_job]}),
        ]

        client = BullhornClient(mock_auth)
        results = client.search("JobOrder", "isOpen:1")

        # Should have refreshed session and retried
        assert mock_auth._refresh_session.called
        assert len(results) == 1


class TestPagination:
    """Tests for search and query pagination."""

    @respx.mock
    def test_search_with_start_offset(self, mock_auth, mock_session):
        """Test search with start parameter for pagination."""
        route = respx.get(f"{mock_session.rest_url}/search/JobOrder").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        client = BullhornClient(mock_auth)
        client.search("JobOrder", "isOpen:1", start=50)

        assert "start=50" in str(route.calls[0].request.url)

    @respx.mock
    def test_query_with_start_offset(self, mock_auth, mock_session):
        """Test query with start parameter for pagination."""
        route = respx.get(f"{mock_session.rest_url}/query/JobOrder").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        client = BullhornClient(mock_auth)
        client.query("JobOrder", "salary > 100000", start=100)

        assert "start=100" in str(route.calls[0].request.url)

    @respx.mock
    def test_search_pagination_combined(self, mock_auth, mock_session):
        """Test search with both start and count for pagination."""
        route = respx.get(f"{mock_session.rest_url}/search/Candidate").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        client = BullhornClient(mock_auth)
        client.search("Candidate", "status:Active", count=25, start=75)

        url = str(route.calls[0].request.url)
        assert "start=75" in url
        assert "count=25" in url


class TestDefaultFields:
    """Tests for default field constants."""

    def test_job_order_defaults(self):
        """Test JobOrder default fields."""
        assert "id" in DEFAULT_FIELDS["JobOrder"]
        assert "title" in DEFAULT_FIELDS["JobOrder"]
        assert "status" in DEFAULT_FIELDS["JobOrder"]
        assert "salary" in DEFAULT_FIELDS["JobOrder"]

    def test_candidate_defaults(self):
        """Test Candidate default fields."""
        assert "id" in DEFAULT_FIELDS["Candidate"]
        assert "firstName" in DEFAULT_FIELDS["Candidate"]
        assert "lastName" in DEFAULT_FIELDS["Candidate"]
        assert "email" in DEFAULT_FIELDS["Candidate"]

    def test_placement_defaults(self):
        """Test Placement default fields."""
        assert "id" in DEFAULT_FIELDS["Placement"]
        assert "candidate" in DEFAULT_FIELDS["Placement"]
        assert "jobOrder" in DEFAULT_FIELDS["Placement"]

    def test_client_corporation_defaults(self):
        """Test ClientCorporation default fields."""
        assert "id" in DEFAULT_FIELDS["ClientCorporation"]
        assert "name" in DEFAULT_FIELDS["ClientCorporation"]
        assert "status" in DEFAULT_FIELDS["ClientCorporation"]

    def test_client_contact_defaults(self):
        """Test ClientContact default fields."""
        assert "id" in DEFAULT_FIELDS["ClientContact"]
        assert "firstName" in DEFAULT_FIELDS["ClientContact"]
        assert "clientCorporation" in DEFAULT_FIELDS["ClientContact"]

    def test_default_fields_client_contact_includes_owner(self):
        """Test ClientContact default fields include owner and status."""
        assert "owner" in DEFAULT_FIELDS["ClientContact"]
        assert "status" in DEFAULT_FIELDS["ClientContact"]

    def test_default_fields_client_corporation_includes_date_added(self):
        """Test ClientCorporation default fields include dateAdded."""
        assert "dateAdded" in DEFAULT_FIELDS["ClientCorporation"]


class TestCreateEntity:
    """Tests for BullhornClient.create() and _request() JSON body support."""

    @respx.mock
    def test_request_with_json_body(self, mock_auth, mock_session):
        """_request() sends JSON body in PUT request."""
        route = respx.put(f"{mock_session.rest_url}/entity/ClientCorporation").mock(
            return_value=httpx.Response(
                200,
                json={"changedEntityId": 123, "changeType": "INSERT"},
            )
        )
        # Mock the subsequent GET for create()
        respx.get(f"{mock_session.rest_url}/entity/ClientCorporation/123").mock(
            return_value=httpx.Response(200, json={"data": {"id": 123, "name": "Acme"}})
        )

        client = BullhornClient(mock_auth)
        client.create("ClientCorporation", {"name": "Acme", "status": "Prospect"})

        request = route.calls[0].request
        import json
        body = json.loads(request.content)
        assert body["name"] == "Acme"
        assert body["status"] == "Prospect"

    @respx.mock
    def test_request_accepts_201_status(self, mock_auth, mock_session):
        """_request() treats 201 as success (no error raised)."""
        respx.put(f"{mock_session.rest_url}/entity/ClientCorporation").mock(
            return_value=httpx.Response(
                201,
                json={"changedEntityId": 456, "changeType": "INSERT"},
            )
        )
        respx.get(f"{mock_session.rest_url}/entity/ClientCorporation/456").mock(
            return_value=httpx.Response(200, json={"data": {"id": 456}})
        )

        client = BullhornClient(mock_auth)
        result = client.create("ClientCorporation", {"name": "Beta Corp"})
        assert result["changedEntityId"] == 456

    @respx.mock
    def test_create_returns_insert_response(self, mock_auth, mock_session):
        """create() returns combined dict with changedEntityId, changeType, and data."""
        respx.put(f"{mock_session.rest_url}/entity/ClientCorporation").mock(
            return_value=httpx.Response(
                200,
                json={"changedEntityId": 123, "changeType": "INSERT"},
            )
        )
        respx.get(f"{mock_session.rest_url}/entity/ClientCorporation/123").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"id": 123, "name": "Acme Corp", "status": "Prospect"}},
            )
        )

        client = BullhornClient(mock_auth)
        result = client.create("ClientCorporation", {"name": "Acme Corp", "status": "Prospect"})

        assert result["changedEntityId"] == 123
        assert result["changeType"] == "INSERT"
        assert result["data"]["id"] == 123
        assert result["data"]["name"] == "Acme Corp"

    @respx.mock
    def test_create_raises_on_api_error(self, mock_auth, mock_session):
        """create() raises BullhornAPIError on non-200/201 response."""
        respx.put(f"{mock_session.rest_url}/entity/ClientCorporation").mock(
            return_value=httpx.Response(400, text="Bad Request: missing required field")
        )

        client = BullhornClient(mock_auth)
        with pytest.raises(BullhornAPIError) as exc_info:
            client.create("ClientCorporation", {})

        assert "400" in str(exc_info.value)


class TestUpdateEntity:
    """Tests for BullhornClient.update()."""

    @respx.mock
    def test_update_returns_update_response(self, mock_auth, mock_session):
        """update() POSTs fields then GETs full record, returning combined dict."""
        respx.post(f"{mock_session.rest_url}/entity/ClientContact/54321").mock(
            return_value=httpx.Response(200, json={"changedEntityId": 54321, "changeType": "UPDATE"})
        )
        respx.get(f"{mock_session.rest_url}/entity/ClientContact/54321").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"id": 54321, "firstName": "Jane", "title": "CTO"}},
            )
        )

        client = BullhornClient(mock_auth)
        result = client.update("ClientContact", 54321, {"title": "CTO"})

        assert result["changedEntityId"] == 54321
        assert result["changeType"] == "UPDATE"
        assert result["data"]["title"] == "CTO"

    @respx.mock
    def test_update_raises_on_api_error(self, mock_auth, mock_session):
        """update() raises BullhornAPIError on non-200/201 response."""
        respx.post(f"{mock_session.rest_url}/entity/ClientContact/54321").mock(
            return_value=httpx.Response(400, text="Bad Request")
        )

        client = BullhornClient(mock_auth)
        with pytest.raises(BullhornAPIError):
            client.update("ClientContact", 54321, {"title": "CTO"})


class TestAddNote:
    """Tests for BullhornClient.add_note()."""

    @respx.mock
    def test_add_note_to_contact(self, mock_auth, mock_session):
        """add_note() for ClientContact sets personReference and commentingPerson."""
        route = respx.put(f"{mock_session.rest_url}/entity/Note").mock(
            return_value=httpx.Response(200, json={"changedEntityId": 88901, "changeType": "INSERT"})
        )
        respx.get(f"{mock_session.rest_url}/entity/Note/88901").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"id": 88901, "action": "General Note",
                               "personReference": {"id": 54321}}},
            )
        )

        client = BullhornClient(mock_auth)
        result = client.add_note("ClientContact", 54321, "General Note", "Test note")

        assert result["changedEntityId"] == 88901
        assert result["changeType"] == "INSERT"
        import json as _json
        body = _json.loads(route.calls[0].request.content)
        assert body["personReference"] == {"id": 54321}
        assert body["commentingPerson"] == {"id": 54321}
        assert body["action"] == "General Note"
        assert body["comments"] == "Test note"

    @respx.mock
    def test_add_note_to_company(self, mock_auth, mock_session):
        """add_note() for ClientCorporation sets clientCorporation field."""
        route = respx.put(f"{mock_session.rest_url}/entity/Note").mock(
            return_value=httpx.Response(200, json={"changedEntityId": 88902, "changeType": "INSERT"})
        )
        respx.get(f"{mock_session.rest_url}/entity/Note/88902").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"id": 88902, "action": "General Note",
                               "clientCorporation": {"id": 98765}}},
            )
        )

        client = BullhornClient(mock_auth)
        result = client.add_note("ClientCorporation", 98765, "General Note", "Company note")

        body = __import__("json").loads(route.calls[0].request.content)
        assert body["clientCorporation"] == {"id": 98765}
        assert "personReference" not in body
        assert result["changedEntityId"] == 88902

    @respx.mock
    def test_add_note_raises_on_api_error(self, mock_auth, mock_session):
        """add_note() raises BullhornAPIError on non-200/201 response."""
        respx.put(f"{mock_session.rest_url}/entity/Note").mock(
            return_value=httpx.Response(400, text="Invalid action")
        )

        client = BullhornClient(mock_auth)
        with pytest.raises(BullhornAPIError):
            client.add_note("ClientContact", 1, "Invalid Action", "note")


class TestResolveOwner:
    """Tests for BullhornClient.resolve_owner()."""

    @respx.mock
    def test_resolve_owner_by_id_passthrough(self, mock_auth, mock_session):
        """resolve_owner returns {"id": int} unchanged without querying Bullhorn."""
        client = BullhornClient(mock_auth)
        result = client.resolve_owner({"id": 42})
        assert result == {"id": 42}

    @respx.mock
    def test_resolve_owner_by_name_single_match(self, mock_auth, mock_session):
        """resolve_owner returns {"id": user_id} when name matches exactly one user."""
        respx.get(f"{mock_session.rest_url}/query/CorporateUser").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"id": 99, "firstName": "Maryrose", "lastName": "Lyons",
                                "email": "m.lyons@firm.com", "department": "Sales"}]},
            )
        )

        client = BullhornClient(mock_auth)
        result = client.resolve_owner("Maryrose Lyons")
        assert result == {"id": 99}

    @respx.mock
    def test_resolve_owner_by_name_multiple_matches(self, mock_auth, mock_session):
        """resolve_owner returns list of matches when name is ambiguous."""
        respx.get(f"{mock_session.rest_url}/query/CorporateUser").mock(
            return_value=httpx.Response(
                200,
                json={"data": [
                    {"id": 10, "firstName": "John", "lastName": "Smith", "email": "j.smith1@firm.com", "department": "Sales"},
                    {"id": 11, "firstName": "John", "lastName": "Smith", "email": "j.smith2@firm.com", "department": "Tech"},
                ]},
            )
        )

        client = BullhornClient(mock_auth)
        result = client.resolve_owner("John Smith")
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["id"] == 10
        assert result[1]["id"] == 11

    @respx.mock
    def test_resolve_owner_by_name_no_match(self, mock_auth, mock_session):
        """resolve_owner raises ValueError when no user found."""
        respx.get(f"{mock_session.rest_url}/query/CorporateUser").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        client = BullhornClient(mock_auth)
        with pytest.raises(ValueError, match="No CorporateUser found matching"):
            client.resolve_owner("Nobody Here")


class TestEdgeCases:
    """Tests for edge cases and error scenarios."""

    @respx.mock
    def test_search_empty_results(self, mock_auth, mock_session):
        """Test search returns empty list when no results."""
        respx.get(f"{mock_session.rest_url}/search/JobOrder").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        client = BullhornClient(mock_auth)
        results = client.search("JobOrder", "title:NonexistentJob12345")

        assert results == []

    @respx.mock
    def test_get_entity_empty_data(self, mock_auth, mock_session):
        """Test get returns empty dict when entity not found."""
        respx.get(f"{mock_session.rest_url}/entity/JobOrder/99999").mock(
            return_value=httpx.Response(200, json={"data": {}})
        )

        client = BullhornClient(mock_auth)
        result = client.get("JobOrder", 99999)

        assert result == {}

    @respx.mock
    def test_query_count_capped_at_500(self, mock_auth, mock_session):
        """Test that query count is also capped at 500."""
        route = respx.get(f"{mock_session.rest_url}/query/JobOrder").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        client = BullhornClient(mock_auth)
        client.query("JobOrder", "isOpen=true", count=1000)

        assert "count=500" in str(route.calls[0].request.url)

    @respx.mock
    def test_search_unknown_entity_uses_id_field(self, mock_auth, mock_session):
        """Test that unknown entity types default to 'id' field."""
        route = respx.get(f"{mock_session.rest_url}/search/UnknownEntity").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        client = BullhornClient(mock_auth)
        client.search("UnknownEntity", "someField:value")

        assert "fields=id" in str(route.calls[0].request.url)
