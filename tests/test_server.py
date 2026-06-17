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

    def _wrap_with_meta(bare_mock):
        """Return a side_effect that wraps bare_mock.return_value in an envelope."""
        def _se(*args, **kwargs):
            se = bare_mock.side_effect
            if se is not None:
                if isinstance(se, BaseException):
                    raise se
                return se(*args, **kwargs)
            data = bare_mock.return_value
            return {
                "data": data,
                "total": len(data),
                "start": kwargs.get("start", 0),
                "count": len(data),
            }
        return _se

    client.search_with_meta.side_effect = _wrap_with_meta(client.search)
    client.query_with_meta.side_effect = _wrap_with_meta(client.query)
    client.get_association_with_meta.side_effect = _wrap_with_meta(client.get_association)
    return client


@pytest.fixture(autouse=True)
def reset_client():
    """Reset the global client, metadata cache, and one-shot flags before each test."""
    server._client = None
    server._metadata = None
    server._shortlist_status_validated = False
    server._valid_note_actions = None
    yield
    server._client = None
    server._metadata = None
    server._shortlist_status_validated = False
    server._valid_note_actions = None


class TestListJobs:
    """Tests for list_jobs tool."""

    def test_list_jobs_basic(self, mock_client, sample_job):
        """Test basic job listing."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_jobs()

        data = json.loads(result)
        assert len(data["data"]) == 1
        assert data["data"][0]["title"] == "Software Engineer"
        mock_client.search_with_meta.assert_called_once()

    def test_list_jobs_with_query(self, mock_client):
        """Test job listing with query parameter."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_jobs(query="title:Engineer")

        call_args = mock_client.search_with_meta.call_args
        assert "title:Engineer" in call_args.kwargs["query"]

    def test_list_jobs_with_status(self, mock_client):
        """Test job listing with status filter."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_jobs(status="Open")

        call_args = mock_client.search_with_meta.call_args
        assert 'status:"Open"' in call_args.kwargs["query"]

    def test_list_jobs_with_limit(self, mock_client):
        """Test job listing with custom limit."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_jobs(limit=50)

        call_args = mock_client.search_with_meta.call_args
        assert call_args.kwargs["count"] == 50

    def test_list_jobs_error_handling(self, mock_client):
        """Test error handling in list_jobs."""
        mock_client.search.side_effect = BullhornAPIError("API Error")

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_jobs()

        assert "ERROR:" in result
        assert "API Error" in result

    def test_list_jobs_start_forwarded(self, mock_client):
        """start is passed through to client.search_with_meta."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_jobs(limit=500, start=500)

        call_args = mock_client.search_with_meta.call_args
        assert call_args.kwargs["start"] == 500
        assert call_args.kwargs["count"] == 500

    def test_list_jobs_default_start_is_zero(self, mock_client):
        """Default start value is 0."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_jobs()

        call_args = mock_client.search_with_meta.call_args
        assert call_args.kwargs["start"] == 0


class TestListCandidates:
    """Tests for list_candidates tool."""

    def test_list_candidates_basic(self, mock_client, sample_candidate):
        """Test basic candidate listing."""
        mock_client.search.return_value = [sample_candidate]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_candidates()

        data = json.loads(result)
        assert len(data["data"]) == 1
        assert data["data"][0]["firstName"] == "John"

    def test_list_candidates_with_query(self, mock_client):
        """Test candidate listing with query."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_candidates(query="skillSet:Python")

        call_args = mock_client.search_with_meta.call_args
        assert "skillSet:Python" in call_args.kwargs["query"]

    def test_list_candidates_auth_error(self, mock_client):
        """Test authentication error handling."""
        mock_client.search.side_effect = AuthenticationError("Auth failed")

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_candidates()

        assert "ERROR:" in result
        assert "Auth failed" in result

    def test_list_candidates_start_forwarded(self, mock_client):
        """start is passed through to client.search_with_meta."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_candidates(limit=500, start=1000)

        call_args = mock_client.search_with_meta.call_args
        assert call_args.kwargs["start"] == 1000
        assert call_args.kwargs["count"] == 500

    def test_list_candidates_default_start_is_zero(self, mock_client):
        """Default start value is 0."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_candidates()

        call_args = mock_client.search_with_meta.call_args
        assert call_args.kwargs["start"] == 0


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


class TestGetCompany:
    """Tests for get_company tool."""

    def test_get_company_by_id(self, mock_client):
        """get_company delegates to client.get with entity=ClientCorporation."""
        mock_client.get.return_value = {"id": 9493, "name": "Pinergy", "status": "Active"}

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_company(company_id=9493)

        data = json.loads(result)
        assert data["id"] == 9493
        assert data["name"] == "Pinergy"
        mock_client.get.assert_called_with(
            entity="ClientCorporation", entity_id=9493, fields=None
        )

    def test_get_company_with_fields(self, mock_client):
        """get_company passes custom fields to client.get."""
        mock_client.get.return_value = {"id": 9493, "name": "Pinergy"}

        with patch.object(server, "get_client", return_value=mock_client):
            server.get_company(company_id=9493, fields="id,name,phone")

        mock_client.get.assert_called_with(
            entity="ClientCorporation", entity_id=9493, fields="id,name,phone"
        )

    def test_get_company_api_error(self, mock_client):
        """get_company returns ERROR prefix on API failure."""
        mock_client.get.side_effect = BullhornAPIError("not found")

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_company(company_id=99999)

        assert result.startswith("ERROR:")


class TestGetContact:
    """Tests for get_contact tool."""

    def test_get_contact_default_fields(self, mock_client):
        """get_contact delegates to client.get with entity=ClientContact and fields=None."""
        mock_client.get.return_value = {
            "id": 123,
            "firstName": "Jane",
            "lastName": "Doe",
            "email": "jane@example.com",
        }

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_contact(contact_id=123)

        data = json.loads(result)
        assert data["id"] == 123
        assert data["firstName"] == "Jane"
        mock_client.get.assert_called_with(
            entity="ClientContact", entity_id=123, fields=None
        )

    def test_get_contact_custom_fields(self, mock_client):
        """get_contact passes custom fields to client.get."""
        mock_client.get.return_value = {"id": 123, "email": "jane@example.com"}

        with patch.object(server, "get_client", return_value=mock_client):
            server.get_contact(contact_id=123, fields="id,email")

        mock_client.get.assert_called_with(
            entity="ClientContact", entity_id=123, fields="id,email"
        )

    def test_get_contact_api_error(self, mock_client):
        """get_contact returns ERROR prefix on API failure."""
        mock_client.get.side_effect = BullhornAPIError("not found")

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_contact(contact_id=99999)

        assert result.startswith("ERROR:")

    def test_get_contact_auth_error(self, mock_client):
        """get_contact returns ERROR prefix on authentication failure."""
        mock_client.get.side_effect = AuthenticationError("session expired")

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_contact(contact_id=123)

        assert result.startswith("ERROR:")


class TestGetJobSubmissions:
    """Tests for get_job_submissions tool."""

    def test_get_job_submissions_basic(self, mock_client):
        """query_with_meta called with correct args; response has data+pagination."""
        sample = {"id": 1, "status": "Shortlisted", "candidate": {"id": 10, "firstName": "Jane"}}
        mock_client.query.return_value = [sample]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_job_submissions(job_id=12345)

        data = json.loads(result)
        assert "data" in data
        assert "pagination" in data
        mock_client.query_with_meta.assert_called_once_with(
            entity="JobSubmission",
            where="jobOrder.id=12345",
            fields="id,candidate(id,firstName,lastName,email),status,dateAdded,sendingUser(id,name)",
            count=20,
            start=0,
        )

    def test_get_job_submissions_status_filter(self, mock_client):
        """status param appended to WHERE clause with quoted value."""
        mock_client.query.return_value = []

        with patch.object(server, "get_client", return_value=mock_client):
            server.get_job_submissions(job_id=12345, status="Shortlisted")

        call_args = mock_client.query_with_meta.call_args
        assert call_args.kwargs["where"] == "jobOrder.id=12345 AND status='Shortlisted'"

    def test_get_job_submissions_pagination(self, mock_client):
        """limit and start forwarded as count and start; next_start populated when has_more."""
        sample = {"id": 1, "status": "Shortlisted"}
        mock_client.query_with_meta.side_effect = None
        mock_client.query_with_meta.return_value = {
            "data": [sample] * 10,
            "total": 100,
            "start": 10,
            "count": 10,
        }

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_job_submissions(job_id=12345, limit=10, start=10)

        call_args = mock_client.query_with_meta.call_args
        assert call_args.kwargs["count"] == 10
        assert call_args.kwargs["start"] == 10

        data = json.loads(result)
        assert data["pagination"]["has_more"] is True
        assert data["pagination"]["next_start"] == 20

    def test_get_job_submissions_custom_fields(self, mock_client):
        """Caller-supplied fields override the default field string."""
        mock_client.query.return_value = []

        with patch.object(server, "get_client", return_value=mock_client):
            server.get_job_submissions(job_id=12345, fields="id,status")

        call_args = mock_client.query_with_meta.call_args
        assert call_args.kwargs["fields"] == "id,status"

    def test_get_job_submissions_empty(self, mock_client):
        """Empty results returned with has_more=false and next_start=null."""
        mock_client.query_with_meta.side_effect = None
        mock_client.query_with_meta.return_value = {"data": [], "total": 0, "start": 0, "count": 0}

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_job_submissions(job_id=12345)

        data = json.loads(result)
        assert data["data"] == []
        assert data["pagination"]["has_more"] is False
        assert data["pagination"]["next_start"] is None

    def test_get_job_submissions_api_error(self, mock_client):
        """BullhornAPIError returns ERROR prefix."""
        mock_client.query.side_effect = BullhornAPIError("not found")

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_job_submissions(job_id=12345)

        assert result.startswith("ERROR:")

    def test_get_job_submissions_auth_error(self, mock_client):
        """AuthenticationError returns ERROR prefix."""
        mock_client.query.side_effect = AuthenticationError("session expired")

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_job_submissions(job_id=12345)

        assert result.startswith("ERROR:")


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
        assert data["data"][0]["status"] == "Approved"
        mock_client.search_with_meta.assert_called_with(
            entity="Placement",
            query="status:Approved",
            fields=None,
            count=20,
            start=0,
        )

    def test_search_with_limit(self, mock_client):
        """Test search with custom limit."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.search_entities(
                entity="ClientCorporation", query="name:Acme*", limit=100
            )

        call_args = mock_client.search_with_meta.call_args
        assert call_args.kwargs["count"] == 100

    def test_search_entities_start_forwarded(self, mock_client):
        """start is passed through to client.search_with_meta."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.search_entities(entity="Candidate", query="status:Active", limit=500, start=500)

        call_args = mock_client.search_with_meta.call_args
        assert call_args.kwargs["start"] == 500
        assert call_args.kwargs["count"] == 500

    def test_search_entities_default_start_is_zero(self, mock_client):
        """Default start value is 0."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.search_entities(entity="Placement", query="status:Approved")

        call_args = mock_client.search_with_meta.call_args
        assert call_args.kwargs["start"] == 0


