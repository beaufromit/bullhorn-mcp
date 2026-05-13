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

    def test_user_message_defaults_omit_comments(self):
        """UserMessage default fields exclude `comments` (body) — added on demand."""
        fields = DEFAULT_FIELDS["UserMessage"]
        assert "id" in fields
        assert "subject" in fields
        assert "smtpSendDate" in fields
        assert "messageFiles(" in fields
        # Body is opt-in via include_body=True on the tool, not a default.
        assert "comments" not in fields
        # _subtype is auto-populated in responses; requesting it errors out.
        assert "_subtype" not in fields

    def test_default_fields_jobsubmission(self):
        """JobSubmission has an explicit safe field list — never falls back to *."""
        assert "JobSubmission" in DEFAULT_FIELDS
        fields = DEFAULT_FIELDS["JobSubmission"]
        assert "id" in fields
        assert "status" in fields
        assert "dateAdded" in fields
        assert "candidate" in fields
        assert "jobOrder" in fields
        assert "sendingUser" in fields
        assert "*" not in fields


class TestSearchExtraParams:
    """Tests for the extra_params argument on BullhornClient.search()."""

    @respx.mock
    def test_search_with_extra_params(self, mock_auth, mock_session):
        """extra_params dict values are merged into the outgoing query string."""
        route = respx.get(f"{mock_session.rest_url}/search/UserMessage").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        client = BullhornClient(mock_auth)
        client.search(
            "UserMessage",
            query="sender.id:1",
            extra_params={"entityId": 42},
        )

        url = str(route.calls[0].request.url)
        assert "entityId=42" in url
        assert "sender.id%3A1" in url  # field + value present in query param (: encoded as %3A)
        assert "isDeleted" in url  # blanket deleted filter applied


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
    def test_create_jobsubmission_does_not_request_all_fields(self, mock_auth, mock_session):
        """create('JobSubmission') enrichment GET uses DEFAULT_FIELDS, never fields=*."""
        respx.put(f"{mock_session.rest_url}/entity/JobSubmission").mock(
            return_value=httpx.Response(
                200,
                json={"changedEntityId": 501, "changeType": "INSERT"},
            )
        )
        get_route = respx.get(f"{mock_session.rest_url}/entity/JobSubmission/501").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"id": 501, "status": "Shortlisted"}},
            )
        )

        client = BullhornClient(mock_auth)
        result = client.create("JobSubmission", {"candidate": {"id": 20}, "jobOrder": {"id": 10}})

        assert result["changedEntityId"] == 501
        get_url = str(get_route.calls[0].request.url)
        assert "fields=%2A" not in get_url      # URL-encoded *
        assert "fields=*" not in get_url         # raw *
        assert "fields=" in get_url              # fields param was sent
        assert "candidate" in get_url            # safe field list used

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

    @respx.mock
    def test_resolve_owner_query_does_not_include_department(self, mock_auth, mock_session):
        """CR3: resolve_owner must not include 'department' in the CorporateUser fields query.

        'department' is not a valid queryable CorporateUser field in some Bullhorn instances.
        Including it caused BullhornAPIError, preventing name resolution entirely.
        """
        route = respx.get(f"{mock_session.rest_url}/query/CorporateUser").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"id": 42, "firstName": "Beau", "lastName": "Warren", "email": "beau@firm.com"}]},
            )
        )

        client = BullhornClient(mock_auth)
        client.resolve_owner("Beau Warren")

        request_url = str(route.calls[0].request.url)
        assert "department" not in request_url

    @respx.mock
    def test_resolve_owner_single_match_returns_id_only(self, mock_auth, mock_session):
        """CR3: resolve_owner returns only {"id": int} for a single match — no other CorporateUser fields.

        Ensures that even if the API returns extra user fields (email, firstName, etc.),
        none of them leak into the returned dict and subsequently into the ClientContact payload.
        """
        respx.get(f"{mock_session.rest_url}/query/CorporateUser").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"id": 42, "firstName": "Beau", "lastName": "Warren", "email": "beau@firm.com"}]},
            )
        )

        client = BullhornClient(mock_auth)
        result = client.resolve_owner("Beau Warren")

        assert result == {"id": 42}
        assert "firstName" not in result
        assert "lastName" not in result
        assert "email" not in result


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


class TestExcludeDeletedFilter:
    """Tests for the blanket isDeleted filter on search() and query()."""

    @respx.mock
    def test_search_appends_is_deleted_by_default(self, mock_auth, mock_session):
        """search() wraps the query and appends AND isDeleted:0 by default."""
        route = respx.get(f"{mock_session.rest_url}/search/Candidate").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        client = BullhornClient(mock_auth)
        client.search("Candidate", "name:Smith")
        url = str(route.calls[0].request.url)
        assert "name%3ASmith" in url        # original term present (URL-encoded :)
        assert "isDeleted%3A0" in url       # filter appended (URL-encoded :)

    @respx.mock
    def test_search_no_filter_when_exclude_deleted_false(self, mock_auth, mock_session):
        """search() passes query verbatim when exclude_deleted=False."""
        route = respx.get(f"{mock_session.rest_url}/search/Candidate").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        client = BullhornClient(mock_auth)
        client.search("Candidate", "name:Smith", exclude_deleted=False)
        url = str(route.calls[0].request.url)
        assert "isDeleted" not in url

    @respx.mock
    def test_search_empty_query_uses_filter_alone(self, mock_auth, mock_session):
        """search() with empty query sends just isDeleted:0 (no extra parens)."""
        route = respx.get(f"{mock_session.rest_url}/search/Candidate").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        client = BullhornClient(mock_auth)
        client.search("Candidate", "")
        url = str(route.calls[0].request.url)
        # Should be exactly isDeleted:0, not () AND isDeleted:0
        assert "isDeleted%3A0" in url
        assert "%28%29" not in url  # no empty parens

    @respx.mock
    def test_search_preserves_or_disjunction(self, mock_auth, mock_session):
        """search() wraps OR disjunctions in parens so AND binds correctly."""
        route = respx.get(f"{mock_session.rest_url}/search/Candidate").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        client = BullhornClient(mock_auth)
        client.search("Candidate", "name:A OR name:B")
        url = str(route.calls[0].request.url)
        # Parens must surround the OR expression before the AND isDeleted
        assert "%28name%3AA+OR+name%3AB%29" in url
        assert "isDeleted%3A0" in url

    @respx.mock
    def test_query_appends_is_deleted_by_default(self, mock_auth, mock_session):
        """query() wraps the WHERE clause and appends AND isDeleted=false by default."""
        route = respx.get(f"{mock_session.rest_url}/query/JobSubmission").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        client = BullhornClient(mock_auth)
        client.query("JobSubmission", "candidate.id=1")
        url = str(route.calls[0].request.url)
        assert "candidate.id%3D1" in url
        assert "isDeleted%3Dfalse" in url

    @respx.mock
    def test_query_no_filter_when_exclude_deleted_false(self, mock_auth, mock_session):
        """query() passes WHERE verbatim when exclude_deleted=False."""
        route = respx.get(f"{mock_session.rest_url}/query/JobSubmission").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        client = BullhornClient(mock_auth)
        client.query("JobSubmission", "candidate.id=1", exclude_deleted=False)
        url = str(route.calls[0].request.url)
        assert "isDeleted" not in url

    @respx.mock
    def test_query_empty_where_uses_filter_alone(self, mock_auth, mock_session):
        """query() with empty WHERE sends just isDeleted=false (no extra parens)."""
        route = respx.get(f"{mock_session.rest_url}/query/JobOrder").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        client = BullhornClient(mock_auth)
        client.query("JobOrder", "")
        url = str(route.calls[0].request.url)
        assert "isDeleted%3Dfalse" in url
        assert "%28%29" not in url  # no empty parens