class TestQueryEntities:
    """Tests for query_entities tool."""

    def test_query_with_where(self, mock_client):
        """Test query with WHERE clause."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.query_entities(
                entity="JobOrder", where="salary > 100000"
            )

        mock_client.query_with_meta.assert_called_with(
            entity="JobOrder",
            where="salary > 100000",
            fields=None,
            count=20,
            start=0,
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

        call_args = mock_client.query_with_meta.call_args
        assert call_args.kwargs["order_by"] == "-dateAdded"

    def test_query_entities_start_forwarded(self, mock_client):
        """start is passed through to client.query_with_meta."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.query_entities(entity="Placement", where="status='Approved'", limit=500, start=500)

        call_args = mock_client.query_with_meta.call_args
        assert call_args.kwargs["start"] == 500
        assert call_args.kwargs["count"] == 500

    def test_query_entities_default_start_is_zero(self, mock_client):
        """Default start value is 0."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.query_entities(entity="JobOrder", where="salary > 100000")

        call_args = mock_client.query_with_meta.call_args
        assert call_args.kwargs["start"] == 0


class TestSearchEmails:
    """Tests for search_emails tool."""

    @pytest.fixture
    def email_client(self):
        """Mock client with empty UserMessage results by default."""
        client = Mock()
        client.search.return_value = []
        client.resolve_owner.return_value = {"id": 0}

        def _search_with_meta_se(*args, **kwargs):
            se = client.search.side_effect
            if se is not None:
                if isinstance(se, BaseException):
                    raise se
                return se(*args, **kwargs)
            data = client.search.return_value
            return {"data": data, "total": len(data), "start": kwargs.get("start", 0), "count": len(data)}

        client.search_with_meta.side_effect = _search_with_meta_se
        return client

    def test_search_emails_basic(self, email_client):
        """Only person_id set: query is the OR clause, entityId forwarded, sort is -smtpReceiveDate."""
        from bullhorn_mcp.identity import IdentityResolutionError
        with patch.object(server, "get_client", return_value=email_client), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")):
            server.search_emails(person_id=34389)

        call_args = email_client.search_with_meta.call_args
        assert call_args.kwargs["entity"] == "UserMessage"
        assert call_args.kwargs["query"] == "(sender.id:34389 OR recipients.id:34389)"
        assert call_args.kwargs["sort"] == "-smtpReceiveDate"
        # entityId must be forwarded — Bullhorn /search/UserMessage requires it.
        assert call_args.kwargs["extra_params"] == {"entityId": 34389}
        # Body should not be requested by default.
        assert "comments" not in call_args.kwargs["fields"]

    def test_search_emails_entity_id_matches_person_id(self, email_client):
        """entityId in extra_params always equals person_id, regardless of other filters."""
        from bullhorn_mcp.identity import IdentityResolutionError
        with patch.object(server, "get_client", return_value=email_client), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")):
            server.search_emails(person_id=99999)

        extra = email_client.search_with_meta.call_args.kwargs["extra_params"]
        assert extra == {"entityId": 99999}

    def test_search_emails_with_user_id(self, email_client):
        """user={"id": N} adds an AND clause with user id and skips resolve_caller."""
        with patch.object(server, "get_client", return_value=email_client), \
             patch.object(server, "resolve_caller") as resolve_caller_mock:
            email_client.resolve_owner.return_value = {"id": 24}
            server.search_emails(person_id=34389, user={"id": 24})

        resolve_caller_mock.assert_not_called()
        query = email_client.search_with_meta.call_args.kwargs["query"]
        assert "(sender.id:34389 OR recipients.id:34389)" in query
        assert "(sender.id:24 OR recipients.id:24)" in query
        assert " AND " in query

    def test_search_emails_with_user_name_unique(self, email_client):
        """user as a name string is resolved to an id via resolve_owner."""
        email_client.resolve_owner.return_value = {"id": 24}
        with patch.object(server, "get_client", return_value=email_client):
            server.search_emails(person_id=34389, user="Andrew Wynne")

        email_client.resolve_owner.assert_called_once_with("Andrew Wynne")
        query = email_client.search_with_meta.call_args.kwargs["query"]
        assert "(sender.id:24 OR recipients.id:24)" in query

    def test_search_emails_user_name_ambiguous(self, email_client):
        """Multiple matches returns user_ambiguous JSON; search is not called."""
        email_client.resolve_owner.return_value = [
            {"id": 10, "firstName": "John", "lastName": "Smith", "email": "j1@firm.com"},
            {"id": 11, "firstName": "John", "lastName": "Smith", "email": "j2@firm.com"},
        ]
        with patch.object(server, "get_client", return_value=email_client):
            result = server.search_emails(person_id=34389, user="John Smith")

        data = json.loads(result)
        assert data["error"] == "user_ambiguous"
        assert len(data["matches"]) == 2
        email_client.search_with_meta.assert_not_called()

    def test_search_emails_user_not_found(self, email_client):
        """resolve_owner ValueError surfaces as user_not_found JSON; search not called."""
        email_client.resolve_owner.side_effect = ValueError(
            "No CorporateUser found matching 'Ghost'"
        )
        with patch.object(server, "get_client", return_value=email_client):
            result = server.search_emails(person_id=34389, user="Ghost")

        data = json.loads(result)
        assert data["error"] == "user_not_found"
        email_client.search_with_meta.assert_not_called()

    def test_search_emails_user_none_resolves_caller(self, email_client):
        """user=None falls back to the authenticated CorporateUser."""
        with patch.object(server, "get_client", return_value=email_client), \
             patch.object(server, "resolve_caller", return_value={"id": 99, "email": "me@firm.com"}):
            server.search_emails(person_id=34389)

        query = email_client.search_with_meta.call_args.kwargs["query"]
        assert "(sender.id:99 OR recipients.id:99)" in query

    def test_search_emails_user_none_no_caller_token(self, email_client):
        """user=None + no JWT (stdio mode): search runs without a user clause."""
        from bullhorn_mcp.identity import IdentityResolutionError
        with patch.object(server, "get_client", return_value=email_client), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")):
            server.search_emails(person_id=34389)

        query = email_client.search_with_meta.call_args.kwargs["query"]
        assert query == "(sender.id:34389 OR recipients.id:34389)"

    def test_search_emails_with_date_range(self, email_client):
        """since/until produce a smtpSendDate Lucene range; either bound may be open."""
        from bullhorn_mcp.identity import IdentityResolutionError
        with patch.object(server, "get_client", return_value=email_client), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")):
            server.search_emails(person_id=1, since="2024-01-01", until="2024-12-31")
            full = email_client.search_with_meta.call_args.kwargs["query"]

            server.search_emails(person_id=1, since=None, until="2024-12-31")
            open_lo = email_client.search_with_meta.call_args.kwargs["query"]

            server.search_emails(person_id=1, since="2024-01-01", until=None)
            open_hi = email_client.search_with_meta.call_args.kwargs["query"]

        assert "smtpSendDate:[2024-01-01 TO 2024-12-31]" in full
        assert "smtpSendDate:[* TO 2024-12-31]" in open_lo
        assert "smtpSendDate:[2024-01-01 TO *]" in open_hi

    def test_search_emails_subject_filter(self, email_client):
        """subject_contains is appended as an AND subject:(…) clause."""
        from bullhorn_mcp.identity import IdentityResolutionError
        with patch.object(server, "get_client", return_value=email_client), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")):
            server.search_emails(person_id=1, subject_contains="proposal")

        query = email_client.search_with_meta.call_args.kwargs["query"]
        assert "subject:(proposal)" in query

    def test_search_emails_include_body_appends_comments(self, email_client):
        """include_body=True appends `comments` to the resolved fields argument."""
        from bullhorn_mcp.identity import IdentityResolutionError
        with patch.object(server, "get_client", return_value=email_client), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")):
            server.search_emails(person_id=1, include_body=True)

        fields = email_client.search_with_meta.call_args.kwargs["fields"]
        assert fields.endswith(",comments")

    def test_search_emails_api_error(self, email_client):
        """API errors surface with the existing ERROR: prefix."""
        from bullhorn_mcp.identity import IdentityResolutionError
        email_client.search.side_effect = BullhornAPIError("boom")
        with patch.object(server, "get_client", return_value=email_client), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")):
            result = server.search_emails(person_id=1)

        assert result.startswith("ERROR:")
        assert "boom" in result


class TestPaginateEnvelope:
    """Tests for the _paginate_envelope helper."""

    def test_has_more_true_when_total_exceeds_returned(self):
        meta = {"data": [{"id": 1}], "total": 100, "start": 0, "count": 1}
        result = server._paginate_envelope(meta, start=0, count=1)
        assert result["pagination"]["has_more"] is True
        assert result["pagination"]["next_start"] == 1
        assert result["pagination"]["total"] == 100

    def test_has_more_false_when_all_returned(self):
        meta = {"data": [{"id": 1}, {"id": 2}], "total": 2, "start": 0, "count": 2}
        result = server._paginate_envelope(meta, start=0, count=2)
        assert result["pagination"]["has_more"] is False
        assert result["pagination"]["next_start"] is None

    def test_has_more_fallback_when_total_none(self):
        """When total is None, has_more is True iff len(data) == count."""
        meta = {"data": [{"id": i} for i in range(20)], "total": None, "start": 0, "count": 20}
        result = server._paginate_envelope(meta, start=0, count=20)
        assert result["pagination"]["has_more"] is True
        assert result["pagination"]["next_start"] == 20

    def test_has_more_false_fallback_short_page(self):
        """When total is None and len(data) < count, assume last page."""
        meta = {"data": [{"id": 1}], "total": None, "start": 0, "count": 20}
        result = server._paginate_envelope(meta, start=0, count=20)
        assert result["pagination"]["has_more"] is False

    def test_list_jobs_returns_pagination_has_more(self, mock_client, sample_job):
        """list_jobs result includes has_more=True when total > returned."""
        # Clear fixture side_effect so return_value takes precedence.
        mock_client.search_with_meta.side_effect = None
        mock_client.search_with_meta.return_value = {
            "data": [sample_job], "total": 999, "start": 0, "count": 1
        }
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_jobs(limit=1)
        data = json.loads(result)
        assert data["pagination"]["has_more"] is True
        assert data["pagination"]["next_start"] == 1
        assert data["pagination"]["total"] == 999


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
        """Test basic contact listing returns JSON object with data and pagination."""
        mock_client.search.return_value = [{"id": 111, "firstName": "Alice", "lastName": "Jones"}]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_contacts()

        data = json.loads(result)
        assert isinstance(data["data"], list)
        assert len(data["data"]) == 1
        assert data["data"][0]["id"] == 111
        mock_client.search_with_meta.assert_called_once()

    def test_list_contacts_with_status(self, mock_client):
        """Test contact listing with status filter appended to query."""
        mock_client.search.return_value = []

        with patch.object(server, "get_client", return_value=mock_client):
            server.list_contacts(status="Active")

        call_args = mock_client.search_with_meta.call_args
        assert 'status:"Active"' in call_args.kwargs["query"]

    def test_list_contacts_api_error(self, mock_client):
        """Test error handling returns ERROR prefix."""
        mock_client.search.side_effect = BullhornAPIError("fail")

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_contacts()

        assert result.startswith("ERROR:")

    def test_list_contacts_start_forwarded(self, mock_client):
        """start is passed through to client.search_with_meta."""
        mock_client.search.return_value = []

        with patch.object(server, "get_client", return_value=mock_client):
            server.list_contacts(limit=500, start=500)

        call_args = mock_client.search_with_meta.call_args
        assert call_args.kwargs["start"] == 500
        assert call_args.kwargs["count"] == 500

    def test_list_contacts_default_start_is_zero(self, mock_client):
        """Default start value is 0."""
        mock_client.search.return_value = []

        with patch.object(server, "get_client", return_value=mock_client):
            server.list_contacts()

        call_args = mock_client.search_with_meta.call_args
        assert call_args.kwargs["start"] == 0


class TestListCompanies:
    """Tests for list_companies tool."""

    def test_list_companies_default(self, mock_client):
        """Test basic company listing returns JSON object with data and pagination."""
        mock_client.search.return_value = [{"id": 222, "name": "Acme Corp"}]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_companies()

        data = json.loads(result)
        assert isinstance(data["data"], list)
        assert len(data["data"]) == 1
        call_args = mock_client.search_with_meta.call_args
        assert call_args.kwargs["entity"] == "ClientCorporation"

    def test_list_companies_with_query(self, mock_client):
        """Test that a custom query is passed through to the search call."""
        mock_client.search.return_value = []

        with patch.object(server, "get_client", return_value=mock_client):
            server.list_companies(query="name:Acme*")

        call_args = mock_client.search_with_meta.call_args
        assert "name:Acme*" in call_args.kwargs["query"]

    def test_list_companies_start_forwarded(self, mock_client):
        """start is passed through to client.search_with_meta."""
        mock_client.search.return_value = []

        with patch.object(server, "get_client", return_value=mock_client):
            server.list_companies(limit=500, start=1000)

        call_args = mock_client.search_with_meta.call_args
        assert call_args.kwargs["start"] == 1000
        assert call_args.kwargs["count"] == 500

    def test_list_companies_default_start_is_zero(self, mock_client):
        """Default start value is 0."""
        mock_client.search.return_value = []

        with patch.object(server, "get_client", return_value=mock_client):
            server.list_companies()

        call_args = mock_client.search_with_meta.call_args
        assert call_args.kwargs["start"] == 0


class TestListPlacements:
    """Tests for list_placements tool."""

    # --- record_type validation ---

    def test_invalid_record_type_returns_error(self, mock_client):
        """Unknown record_type returns an error envelope (not an exception)."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_placements(record_type="banana")
        data = json.loads(result)
        assert data["error"] == "invalid_record_type"

    # --- date parsing ---

    def test_invalid_since_returns_error(self, mock_client):
        """Malformed since string returns an error envelope."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_placements(since="not-a-date")
        data = json.loads(result)
        assert data["error"] == "invalid_date"
        assert "since" in data["message"]

    def test_invalid_until_returns_error(self, mock_client):
        """Malformed until string returns an error envelope."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_placements(until="2025/01/01")
        data = json.loads(result)
        assert data["error"] == "invalid_date"
        assert "until" in data["message"]

    def test_since_converted_to_epoch_ms(self, mock_client):
        """since='2025-01-01' is converted to epoch-ms >= clause in WHERE."""
        mock_client.query.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_placements(record_type="new", since="2025-01-01")
        call_args = mock_client.query_with_meta.call_args
        # 2025-01-01 UTC midnight = 1735689600000 ms
        assert "dateBegin >= 1735689600000" in call_args.kwargs["where"]

    def test_until_adds_one_day_to_include_full_day(self, mock_client):
        """until='2025-01-01' adds 86400000ms so the whole day is included."""
        mock_client.query.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_placements(record_type="new", until="2025-01-01")
        call_args = mock_client.query_with_meta.call_args
        # 2025-01-01 + 1 day = 1735689600000 + 86400000 = 1735776000000
        assert "dateBegin < 1735776000000" in call_args.kwargs["where"]

    # --- record_type="new" ---

    def test_new_uses_placement_entity(self, mock_client):
        """record_type='new' queries Placement."""
        mock_client.query.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_placements(record_type="new")
        call_args = mock_client.query_with_meta.call_args
        assert call_args.kwargs["entity"] == "Placement"

    def test_new_default_order_by_date_begin(self, mock_client):
        """record_type='new' defaults to order by -dateBegin."""
        mock_client.query.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_placements(record_type="new")
        call_args = mock_client.query_with_meta.call_args
        assert call_args.kwargs["order_by"] == "-dateBegin"

    def test_new_rows_tagged_record_type_new(self, mock_client):
        """Rows returned for record_type='new' carry record_type='new'."""
        mock_client.query.return_value = [{"id": 1, "status": "Approved"}]
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_placements(record_type="new")
        data = json.loads(result)
        assert data["data"][0]["record_type"] == "new"

    def test_new_default_fields_exclude_custom_int3(self, mock_client):
        """Default fields for new placements do not include customInt3."""
        mock_client.query.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_placements(record_type="new")
        call_args = mock_client.query_with_meta.call_args
        assert "customInt3" not in (call_args.kwargs.get("fields") or "")

    def test_new_with_status_filter(self, mock_client):
        """status param is added to the WHERE clause for new placements."""
        mock_client.query.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_placements(record_type="new", status="Approved")
        call_args = mock_client.query_with_meta.call_args
        assert "status='Approved'" in call_args.kwargs["where"]

    def test_new_no_date_defaults_to_tautology(self, mock_client):
        """Without since/until/status/query the WHERE is 'id IS NOT NULL'."""
        mock_client.query.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_placements(record_type="new")
        call_args = mock_client.query_with_meta.call_args
        assert call_args.kwargs["where"] == "id IS NOT NULL"

    def test_new_with_extra_query(self, mock_client):
        """Custom query fragment is appended to the WHERE clause."""
        mock_client.query.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_placements(record_type="new", query="employmentType='Daily Rate'")
        call_args = mock_client.query_with_meta.call_args
        assert "(employmentType='Daily Rate')" in call_args.kwargs["where"]

    def test_new_returns_pagination_envelope(self, mock_client):
        """record_type='new' returns the standard data+pagination envelope."""
        mock_client.query.return_value = [{"id": 1}]
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_placements(record_type="new")
        data = json.loads(result)
        assert "data" in data
        assert "pagination" in data

    # --- record_type="extensions" ---

    def test_extensions_uses_pcr_entity(self, mock_client):
        """record_type='extensions' queries PlacementChangeRequest."""
        mock_client.query.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_placements(record_type="extensions")
        call_args = mock_client.query_with_meta.call_args
        assert call_args.kwargs["entity"] == "PlacementChangeRequest"

    def test_extensions_always_filters_request_type(self, mock_client):
        """requestType='Contract Extension' is always in the WHERE clause."""
        mock_client.query.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_placements(record_type="extensions")
        call_args = mock_client.query_with_meta.call_args
        assert "requestType='Contract Extension'" in call_args.kwargs["where"]

    def test_extensions_date_uses_request_custom_date1(self, mock_client):
        """since is applied to requestCustomDate1 for extensions."""
        mock_client.query.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_placements(record_type="extensions", since="2025-01-01")
        call_args = mock_client.query_with_meta.call_args
        assert "requestCustomDate1 >= 1735689600000" in call_args.kwargs["where"]

    def test_extensions_default_order_by(self, mock_client):
        """record_type='extensions' defaults to order by -requestCustomDate1."""
        mock_client.query.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_placements(record_type="extensions")
        call_args = mock_client.query_with_meta.call_args
        assert call_args.kwargs["order_by"] == "-requestCustomDate1"

    def test_extensions_rows_tagged_record_type_extension(self, mock_client):
        """Rows returned for record_type='extensions' carry record_type='extension'."""
        mock_client.query.return_value = [{"id": 42, "requestType": "Contract Extension"}]
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_placements(record_type="extensions")
        data = json.loads(result)
        assert data["data"][0]["record_type"] == "extension"

    def test_extensions_status_param_ignored(self, mock_client):
        """status param does not appear in the extensions WHERE clause."""
        mock_client.query.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_placements(record_type="extensions", status="Approved")
        call_args = mock_client.query_with_meta.call_args
        # status should not be in the WHERE (it is only for new placements)
        assert "status='Approved'" not in call_args.kwargs["where"]

    # --- record_type="both" ---

    def test_both_returns_new_and_extensions_keys(self, mock_client):
        """record_type='both' returns a dict with 'new' and 'extensions' keys."""
        mock_client.query.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_placements(record_type="both")
        data = json.loads(result)
        assert "new" in data
        assert "extensions" in data

    def test_both_calls_query_twice(self, mock_client):
        """record_type='both' calls query_with_meta twice (once per type)."""
        mock_client.query.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_placements(record_type="both")
        assert mock_client.query_with_meta.call_count == 2

    def test_both_new_and_extensions_have_envelopes(self, mock_client):
        """Each sub-result in 'both' has its own data+pagination envelope."""
        mock_client.query.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_placements(record_type="both")
        data = json.loads(result)
        assert "data" in data["new"]
        assert "pagination" in data["new"]
        assert "data" in data["extensions"]
        assert "pagination" in data["extensions"]

    def test_both_new_rows_tagged_new(self, mock_client):
        """Rows under 'both' -> 'new' are tagged record_type='new'."""
        placement_row = {"id": 1, "status": "Approved"}
        ext_row = {"id": 99, "requestType": "Contract Extension"}

        def side_effect(**kwargs):
            if kwargs.get("entity") == "Placement":
                return {"data": [placement_row.copy()], "total": 1, "start": 0, "count": 1}
            return {"data": [ext_row.copy()], "total": 1, "start": 0, "count": 1}

        mock_client.query_with_meta.side_effect = side_effect

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_placements(record_type="both")
        data = json.loads(result)
        assert data["new"]["data"][0]["record_type"] == "new"
        assert data["extensions"]["data"][0]["record_type"] == "extension"

    # --- error handling ---

    def test_api_error_returns_error_string(self, mock_client):
        """BullhornAPIError is caught and returned as ERROR: prefix string."""
        mock_client.query.side_effect = BullhornAPIError("something went wrong")
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_placements(record_type="new")
        assert result.startswith("ERROR:")

    def test_auth_error_returns_error_string(self, mock_client):
        """AuthenticationError is caught and returned as ERROR: prefix string."""
        mock_client.query.side_effect = AuthenticationError("session expired")
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_placements(record_type="new")
        assert result.startswith("ERROR:")

    # --- pagination ---

    def test_limit_and_start_forwarded(self, mock_client):
        """limit and start are forwarded as count and start to query_with_meta."""
        mock_client.query.return_value = []
        with patch.object(server, "get_client", return_value=mock_client):
            server.list_placements(record_type="new", limit=50, start=100)
        call_args = mock_client.query_with_meta.call_args
        assert call_args.kwargs["count"] == 50
        assert call_args.kwargs["start"] == 100


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
        assert isinstance(contacts_data["data"], list)
        assert "id" in contacts_data["data"][0]

        companies_data = json.loads(companies_result)
        assert isinstance(companies_data["data"], list)
        assert "id" in companies_data["data"][0]


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
        mock_client.create.assert_called_once_with(
            "ClientCorporation", {"name": "Acme Holdings Ltd", "status": "Prospect", "owner": {"id": 1}}
        )

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

        # resolve_fields receives the caller fields plus the auto-injected owner
        meta.resolve_fields.assert_called_once_with(
            "ClientCorporation", {"name": "Acme", "Industry": "Technology", "owner": {"id": 1}}
        )
        # client.create receives the resolved fields (label "Industry" → "industryList")
        mock_client.create.assert_called_once_with(
            "ClientCorporation", {"name": "Acme", "industryList": "Technology", "owner": {"id": 1}}
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

    def test_create_contact_name_always_computed(self, mock_client, mock_metadata):
        """create_contact injects name into payload from firstName + lastName."""
        mock_client.resolve_owner.return_value = {"id": 99}
        mock_client.search.return_value = []
        mock_client.create.return_value = {
            "changedEntityId": 2, "changeType": "INSERT",
            "data": {"id": 2, "firstName": "Jane", "lastName": "Doe"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            server.create_contact({
                "firstName": "Jane", "lastName": "Doe",
                "clientCorporation": {"id": 1}, "owner": {"id": 99},
            })

        call_kwargs = mock_client.create.call_args[0][1]
        assert call_kwargs["name"] == "Jane Doe"

    def test_create_contact_strips_name_field(self, mock_client, mock_metadata):
        """create_contact ignores LLM-supplied 'name', warns, then injects MCP-computed value."""
        mock_client.resolve_owner.return_value = {"id": 99}
        mock_client.search.return_value = []
        mock_client.create.return_value = {
            "changedEntityId": 3, "changeType": "INSERT",
            "data": {"id": 3, "firstName": "Jane", "lastName": "Doe"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.create_contact({
                "firstName": "Jane", "lastName": "Doe",
                "name": "Bogus Name",
                "clientCorporation": {"id": 1}, "owner": {"id": 99},
            })

        data = json.loads(result)
        assert "warnings" in data
        assert any("name" in w for w in data["warnings"])
        call_kwargs = mock_client.create.call_args[0][1]
        assert call_kwargs["name"] == "Jane Doe"


class TestCreateJob:
    """Tests for create_job tool (CR14 dict-based signature)."""

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        return meta

    def test_create_job_minimal_success(self, mock_client, mock_metadata):
        """create_job with only the three required params creates a JobOrder."""
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {"id": 1}}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 42}):
            result = server.create_job(
                clientCorporation={"id": 1},
                clientContact={"id": 2},
                title="Engineer",
            )
        data = json.loads(result)
        assert data["changedEntityId"] == 1
        payload = mock_client.create.call_args.args[1]
        assert payload["clientCorporation"] == {"id": 1}
        assert payload["clientContact"] == {"id": 2}
        assert payload["title"] == "Engineer"
        assert payload["owner"] == {"id": 42}
        assert mock_client.create.call_args.args[0] == "JobOrder"

    def test_create_job_requires_client_corporation(self, mock_client, mock_metadata):
        result = server.create_job(
            clientCorporation=None,
            clientContact={"id": 2},
            title="Engineer",
        )
        data = json.loads(result)
        assert data["error"] == "clientCorporation_required"
        mock_client.create.assert_not_called()

    def test_create_job_rejects_malformed_client_corporation(self, mock_client, mock_metadata):
        result = server.create_job(
            clientCorporation={"name": "Acme"},
            clientContact={"id": 2},
            title="Engineer",
        )
        data = json.loads(result)
        assert data["error"] == "clientCorporation_required"
        mock_client.create.assert_not_called()

    def test_create_job_requires_client_contact(self, mock_client, mock_metadata):
        result = server.create_job(
            clientCorporation={"id": 1},
            clientContact=None,
            title="Engineer",
        )
        data = json.loads(result)
        assert data["error"] == "clientContact_required"
        mock_client.create.assert_not_called()

    def test_create_job_rejects_malformed_client_contact(self, mock_client, mock_metadata):
        result = server.create_job(
            clientCorporation={"id": 1},
            clientContact={"name": "Jane"},
            title="Engineer",
        )
        data = json.loads(result)
        assert data["error"] == "clientContact_required"
        mock_client.create.assert_not_called()

    def test_create_job_requires_title(self, mock_client, mock_metadata):
        for bad_title in [None, "", "   "]:
            mock_client.reset_mock()
            result = server.create_job(
                clientCorporation={"id": 1},
                clientContact={"id": 2},
                title=bad_title,
            )
            data = json.loads(result)
            assert data["error"] == "title_required", f"Expected title_required for {bad_title!r}"
            mock_client.create.assert_not_called()

    def test_create_job_fields_passthrough(self, mock_client, mock_metadata):
        """Arbitrary keys in fields appear in the Bullhorn payload."""
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {"id": 1}}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 42}):
            server.create_job(
                clientCorporation={"id": 1},
                clientContact={"id": 2},
                title="Engineer",
                fields={"source": "Email", "salary": 90000},
            )
        payload = mock_client.create.call_args.args[1]
        assert payload["source"] == "Email"
        assert payload["salary"] == 90000

    def test_create_job_alias_resolution(self, mock_client):
        """resolve_fields is called on caller fields enabling alias substitution."""
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        # Simulate "sector" → "customText1" alias in resolve_fields
        def resolve_with_alias(entity, fields):
            return {("customText1" if k == "sector" else k): v for k, v in fields.items()}
        meta.resolve_fields.side_effect = resolve_with_alias
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {"id": 1}}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta), \
             patch.object(server, "resolve_caller", return_value={"id": 42}):
            server.create_job(
                clientCorporation={"id": 1},
                clientContact={"id": 2},
                title="Engineer",
                fields={"sector": "Technology"},
            )
        payload = mock_client.create.call_args.args[1]
        assert "customText1" in payload
        assert "sector" not in payload

    def test_create_job_defaults_applied(self, mock_client, mock_metadata, monkeypatch):
        """Env defaults are applied to fields the caller does not supply."""
        monkeypatch.setenv("BULLHORN_JOBORDER_DEFAULTS", '{"status": "Accepting Candidates"}')
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {"id": 1}}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 42}):
            server.create_job(
                clientCorporation={"id": 1},
                clientContact={"id": 2},
                title="Engineer",
            )
        payload = mock_client.create.call_args.args[1]
        assert payload["status"] == "Accepting Candidates"

    def test_create_job_caller_overrides_default(self, mock_client, mock_metadata, monkeypatch):
        """Caller-supplied value always wins over env default."""
        monkeypatch.setenv("BULLHORN_JOBORDER_DEFAULTS", '{"status": "Accepting Candidates"}')
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {"id": 1}}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 42}):
            server.create_job(
                clientCorporation={"id": 1},
                clientContact={"id": 2},
                title="Engineer",
                fields={"status": "Closed"},
            )
        payload = mock_client.create.call_args.args[1]
        assert payload["status"] == "Closed"

    def test_create_job_required_validation_passes(self, mock_client, mock_metadata, monkeypatch):
        """Env required field present in caller fields: create proceeds."""
        monkeypatch.setenv("BULLHORN_JOBORDER_REQUIRED", '["source"]')
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {"id": 1}}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 42}):
            result = server.create_job(
                clientCorporation={"id": 1},
                clientContact={"id": 2},
                title="Engineer",
                fields={"source": "Email"},
            )
        data = json.loads(result)
        assert data["changedEntityId"] == 1

    def test_create_job_required_validation_fails(self, mock_client, mock_metadata, monkeypatch):
        """Env required field absent from caller fields: returns required_fields_missing."""
        monkeypatch.setenv("BULLHORN_JOBORDER_REQUIRED", '["source"]')
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 42}):
            result = server.create_job(
                clientCorporation={"id": 1},
                clientContact={"id": 2},
                title="Engineer",
            )
        data = json.loads(result)
        assert data["error"] == "required_fields_missing"
        assert "source" in data["fields"]
        mock_client.create.assert_not_called()

    def test_create_job_required_via_alias(self, mock_client, monkeypatch):
        """Env required list with alias entries resolves to API names before validation."""
        monkeypatch.setenv("BULLHORN_JOBORDER_REQUIRED", '["sector"]')
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        # "sector" resolves to "customText1"
        def resolve(entity, fields):
            return {("customText1" if k == "sector" else k): v for k, v in fields.items()}
        meta.resolve_fields.side_effect = resolve
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta), \
             patch.object(server, "resolve_caller", return_value={"id": 42}):
            # No "sector" or "customText1" supplied — required check must fail
            result = server.create_job(
                clientCorporation={"id": 1},
                clientContact={"id": 2},
                title="Engineer",
            )
        data = json.loads(result)
        assert data["error"] == "required_fields_missing"
        mock_client.create.assert_not_called()

    def test_create_job_owner_auto_populated(self, mock_client, mock_metadata):
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {"id": 1}}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 77, "email": "user@example.com"}):
            server.create_job(
                clientCorporation={"id": 1},
                clientContact={"id": 2},
                title="Engineer",
            )
        payload = mock_client.create.call_args.args[1]
        assert payload["owner"] == {"id": 77}

    def test_create_job_explicit_owner_wins(self, mock_client, mock_metadata):
        """Caller-supplied owner in fields is used; resolve_caller is not called."""
        mock_client.resolve_owner.return_value = {"id": 99}
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {"id": 1}}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller") as mock_resolve:
            server.create_job(
                clientCorporation={"id": 1},
                clientContact={"id": 2},
                title="Engineer",
                fields={"owner": {"id": 99}},
            )
        mock_resolve.assert_not_called()
        assert mock_client.create.call_args.args[1]["owner"] == {"id": 99}

    def test_create_job_owner_ambiguous(self, mock_client, mock_metadata):
        """create_job returns owner_ambiguous when a name resolves to multiple CorporateUsers."""
        mock_client.resolve_owner.return_value = [
            {"id": 10, "firstName": "John", "lastName": "Smith", "email": "j1@firm.com"},
            {"id": 11, "firstName": "John", "lastName": "Smith", "email": "j2@firm.com"},
        ]
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.create_job(
                clientCorporation={"id": 1},
                clientContact={"id": 2},
                title="Engineer",
                fields={"owner": "John Smith"},
            )
        data = json.loads(result)
        assert data["error"] == "owner_ambiguous"
        assert len(data["matches"]) == 2
        mock_client.create.assert_not_called()

    def test_create_job_identity_resolution_fails(self, mock_client, mock_metadata):
        from bullhorn_mcp.identity import IdentityResolutionError
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("No token")):
            result = server.create_job(
                clientCorporation={"id": 1},
                clientContact={"id": 2},
                title="Engineer",
            )
        data = json.loads(result)
        assert data["error"] == "identity_resolution_failed"
        mock_client.create.assert_not_called()

    def test_create_job_payload_no_unexpected_keys(self, mock_client, mock_metadata):
        """No website_* or other placeholder keys from CR13 leak into the Bullhorn payload."""
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {"id": 1}}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 42}):
            server.create_job(
                clientCorporation={"id": 1},
                clientContact={"id": 2},
                title="Engineer",
            )
        payload = mock_client.create.call_args.args[1]
        for bad_key in [
            "website_sector_range", "website_salary_range", "website_location",
            "source", "grade", "fee", "salary",
        ]:
            assert bad_key not in payload, f"Unexpected key in payload: {bad_key}"