class TestMultipartRequest:
    """Tests for BullhornClient._request_multipart()."""

    @respx.mock
    def test_multipart_sends_file(self, mock_auth, mock_session, sample_parsed_resume):
        """_request_multipart() sends a multipart/form-data request."""
        route = respx.post(f"{mock_session.rest_url}/resume/parseToCandidate").mock(
            return_value=httpx.Response(200, json=sample_parsed_resume)
        )

        client = BullhornClient(mock_auth)
        result = client._request_multipart(
            "POST",
            "/resume/parseToCandidate",
            files={"resume": ("cv.pdf", b"%PDF-fake", "application/pdf")},
        )

        assert route.called
        # Response body is returned
        assert result["candidate"]["firstName"] == "Jane"

    @respx.mock
    def test_multipart_refresh_on_401(self, mock_auth, mock_session, sample_parsed_resume):
        """_request_multipart() retries after 401 and calls _refresh_session."""
        route = respx.post(f"{mock_session.rest_url}/resume/parseToCandidate")
        route.side_effect = [
            httpx.Response(401, text="Unauthorized"),
            httpx.Response(200, json=sample_parsed_resume),
        ]

        client = BullhornClient(mock_auth)
        result = client._request_multipart(
            "POST",
            "/resume/parseToCandidate",
            files={"resume": ("cv.pdf", b"%PDF-fake", "application/pdf")},
        )

        assert mock_auth._refresh_session.called
        assert result["candidate"]["firstName"] == "Jane"

    @respx.mock
    def test_multipart_raises_on_api_error(self, mock_auth, mock_session):
        """_request_multipart() raises BullhornAPIError on non-200/201 response."""
        respx.post(f"{mock_session.rest_url}/resume/parseToCandidate").mock(
            return_value=httpx.Response(400, text="Bad Request")
        )

        client = BullhornClient(mock_auth)
        with pytest.raises(BullhornAPIError) as exc_info:
            client._request_multipart(
                "POST",
                "/resume/parseToCandidate",
                files={"resume": ("cv.pdf", b"fake", "application/pdf")},
            )

        assert "400" in str(exc_info.value)


class TestParseResume:
    """Tests for BullhornClient.parse_resume_file() and parse_resume_text()."""

    @respx.mock
    def test_parse_resume_file_calls_endpoint(self, mock_auth, mock_session, sample_parsed_resume):
        """parse_resume_file() sends to /resume/parseToCandidate with correct params."""
        route = respx.post(f"{mock_session.rest_url}/resume/parseToCandidate").mock(
            return_value=httpx.Response(200, json=sample_parsed_resume)
        )

        client = BullhornClient(mock_auth)
        result = client.parse_resume_file(b"%PDF-fake", "resume.pdf", "pdf")

        assert route.called
        url = str(route.calls[0].request.url)
        assert "format=pdf" in url
        assert "populateDescription=true" in url
        assert result["candidate"]["email"] == "jane.doe@example.com"

    @respx.mock
    def test_parse_resume_file_infers_content_type(self, mock_auth, mock_session, sample_parsed_resume):
        """parse_resume_file() uses the correct MIME type for known formats."""
        route = respx.post(f"{mock_session.rest_url}/resume/parseToCandidate").mock(
            return_value=httpx.Response(200, json=sample_parsed_resume)
        )

        client = BullhornClient(mock_auth)
        client.parse_resume_file(b"fake-docx-bytes", "resume.docx", "docx")

        # Content-type header in multipart boundary — check that request was sent
        assert route.called

    @respx.mock
    def test_parse_resume_text_uses_json_body(self, mock_auth, mock_session, sample_parsed_resume):
        """parse_resume_text() POSTs JSON to /resume/parseToCandidateViaJson."""
        import json as _json
        route = respx.post(f"{mock_session.rest_url}/resume/parseToCandidateViaJson").mock(
            return_value=httpx.Response(200, json=sample_parsed_resume)
        )

        client = BullhornClient(mock_auth)
        result = client.parse_resume_text("Jane Doe\nEngineer\njane@example.com", "text/plain")

        assert route.called
        body = _json.loads(route.calls[0].request.content)
        assert body["resume"] == "Jane Doe\nEngineer\njane@example.com"
        assert body["type"] == "text/plain"
        assert body["format"] == "text"
        assert result["candidate"]["firstName"] == "Jane"

    @respx.mock
    def test_parse_resume_text_html_type(self, mock_auth, mock_session, sample_parsed_resume):
        """parse_resume_text() passes content_type through to the JSON body."""
        import json as _json
        route = respx.post(f"{mock_session.rest_url}/resume/parseToCandidateViaJson").mock(
            return_value=httpx.Response(200, json=sample_parsed_resume)
        )

        client = BullhornClient(mock_auth)
        client.parse_resume_text("<html><body>Jane Doe</body></html>", "text/html")

        body = _json.loads(route.calls[0].request.content)
        assert body["type"] == "text/html"

    def test_guess_content_type_known_formats(self, mock_auth):
        """_guess_content_type returns correct MIME type for known formats."""
        client = BullhornClient(mock_auth)
        assert client._guess_content_type("pdf") == "application/pdf"
        assert client._guess_content_type("doc") == "application/msword"
        assert client._guess_content_type("html") == "text/html"
        assert client._guess_content_type("text") == "text/plain"

    def test_guess_content_type_unknown_falls_back(self, mock_auth):
        """_guess_content_type returns application/octet-stream for unknown format."""
        client = BullhornClient(mock_auth)
        assert client._guess_content_type("xyz") == "application/octet-stream"