def test_joborder_no_legacy_validation():
    """CR14 removal: legacy helpers from CR13 must not exist in server module."""
    import bullhorn_mcp.server as srv
    for name in [
        "JOB_REQUIRED_BUSINESS_FIELDS",
        "_missing_job_required_fields",
        "_validate_job_fields_known",
        "_validate_job_reference",
    ]:
        assert not hasattr(srv, name), f"Legacy symbol still present in server.py: {name}"


class TestUpdateJob:
    """Tests for update_job tool."""

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        return meta

    def test_update_job_success(self, mock_client, mock_metadata):
        mock_client.update.return_value = {
            "changedEntityId": 12345,
            "changeType": "UPDATE",
            "data": {"id": 12345, "title": "Senior Engineer"},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.update_job(12345, {"title": "Senior Engineer"})

        data = json.loads(result)
        assert data["changedEntityId"] == 12345
        mock_client.update.assert_called_once_with("JobOrder", 12345, {"title": "Senior Engineer"})

    def test_update_job_label_resolution(self, mock_client):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.return_value = {"publicDescription": "Copy"}
        mock_client.update.return_value = {"changedEntityId": 1, "changeType": "UPDATE", "data": {"id": 1}}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta):
            server.update_job(1, {"Published Description": "Copy"})

        meta.resolve_fields.assert_called_once_with("JobOrder", {"Published Description": "Copy"})
        mock_client.update.assert_called_once_with("JobOrder", 1, {"publicDescription": "Copy"})

    def test_update_job_public_description_alias(self, mock_client):
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = BullhornMetadata(mock_client)
        mock_client.get_meta.return_value = {"fields": []}
        mock_client.update.return_value = {"changedEntityId": 1, "changeType": "UPDATE", "data": {"id": 1}}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta):
            server.update_job(1, {"published description": "Copy"})

        mock_client.update.assert_called_once_with("JobOrder", 1, {"publicDescription": "Copy"})

    def test_update_job_publish_on_website_alias(self, mock_client):
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = BullhornMetadata(mock_client)
        mock_client.get_meta.return_value = {"fields": []}
        mock_client.update.return_value = {"changedEntityId": 1, "changeType": "UPDATE", "data": {"id": 1}}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta):
            server.update_job(1, {"publish on website": 0})

        mock_client.update.assert_called_once_with("JobOrder", 1, {"customText12": 0})

    def test_update_job_does_not_strip_title(self, mock_client, mock_metadata):
        mock_client.update.return_value = {"changedEntityId": 1, "changeType": "UPDATE", "data": {"id": 1}}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            server.update_job(1, {"title": "Senior Engineer"})

        assert mock_client.update.call_args.args[2] == {"title": "Senior Engineer"}

    def test_update_job_payload_only_contains_caller_fields(self, mock_client, mock_metadata):
        mock_client.update.return_value = {"changedEntityId": 1, "changeType": "UPDATE", "data": {"id": 1}}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller") as mock_resolve:
            server.update_job(1, {"publicDescription": "Copy"})

        mock_resolve.assert_not_called()
        assert mock_client.update.call_args.args[2] == {"publicDescription": "Copy"}

    def test_update_job_api_error(self, mock_client, mock_metadata):
        mock_client.update.side_effect = BullhornAPIError("update failed")
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.update_job(1, {"title": "Senior Engineer"})

        assert result.startswith("ERROR:")


class TestSprint21JobOrderE2E:
    """E2E-style tests for first-class JobOrder write tools."""

    @pytest.fixture
    def mock_auth(self, mock_session):
        from unittest.mock import Mock, PropertyMock
        from bullhorn_mcp.auth import BullhornAuth
        auth = Mock(spec=BullhornAuth)
        type(auth).session = PropertyMock(return_value=mock_session)
        return auth

    def _job_meta_response(self):
        names = [
            "clientCorporation",
            "clientContact",
            "title",
            "source",
            "grade",
            "fee",
            "salary",
            "website_sector_range",
            "website_salary_range",
            "website_location",
            "status",
            "isOpen",
            "customText12",
            "publicDescription",
            "description",
            "owner",
        ]
        return {
            "entity": "JobOrder",
            "fields": [
                {"name": name, "label": name, "type": "STRING", "required": False}
                for name in names
            ],
        }

    def test_e2e_create_job_minimal(self, mock_auth, mock_session):
        """Minimal create_job call sends only the 3 required params plus owner; no placeholder keys."""
        import httpx
        import respx
        from bullhorn_mcp.client import BullhornClient
        from bullhorn_mcp.metadata import BullhornMetadata

        captured = {}

        def capture_put(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"changedEntityId": 1, "changeType": "INSERT"})

        real_client = BullhornClient(mock_auth)
        real_metadata = BullhornMetadata(real_client)

        with respx.mock:
            respx.get(f"{mock_session.rest_url}/meta/JobOrder").mock(
                return_value=httpx.Response(200, json={"entity": "JobOrder", "fields": []})
            )
            respx.put(f"{mock_session.rest_url}/entity/JobOrder").mock(side_effect=capture_put)
            respx.get(f"{mock_session.rest_url}/entity/JobOrder/1").mock(
                return_value=httpx.Response(200, json={"data": {"id": 1, "title": "Engineer"}})
            )

            with patch.object(server, "get_client", return_value=real_client), \
                 patch.object(server, "get_metadata", return_value=real_metadata), \
                 patch.object(server, "resolve_caller", return_value={"id": 42}):
                result = server.create_job(
                    clientCorporation={"id": 1},
                    clientContact={"id": 2},
                    title="Engineer",
                )

        data = json.loads(result)
        assert data["changedEntityId"] == 1
        # Raw PUT body must be exactly these 4 keys — no website_* or other injected keys
        assert captured["body"] == {
            "clientCorporation": {"id": 1},
            "clientContact": {"id": 2},
            "title": "Engineer",
            "owner": {"id": 42},
        }

    def test_e2e_create_job_with_defaults(self, mock_auth, mock_session, monkeypatch):
        """Env defaults are applied to the Bullhorn payload; caller fields still win on conflict."""
        import httpx
        import respx
        from bullhorn_mcp.client import BullhornClient
        from bullhorn_mcp.metadata import BullhornMetadata

        monkeypatch.setenv(
            "BULLHORN_JOBORDER_DEFAULTS",
            '{"status": "Accepting Candidates", "isOpen": true, "customText12": 0}',
        )
        captured = {}

        def capture_put(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"changedEntityId": 1, "changeType": "INSERT"})

        real_client = BullhornClient(mock_auth)
        real_metadata = BullhornMetadata(real_client)

        with respx.mock:
            respx.get(f"{mock_session.rest_url}/meta/JobOrder").mock(
                return_value=httpx.Response(200, json={"entity": "JobOrder", "fields": []})
            )
            respx.put(f"{mock_session.rest_url}/entity/JobOrder").mock(side_effect=capture_put)
            respx.get(f"{mock_session.rest_url}/entity/JobOrder/1").mock(
                return_value=httpx.Response(200, json={"data": {"id": 1}})
            )

            with patch.object(server, "get_client", return_value=real_client), \
                 patch.object(server, "get_metadata", return_value=real_metadata), \
                 patch.object(server, "resolve_caller", return_value={"id": 42}):
                result = server.create_job(
                    clientCorporation={"id": 1},
                    clientContact={"id": 2},
                    title="Engineer",
                    fields={"publicDescription": "Interesting role."},
                )

        data = json.loads(result)
        assert data["changedEntityId"] == 1
        assert captured["body"]["status"] == "Accepting Candidates"
        assert captured["body"]["isOpen"] is True
        assert captured["body"]["customText12"] == 0
        assert captured["body"]["publicDescription"] == "Interesting role."
        assert captured["body"]["owner"] == {"id": 42}

    def test_e2e_update_job_public_description(self, mock_auth, mock_session):
        """Full update_job path resolves published-description alias before POST."""
        import httpx
        import respx
        from bullhorn_mcp.client import BullhornClient
        from bullhorn_mcp.metadata import BullhornMetadata

        captured = {}

        def capture_post(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"changedEntityId": 12345, "changeType": "UPDATE"})

        updated_record = {
            "id": 12345,
            "publicDescription": "Updated public-facing job description...",
        }
        real_client = BullhornClient(mock_auth)
        real_metadata = BullhornMetadata(real_client)

        with respx.mock:
            respx.post(f"{mock_session.rest_url}/entity/JobOrder/12345").mock(
                side_effect=capture_post
            )
            respx.get(f"{mock_session.rest_url}/entity/JobOrder/12345").mock(
                return_value=httpx.Response(200, json={"data": updated_record})
            )

            with patch.object(server, "get_client", return_value=real_client), \
                 patch.object(server, "get_metadata", return_value=real_metadata):
                result = server.update_job(
                    12345,
                    {"published description": "Updated public-facing job description..."},
                )

        data = json.loads(result)
        assert data["changedEntityId"] == 12345
        assert captured["body"] == {
            "publicDescription": "Updated public-facing job description..."
        }


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

    def test_update_record_candidate_name_recomputed_both(self, mock_client, mock_metadata):
        """update_record recomputes name when both firstName and lastName in payload — no GET needed."""
        mock_client.update.return_value = {
            "changedEntityId": 10, "changeType": "UPDATE",
            "data": {"id": 10, "firstName": "New", "lastName": "Name"},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            server.update_record("Candidate", 10, {"firstName": "New", "lastName": "Name"})

        mock_client.get.assert_not_called()
        payload = mock_client.update.call_args[0][2]
        assert payload["name"] == "New Name"

    def test_update_record_candidate_name_recomputed_first_only(self, mock_client, mock_metadata):
        """update_record fetches missing lastName to recompute name when only firstName updated."""
        mock_client.get.return_value = {"firstName": "Old", "lastName": "Smith"}
        mock_client.update.return_value = {
            "changedEntityId": 11, "changeType": "UPDATE",
            "data": {"id": 11},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            server.update_record("Candidate", 11, {"firstName": "Updated"})

        mock_client.get.assert_called_once_with("Candidate", 11, fields="firstName,lastName")
        payload = mock_client.update.call_args[0][2]
        assert payload["name"] == "Updated Smith"

    def test_update_record_candidate_name_recomputed_last_only(self, mock_client, mock_metadata):
        """update_record fetches missing firstName to recompute name when only lastName updated."""
        mock_client.get.return_value = {"firstName": "Jane", "lastName": "Old"}
        mock_client.update.return_value = {
            "changedEntityId": 12, "changeType": "UPDATE",
            "data": {"id": 12},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            server.update_record("Candidate", 12, {"lastName": "Updated"})

        mock_client.get.assert_called_once_with("Candidate", 12, fields="firstName,lastName")
        payload = mock_client.update.call_args[0][2]
        assert payload["name"] == "Jane Updated"

    def test_update_record_candidate_no_name_recompute_other_fields(self, mock_client, mock_metadata):
        """update_record does not recompute name when neither firstName nor lastName is updated."""
        mock_client.update.return_value = {
            "changedEntityId": 13, "changeType": "UPDATE",
            "data": {"id": 13},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            server.update_record("Candidate", 13, {"occupation": "Engineer"})

        mock_client.get.assert_not_called()
        payload = mock_client.update.call_args[0][2]
        assert "name" not in payload

    def test_update_record_contact_name_recomputed(self, mock_client, mock_metadata):
        """update_record recomputes name for ClientContact too."""
        mock_client.update.return_value = {
            "changedEntityId": 14, "changeType": "UPDATE",
            "data": {"id": 14},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            server.update_record("ClientContact", 14, {"firstName": "Alice", "lastName": "Brown"})

        mock_client.get.assert_not_called()
        payload = mock_client.update.call_args[0][2]
        assert payload["name"] == "Alice Brown"

    def test_update_record_other_entity_no_name_injection(self, mock_client, mock_metadata):
        """update_record does not inject name for entities other than Candidate/ClientContact."""
        mock_client.update.return_value = {
            "changedEntityId": 15, "changeType": "UPDATE",
            "data": {"id": 15},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            server.update_record("ClientCorporation", 15, {"firstName": "Acme", "lastName": "Corp"})

        mock_client.get.assert_not_called()
        payload = mock_client.update.call_args[0][2]
        assert "name" not in payload


class TestAddNote:
    """Tests for add_note tool."""

    def test_add_note_to_contact_success(self, mock_client):
        """add_note returns Note ID on success."""
        from bullhorn_mcp.identity import IdentityResolutionError
        mock_client.add_note.return_value = {
            "changedEntityId": 88901,
            "changeType": "INSERT",
            "data": {"id": 88901, "action": "General Note", "comments": "Test"},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")):
            result = server.add_note("ClientContact", 54321, "General Note", "Test")

        data = json.loads(result)
        assert data["changedEntityId"] == 88901
        assert data["changeType"] == "INSERT"

    def test_add_note_to_candidate_success(self, mock_client):
        """add_note works for Candidate entity."""
        from bullhorn_mcp.identity import IdentityResolutionError
        mock_client.add_note.return_value = {
            "changedEntityId": 88903,
            "changeType": "INSERT",
            "data": {"id": 88903, "action": "General Note"},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")):
            result = server.add_note("Candidate", 11111, "General Note", "Strong fit")

        data = json.loads(result)
        assert data["changedEntityId"] == 88903
        mock_client.add_note.assert_called_once_with(
            "Candidate", 11111, "General Note", "Strong fit", commenting_person_id=None
        )

    def test_add_note_invalid_entity(self, mock_client):
        """add_note returns error for unsupported entity type."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.add_note("FooBar", 1, "General Note", "Test")

        data = json.loads(result)
        assert data["error"] == "invalid_entity"
        mock_client.add_note.assert_not_called()

    def test_add_note_resolves_caller_for_commenting_person(self, mock_client):
        """add_note passes caller id as commenting_person_id when identity resolves."""
        mock_client.add_note.return_value = {
            "changedEntityId": 88904,
            "changeType": "INSERT",
            "data": {"id": 88904},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "resolve_caller", return_value={"id": 99, "email": "me@firm.com"}):
            server.add_note("JobOrder", 22222, "General Note", "On hold")

        mock_client.add_note.assert_called_once_with(
            "JobOrder", 22222, "General Note", "On hold", commenting_person_id=99
        )

    def test_add_note_handles_identity_resolution_error(self, mock_client):
        """add_note falls back to commenting_person_id=None when identity resolution fails."""
        from bullhorn_mcp.identity import IdentityResolutionError
        mock_client.add_note.return_value = {
            "changedEntityId": 88905,
            "changeType": "INSERT",
            "data": {"id": 88905},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")):
            result = server.add_note("Placement", 33333, "General Note", "Started")

        data = json.loads(result)
        assert data["changedEntityId"] == 88905
        mock_client.add_note.assert_called_once_with(
            "Placement", 33333, "General Note", "Started", commenting_person_id=None
        )

    def test_add_note_api_error(self, mock_client):
        """add_note returns ERROR prefix on API failure."""
        from bullhorn_mcp.identity import IdentityResolutionError
        mock_client.add_note.side_effect = BullhornAPIError("invalid action type")
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")):
            result = server.add_note("ClientContact", 1, "Bad Action", "note")
        assert result.startswith("ERROR:")

    def test_add_note_value_error_returns_error_prefix(self, mock_client):
        """add_note returns ERROR prefix when client raises ValueError (e.g. entity/dispatch divergence)."""
        from bullhorn_mcp.identity import IdentityResolutionError
        mock_client.add_note.side_effect = ValueError("add_note does not support entity 'NewEntity'")
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")):
            result = server.add_note("ClientContact", 1, "General Note", "note")
        assert result.startswith("ERROR:")

    def test_invalid_action_blocked_with_valid_list(self, mock_client):
        """add_note returns invalid_action error when action is not in picklist."""
        valid = {"General Note", "Outbound Call", "Email"}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "_load_valid_note_actions", return_value=valid):
            result = server.add_note("Candidate", 1, "Bogus Action", "test")

        data = json.loads(result)
        assert data["error"] == "invalid_action"
        assert "Bogus Action" in data["message"]
        assert sorted(data["valid_actions"]) == sorted(valid)
        mock_client.add_note.assert_not_called()

    def test_valid_action_passes_through(self, mock_client):
        """add_note succeeds when action is in the picklist."""
        from bullhorn_mcp.identity import IdentityResolutionError
        valid = {"General Note", "Outbound Call"}
        mock_client.add_note.return_value = {
            "changedEntityId": 999, "changeType": "INSERT",
            "data": {"id": 999, "action": "General Note"},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")), \
             patch.object(server, "_load_valid_note_actions", return_value=valid):
            result = server.add_note("Candidate", 1, "General Note", "note")

        data = json.loads(result)
        assert data["changedEntityId"] == 999
        mock_client.add_note.assert_called_once()

    def test_action_validation_skipped_when_picklist_unavailable(self, mock_client):
        """add_note proceeds without validation when picklist cannot be loaded."""
        from bullhorn_mcp.identity import IdentityResolutionError
        mock_client.add_note.return_value = {
            "changedEntityId": 998, "changeType": "INSERT",
            "data": {"id": 998},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")), \
             patch.object(server, "_load_valid_note_actions", return_value=None):
            result = server.add_note("Candidate", 1, "Any Action", "note")

        data = json.loads(result)
        assert data["changedEntityId"] == 998
        mock_client.add_note.assert_called_once()

    def test_load_valid_note_actions_returns_set_from_metadata(self, mock_client):
        """_load_valid_note_actions extracts values from Note.action picklist options."""
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.get_fields.return_value = [
            {
                "name": "action",
                "options": [
                    {"value": "General Note"},
                    {"value": "Outbound Call"},
                    {"value": ""},
                ],
            },
            {"name": "comments"},
        ]
        result = server._load_valid_note_actions(meta)
        assert result == {"General Note", "Outbound Call"}
        meta.get_fields.assert_called_once_with("Note")

    def test_load_valid_note_actions_returns_none_when_no_action_field(self, mock_client):
        """_load_valid_note_actions returns None when Note metadata has no action field."""
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.get_fields.return_value = [{"name": "comments"}, {"name": "dateAdded"}]
        result = server._load_valid_note_actions(meta)
        assert result is None

    def test_load_valid_note_actions_returns_none_when_options_empty(self, mock_client):
        """_load_valid_note_actions returns None when action field has no options."""
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.get_fields.return_value = [{"name": "action", "options": []}]
        result = server._load_valid_note_actions(meta)
        assert result is None

    def test_load_valid_note_actions_returns_none_on_metadata_exception(self, mock_client):
        """_load_valid_note_actions returns None and does not raise when metadata fails."""
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.get_fields.side_effect = Exception("metadata unavailable")
        result = server._load_valid_note_actions(meta)
        assert result is None


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
        """Same name with different email is flagged as partial_match."""
        mock_client.search.return_value = [
            {"id": 11, "firstName": "John", "lastName": "Smith",
             "email": "other@co.com", "phone": None, "clientCorporation": {"id": 123}}
        ]
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_contacts(
                "John", "Smith", client_corporation_id=123, email="john@co.com"
            )

        data = json.loads(result)
        assert data["matches"][0].get("partial_match") is True

    def test_find_duplicate_contacts_same_email_not_partial(self, mock_client):
        """Same name with same email is not flagged as partial_match."""
        mock_client.search.return_value = [
            {"id": 11, "firstName": "John", "lastName": "Smith",
             "email": "john@co.com", "phone": None, "clientCorporation": {"id": 123}}
        ]
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_contacts(
                "John", "Smith", client_corporation_id=123, email="john@co.com"
            )

        data = json.loads(result)
        assert "partial_match" not in data["matches"][0]

    def test_find_duplicate_contacts_without_email_preserves_existing_shape(self, mock_client):
        """Without input email, same-name matches are returned without partial_match."""
        mock_client.search.return_value = [
            {"id": 11, "firstName": "John", "lastName": "Smith",
             "email": "other@co.com", "phone": None, "clientCorporation": {"id": 123}}
        ]
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_contacts("John", "Smith", 123)

        data = json.loads(result)
        assert data["matches"][0]["category"] == "exact"
        assert "partial_match" not in data["matches"][0]

    def test_find_duplicate_contacts_by_company_name(self, mock_client):
        """Resolves a company name to ClientCorporation ID before searching contacts."""
        mock_client.search.side_effect = [
            [{"id": 123, "name": "Acme Ltd", "status": "Active", "phone": None}],
            [{"id": 11, "firstName": "John", "lastName": "Smith",
              "email": "john@acme.com", "phone": None,
              "clientCorporation": {"id": 123, "name": "Acme Ltd"}}],
        ]
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_contacts(
                "John", "Smith", company_name="Acme Limited"
            )

        data = json.loads(result)
        assert data["query"]["clientCorporation"]["id"] == 123
        assert data["resolved_company"]["id"] == 123
        assert data["matches"][0]["record"]["id"] == 11
        assert mock_client.search.call_args_list[0].args[0] == "ClientCorporation"
        assert mock_client.search.call_args_list[1].args[0] == "ClientContact"

    def test_find_duplicate_contacts_requires_company_reference(self, mock_client):
        """Returns a structured error when no company reference is supplied."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_contacts("John", "Smith")

        data = json.loads(result)
        assert data["error"] == "company_reference_required"
        mock_client.search.assert_not_called()

    def test_find_duplicate_contacts_company_name_no_match(self, mock_client):
        """Returns structured error when company_name cannot be resolved."""
        mock_client.search.return_value = [
            {"id": 999, "name": "Globex Corporation", "status": "Active", "phone": None}
        ]
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_contacts(
                "John", "Smith", company_name="Acme Limited"
            )

        data = json.loads(result)
        assert data["error"] == "company_not_found"
        assert mock_client.search.call_count == 1

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

    def test_sprint20_find_duplicate_contacts_company_name_flow(self, mock_client):
        """E2E-style flow: resolve company name, then return likely contact duplicate."""
        mock_client.search.side_effect = [
            [{"id": 44321, "name": "Bank of New York Mellon", "status": "Active"}],
            [{"id": 11234, "firstName": "John", "lastName": "Smyth",
              "email": "john.smyth@bnymellon.com", "phone": "+1 212 495 2000",
              "clientCorporation": {"id": 44321, "name": "Bank of New York Mellon"}}],
        ]
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_contacts(
                "John", "Smith", company_name="BNY", email="john.smith@bnymellon.com"
            )

        data = json.loads(result)
        assert data["resolved_company"]["id"] == 44321
        assert data["matches"][0]["category"] in {"likely", "possible"}
        assert data["matches"][0]["record"]["id"] == 11234
        assert mock_client.search.call_args_list[0].kwargs["query"] == "name:B*"

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
        assert "partial_match" not in data["matches"][0]  # no query email was provided


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
        assert "create_job" in tools
        assert "update_job" in tools
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
        """PUT body for create_contact contains exactly the caller-provided keys plus MCP-computed name.

        Only 'owner' is transformed (string → {"id": int}); 'name' is always
        computed by the MCP from firstName + lastName. No other fields are added.
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
        assert set(create_fields.keys()) == {"firstName", "lastName", "clientCorporation", "owner", "name"}
        assert create_fields["name"] == "Jane Doe"

    def test_create_contact_owner_normalised_not_injected(self, mock_client, mock_metadata):
        """When owner is a name string, only that key is transformed; name is MCP-computed."""
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
        assert set(create_fields.keys()) == {"firstName", "lastName", "clientCorporation", "owner", "name"}
        assert create_fields["owner"] == {"id": 55}
        assert create_fields["name"] == "Jane Doe"

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

        # The PUT body must contain exactly the caller-supplied fields plus MCP-computed name
        create_fields = mock_client.create.call_args[0][1]
        assert create_fields == {
            "firstName": "Jane",
            "lastName": "Doe",
            "name": "Jane Doe",
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
        """E2E: update_record("ClientContact", 1, {"firstName": "Aleksandr"}) sends firstName + name.

        Exercises the full stack: server.update_record() → metadata.resolve_fields()
        → client.update() → HTTP POST. Captures the raw POST body and asserts it contains
        firstName and the MCP-computed name (fetched from current record for missing lastName).
        No other unexpected keys are injected.
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

        # Current record has both firstName and lastName so name can be fully computed
        contact_record = {"id": 1, "firstName": "Old", "lastName": "Smith"}

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
        # name is MCP-computed from the updated firstName + fetched lastName
        assert captured["body"] == {"firstName": "Aleksandr", "name": "Aleksandr Smith"}, (
            f"POST body was unexpected: {captured['body']}"
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

    def test_main_stdio_logs_transport(self, caplog):
        """main() logs the active stdio transport mode before running."""
        with patch.object(server, "_transport_mode", "stdio"):
            with patch.object(server.mcp, "run"):
                with caplog.at_level("INFO", logger="bullhorn_mcp.server"):
                    server.main()

        assert "Starting Bullhorn MCP server in stdio mode" in caplog.text

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

    @pytest.mark.asyncio
    async def test_sprint20_http_transport_smoke_request(self):
        """In-process streamable HTTP request reaches a registered MCP tool."""
        import httpx
        from fastmcp import Client
        from fastmcp.client.transports import StreamableHttpTransport

        app = server.mcp.http_app(
            path="/mcp",
            transport="streamable-http",
            stateless_http=True,
        )

        def httpx_client_factory(**kwargs):
            kwargs.setdefault("base_url", "http://testserver")
            return httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                **kwargs,
            )

        mock_bullhorn = Mock()
        mock_bullhorn.search.return_value = [{"id": 1, "title": "Smoke"}]
        mock_bullhorn.search_with_meta.return_value = {
            "data": [{"id": 1, "title": "Smoke"}], "total": 1, "start": 0, "count": 1
        }

        async with app.router.lifespan_context(app):
            transport = StreamableHttpTransport(
                "http://testserver/mcp",
                httpx_client_factory=httpx_client_factory,
            )
            async with Client(transport) as client:
                assert await client.ping()

                tool_names = {tool.name for tool in await client.list_tools()}
                assert "list_jobs" in tool_names

                with patch.object(server, "get_client", return_value=mock_bullhorn):
                    result = await client.call_tool("list_jobs", {"limit": 1})

        assert not result.is_error
        assert "Smoke" in str(result.data)
        mock_bullhorn.search_with_meta.assert_called_once()


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
        # The owner value must be only {id: 42} — no other CorporateUser fields leaked
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
        token.claims = {"sub": "sub-beau", "email": "beau@thepanel.com"}

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
        token.claims = {"sub": "sub-beau", "email": "beau@thepanel.com"}

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


class TestShortlistCandidate:
    """Tests for shortlist_candidate tool (CR15)."""

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        meta.get_fields.return_value = []
        return meta

    def _no_duplicate(self, mock_client):
        mock_client.query.return_value = []

    def _with_duplicate(self, mock_client, existing_id=9999):
        mock_client.query.return_value = [{"id": existing_id, "status": "Shortlisted"}]

    def test_minimal_success(self, mock_client, mock_metadata):
        """shortlist_candidate creates a JobSubmission with auto-stamped sendingUser and dateWebResponse."""
        self._no_duplicate(mock_client)
        mock_client.create.return_value = {
            "changedEntityId": 501,
            "changeType": "INSERT",
            "data": {"id": 501},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 42}):
            result = server.shortlist_candidate(job_id=10, candidate_id=20)

        data = json.loads(result)
        assert data["changedEntityId"] == 501
        assert data["duplicate"] is False

        call_payload = mock_client.create.call_args[0][1]
        assert call_payload["candidate"] == {"id": 20}
        assert call_payload["jobOrder"] == {"id": 10}
        assert call_payload["status"] == "Shortlisted"
        assert call_payload["sendingUser"] == {"id": 42}
        assert "dateWebResponse" in call_payload
        assert isinstance(call_payload["dateWebResponse"], int)

    def test_status_override(self, mock_client, mock_metadata, monkeypatch):
        """Caller-supplied status overrides the configured default."""
        monkeypatch.setenv("BULLHORN_SHORTLIST_STATUS", "Internal Review")
        self._no_duplicate(mock_client)
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {}}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            server.shortlist_candidate(job_id=10, candidate_id=20, status="Long-listed")

        call_payload = mock_client.create.call_args[0][1]
        assert call_payload["status"] == "Long-listed"

    def test_status_env_default(self, mock_client, mock_metadata, monkeypatch):
        """Configured BULLHORN_SHORTLIST_STATUS is used when no status passed."""
        monkeypatch.setenv("BULLHORN_SHORTLIST_STATUS", "Pre-screen")
        self._no_duplicate(mock_client)
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {}}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            server.shortlist_candidate(job_id=10, candidate_id=20)

        call_payload = mock_client.create.call_args[0][1]
        assert call_payload["status"] == "Pre-screen"

    def test_fields_dict_merged(self, mock_client, mock_metadata):
        """Extra fields are merged into the payload."""
        self._no_duplicate(mock_client)
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {}}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            server.shortlist_candidate(job_id=10, candidate_id=20, fields={"source": "Web", "comments": "Strong match"})

        call_payload = mock_client.create.call_args[0][1]
        assert call_payload["source"] == "Web"
        assert call_payload["comments"] == "Strong match"

    def test_fields_status_does_not_override_status_param(self, mock_client, mock_metadata):
        """status key in fields dict must not override the dedicated status parameter."""
        self._no_duplicate(mock_client)
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {}}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            server.shortlist_candidate(
                job_id=10, candidate_id=20, status="Shortlisted",
                fields={"status": "Rejected", "source": "Web"},
            )

        call_payload = mock_client.create.call_args[0][1]
        assert call_payload["status"] == "Shortlisted"
        assert call_payload["source"] == "Web"

    def test_fields_alias_resolution(self, mock_client, mock_metadata):
        """resolve_fields is called before building the payload."""
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.get_fields.return_value = []
        # Simulate alias resolution: "Source" → "source"
        meta.resolve_fields.side_effect = lambda entity, fields: {
            k.lower(): v for k, v in fields.items()
        }
        self._no_duplicate(mock_client)
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {}}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            server.shortlist_candidate(job_id=10, candidate_id=20, fields={"Source": "Web"})

        call_payload = mock_client.create.call_args[0][1]
        assert "source" in call_payload

    def test_sending_user_autostamp(self, mock_client, mock_metadata):
        """sendingUser is auto-stamped from resolve_caller when not in fields."""
        self._no_duplicate(mock_client)
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {}}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 77}):
            server.shortlist_candidate(job_id=10, candidate_id=20)

        call_payload = mock_client.create.call_args[0][1]
        assert call_payload["sendingUser"] == {"id": 77}

    def test_sending_user_override(self, mock_client, mock_metadata):
        """Caller-supplied sendingUser wins over auto-stamp."""
        self._no_duplicate(mock_client)
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {}}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 77}):
            server.shortlist_candidate(job_id=10, candidate_id=20, fields={"sendingUser": {"id": 99}})

        call_payload = mock_client.create.call_args[0][1]
        assert call_payload["sendingUser"] == {"id": 99}

    def test_sending_user_identity_failure(self, mock_client, mock_metadata):
        """On IdentityResolutionError, sendingUser is omitted and create still proceeds."""
        from bullhorn_mcp.identity import IdentityResolutionError
        self._no_duplicate(mock_client)
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {}}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")):
            result = server.shortlist_candidate(job_id=10, candidate_id=20)

        mock_client.create.assert_called_once()
        call_payload = mock_client.create.call_args[0][1]
        assert "sendingUser" not in call_payload
        data = json.loads(result)
        assert data["changedEntityId"] == 1

    def test_date_web_response_autostamp(self, mock_client, mock_metadata):
        """dateWebResponse is auto-stamped to a current Unix ms timestamp."""
        import time
        self._no_duplicate(mock_client)
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {}}

        before = int(time.time() * 1000)
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            server.shortlist_candidate(job_id=10, candidate_id=20)
        after = int(time.time() * 1000)

        call_payload = mock_client.create.call_args[0][1]
        assert before <= call_payload["dateWebResponse"] <= after

    def test_date_web_response_override(self, mock_client, mock_metadata):
        """Caller-supplied dateWebResponse wins over auto-stamp."""
        self._no_duplicate(mock_client)
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {}}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            server.shortlist_candidate(job_id=10, candidate_id=20, fields={"dateWebResponse": 1234567890})

        call_payload = mock_client.create.call_args[0][1]
        assert call_payload["dateWebResponse"] == 1234567890

    def test_duplicate_existing_returned(self, mock_client, mock_metadata):
        """If a JobSubmission exists, it is returned with duplicate=true and no create called."""
        self._with_duplicate(mock_client, existing_id=888)

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.shortlist_candidate(job_id=10, candidate_id=20)

        mock_client.create.assert_not_called()
        data = json.loads(result)
        assert data["duplicate"] is True
        assert data["existing"]["id"] == 888

    def test_duplicate_none_creates(self, mock_client, mock_metadata):
        """When no existing submission is found, create is called."""
        self._no_duplicate(mock_client)
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {}}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            server.shortlist_candidate(job_id=10, candidate_id=20)

        mock_client.create.assert_called_once()

    def test_invalid_job_id(self, mock_client, mock_metadata):
        """Non-positive job_id returns structured error without API calls."""
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.shortlist_candidate(job_id=0, candidate_id=20)

        data = json.loads(result)
        assert data["error"] == "invalid_argument"
        mock_client.create.assert_not_called()
        mock_client.query.assert_not_called()

    def test_invalid_candidate_id(self, mock_client, mock_metadata):
        """Non-positive candidate_id returns structured error without API calls."""
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.shortlist_candidate(job_id=10, candidate_id=-5)

        data = json.loads(result)
        assert data["error"] == "invalid_argument"
        mock_client.create.assert_not_called()

    def test_api_error_propagates(self, mock_client, mock_metadata):
        """BullhornAPIError during create returns ERROR: string."""
        self._no_duplicate(mock_client)
        mock_client.create.side_effect = BullhornAPIError("invalid status")

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.shortlist_candidate(job_id=10, candidate_id=20)

        assert result.startswith("ERROR:")
        assert "invalid status" in result