class TestAttachFile:
    """Tests for BullhornClient.attach_file()."""

    @respx.mock
    def test_attach_file_puts_to_raw_endpoint(self, mock_auth, mock_session):
        """attach_file() PUTs to /file/{entity}/{id}/raw."""
        route = respx.put(f"{mock_session.rest_url}/file/Candidate/123/raw").mock(
            return_value=httpx.Response(200, json={"fileId": 55, "name": "cv.pdf"})
        )

        client = BullhornClient(mock_auth)
        result = client.attach_file("Candidate", 123, b"%PDF-fake", "cv.pdf", "application/pdf")

        assert route.called
        assert result["fileId"] == 55

    @respx.mock
    def test_attach_file_sends_query_params(self, mock_auth, mock_session):
        """attach_file() passes externalID and fileType as query parameters."""
        route = respx.put(f"{mock_session.rest_url}/file/Candidate/123/raw").mock(
            return_value=httpx.Response(200, json={"fileId": 66})
        )

        client = BullhornClient(mock_auth)
        client.attach_file(
            "Candidate", 123, b"%PDF-fake", "cv.pdf", "application/pdf",
            external_id="EXT-001", file_type="CV",
        )

        url = str(route.calls[0].request.url)
        assert "externalID=EXT-001" in url
        assert "fileType=CV" in url

    @respx.mock
    def test_attach_file_no_optional_params(self, mock_auth, mock_session):
        """attach_file() omits externalID and fileType query params when not provided."""
        route = respx.put(f"{mock_session.rest_url}/file/Candidate/456/raw").mock(
            return_value=httpx.Response(200, json={"fileId": 77})
        )

        client = BullhornClient(mock_auth)
        client.attach_file("Candidate", 456, b"data", "resume.pdf", "application/pdf")

        url = str(route.calls[0].request.url)
        assert "externalID" not in url
        assert "fileType" not in url

    @respx.mock
    def test_attach_file_raises_on_api_error(self, mock_auth, mock_session):
        """attach_file() raises BullhornAPIError on non-200/201 response."""
        respx.put(f"{mock_session.rest_url}/file/Candidate/123/raw").mock(
            return_value=httpx.Response(400, text="Bad Request")
        )

        client = BullhornClient(mock_auth)
        with pytest.raises(BullhornAPIError):
            client.attach_file("Candidate", 123, b"data", "cv.pdf", "application/pdf")