class TestShortlistCandidates:
    """Tests for shortlist_candidates batch tool (CR15)."""

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        meta.get_fields.return_value = []
        return meta

    def test_batch_all_created(self, mock_client, mock_metadata):
        """Three new candidates — all created, summary counts correct."""
        mock_client.query.return_value = []
        mock_client.create.side_effect = [
            {"changedEntityId": 101, "changeType": "INSERT", "data": {}},
            {"changedEntityId": 102, "changeType": "INSERT", "data": {}},
            {"changedEntityId": 103, "changeType": "INSERT", "data": {}},
        ]

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.shortlist_candidates(job_id=10, candidate_ids=[20, 21, 22])

        data = json.loads(result)
        assert data["job_id"] == 10
        assert data["summary"] == {"created": 3, "duplicates": 0, "errors": 0}
        assert all(r["status"] == "created" for r in data["results"])

    def test_batch_mixed_results(self, mock_client, mock_metadata):
        """First created, second duplicate, third API error."""
        from bullhorn_mcp.client import BullhornAPIError as _BullhornAPIError

        def query_side_effect(*args, **kwargs):
            where = kwargs.get("where", "")
            if "candidate.id=21" in where:
                return [{"id": 999}]
            return []

        mock_client.query.side_effect = query_side_effect
        mock_client.create.side_effect = [
            {"changedEntityId": 101, "changeType": "INSERT", "data": {}},
            _BullhornAPIError("not found"),
        ]

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.shortlist_candidates(job_id=10, candidate_ids=[20, 21, 22])

        data = json.loads(result)
        assert data["summary"]["created"] == 1
        assert data["summary"]["duplicates"] == 1
        assert data["summary"]["errors"] == 1
        statuses = [r["status"] for r in data["results"]]
        assert statuses == ["created", "duplicate", "error"]

    def test_batch_empty_list(self, mock_client, mock_metadata):
        """Empty candidate_ids returns zero summary without any API calls."""
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.shortlist_candidates(job_id=10, candidate_ids=[])

        data = json.loads(result)
        assert data["results"] == []
        assert data["summary"] == {"created": 0, "duplicates": 0, "errors": 0}
        mock_client.create.assert_not_called()
        mock_client.query.assert_not_called()

    def test_batch_single_element(self, mock_client, mock_metadata):
        """Single-element list behaves identically to shortlist_candidate."""
        mock_client.query.return_value = []
        mock_client.create.return_value = {"changedEntityId": 55, "changeType": "INSERT", "data": {}}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.shortlist_candidates(job_id=10, candidate_ids=[20])

        data = json.loads(result)
        assert data["summary"]["created"] == 1
        assert data["results"][0]["submission_id"] == 55

    def test_batch_identity_resolved_once(self, mock_client, mock_metadata):
        """resolve_caller is called exactly once regardless of how many candidates."""
        mock_client.query.return_value = []
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {}}

        resolve_mock = Mock(return_value={"id": 1})
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", resolve_mock):
            server.shortlist_candidates(job_id=10, candidate_ids=[20, 21, 22, 23, 24])

        resolve_mock.assert_called_once()

    def test_batch_status_override(self, mock_client, mock_metadata):
        """Caller-supplied status is used for every candidate in the batch."""
        mock_client.query.return_value = []
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {}}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            server.shortlist_candidates(job_id=10, candidate_ids=[20, 21], status="Long-listed")

        for call in mock_client.create.call_args_list:
            assert call[0][1]["status"] == "Long-listed"

    def test_batch_invalid_job_id(self, mock_client, mock_metadata):
        """Non-positive job_id returns structured error without iteration."""
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.shortlist_candidates(job_id=0, candidate_ids=[20, 21])

        data = json.loads(result)
        assert data["error"] == "invalid_argument"
        mock_client.query.assert_not_called()
        mock_client.create.assert_not_called()

    def test_batch_invalid_candidate_id(self, mock_client, mock_metadata):
        """Non-positive candidate_id in list is recorded as error without API call."""
        mock_client.query.return_value = []
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {}}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.shortlist_candidates(job_id=10, candidate_ids=[20, 0, 21])

        data = json.loads(result)
        assert data["summary"] == {"created": 2, "duplicates": 0, "errors": 1}
        statuses = [r["status"] for r in data["results"]]
        assert statuses == ["created", "error", "created"]
        assert data["results"][1]["error"] == "candidate_id must be a positive integer."
        mock_client.create.assert_called()
        assert mock_client.create.call_count == 2

    def test_batch_sending_user_identity_failure(self, mock_client, mock_metadata):
        """IdentityResolutionError falls through to sendingUser=None; batch still completes."""
        from bullhorn_mcp.identity import IdentityResolutionError as _IRE
        mock_client.query.return_value = []
        mock_client.create.return_value = {"changedEntityId": 55, "changeType": "INSERT", "data": {}}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", side_effect=_IRE("unavailable")):
            result = server.shortlist_candidates(job_id=10, candidate_ids=[20, 21])

        data = json.loads(result)
        assert data["summary"] == {"created": 2, "duplicates": 0, "errors": 0}
        for call in mock_client.create.call_args_list:
            assert "sendingUser" not in call[0][1]


class TestShortlistStartupValidation:
    """Tests for one-shot startup status picklist validation (CR15)."""

    @pytest.fixture
    def mock_metadata_with_picklist(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        meta.get_fields.return_value = [
            {
                "name": "status",
                "options": [
                    {"value": "New Lead"},
                    {"value": "Shortlisted"},
                    {"value": "Submitted"},
                ],
            }
        ]
        return meta

    def test_warning_when_status_missing(self, mock_client, mock_metadata_with_picklist, caplog, monkeypatch):
        """WARNING is emitted when configured status is not in the picklist."""
        import logging
        monkeypatch.setenv("BULLHORN_SHORTLIST_STATUS", "Not A Real Status")
        mock_client.query.return_value = []
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {}}

        with caplog.at_level(logging.WARNING, logger="bullhorn_mcp.server"), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata_with_picklist), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            server.shortlist_candidate(job_id=10, candidate_id=20)

        assert any("Not A Real Status" in r.message for r in caplog.records)

    def test_no_warning_when_status_present(self, mock_client, mock_metadata_with_picklist, caplog, monkeypatch):
        """No WARNING emitted when configured status is valid."""
        import logging
        monkeypatch.setenv("BULLHORN_SHORTLIST_STATUS", "Shortlisted")
        mock_client.query.return_value = []
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {}}

        with caplog.at_level(logging.WARNING, logger="bullhorn_mcp.server"), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata_with_picklist), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            server.shortlist_candidate(job_id=10, candidate_id=20)

        status_warnings = [r for r in caplog.records if "BULLHORN_SHORTLIST_STATUS" in r.message]
        assert len(status_warnings) == 0

    def test_validation_failure_does_not_raise(self, mock_client, caplog):
        """If get_fields raises, shortlist_candidate still succeeds."""
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        meta.get_fields.side_effect = Exception("metadata unavailable")
        mock_client.query.return_value = []
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {}}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.shortlist_candidate(job_id=10, candidate_id=20)

        data = json.loads(result)
        assert data["changedEntityId"] == 1

    def test_validation_runs_once(self, mock_client, mock_metadata_with_picklist, monkeypatch):
        """get_fields for JobSubmission is called at most once across multiple shortlist calls."""
        monkeypatch.setenv("BULLHORN_SHORTLIST_STATUS", "Shortlisted")
        mock_client.query.return_value = []
        mock_client.create.return_value = {"changedEntityId": 1, "changeType": "INSERT", "data": {}}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata_with_picklist), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            server.shortlist_candidate(job_id=10, candidate_id=20)
            server.shortlist_candidate(job_id=10, candidate_id=21)

        assert mock_metadata_with_picklist.get_fields.call_count == 1


class TestSprint23ShortlistE2E:
    """End-to-end HTTP-mocked tests for shortlist tools (CR15)."""

    @pytest.fixture
    def mock_auth(self, mock_session):
        from unittest.mock import PropertyMock
        from bullhorn_mcp.auth import BullhornAuth
        auth = Mock(spec=BullhornAuth)
        type(auth).session = PropertyMock(return_value=mock_session)
        return auth

    def test_e2e_shortlist_single_success(self, mock_auth, mock_session):
        """Full HTTP round trip: duplicate query empty, PUT creates JobSubmission."""
        import httpx
        import respx
        from bullhorn_mcp.client import BullhornClient
        from bullhorn_mcp.metadata import BullhornMetadata

        real_client = BullhornClient(mock_auth)
        new_submission = {"id": 701, "status": "Shortlisted"}
        captured = {}

        def capture_put(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"changedEntityType": "JobSubmission", "changedEntityId": 701, "changeType": "INSERT"})

        meta = BullhornMetadata(real_client)

        with respx.mock:
            # Duplicate check query
            respx.get(f"{mock_session.rest_url}/query/JobSubmission").mock(
                return_value=httpx.Response(200, json={"data": [], "total": 0})
            )
            # JobSubmission PUT
            respx.put(f"{mock_session.rest_url}/entity/JobSubmission").mock(
                side_effect=capture_put
            )
            # JobSubmission GET (post-create fetch)
            respx.get(f"{mock_session.rest_url}/entity/JobSubmission/701").mock(
                return_value=httpx.Response(200, json={"data": new_submission})
            )
            # JobSubmission metadata (for startup validation)
            respx.get(f"{mock_session.rest_url}/meta/JobSubmission").mock(
                return_value=httpx.Response(200, json={"fields": []})
            )

            with patch.object(server, "get_client", return_value=real_client), \
                 patch.object(server, "get_metadata", return_value=meta), \
                 patch.object(server, "resolve_caller", return_value={"id": 5}):
                result = server.shortlist_candidate(job_id=10, candidate_id=20)

        data = json.loads(result)
        assert data["changedEntityId"] == 701
        assert data["duplicate"] is False
        assert "body" in captured
        assert captured["body"]["candidate"] == {"id": 20}
        assert captured["body"]["jobOrder"] == {"id": 10}
        assert captured["body"]["sendingUser"] == {"id": 5}
        assert "dateWebResponse" in captured["body"]

    def test_e2e_shortlist_duplicate_path(self, mock_auth, mock_session):
        """If JobSubmission already exists, PUT is never issued."""
        import httpx
        import respx
        from bullhorn_mcp.client import BullhornClient
        from bullhorn_mcp.metadata import BullhornMetadata

        real_client = BullhornClient(mock_auth)
        existing = [{"id": 888, "status": "Shortlisted"}]
        meta = BullhornMetadata(real_client)

        with respx.mock:
            respx.get(f"{mock_session.rest_url}/query/JobSubmission").mock(
                return_value=httpx.Response(200, json={"data": existing, "total": 1})
            )
            respx.get(f"{mock_session.rest_url}/meta/JobSubmission").mock(
                return_value=httpx.Response(200, json={"fields": []})
            )

            with patch.object(server, "get_client", return_value=real_client), \
                 patch.object(server, "get_metadata", return_value=meta), \
                 patch.object(server, "resolve_caller", return_value={"id": 5}):
                result = server.shortlist_candidate(job_id=10, candidate_id=20)

        data = json.loads(result)
        assert data["duplicate"] is True
        assert data["existing"]["id"] == 888


class TestCR16DeletedRecordFilter:
    """Regression tests: all duplicate-detection and pass-through searches must exclude deleted records (CR16)."""

    @pytest.fixture
    def mock_auth(self, mock_session):
        from unittest.mock import PropertyMock
        from bullhorn_mcp.auth import BullhornAuth
        auth = Mock(spec=BullhornAuth)
        type(auth).session = PropertyMock(return_value=mock_session)
        return auth

    def test_find_duplicate_companies_excludes_deleted(self, mock_auth, mock_session):
        """find_duplicate_companies search must include isDeleted:0 in query."""
        import httpx
        import respx
        from bullhorn_mcp.client import BullhornClient

        real_client = BullhornClient(mock_auth)
        captured = {}

        with respx.mock:
            def capture(request):
                captured["url"] = str(request.url)
                return httpx.Response(200, json={"data": []})

            respx.get(f"{mock_session.rest_url}/search/ClientCorporation").mock(side_effect=capture)

            with patch.object(server, "get_client", return_value=real_client):
                server.find_duplicate_companies(name="Acme Corp")

        assert "isDeleted" not in captured["url"]  # ClientCorporation has no isDeleted field

    def test_find_duplicate_contacts_company_and_contact_search_excludes_deleted(self, mock_auth, mock_session):
        """Company search skips isDeleted (ClientCorporation denylist); contact search includes it.

        Returns an exact-match company so find_duplicate_contacts proceeds past the
        company lookup and also issues the ClientContact search — exercising both legs.
        """
        import httpx
        import respx
        from bullhorn_mcp.client import BullhornClient

        real_client = BullhornClient(mock_auth)
        captured_urls = []

        with respx.mock:
            def capture_company(request):
                captured_urls.append(str(request.url))
                # Return an exact match so the function proceeds to search contacts
                return httpx.Response(200, json={"data": [{"id": 1, "name": "Acme Corp", "status": "Active", "phone": ""}]})

            def capture_contact(request):
                captured_urls.append(str(request.url))
                return httpx.Response(200, json={"data": []})

            respx.get(f"{mock_session.rest_url}/search/ClientCorporation").mock(side_effect=capture_company)
            respx.get(f"{mock_session.rest_url}/search/ClientContact").mock(side_effect=capture_contact)

            with patch.object(server, "get_client", return_value=real_client):
                server.find_duplicate_contacts(
                    first_name="Jane", last_name="Doe", company_name="Acme Corp"
                )

        assert len(captured_urls) == 2, f"Expected 2 searches (company + contact), got {len(captured_urls)}"
        company_url, contact_url = captured_urls
        assert "isDeleted" not in company_url, "ClientCorporation search must NOT include isDeleted (denylist)"
        assert "isDeleted" in contact_url, "ClientContact search must include isDeleted filter"

    def test_find_duplicate_contacts_contact_search_excludes_deleted(self, mock_auth, mock_session):
        """find_duplicate_contacts contact search must include isDeleted:0 when corp_id is supplied."""
        import httpx
        import respx
        from bullhorn_mcp.client import BullhornClient

        real_client = BullhornClient(mock_auth)
        captured = {}

        with respx.mock:
            def capture(request):
                captured["url"] = str(request.url)
                return httpx.Response(200, json={"data": []})

            respx.get(f"{mock_session.rest_url}/search/ClientContact").mock(side_effect=capture)

            with patch.object(server, "get_client", return_value=real_client):
                server.find_duplicate_contacts(
                    first_name="Jane", last_name="Doe", client_corporation_id=123
                )

        assert "isDeleted" in captured["url"]

    def test_create_contact_dedup_excludes_deleted(self, mock_auth, mock_session):
        """create_contact dedup pre-check search must include isDeleted:0."""
        import httpx
        import respx
        from bullhorn_mcp.client import BullhornClient
        from bullhorn_mcp.metadata import BullhornMetadata

        real_client = BullhornClient(mock_auth)
        meta = BullhornMetadata(real_client)
        captured_urls = []

        with respx.mock:
            def capture_search(request):
                captured_urls.append(str(request.url))
                return httpx.Response(200, json={"data": []})

            respx.get(f"{mock_session.rest_url}/search/ClientContact").mock(side_effect=capture_search)
            # resolve_owner query
            respx.get(f"{mock_session.rest_url}/query/CorporateUser").mock(
                return_value=httpx.Response(200, json={"data": [{"id": 99}]})
            )
            respx.get(f"{mock_session.rest_url}/meta/ClientContact").mock(
                return_value=httpx.Response(200, json={
                    "fields": [{"name": "isDeleted", "type": "SCALAR"}]
                })
            )
            # No duplicate found → create proceeds; mock the PUT and follow-up GET
            respx.put(f"{mock_session.rest_url}/entity/ClientContact").mock(
                return_value=httpx.Response(200, json={"changedEntityId": 500, "changeType": "INSERT"})
            )
            respx.get(f"{mock_session.rest_url}/entity/ClientContact/500").mock(
                return_value=httpx.Response(200, json={"data": {"id": 500}})
            )

            with patch.object(server, "get_client", return_value=real_client), \
                 patch.object(server, "get_metadata", return_value=meta), \
                 patch.object(server, "resolve_caller", side_effect=Exception("no caller")):
                server.create_contact({
                    "firstName": "Jane", "lastName": "Doe",
                    "clientCorporation": {"id": 123},
                    "owner": {"id": 99},
                })

        assert captured_urls, "Expected at least one ClientContact search"
        assert all("isDeleted" in url for url in captured_urls)

    def test_search_entities_excludes_deleted_by_default(self, mock_auth, mock_session):
        """search_entities pass-through tool inherits the blanket isDeleted filter."""
        import httpx
        import respx
        from bullhorn_mcp.client import BullhornClient

        real_client = BullhornClient(mock_auth)
        captured = {}

        with respx.mock:
            def capture(request):
                captured["url"] = str(request.url)
                return httpx.Response(200, json={"data": []})

            respx.get(f"{mock_session.rest_url}/search/Placement").mock(side_effect=capture)

            with patch.object(server, "get_client", return_value=real_client):
                server.search_entities(entity="Placement", query="status:Approved")

        assert "isDeleted" in captured["url"]

    def test_query_entities_excludes_deleted_by_default(self, mock_auth, mock_session):
        """query_entities pass-through tool inherits the blanket isDeleted filter."""
        import httpx
        import respx
        from bullhorn_mcp.client import BullhornClient

        real_client = BullhornClient(mock_auth)
        captured = {}

        with respx.mock:
            def capture(request):
                captured["url"] = str(request.url)
                return httpx.Response(200, json={"data": []})

            respx.get(f"{mock_session.rest_url}/query/JobOrder").mock(side_effect=capture)

            with patch.object(server, "get_client", return_value=real_client):
                server.query_entities(entity="JobOrder", where="salary > 100000")

        assert "isDeleted" in captured["url"]

    def test_find_duplicate_companies_empty_name_sends_isdeleted_filter(self, mock_auth, mock_session):
        """find_duplicate_companies with empty name sends isDeleted:0 with no name: term.

        After CR16, _company_broad_query("") returns "" and the client wraps the
        empty query to isDeleted:0. This differs from the pre-CR16 behaviour
        (name:*) but is documented here so regressions are caught.
        """
        import httpx
        import respx
        from bullhorn_mcp.client import BullhornClient

        real_client = BullhornClient(mock_auth)
        captured = {}

        with respx.mock:
            def capture(request):
                captured["url"] = str(request.url)
                return httpx.Response(200, json={"data": []})

            respx.get(f"{mock_session.rest_url}/search/ClientCorporation").mock(side_effect=capture)

            with patch.object(server, "get_client", return_value=real_client):
                server.find_duplicate_companies(name="")

        assert "isDeleted" not in captured["url"]  # ClientCorporation has no isDeleted field (denylist)
        assert "name%3A" not in captured["url"]  # no name: Lucene filter for empty input


# ---------------------------------------------------------------------------
# CR19 — Candidate Creation and CV Parsing
# ---------------------------------------------------------------------------

class TestCreateCandidate:
    """Tests for create_candidate tool."""

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        meta.get_fields.return_value = []
        return meta

    @pytest.fixture(autouse=True)
    def clear_candidate_required(self):
        """Patch get_candidate_required to [] so existing tests aren't broken by .env defaults."""
        with patch("bullhorn_mcp.server.get_candidate_required", return_value=[]):
            yield

    def test_create_candidate_success(self, mock_client, mock_metadata):
        """create_candidate with minimal required fields creates record."""
        mock_client.resolve_owner.return_value = {"id": 99}
        mock_client.search.return_value = []
        mock_client.create.return_value = {
            "changedEntityId": 111,
            "changeType": "INSERT",
            "data": {"id": 111, "firstName": "Jane", "lastName": "Doe", "owner": {"id": 99}},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate({
                "firstName": "Jane", "lastName": "Doe", "owner": {"id": 99},
            })

        data = json.loads(result)
        assert data["changedEntityId"] == 111
        assert data["changeType"] == "INSERT"
        mock_client.create.assert_called_once()

    def test_create_candidate_missing_first_name(self, mock_client, mock_metadata):
        """create_candidate returns error when firstName is absent."""
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate({"lastName": "Doe", "owner": {"id": 1}})

        data = json.loads(result)
        assert data["error"] == "firstName_required"
        mock_client.create.assert_not_called()

    def test_create_candidate_missing_last_name(self, mock_client, mock_metadata):
        """create_candidate returns error when lastName is absent."""
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate({"firstName": "Jane", "owner": {"id": 1}})

        data = json.loads(result)
        assert data["error"] == "lastName_required"
        mock_client.create.assert_not_called()

    def test_create_candidate_rejects_client_corporation(self, mock_client, mock_metadata):
        """create_candidate rejects clientCorporation field and points to companyName."""
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.create_candidate({
                "firstName": "Jane", "lastName": "Doe",
                "clientCorporation": {"id": 1}, "owner": {"id": 1},
            })

        data = json.loads(result)
        assert data["error"] == "clientCorporation_not_valid"
        assert "companyName" in data["message"]
        mock_client.create.assert_not_called()

    def test_create_candidate_rejects_client_corporation_via_label(self, mock_client, mock_metadata):
        """Post-resolution guard blocks clientCorporation smuggled via display label."""
        # Simulate a label that resolves to "clientCorporation" after metadata resolution
        def resolve_with_label(entity, fields):
            result = dict(fields)
            if "Company" in result:
                result["clientCorporation"] = result.pop("Company")
            return result

        mock_metadata.resolve_fields.side_effect = resolve_with_label
        mock_client.resolve_owner.return_value = {"id": 1}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate({
                "firstName": "Jane", "lastName": "Doe",
                "Company": {"id": 1}, "owner": {"id": 1},
            })

        data = json.loads(result)
        assert data["error"] == "clientCorporation_not_valid"
        assert "companyName" in data["message"]
        mock_client.create.assert_not_called()

    def test_create_candidate_strips_title_field(self, mock_client, mock_metadata):
        """create_candidate strips 'title' field and includes warning in response."""
        mock_client.resolve_owner.return_value = {"id": 1}
        mock_client.search.return_value = []
        mock_client.create.return_value = {
            "changedEntityId": 112, "changeType": "INSERT",
            "data": {"id": 112, "firstName": "Jane", "lastName": "Doe"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate({
                "firstName": "Jane", "lastName": "Doe",
                "title": "Dr.", "owner": {"id": 1},
            })

        data = json.loads(result)
        assert "warnings" in data
        assert any("title" in w for w in data["warnings"])
        # title must not be in the create payload
        call_kwargs = mock_client.create.call_args[0][1]
        assert "title" not in call_kwargs

    def test_create_candidate_strips_name_field(self, mock_client, mock_metadata):
        """create_candidate ignores LLM-supplied 'name', warns, then injects MCP-computed value."""
        mock_client.resolve_owner.return_value = {"id": 1}
        mock_client.search.return_value = []
        mock_client.create.return_value = {
            "changedEntityId": 113, "changeType": "INSERT",
            "data": {"id": 113, "firstName": "Jane", "lastName": "Doe"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate({
                "firstName": "Jane", "lastName": "Doe",
                "name": "Bogus Name", "owner": {"id": 1},
            })

        data = json.loads(result)
        assert "warnings" in data
        assert any("name" in w for w in data["warnings"])
        call_kwargs = mock_client.create.call_args[0][1]
        # MCP injects the correct computed value, not the LLM-supplied bogus string
        assert call_kwargs["name"] == "Jane Doe"

    def test_create_candidate_name_always_computed(self, mock_client, mock_metadata):
        """create_candidate injects name into payload even when LLM does not supply it."""
        mock_client.resolve_owner.return_value = {"id": 1}
        mock_client.search.return_value = []
        mock_client.create.return_value = {
            "changedEntityId": 116, "changeType": "INSERT",
            "data": {"id": 116, "firstName": "Alice", "lastName": "Smith"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            server.create_candidate({"firstName": "Alice", "lastName": "Smith", "owner": {"id": 1}})

        call_kwargs = mock_client.create.call_args[0][1]
        assert call_kwargs["name"] == "Alice Smith"

    def test_create_candidate_dup_found_no_force(self, mock_client, mock_metadata):
        """create_candidate returns duplicate_found when a match is detected."""
        mock_client.resolve_owner.return_value = {"id": 1}
        mock_client.search.return_value = [
            {"id": 50, "firstName": "Jane", "lastName": "Doe",
             "email": "jane@example.com", "phone": "", "occupation": "", "companyName": "", "dateAdded": 0},
        ]

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate({
                "firstName": "Jane", "lastName": "Doe", "owner": {"id": 1},
            })

        data = json.loads(result)
        assert data["duplicate_found"] is True
        assert "match" in data
        mock_client.create.assert_not_called()

    def test_create_candidate_force_bypasses_dup_check(self, mock_client, mock_metadata):
        """create_candidate with force=True skips duplicate check."""
        mock_client.resolve_owner.return_value = {"id": 1}
        mock_client.create.return_value = {
            "changedEntityId": 114, "changeType": "INSERT",
            "data": {"id": 114, "firstName": "Jane", "lastName": "Doe"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate(
                {"firstName": "Jane", "lastName": "Doe", "owner": {"id": 1}},
                force=True,
            )

        data = json.loads(result)
        assert data["changedEntityId"] == 114
        # search should NOT be called since force=True skips dup check
        mock_client.search.assert_not_called()

    def test_create_candidate_owner_auto_stamp(self, mock_client, mock_metadata):
        """create_candidate auto-stamps owner from resolve_caller when absent."""
        mock_client.resolve_owner.return_value = {"id": 42}
        mock_client.search.return_value = []
        mock_client.create.return_value = {
            "changedEntityId": 115, "changeType": "INSERT",
            "data": {"id": 115, "firstName": "Jane", "lastName": "Doe", "owner": {"id": 42}},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 42}) as mock_caller:
            server.create_candidate({"firstName": "Jane", "lastName": "Doe"})

        mock_caller.assert_called_once()
        call_kwargs = mock_client.create.call_args[0][1]
        assert call_kwargs.get("owner") == {"id": 42}

    def test_create_candidate_identity_resolution_failed(self, mock_client, mock_metadata):
        """create_candidate returns identity_resolution_failed when resolve_caller raises."""
        from bullhorn_mcp.identity import IdentityResolutionError
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")):
            result = server.create_candidate({"firstName": "Jane", "lastName": "Doe"})

        data = json.loads(result)
        assert data["error"] == "identity_resolution_failed"
        mock_client.create.assert_not_called()

    def test_create_candidate_owner_ambiguous(self, mock_client, mock_metadata):
        """create_candidate returns disambiguation JSON when owner matches multiple users."""
        mock_client.resolve_owner.return_value = [
            {"id": 10, "firstName": "John", "lastName": "Smith"},
            {"id": 11, "firstName": "John", "lastName": "Smith"},
        ]

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate({
                "firstName": "Jane", "lastName": "Doe", "owner": "John Smith",
            })

        data = json.loads(result)
        assert data["error"] == "owner_ambiguous"
        mock_client.create.assert_not_called()

    def test_create_candidate_owner_not_found(self, mock_client, mock_metadata):
        """create_candidate returns owner_not_found error when name resolves to nobody."""
        mock_client.resolve_owner.side_effect = ValueError("No CorporateUser found matching 'Ghost'")

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate({
                "firstName": "Jane", "lastName": "Doe", "owner": "Ghost",
            })

        data = json.loads(result)
        assert data["error"] == "owner_not_found"
        mock_client.create.assert_not_called()

    def test_create_candidate_api_error(self, mock_client, mock_metadata):
        """create_candidate returns ERROR: prefix on BullhornAPIError."""
        mock_client.resolve_owner.return_value = {"id": 1}
        mock_client.search.return_value = []
        mock_client.create.side_effect = BullhornAPIError("500 Internal Server Error")

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate({
                "firstName": "Jane", "lastName": "Doe", "owner": {"id": 1},
            })

        assert result.startswith("ERROR:")

    def test_create_candidate_label_resolution(self, mock_client, mock_metadata):
        """create_candidate calls resolve_fields with Candidate entity."""
        mock_client.resolve_owner.return_value = {"id": 1}
        mock_client.search.return_value = []
        mock_client.create.return_value = {
            "changedEntityId": 116, "changeType": "INSERT",
            "data": {"id": 116, "firstName": "Jane", "lastName": "Doe"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            server.create_candidate({"firstName": "Jane", "lastName": "Doe", "owner": {"id": 1}})

        # resolve_fields is called with "Candidate" at least once
        calls = mock_metadata.resolve_fields.call_args_list
        assert any(c.args[0] == "Candidate" for c in calls)

    def test_source_auto_stamped_when_not_provided(self, mock_client, mock_metadata):
        """create_candidate stamps source=get_mcp_source() when caller omits source."""
        mock_client.resolve_owner.return_value = {"id": 1}
        mock_client.search.return_value = []
        mock_client.create.return_value = {
            "changedEntityId": 120, "changeType": "INSERT",
            "data": {"id": 120},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}), \
             patch("bullhorn_mcp.server.get_mcp_source", return_value="Claude"):
            server.create_candidate({"firstName": "Jane", "lastName": "Doe", "owner": {"id": 1}})

        payload = mock_client.create.call_args[0][1]
        assert payload.get("source") == "Claude"

    def test_user_supplied_source_wins(self, mock_client, mock_metadata):
        """create_candidate does not overwrite source when caller supplies it."""
        mock_client.resolve_owner.return_value = {"id": 1}
        mock_client.search.return_value = []
        mock_client.create.return_value = {
            "changedEntityId": 121, "changeType": "INSERT",
            "data": {"id": 121},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}), \
             patch("bullhorn_mcp.server.get_mcp_source", return_value="Claude"):
            server.create_candidate({
                "firstName": "Jane", "lastName": "Doe",
                "source": "LinkedIn", "owner": {"id": 1},
            })

        payload = mock_client.create.call_args[0][1]
        assert payload.get("source") == "LinkedIn"

    def test_custom_mcp_source_env_var(self, mock_client, mock_metadata):
        """get_mcp_source() reads BULLHORN_MCP_SOURCE env var."""
        from bullhorn_mcp.candidate_config import get_mcp_source
        import os
        original = os.environ.get("BULLHORN_MCP_SOURCE")
        try:
            os.environ["BULLHORN_MCP_SOURCE"] = "GPT-4o"
            assert get_mcp_source() == "GPT-4o"
        finally:
            if original is None:
                os.environ.pop("BULLHORN_MCP_SOURCE", None)
            else:
                os.environ["BULLHORN_MCP_SOURCE"] = original

    def test_mcp_source_defaults_to_claude(self):
        """get_mcp_source() defaults to 'Claude' when env var is unset."""
        from bullhorn_mcp.candidate_config import get_mcp_source
        import os
        original = os.environ.pop("BULLHORN_MCP_SOURCE", None)
        try:
            assert get_mcp_source() == "Claude"
        finally:
            if original is not None:
                os.environ["BULLHORN_MCP_SOURCE"] = original


class TestFindDuplicateCandidates:
    """Tests for find_duplicate_candidates tool."""

    def test_find_dup_candidates_email_exact_match(self, mock_client, sample_candidate):
        """find_duplicate_candidates detects email exact match as 'exact' category."""
        sample_candidate["email"] = "jane@example.com"
        sample_candidate["firstName"] = "Jane"
        sample_candidate["lastName"] = "Doe"
        sample_candidate["occupation"] = "Engineer"
        sample_candidate["companyName"] = "Acme"
        sample_candidate["dateAdded"] = 0
        mock_client.search.return_value = [sample_candidate]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_candidates("Jane", "Doe", email="jane@example.com")

        data = json.loads(result)
        assert data["exact_match"] is True
        assert len(data["matches"]) == 1
        assert data["matches"][0]["category"] == "exact"

    def test_find_dup_candidates_name_fuzzy_match(self, mock_client, sample_candidate):
        """find_duplicate_candidates scores name-only match correctly."""
        sample_candidate["firstName"] = "Jane"
        sample_candidate["lastName"] = "Doe"
        sample_candidate["email"] = "other@example.com"
        sample_candidate["occupation"] = ""
        sample_candidate["companyName"] = ""
        sample_candidate["dateAdded"] = 0
        mock_client.search.return_value = [sample_candidate]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_candidates("Jane", "Doe")

        data = json.loads(result)
        assert len(data["matches"]) == 1
        assert data["matches"][0]["confidence"] >= 0.50

    def test_find_dup_candidates_no_match(self, mock_client):
        """find_duplicate_candidates returns empty matches when no records found."""
        mock_client.search.return_value = []

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_candidates("Completely", "Unknown")

        data = json.loads(result)
        assert data["matches"] == []
        assert data["exact_match"] is False

    def test_find_dup_candidates_api_error(self, mock_client):
        """find_duplicate_candidates returns ERROR: prefix on BullhornAPIError."""
        mock_client.search.side_effect = BullhornAPIError("Search failed")

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_candidates("Jane", "Doe")

        assert result.startswith("ERROR:")


class TestParseCv:
    """Tests for parse_cv tool."""

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        meta.get_fields.return_value = []
        return meta

    def test_parse_cv_returns_parsed_and_dup_check(self, mock_client, mock_metadata, sample_parsed_resume):
        """parse_cv returns parsed data and duplicate_check result without writing."""
        import base64
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        mock_client.search.return_value = []

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.parse_cv(
                file_b64=base64.b64encode(b"%PDF-fake").decode(),
                filename="cv.pdf",
            )

        data = json.loads(result)
        assert "parsed" in data
        assert data["parsed"]["candidate"]["firstName"] == "Jane"
        assert "duplicate_check" in data
        mock_client.create.assert_not_called()

    def test_parse_cv_invalid_base64(self, mock_client, mock_metadata):
        """parse_cv returns error on malformed base64 input."""
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.parse_cv(
                file_b64="!not-valid-base64!",
                filename="cv.pdf",
            )

        data = json.loads(result)
        assert data["error"] == "invalid_base64"
        mock_client.parse_resume_file.assert_not_called()

    def test_parse_cv_dup_found_in_preview(self, mock_client, mock_metadata, sample_parsed_resume, sample_candidate):
        """parse_cv includes duplicate_check result when a matching Candidate is found."""
        import base64
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        sample_candidate["firstName"] = "Jane"
        sample_candidate["lastName"] = "Doe"
        sample_candidate["email"] = "jane.doe@example.com"
        sample_candidate["occupation"] = ""
        sample_candidate["companyName"] = ""
        sample_candidate["dateAdded"] = 0
        mock_client.search.return_value = [sample_candidate]

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.parse_cv(
                file_b64=base64.b64encode(b"%PDF-fake").decode(),
                filename="cv.pdf",
            )

        data = json.loads(result)
        assert data["duplicate_check"] is not None
        assert data["duplicate_check"]["category"] == "exact"

    def test_parse_cv_api_error(self, mock_client, mock_metadata):
        """parse_cv returns ERROR: prefix on BullhornAPIError from parse_resume_file."""
        import base64
        mock_client.parse_resume_file.side_effect = BullhornAPIError("Parse failed")

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.parse_cv(
                file_b64=base64.b64encode(b"%PDF-fake").decode(),
                filename="cv.pdf",
            )

        assert result.startswith("ERROR:")


class TestParseCvText:
    """Tests for parse_cv_text tool."""

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        meta.get_fields.return_value = []
        return meta

    def test_parse_cv_text_returns_parsed_and_dup_check(self, mock_client, mock_metadata, sample_parsed_resume):
        """parse_cv_text returns parsed data without writing anything."""
        mock_client.parse_resume_text.return_value = sample_parsed_resume
        mock_client.search.return_value = []

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.parse_cv_text(content="Jane Doe\nEngineer\njane@example.com")

        data = json.loads(result)
        assert "parsed" in data
        assert data["parsed"]["candidate"]["firstName"] == "Jane"
        assert "duplicate_check" in data
        mock_client.create.assert_not_called()

    def test_parse_cv_text_html_content_type(self, mock_client, mock_metadata, sample_parsed_resume):
        """parse_cv_text passes content_type through to client.parse_resume_text."""
        mock_client.parse_resume_text.return_value = sample_parsed_resume
        mock_client.search.return_value = []

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            server.parse_cv_text(content="<html>Jane Doe</html>", content_type="text/html")

        mock_client.parse_resume_text.assert_called_once_with("<html>Jane Doe</html>", "text/html")

    def test_parse_cv_text_api_error(self, mock_client, mock_metadata):
        """parse_cv_text returns ERROR: prefix on BullhornAPIError."""
        mock_client.parse_resume_text.side_effect = BullhornAPIError("Parser unavailable")

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.parse_cv_text(content="some text")

        assert result.startswith("ERROR:")


class TestCreateCandidateFromCv:
    """Tests for create_candidate_from_cv tool."""

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        meta.get_fields.return_value = []
        return meta

    def test_create_from_cv_binary_success(self, mock_client, mock_metadata, sample_parsed_resume):
        """create_candidate_from_cv binary path creates candidate and child records."""
        import base64
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        mock_client.search.return_value = []
        mock_client.create.side_effect = [
            {"changedEntityId": 200, "changeType": "INSERT", "data": {"id": 200}},  # Candidate
            {"changedEntityId": 201, "changeType": "INSERT", "data": {"id": 201}},  # work history 1
            {"changedEntityId": 202, "changeType": "INSERT", "data": {"id": 202}},  # work history 2
            {"changedEntityId": 203, "changeType": "INSERT", "data": {"id": 203}},  # education
        ]
        mock_client.update.return_value = {"changedEntityId": 200, "changeType": "UPDATE", "data": {"id": 200}}
        mock_client.get.return_value = {"id": 200, "skillSet": ""}
        mock_client.attach_file.return_value = {"fileId": 55, "name": "cv.pdf"}
        mock_client._guess_content_type.return_value = "application/pdf"

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate_from_cv(
                file_b64=base64.b64encode(b"%PDF-fake").decode(),
                filename="cv.pdf",
            )

        data = json.loads(result)
        assert data["created"] is True
        assert data["candidate_id"] == 200
        assert len(data["work_history_ids"]) == 2
        assert len(data["education_ids"]) == 1
        assert data["file_attachment"] is not None

        # Verify the Candidate write payload — the full derivation chain must be tested
        candidate_call = mock_client.create.call_args_list[0]
        assert candidate_call[0][0] == "Candidate"
        payload = candidate_call[0][1]
        assert payload["firstName"] == "Jane"
        assert payload["lastName"] == "Doe"
        assert payload["email"] == "jane.doe@example.com"
        assert payload["occupation"] == "Senior Software Engineer"
        assert "title" not in payload        # stripped by _strip_contact_title
        assert payload["name"] == "Jane Doe"  # computed by MCP from firstName + lastName
        assert "owner" in payload             # auto-stamped from resolve_caller

    def test_create_from_cv_text_success(self, mock_client, mock_metadata, sample_parsed_resume):
        """create_candidate_from_cv text path creates candidate without file attach."""
        mock_client.parse_resume_text.return_value = sample_parsed_resume
        mock_client.search.return_value = []
        mock_client.create.side_effect = [
            {"changedEntityId": 210, "changeType": "INSERT", "data": {"id": 210}},
            {"changedEntityId": 211, "changeType": "INSERT", "data": {"id": 211}},
            {"changedEntityId": 212, "changeType": "INSERT", "data": {"id": 212}},
            {"changedEntityId": 213, "changeType": "INSERT", "data": {"id": 213}},
        ]
        mock_client.update.return_value = {"changedEntityId": 210, "changeType": "UPDATE", "data": {"id": 210}}
        mock_client.get.return_value = {"id": 210, "skillSet": ""}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate_from_cv(content="Jane Doe\nEngineer")

        data = json.loads(result)
        assert data["created"] is True
        assert data["file_attachment"] is None  # text-only skips attach
        mock_client.attach_file.assert_not_called()

        # Verify the Candidate write payload for the text path
        candidate_call = mock_client.create.call_args_list[0]
        assert candidate_call[0][0] == "Candidate"
        payload = candidate_call[0][1]
        assert payload["firstName"] == "Jane"
        assert payload["lastName"] == "Doe"
        assert "title" not in payload        # stripped by _strip_contact_title
        assert payload["name"] == "Jane Doe"  # computed by MCP from firstName + lastName
        assert "owner" in payload             # auto-stamped from resolve_caller

    def test_create_from_cv_duplicate_found(self, mock_client, mock_metadata, sample_parsed_resume, sample_candidate):
        """create_candidate_from_cv returns duplicate_found when match detected."""
        import base64
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        sample_candidate["firstName"] = "Jane"
        sample_candidate["lastName"] = "Doe"
        sample_candidate["email"] = "jane.doe@example.com"
        sample_candidate["occupation"] = ""
        sample_candidate["companyName"] = ""
        sample_candidate["dateAdded"] = 0
        mock_client.search.return_value = [sample_candidate]

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate_from_cv(
                file_b64=base64.b64encode(b"%PDF-fake").decode(),
                filename="cv.pdf",
            )

        data = json.loads(result)
        assert data["duplicate_found"] is True
        assert "hint" in data
        mock_client.create.assert_not_called()

    def test_create_from_cv_force_bypasses_dup(self, mock_client, mock_metadata, sample_parsed_resume, sample_candidate):
        """create_candidate_from_cv force=True skips dup check and creates."""
        import base64
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        mock_client.create.side_effect = [
            {"changedEntityId": 220, "changeType": "INSERT", "data": {"id": 220}},
            {"changedEntityId": 221, "changeType": "INSERT", "data": {"id": 221}},
            {"changedEntityId": 222, "changeType": "INSERT", "data": {"id": 222}},
            {"changedEntityId": 223, "changeType": "INSERT", "data": {"id": 223}},
        ]
        mock_client.update.return_value = {"changedEntityId": 220, "changeType": "UPDATE", "data": {"id": 220}}
        mock_client.get.return_value = {"id": 220, "skillSet": ""}
        mock_client.attach_file.return_value = {"fileId": 60}
        mock_client._guess_content_type.return_value = "application/pdf"

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate_from_cv(
                file_b64=base64.b64encode(b"%PDF-fake").decode(),
                filename="cv.pdf",
                force=True,
            )

        data = json.loads(result)
        assert data["created"] is True
        mock_client.search.assert_not_called()

    def test_create_from_cv_required_fields_missing(self, mock_client, mock_metadata, sample_parsed_resume):
        """create_candidate_from_cv returns required_fields_missing when env-required field absent."""
        import base64
        # Remove email from parsed data so the required field is absent
        resume = dict(sample_parsed_resume)
        resume["candidate"] = {k: v for k, v in resume["candidate"].items() if k != "email"}
        mock_client.parse_resume_file.return_value = resume
        mock_client.search.return_value = []

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}), \
             patch("bullhorn_mcp.server.get_candidate_required", return_value=["email"]):
            result = server.create_candidate_from_cv(
                file_b64=base64.b64encode(b"%PDF-fake").decode(),
                filename="cv.pdf",
                force=True,
            )

        data = json.loads(result)
        assert data["error"] == "required_fields_missing"
        assert "email" in data["fields"]
        mock_client.create.assert_not_called()

    def test_create_from_cv_no_input_error(self, mock_client, mock_metadata):
        """create_candidate_from_cv returns error when neither binary nor text provided."""
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.create_candidate_from_cv()

        data = json.loads(result)
        assert data["error"] == "input_required"

    def test_create_from_cv_child_record_failure_best_effort(self, mock_client, mock_metadata, sample_parsed_resume):
        """create_candidate_from_cv includes warnings when child records fail."""
        import base64
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        mock_client.search.return_value = []

        def create_side_effect(entity, data):
            if entity == "Candidate":
                return {"changedEntityId": 230, "changeType": "INSERT", "data": {"id": 230}}
            raise BullhornAPIError("Child record failed")

        mock_client.create.side_effect = create_side_effect
        mock_client.update.side_effect = BullhornAPIError("update failed")
        mock_client.get.return_value = {"id": 230, "skillSet": ""}
        mock_client._guess_content_type.return_value = "application/pdf"
        mock_client.attach_file.return_value = {"fileId": 70}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate_from_cv(
                file_b64=base64.b64encode(b"%PDF-fake").decode(),
                filename="cv.pdf",
            )

        data = json.loads(result)
        # Candidate was created despite child failures
        assert data["created"] is True
        assert data["candidate_id"] == 230
        # Warnings surfaced for child failures
        assert "warnings" in data
        assert len(data["warnings"]) > 0

    def test_source_auto_stamped_when_not_provided(self, mock_client, mock_metadata, sample_parsed_resume):
        """create_candidate_from_cv stamps source=get_mcp_source() when caller omits source."""
        mock_client.parse_resume_text.return_value = sample_parsed_resume
        mock_client.search.return_value = []
        mock_client.create.side_effect = [
            {"changedEntityId": 250, "changeType": "INSERT", "data": {"id": 250}},
            {"changedEntityId": 251, "changeType": "INSERT", "data": {"id": 251}},
            {"changedEntityId": 252, "changeType": "INSERT", "data": {"id": 252}},
            {"changedEntityId": 253, "changeType": "INSERT", "data": {"id": 253}},
        ]
        mock_client.update.return_value = {"changedEntityId": 250, "changeType": "UPDATE", "data": {"id": 250}}
        mock_client.get.return_value = {"id": 250, "skillSet": ""}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}), \
             patch("bullhorn_mcp.server.get_mcp_source", return_value="Claude"):
            server.create_candidate_from_cv(content="Jane Doe\nEngineer")

        candidate_call = mock_client.create.call_args_list[0]
        assert candidate_call[0][0] == "Candidate"
        payload = candidate_call[0][1]
        assert payload.get("source") == "Claude"

    def test_user_supplied_source_wins_in_cv_flow(self, mock_client, mock_metadata, sample_parsed_resume):
        """create_candidate_from_cv does not overwrite source when caller supplies it via fields_override."""
        mock_client.parse_resume_text.return_value = sample_parsed_resume
        mock_client.search.return_value = []
        mock_client.create.side_effect = [
            {"changedEntityId": 255, "changeType": "INSERT", "data": {"id": 255}},
            {"changedEntityId": 256, "changeType": "INSERT", "data": {"id": 256}},
            {"changedEntityId": 257, "changeType": "INSERT", "data": {"id": 257}},
            {"changedEntityId": 258, "changeType": "INSERT", "data": {"id": 258}},
        ]
        mock_client.update.return_value = {"changedEntityId": 255, "changeType": "UPDATE", "data": {"id": 255}}
        mock_client.get.return_value = {"id": 255, "skillSet": ""}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}), \
             patch("bullhorn_mcp.server.get_mcp_source", return_value="Claude"):
            server.create_candidate_from_cv(
                content="Jane Doe\nEngineer",
                fields_override={"source": "LinkedIn"},
            )

        candidate_call = mock_client.create.call_args_list[0]
        assert candidate_call[0][0] == "Candidate"
        payload = candidate_call[0][1]
        assert payload.get("source") == "LinkedIn"


class TestAttachCv:
    """Tests for attach_cv tool (two-call confirmation flow)."""

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        meta.get_fields.return_value = []
        return meta

    def test_attach_cv_preview_returns_diff(self, mock_client, mock_metadata, sample_parsed_resume, sample_candidate):
        """attach_cv without fields_to_update returns preview diff without writing."""
        import base64
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        mock_client.get.return_value = {
            **sample_candidate,
            "occupation": "Junior Developer",
            "mobile": None,
        }
        mock_client.query.return_value = []

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.attach_cv(
                candidate_id=sample_candidate["id"],
                file_b64=base64.b64encode(b"%PDF-fake").decode(),
                filename="cv.pdf",
            )

        data = json.loads(result)
        assert data["preview"] is True
        assert data["candidate_id"] == sample_candidate["id"]
        assert "proposed_field_changes" in data
        assert "message" in data
        # Nothing written
        mock_client.update.assert_not_called()
        mock_client.attach_file.assert_not_called()

    def test_attach_cv_commit_applies_selected_fields(self, mock_client, mock_metadata, sample_parsed_resume, sample_candidate):
        """attach_cv commit applies only fields_to_update and attaches CV."""
        import base64
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        mock_client.get.return_value = {**sample_candidate, "occupation": "Junior Developer"}
        mock_client.query.return_value = []
        mock_client.update.return_value = {
            "changedEntityId": sample_candidate["id"], "changeType": "UPDATE",
            "data": {**sample_candidate, "occupation": "Senior Software Engineer"},
        }
        mock_client.attach_file.return_value = {"fileId": 80, "name": "cv.pdf"}
        mock_client._guess_content_type.return_value = "application/pdf"

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.attach_cv(
                candidate_id=sample_candidate["id"],
                file_b64=base64.b64encode(b"%PDF-fake").decode(),
                filename="cv.pdf",
                fields_to_update=["occupation"],
            )

        data = json.loads(result)
        assert data["committed"] is True
        assert "occupation" in data["fields_updated"]
        assert data["file_attachment"] is not None
        mock_client.attach_file.assert_called_once()

    def test_attach_cv_force_all_applies_everything(self, mock_client, mock_metadata, sample_parsed_resume, sample_candidate):
        """attach_cv with force_all=True applies all proposed changes."""
        import base64
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        mock_client.get.return_value = {**sample_candidate, "occupation": "Junior Developer"}
        mock_client.query.return_value = []
        mock_client.update.return_value = {
            "changedEntityId": sample_candidate["id"], "changeType": "UPDATE",
            "data": {**sample_candidate, "occupation": "Senior Software Engineer"},
        }
        mock_client.attach_file.return_value = {"fileId": 81}
        mock_client._guess_content_type.return_value = "application/pdf"

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.attach_cv(
                candidate_id=sample_candidate["id"],
                file_b64=base64.b64encode(b"%PDF-fake").decode(),
                filename="cv.pdf",
                force_all=True,
            )

        data = json.loads(result)
        assert data["committed"] is True
        mock_client.attach_file.assert_called_once()

    def test_attach_cv_invalid_base64(self, mock_client, mock_metadata):
        """attach_cv returns error on malformed base64."""
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.attach_cv(
                candidate_id=123,
                file_b64="!not-base64!",
                filename="cv.pdf",
            )

        data = json.loads(result)
        assert data["error"] == "invalid_base64"
        mock_client.attach_file.assert_not_called()

    def test_attach_cv_api_error(self, mock_client, mock_metadata):
        """attach_cv returns ERROR: prefix on BullhornAPIError from parse."""
        import base64
        mock_client.parse_resume_file.side_effect = BullhornAPIError("Parse failed")

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.attach_cv(
                candidate_id=123,
                file_b64=base64.b64encode(b"%PDF-fake").decode(),
                filename="cv.pdf",
            )

        assert result.startswith("ERROR:")

    def test_attach_cv_commit_recomputes_name_both_components(self, mock_client, mock_metadata, sample_parsed_resume, sample_candidate):
        """attach_cv commit injects recomputed name when both firstName and lastName are updated."""
        import base64
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        # parsed has firstName="Jane", lastName="Doe"; candidate has firstName="John", lastName="Smith"
        mock_client.get.return_value = {**sample_candidate, "occupation": "Junior Developer"}
        mock_client.query.return_value = []
        mock_client.update.return_value = {
            "changedEntityId": sample_candidate["id"], "changeType": "UPDATE", "data": {},
        }
        mock_client.attach_file.return_value = {"fileId": 90, "name": "cv.pdf"}
        mock_client._guess_content_type.return_value = "application/pdf"

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.attach_cv(
                candidate_id=sample_candidate["id"],
                file_b64=base64.b64encode(b"%PDF-fake").decode(),
                filename="cv.pdf",
                fields_to_update=["firstName", "lastName"],
            )

        data = json.loads(result)
        assert data["committed"] is True
        call_kwargs = mock_client.update.call_args[0][2]
        assert call_kwargs.get("name") == "Jane Doe"
        # No extra client.get call needed when both components present
        assert mock_client.get.call_count == 1

    def test_attach_cv_commit_recomputes_name_single_component(self, mock_client, mock_metadata, sample_parsed_resume, sample_candidate):
        """attach_cv commit fetches the other half from Bullhorn when only one name component is updated."""
        import base64
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        # First get: broad candidate fetch. Second get: firstName,lastName for name recomputation.
        mock_client.get.side_effect = [
            {**sample_candidate, "occupation": "Junior Developer"},
            {"firstName": "John", "lastName": "Smith"},
        ]
        mock_client.query.return_value = []
        mock_client.update.return_value = {
            "changedEntityId": sample_candidate["id"], "changeType": "UPDATE", "data": {},
        }
        mock_client.attach_file.return_value = {"fileId": 91, "name": "cv.pdf"}
        mock_client._guess_content_type.return_value = "application/pdf"

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.attach_cv(
                candidate_id=sample_candidate["id"],
                file_b64=base64.b64encode(b"%PDF-fake").decode(),
                filename="cv.pdf",
                fields_to_update=["firstName"],
            )

        data = json.loads(result)
        assert data["committed"] is True
        call_kwargs = mock_client.update.call_args[0][2]
        # firstName changed to "Jane", lastName stays "Smith"
        assert call_kwargs.get("name") == "Jane Smith"
        assert mock_client.get.call_count == 2


class TestGetNotesForEntity:
    """Tests for get_notes_for_entity tool."""

    def test_returns_notes_for_candidate(self, mock_client, sample_note_records):
        """Happy path: returns cleaned list for a valid entity."""
        mock_client.get_association.return_value = [sample_note_records[0], sample_note_records[1]]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_notes_for_entity("Candidate", 169020)

        data = json.loads(result)
        assert isinstance(data["data"], list)
        assert len(data["data"]) == 2
        assert data["data"][0]["id"] == 1001

    def test_get_association_called_with_correct_args(self, mock_client, sample_note_records):
        """Verifies get_association_with_meta is called with entity, id, and 'notes'."""
        mock_client.get_association.return_value = [sample_note_records[0]]

        with patch.object(server, "get_client", return_value=mock_client):
            server.get_notes_for_entity("Candidate", 169020, limit=25, order_by="-dateAdded")

        mock_client.get_association_with_meta.assert_called_once()
        call_args = mock_client.get_association_with_meta.call_args
        assert call_args.args[0] == "Candidate"
        assert call_args.args[1] == 169020
        assert call_args.args[2] == "notes"
        assert call_args.kwargs.get("count") == 25
        assert call_args.kwargs.get("order_by") == "-dateAdded"

    def test_cc_telemetry_stripped_from_comments(self, mock_client, sample_note_records, sample_cc_telemetry_comment):
        """CC tag is removed from comments; call_metadata is populated."""
        mock_client.get_association.return_value = [sample_note_records[1]]  # note 1002 has CC tag

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_notes_for_entity("Candidate", 169020)

        data = json.loads(result)
        notes = data["data"]
        assert len(notes) == 1
        assert "[cc:" not in notes[0]["comments"]
        assert "call_metadata" in notes[0]
        assert len(notes[0]["call_metadata"]) == 1

    def test_soft_deleted_excluded_by_default(self, mock_client, sample_note_records):
        """Notes with isDeleted=True are excluded unless include_deleted=True."""
        mock_client.get_association.return_value = [sample_note_records[0], sample_note_records[2]]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_notes_for_entity("Candidate", 169020)

        data = json.loads(result)
        notes = data["data"]
        assert all(not n.get("isDeleted") for n in notes)
        assert len(notes) == 1
        assert notes[0]["id"] == 1001

    def test_include_deleted_returns_all(self, mock_client, sample_note_records):
        """include_deleted=True returns deleted notes alongside active ones."""
        mock_client.get_association.return_value = [sample_note_records[0], sample_note_records[2]]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_notes_for_entity("Candidate", 169020, include_deleted=True)

        data = json.loads(result)
        assert len(data["data"]) == 2

    def test_pagination_next_start_advances_by_raw_page_count(self, mock_client, sample_note_records):
        """next_start uses the raw Bullhorn page count so it always advances past deleted records.

        When include_deleted=False and some notes are isDeleted=True, the raw page
        returned by Bullhorn may be larger than len(data). next_start must be
        start + raw_page_count, not start + len(data), to avoid re-fetching the same
        deleted records on the next call.
        """
        # Page has 2 raw notes; 1 is deleted → len(cleaned) = 1, raw_page_count = 2
        mock_client.get_association_with_meta.side_effect = None
        mock_client.get_association_with_meta.return_value = {
            "data": [sample_note_records[0], sample_note_records[2]],  # [active, deleted]
            "total": 10,
            "start": 0,
            "count": 2,
        }

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_notes_for_entity("Candidate", 169020, limit=2)

        data = json.loads(result)
        assert len(data["data"]) == 1  # deleted note filtered out
        assert data["pagination"]["count"] == 1
        assert data["pagination"]["has_more"] is True
        # next_start must be 2 (raw page count), not 1 (cleaned count) — prevents re-fetch loop
        assert data["pagination"]["next_start"] == 2

    def test_invalid_entity_returns_error(self, mock_client):
        """Returns error dict for unsupported entity without calling client."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_notes_for_entity("FooBar", 1)

        data = json.loads(result)
        assert data["error"] == "invalid_entity"
        mock_client.get_association_with_meta.assert_not_called()

    def test_empty_result_returns_empty_data(self, mock_client):
        """Returns empty data array when the record has no notes."""
        mock_client.get_association.return_value = []

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_notes_for_entity("Candidate", 169020)

        data = json.loads(result)
        assert data["data"] == []

    def test_api_error_returns_error_string(self, mock_client):
        """BullhornAPIError is caught and returned as ERROR: string."""
        mock_client.get_association.side_effect = BullhornAPIError("timeout")

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_notes_for_entity("Candidate", 169020)

        assert result.startswith("ERROR:")

    def test_note_without_cc_tag_has_no_call_metadata(self, mock_client, sample_note_records):
        """Notes without CC tags do not get a call_metadata key."""
        mock_client.get_association.return_value = [sample_note_records[0]]  # no CC tag

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_notes_for_entity("Candidate", 169020)

        data = json.loads(result)
        assert "call_metadata" not in data["data"][0]

    def test_returns_notes_for_client_contact(self, mock_client):
        """ClientContact uses the same association endpoint and returns real notes."""
        contact_note = {
            "id": 2001,
            "action": "Outbound Call",
            "comments": "Follow-up call re candidate submissions.",
            "dateAdded": 1741000000000,
            "isDeleted": False,
            "commentingPerson": {"id": 2, "firstName": "Paul", "lastName": "McArdle"},
            "personReference": {"id": 132773, "firstName": "Anne", "lastName": "McEvoy"},
            "jobOrder": None,
        }
        mock_client.get_association.return_value = [contact_note]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_notes_for_entity("ClientContact", 132773)

        data = json.loads(result)
        notes = data["data"]
        assert len(notes) == 1
        assert notes[0]["id"] == 2001
        call_args = mock_client.get_association_with_meta.call_args
        assert call_args.args[0] == "ClientContact"
        assert call_args.args[1] == 132773
        assert call_args.args[2] == "notes"

    def test_returns_notes_for_job_order(self, mock_client):
        """JobOrder uses the same association endpoint."""
        job_note = {
            "id": 3001,
            "action": "General Note",
            "comments": "Role put on hold.",
            "dateAdded": 1740000000000,
            "isDeleted": False,
            "commentingPerson": {"id": 5, "firstName": "Sarah", "lastName": "Jones"},
            "personReference": None,
            "jobOrder": {"id": 51227, "title": "Interim CIO"},
        }
        mock_client.get_association.return_value = [job_note]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_notes_for_entity("JobOrder", 51227)

        data = json.loads(result)
        notes = data["data"]
        assert len(notes) == 1
        assert notes[0]["id"] == 3001
        call_args = mock_client.get_association_with_meta.call_args
        assert call_args.args[0] == "JobOrder"
        assert call_args.args[1] == 51227


class TestSearchNotes:
    """Tests for search_notes tool."""

    def test_happy_path_returns_results(self, mock_client, sample_note_records):
        """Returns notes matching the Lucene query."""
        mock_client.search.return_value = [sample_note_records[0]]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_notes("strong fit")

        data = json.loads(result)
        notes = data["data"]
        assert len(notes) == 1
        assert notes[0]["id"] == 1001
        mock_client.search_with_meta.assert_called_once()
        call_args = mock_client.search_with_meta.call_args
        assert call_args.kwargs.get("entity") == "Note" or call_args.args[0] == "Note"

    def test_entity_filter_uses_association_endpoint(self, mock_client, sample_note_records):
        """entity_filter path calls get_association, not search."""
        mock_client.get_association.return_value = [sample_note_records[0], sample_note_records[1]]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_notes(
                "strong",
                entity_filter={"type": "Candidate", "id": 169020},
            )

        mock_client.get_association.assert_called_once()
        mock_client.search_with_meta.assert_not_called()
        call_args = mock_client.get_association.call_args
        assert call_args.args[0] == "Candidate"
        assert call_args.args[1] == 169020
        assert call_args.args[2] == "notes"
        data = json.loads(result)
        notes = data["data"]
        assert len(notes) == 1  # only note 1001 has "strong" in comments
        assert notes[0]["id"] == 1001

    def test_entity_filter_keyword_filters_comments(self, mock_client, sample_note_records):
        """entity_filter path returns only notes whose comments contain the keyword."""
        # sample_note_records[0] has "strong fit", [1] has "voicemail", [2] has "Old deleted"
        # Exclude deleted [2] by default, then keyword-match on "voicemail"
        mock_client.get_association.return_value = [sample_note_records[0], sample_note_records[1]]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_notes(
                "voicemail",
                entity_filter={"type": "Candidate", "id": 169020},
            )

        data = json.loads(result)
        notes = data["data"]
        assert len(notes) == 1
        assert notes[0]["id"] == 1002

    def test_entity_filter_keyword_case_insensitive(self, mock_client, sample_note_records):
        """Keyword matching in entity_filter path is case-insensitive."""
        mock_client.get_association.return_value = [sample_note_records[0]]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_notes(
                "STRONG FIT",
                entity_filter={"type": "Candidate", "id": 169020},
            )

        data = json.loads(result)
        assert len(data["data"]) == 1

    def test_entity_filter_no_keyword_match_returns_empty(self, mock_client, sample_note_records):
        """entity_filter path returns empty data array when keyword matches no note comments."""
        mock_client.get_association.return_value = [sample_note_records[0]]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_notes(
                "nonexistentterm",
                entity_filter={"type": "Candidate", "id": 169020},
            )

        assert json.loads(result)["data"] == []

    def test_no_entity_filter_uses_lucene_search(self, mock_client, sample_note_records):
        """Without entity_filter, search_with_meta() is called (Lucene path)."""
        mock_client.search.return_value = [sample_note_records[0]]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_notes("strong fit")

        mock_client.search_with_meta.assert_called_once()
        mock_client.get_association.assert_not_called()
        data = json.loads(result)
        assert data["data"][0]["id"] == 1001

    def test_cc_telemetry_stripped(self, mock_client, sample_note_records):
        """CC tags are stripped from comments in search_notes results too."""
        mock_client.search.return_value = [sample_note_records[1]]  # has CC tag

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_notes("voicemail")

        data = json.loads(result)
        notes = data["data"]
        assert "[cc:" not in notes[0]["comments"]
        assert "call_metadata" in notes[0]

    def test_api_error_returns_error_string(self, mock_client):
        """BullhornAPIError is returned as ERROR: string."""
        mock_client.search.side_effect = BullhornAPIError("service unavailable")

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_notes("visa sponsorship")

        assert result.startswith("ERROR:")

    def test_entity_filter_api_error_returns_error_string(self, mock_client):
        """BullhornAPIError from get_association is returned as ERROR: string."""
        mock_client.get_association.side_effect = BullhornAPIError("timeout")

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_notes("element", entity_filter={"type": "Candidate", "id": 169020})

        assert result.startswith("ERROR:")

    def test_wildcard_query_returns_invalid_query_error(self, mock_client):
        """search_notes('*') returns structured error without making an HTTP call."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_notes("*")

        data = json.loads(result)
        assert data["error"] == "invalid_query"
        assert "get_notes_for_entity" in data["message"]
        mock_client.search.assert_not_called()

    def test_empty_query_returns_invalid_query_error(self, mock_client):
        """search_notes('') returns structured error without making an HTTP call."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_notes("  ")

        data = json.loads(result)
        assert data["error"] == "invalid_query"
        mock_client.search.assert_not_called()

    def test_default_fields_do_not_include_client_corporation(self, mock_client, sample_note_records):
        """Default fields for search_notes exclude clientCorporation (invalid on /search/Note)."""
        mock_client.search.return_value = [sample_note_records[0]]

        with patch.object(server, "get_client", return_value=mock_client):
            server.search_notes("strong fit")

        call_args = mock_client.search_with_meta.call_args
        fields_arg = call_args.kwargs.get("fields") or call_args.args[2]
        assert "clientCorporation" not in fields_arg


class TestCVUploadEndpoint:
    """Tests for the POST /upload-cv HTTP route."""

    class _FakeUpload:
        def __init__(self, data: bytes):
            self._data = data

        async def read(self):
            return self._data

    class _FakeRequest:
        def __init__(self, form_fields, headers=None):
            self.headers = headers or {}
            self.client = None
            self._form = form_fields

        async def form(self):
            return self._form

    def _make_request(self, file_bytes=b"%PDF-fake", filename="cv.pdf", fmt=None,
                      candidate_id=None, force=None, secret="s"):
        form = {"file": self._FakeUpload(file_bytes), "filename": filename}
        if fmt is not None:
            form["format"] = fmt
        if candidate_id is not None:
            form["candidate_id"] = str(candidate_id)
        if force is not None:
            form["force"] = force
        headers = {"X-Upload-Secret": secret} if secret is not None else {}
        return self._FakeRequest(form, headers)

    @pytest.mark.asyncio
    async def test_upload_cv_valid_secret_no_candidate_id(self, monkeypatch):
        """Valid secret + file, no candidate_id → calls create_candidate_from_cv, returns 200 JSON."""
        monkeypatch.setenv("UPLOAD_SECRET", "s")
        req = self._make_request()
        with patch.object(server, "create_candidate_from_cv", return_value='{"candidate_id": 1}') as mock_create:
            resp = await server._upload_cv_handler(req)
        assert resp.status_code == 200
        mock_create.assert_called_once()
        call_kw = mock_create.call_args.kwargs
        assert call_kw["filename"] == "cv.pdf"
        assert call_kw["format"] == "pdf"
        assert call_kw["force"] is False
        import base64
        assert base64.b64decode(call_kw["file_b64"]) == b"%PDF-fake"

    @pytest.mark.asyncio
    async def test_upload_cv_missing_secret_header(self, monkeypatch):
        """No X-Upload-Secret header → 401."""
        monkeypatch.setenv("UPLOAD_SECRET", "s")
        req = self._make_request(secret=None)
        resp = await server._upload_cv_handler(req)
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_upload_cv_wrong_secret(self, monkeypatch):
        """Wrong X-Upload-Secret value → 401."""
        monkeypatch.setenv("UPLOAD_SECRET", "correct")
        req = self._make_request(secret="wrong")
        resp = await server._upload_cv_handler(req)
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_upload_cv_no_secret_configured(self, monkeypatch):
        """UPLOAD_SECRET not set → 400 regardless of header."""
        monkeypatch.delenv("UPLOAD_SECRET", raising=False)
        req = self._make_request(secret="anything")
        resp = await server._upload_cv_handler(req)
        assert resp.status_code == 400
        import json as _json
        body = _json.loads(resp.body)
        assert body["error"] == "upload_secret_not_configured"

    @pytest.mark.asyncio
    async def test_upload_cv_with_candidate_id(self, monkeypatch):
        """candidate_id provided → calls attach_file, NOT create_candidate_from_cv."""
        monkeypatch.setenv("UPLOAD_SECRET", "s")
        mock_client = Mock()
        mock_client._guess_content_type.return_value = "application/pdf"
        mock_client.attach_file.return_value = {"fileId": 99, "name": "cv.pdf"}
        req = self._make_request(candidate_id=42)
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "create_candidate_from_cv") as mock_create:
            resp = await server._upload_cv_handler(req)
        assert resp.status_code == 200
        mock_create.assert_not_called()
        mock_client.attach_file.assert_called_once_with(
            "Candidate", 42, b"%PDF-fake", "cv.pdf", "application/pdf", None, "CV"
        )

    @pytest.mark.asyncio
    async def test_upload_cv_force_true_passed_through(self, monkeypatch):
        """force='true' form field → create_candidate_from_cv called with force=True."""
        monkeypatch.setenv("UPLOAD_SECRET", "s")
        req = self._make_request(force="true")
        with patch.object(server, "create_candidate_from_cv", return_value='{}') as mock_create:
            await server._upload_cv_handler(req)
        assert mock_create.call_args.kwargs["force"] is True

    @pytest.mark.asyncio
    async def test_upload_cv_default_format_is_pdf(self, monkeypatch):
        """No format field → format defaults to 'pdf'."""
        monkeypatch.setenv("UPLOAD_SECRET", "s")
        req = self._make_request(fmt=None)
        with patch.object(server, "create_candidate_from_cv", return_value='{}') as mock_create:
            await server._upload_cv_handler(req)
        assert mock_create.call_args.kwargs["format"] == "pdf"

    @pytest.mark.asyncio
    async def test_upload_cv_server_error_returns_500(self, monkeypatch):
        """BullhornAPIError in create path → 500 with JSON error body."""
        monkeypatch.setenv("UPLOAD_SECRET", "s")
        req = self._make_request()
        with patch.object(server, "create_candidate_from_cv", side_effect=BullhornAPIError("boom")):
            resp = await server._upload_cv_handler(req)
        assert resp.status_code == 500
        import json as _json
        body = _json.loads(resp.body)
        assert body["error"] == "bullhorn_error"
        assert "boom" in body["message"]

    @pytest.mark.asyncio
    async def test_upload_cv_create_returns_tool_error_as_500(self, monkeypatch):
        """create_candidate_from_cv returning JSON with 'error' key → handler returns 500."""
        monkeypatch.setenv("UPLOAD_SECRET", "s")
        req = self._make_request()
        error_body = '{"error": "identity_resolution_failed", "message": "No authentication token available"}'
        with patch.object(server, "create_candidate_from_cv", return_value=error_body):
            resp = await server._upload_cv_handler(req)
        assert resp.status_code == 500
        import json as _json
        body = _json.loads(resp.body)
        assert body["error"] == "identity_resolution_failed"


class TestQueryEntitiesNoteGuard:
    """Tests for query_entities hard refusal when entity='Note'."""

    def test_note_entity_returns_error_without_api_call(self, mock_client):
        """query_entities('Note', ...) returns structured error, no client call."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.query_entities("Note", "comments LIKE '%foo%'")

        data = json.loads(result)
        assert data["error"] == "entity_not_queryable"
        assert "get_notes_for_entity" in data["message"]
        assert "search_notes" in data["message"]
        mock_client.query.assert_not_called()

    def test_non_note_entity_still_passes_through(self, mock_client, sample_job):
        """query_entities for JobOrder is not affected by the Note guard."""
        mock_client.query.return_value = [sample_job]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.query_entities("JobOrder", "salary > 100000")

        data = json.loads(result)
        assert isinstance(data["data"], list)
        mock_client.query_with_meta.assert_called_once()


class TestUpdateRecordCandidate:
    """Tests for update_record with Candidate entity (CR31)."""

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        return meta

    def test_update_candidate_basic(self, mock_client, mock_metadata):
        """update_record calls client.update with Candidate entity and resolved fields."""
        mock_client.update.return_value = {
            "changedEntityId": 11234,
            "changeType": "UPDATE",
            "data": {"id": 11234, "occupation": "Head of Engineering"},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.update_record("Candidate", 11234, {"occupation": "Head of Engineering"})

        mock_client.update.assert_called_once_with("Candidate", 11234, {"occupation": "Head of Engineering"})
        data = json.loads(result)
        assert data["changedEntityId"] == 11234
        assert data["changeType"] == "UPDATE"

    def test_update_candidate_strips_title(self, mock_client, mock_metadata):
        """update_record strips 'title' from Candidate payload and returns warnings."""
        captured = {}

        def capture_update(entity, entity_id, fields):
            captured["fields"] = dict(fields)
            return {
                "changedEntityId": 11234,
                "changeType": "UPDATE",
                "data": {"id": 11234, "occupation": "CTO"},
            }

        mock_client.update.side_effect = capture_update

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.update_record("Candidate", 11234, {"title": "Mr", "occupation": "CTO"})

        data = json.loads(result)
        assert "title" not in captured["fields"], "title must be stripped from Candidate payload"
        assert captured["fields"].get("occupation") == "CTO"
        assert "warnings" in data
        assert any("title" in w for w in data["warnings"])

    def test_update_candidate_name_recomputed(self, mock_client, mock_metadata):
        """update_record fetches missing name part and recomputes 'name' when only firstName updated."""
        mock_client.get.return_value = {"firstName": "Old", "lastName": "Smith"}
        mock_client.update.return_value = {
            "changedEntityId": 11234,
            "changeType": "UPDATE",
            "data": {"id": 11234},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            server.update_record("Candidate", 11234, {"firstName": "John"})

        mock_client.get.assert_called_once_with("Candidate", 11234, fields="firstName,lastName")
        payload = mock_client.update.call_args[0][2]
        assert payload["name"] == "John Smith"

    def test_update_candidate_api_error(self, mock_client, mock_metadata):
        """update_record returns ERROR prefix when client.update raises BullhornAPIError."""
        mock_client.update.side_effect = BullhornAPIError("candidate update failed")
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.update_record("Candidate", 11234, {"occupation": "Engineer"})

        assert result.startswith("ERROR:")


class TestTearsheetTools:
    """Tests for tearsheet (hotlist) tools."""

    def test_list_tearsheets_default(self, mock_client):
        """list_tearsheets calls search_with_meta with entity=Tearsheet and empty query."""
        mock_client.search.return_value = [{"id": 1, "name": "CFO Pipeline"}]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_tearsheets()

        data = json.loads(result)
        assert "data" in data
        assert "pagination" in data
        call_kwargs = mock_client.search_with_meta.call_args.kwargs
        assert call_kwargs["entity"] == "Tearsheet"
        assert call_kwargs["query"] == ""

    def test_list_tearsheets_with_query(self, mock_client):
        """list_tearsheets passes query string to search_with_meta."""
        mock_client.search.return_value = [{"id": 1, "name": "CFO Pipeline"}]

        with patch.object(server, "get_client", return_value=mock_client):
            server.list_tearsheets(query="name:CFO*")

        call_kwargs = mock_client.search_with_meta.call_args.kwargs
        assert call_kwargs["query"] == "name:CFO*"

    def test_list_tearsheets_pagination(self, mock_client):
        """list_tearsheets forwards limit/start; next_start is populated when there are more results."""
        # Override side_effect to return a real meta dict with total > count so has_more is True.
        mock_client.search_with_meta.side_effect = None
        mock_client.search_with_meta.return_value = {
            "data": [{"id": i} for i in range(20)],
            "total": 100,
            "start": 0,
            "count": 20,
        }

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_tearsheets(limit=20, start=0)

        call_kwargs = mock_client.search_with_meta.call_args.kwargs
        assert call_kwargs["count"] == 20
        assert call_kwargs["start"] == 0
        data = json.loads(result)
        assert data["pagination"]["next_start"] == 20

    def test_get_tearsheet_returns_metadata_and_members(self, mock_client):
        """get_tearsheet fetches tearsheet header then candidates via association."""
        mock_client.get.return_value = {"id": 55, "name": "Pipeline"}
        mock_client.get_association.return_value = [{"id": 101, "firstName": "Jane"}]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_tearsheet(tearsheet_id=55)

        mock_client.get.assert_called_with("Tearsheet", 55)
        assoc_kwargs = mock_client.get_association_with_meta.call_args.kwargs
        assert assoc_kwargs["entity"] == "Tearsheet"
        assert assoc_kwargs["entity_id"] == 55
        assert assoc_kwargs["association"] == "candidates"

        data = json.loads(result)
        assert "candidates" in data
        assert data["candidates"]["data"][0]["firstName"] == "Jane"

    def test_get_tearsheet_custom_candidate_fields(self, mock_client):
        """get_tearsheet forwards custom candidate_fields to get_association_with_meta."""
        mock_client.get.return_value = {"id": 55, "name": "Pipeline"}
        mock_client.get_association.return_value = []

        with patch.object(server, "get_client", return_value=mock_client):
            server.get_tearsheet(tearsheet_id=55, candidate_fields="id,firstName")

        assoc_kwargs = mock_client.get_association_with_meta.call_args.kwargs
        assert assoc_kwargs["fields"] == "id,firstName"

    def test_create_tearsheet_basic(self, mock_client):
        """create_tearsheet auto-resolves owner via resolve_caller when owner omitted."""
        mock_client.create.return_value = {
            "changedEntityId": 100,
            "changeType": "INSERT",
            "data": {"id": 100, "name": "Test"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "resolve_caller", return_value={"id": 77}):
            result = server.create_tearsheet(name="Test Sheet")

        mock_client.create.assert_called_once_with(
            "Tearsheet", {"name": "Test Sheet", "owner": {"id": 77}}
        )
        data = json.loads(result)
        assert data["changedEntityId"] == 100

    def test_create_tearsheet_explicit_owner(self, mock_client):
        """create_tearsheet uses explicit owner and does not call resolve_caller."""
        mock_client.create.return_value = {
            "changedEntityId": 101,
            "changeType": "INSERT",
            "data": {"id": 101, "name": "Test Sheet"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "resolve_caller") as mock_resolve:
            server.create_tearsheet(name="Test Sheet", owner=42)

        mock_resolve.assert_not_called()
        mock_client.create.assert_called_once_with(
            "Tearsheet", {"name": "Test Sheet", "owner": {"id": 42}}
        )

    def test_create_tearsheet_identity_resolution_fails(self, mock_client):
        """create_tearsheet returns identity_resolution_failed when resolve_caller raises."""
        from bullhorn_mcp.identity import IdentityResolutionError

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")):
            result = server.create_tearsheet(name="Test Sheet")

        data = json.loads(result)
        assert data["error"] == "identity_resolution_failed"

    def test_create_tearsheet_with_description(self, mock_client):
        """create_tearsheet includes description in payload when provided."""
        mock_client.create.return_value = {
            "changedEntityId": 102,
            "changeType": "INSERT",
            "data": {"id": 102, "name": "Test Sheet"},
        }

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "resolve_caller", return_value={"id": 42}):
            server.create_tearsheet(name="Test Sheet", description="Senior devs", owner=42)

        mock_client.create.assert_called_once_with(
            "Tearsheet",
            {"name": "Test Sheet", "description": "Senior devs", "owner": {"id": 42}},
        )

    def test_add_to_tearsheet_single(self, mock_client):
        """add_to_tearsheet calls add_association and returns confirmation dict."""
        mock_client.add_association.return_value = {}

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.add_to_tearsheet(tearsheet_id=55, candidate_ids=[101])

        mock_client.add_association.assert_called_once_with(
            "Tearsheet", 55, "candidates", [101]
        )
        data = json.loads(result)
        assert data["added"] == [101]
        assert data["count"] == 1
        assert data["tearsheet_id"] == 55

    def test_add_to_tearsheet_multiple(self, mock_client):
        """add_to_tearsheet handles multiple candidate IDs."""
        mock_client.add_association.return_value = {}

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.add_to_tearsheet(tearsheet_id=55, candidate_ids=[101, 102, 103])

        mock_client.add_association.assert_called_once_with(
            "Tearsheet", 55, "candidates", [101, 102, 103]
        )
        data = json.loads(result)
        assert data["count"] == 3

    def test_remove_from_tearsheet_single(self, mock_client):
        """remove_from_tearsheet calls remove_association and returns confirmation dict."""
        mock_client.remove_association.return_value = {}

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.remove_from_tearsheet(tearsheet_id=55, candidate_ids=[101])

        mock_client.remove_association.assert_called_once_with(
            "Tearsheet", 55, "candidates", [101]
        )
        data = json.loads(result)
        assert data["removed"] == [101]
        assert data["count"] == 1

    def test_remove_from_tearsheet_multiple(self, mock_client):
        """remove_from_tearsheet handles multiple candidate IDs."""
        mock_client.remove_association.return_value = {}

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.remove_from_tearsheet(tearsheet_id=55, candidate_ids=[101, 102])

        data = json.loads(result)
        assert data["count"] == 2

    def test_tearsheet_tool_api_error(self, mock_client):
        """list_tearsheets returns ERROR prefix when search_with_meta raises BullhornAPIError."""
        mock_client.search_with_meta.side_effect = BullhornAPIError("API Error")

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_tearsheets()

        assert result.startswith("ERROR:")

    def test_add_to_tearsheet_empty_list(self, mock_client):
        """add_to_tearsheet returns invalid_argument error when candidate_ids is empty."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.add_to_tearsheet(tearsheet_id=55, candidate_ids=[])

        data = json.loads(result)
        assert data["error"] == "invalid_argument"
        mock_client.add_association.assert_not_called()

    def test_remove_from_tearsheet_empty_list(self, mock_client):
        """remove_from_tearsheet returns invalid_argument error when candidate_ids is empty."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.remove_from_tearsheet(tearsheet_id=55, candidate_ids=[])

        data = json.loads(result)
        assert data["error"] == "invalid_argument"
        mock_client.remove_association.assert_not_called()
