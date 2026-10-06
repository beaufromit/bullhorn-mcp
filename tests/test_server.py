"""Tests for MCP server tools."""

import importlib
import json
import os
import pytest
from unittest.mock import Mock, call, patch, patch as mock_patch
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


def _match(candidate_id=50, name="Jane Doe", percentage=97, band="high", flags=None, reasons=None):
    """One scored match as match_candidates returns it."""
    reasons = reasons or ["Same email jane@example.com", "Same name Jane Doe"]
    return {
        "candidate_id": candidate_id, "name": name, "points": 12.5, "percentage": percentage, "band": band,
        "breakdown": [{"signal": "email", "points": 6.0, "reason": r} for r in reasons],
        "flags": list(flags or []),
    }


def _match_result(matches=None, deleted_matches=None, flags=None, check_id="chk-new"):
    """A match_candidates result; no matches by default."""
    return {
        "match_check_id": check_id, "config_version": "1", "profile": {},
        "matches": list(matches or []), "flags": list(flags or []),
        "deleted_matches": list(deleted_matches or []),
    }


@pytest.fixture(autouse=True)
def match_stub():
    """Stub the CR44 retrieval and the match log: no tool test depends on retrieval or writes a log.

    Retrieval has its own tests (tests/test_duplicate_retrieval.py). Tests set
    ``match_stub.match.return_value`` / ``side_effect`` and assert on ``match_stub.log``.
    """
    from types import SimpleNamespace
    with patch.object(server, "match_candidates", return_value=_match_result()) as match, \
         patch.object(server.match_log, "log_outcome") as log:
        yield SimpleNamespace(match=match, log=log)


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

    def test_invalid_status_returns_error(self, mock_client):
        """status containing a single quote returns an error envelope."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_job_submissions(job_id=12345, status="Shortlisted' OR '1'='1")
        data = json.loads(result)
        assert data["error"] == "invalid_status"
        assert "single quotes" in data["message"]
        mock_client.query_with_meta.assert_not_called()


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


class TestNoteActionFilter:
    """CR37: the note_action parameter on list_contacts/list_candidates/list_jobs."""

    VALID_ACTIONS = {"BD Call", "Agent added", "Outbound Call"}

    @pytest.fixture
    def picklist(self):
        """Patch the Note.action picklist loader to a known value set."""
        with patch.object(
            server, "_load_valid_note_actions", return_value=set(self.VALID_ACTIONS)
        ):
            yield

    @pytest.mark.parametrize(
        "tool_name,entity",
        [
            ("list_contacts", "ClientContact"),
            ("list_candidates", "Candidate"),
            ("list_jobs", "JobOrder"),
        ],
    )
    def test_note_action_builds_quoted_clause(self, mock_client, picklist, tool_name, entity):
        """The value must be double-quoted: an unquoted multi-word action matches nothing."""
        mock_client.search.return_value = []

        with patch.object(server, "get_client", return_value=mock_client):
            getattr(server, tool_name)(note_action="BD Call")

        call_args = mock_client.search_with_meta.call_args
        assert call_args.kwargs["query"] == 'notes.action:"BD Call"'
        assert call_args.kwargs["entity"] == entity

    def test_note_action_combines_with_query_and_status(self, mock_client, picklist):
        """Combining a note filter with parent filters is the whole point of the parameter."""
        mock_client.search.return_value = []

        with patch.object(server, "get_client", return_value=mock_client):
            server.list_contacts(query="lastName:Smith", status="Active", note_action="BD Call")

        query = mock_client.search_with_meta.call_args.kwargs["query"]
        assert query == '((lastName:Smith) AND status:"Active") AND notes.action:"BD Call"'

    def test_note_action_normalises_case_to_picklist(self, mock_client, picklist):
        """Lucene matches actions case-insensitively; normalise rather than reject."""
        mock_client.search.return_value = []

        with patch.object(server, "get_client", return_value=mock_client):
            server.list_contacts(note_action="bd call")

        assert mock_client.search_with_meta.call_args.kwargs["query"] == 'notes.action:"BD Call"'

    def test_note_action_rejects_unknown_value(self, mock_client, picklist):
        """An unknown action is rejected with the valid picklist in the error."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_contacts(note_action="Nonexistent Action")

        data = json.loads(result)
        assert data["error"] == "invalid_note_action"
        assert data["valid_actions"] == sorted(self.VALID_ACTIONS)
        mock_client.search_with_meta.assert_not_called()

    @pytest.mark.parametrize("bad_value", ['BD "Call', "BD 'Call", "   "])
    def test_note_action_rejects_quotes_and_blanks(self, mock_client, picklist, bad_value):
        """Quote characters would break out of the generated clause."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_contacts(note_action=bad_value)

        assert json.loads(result)["error"] == "invalid_note_action"
        mock_client.search_with_meta.assert_not_called()

    def test_note_action_builds_clause_when_picklist_unavailable(self, mock_client):
        """A failed /meta call must not block a working search (CR37 deliverable D)."""
        mock_client.search.return_value = []

        with patch.object(server, "_load_valid_note_actions", return_value=None), \
             patch.object(server, "get_client", return_value=mock_client):
            result = server.list_contacts(note_action="Anything At All")

        assert "error" not in json.loads(result)
        query = mock_client.search_with_meta.call_args.kwargs["query"]
        assert query == 'notes.action:"Anything At All"'

    def test_omitting_note_action_leaves_query_untouched(self, mock_client, picklist):
        """No note_action means no nested clause, preserving pre-CR37 behaviour."""
        mock_client.search.return_value = []

        with patch.object(server, "get_client", return_value=mock_client):
            server.list_contacts(query="lastName:Smith")

        assert mock_client.search_with_meta.call_args.kwargs["query"] == "lastName:Smith"

    @pytest.mark.parametrize(
        "tool_name", ["list_contacts", "list_candidates", "list_jobs"]
    )
    def test_no_generated_query_uses_notes_isdeleted(self, mock_client, picklist, tool_name):
        """notes.isDeleted returns 0 on every entity, so it must never be generated.

        A future edit adding it for symmetry with the top-level isDeleted
        auto-append would silently break every note filter.
        """
        mock_client.search.return_value = []

        with patch.object(server, "get_client", return_value=mock_client):
            getattr(server, tool_name)(note_action="BD Call", status="Active")

        query = mock_client.search_with_meta.call_args.kwargs["query"]
        assert "notes.isDeleted" not in query

    def test_note_guidance_reaches_the_rendered_tool_description(self):
        """Assert on what the agent RECEIVES, not on the Python docstring.

        FastMCP builds tool.description from the docstring text BEFORE the "Args:"
        section only; Args entries become parameter-schema descriptions and
        everything after them (Returns:, Examples:) is dropped. Guidance placed
        after Examples: therefore never reaches the agent, which is exactly the
        discoverability failure CR37 exists to fix — so this test reads the
        rendered description rather than __doc__.
        """
        import asyncio

        tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}

        for name in ("list_contacts", "list_candidates", "list_jobs", "search_entities"):
            description = tools[name].description or ""
            assert "notes.action" in description, f"{name} description omits the nested path"
            assert 'notes.action:"' in description, f"{name} description omits the quoting rule"
            assert "notes.isDeleted" in description, f"{name} description omits the isDeleted caveat"
            assert "get_notes_for_entity" in description, f"{name} description omits the notes route"

        for name in ("list_contacts", "list_candidates", "list_jobs"):
            note_action = tools[name].parameters["properties"]["note_action"]
            assert "note" in (note_action.get("description") or "").lower()

    def test_search_notes_description_routes_to_working_paths(self):
        """search_notes must name where to go instead, in the text the agent reads."""
        import asyncio

        tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
        description = tools["search_notes"].description or ""

        assert "note_action" in description
        assert 'notes.action:"BD Call"' in description
        assert "get_notes_for_entity" in description
        assert "advanced note searching" not in description.lower()


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

    def test_invalid_status_returns_error(self, mock_client):
        """status containing a single quote returns an error envelope."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.list_placements(status="Approved' OR '1'='1")
        data = json.loads(result)
        assert data["error"] == "invalid_status"
        assert "single quotes" in data["message"]

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
        mock_client.add_note.assert_called_once_with(
            "ClientContact", 54321, "General Note", "Test",
            commenting_person_id=None, person_reference_id=None,
        )

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
            "Candidate", 11111, "General Note", "Strong fit",
            commenting_person_id=None, person_reference_id=None,
        )

    def test_add_note_invalid_entity(self, mock_client):
        """add_note returns error for unsupported entity type."""
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.add_note("FooBar", 1, "General Note", "Test")

        data = json.loads(result)
        assert data["error"] == "invalid_entity"
        mock_client.add_note.assert_not_called()

    def test_add_note_resolves_caller_for_commenting_person(self, mock_client):
        """add_note passes caller id as commenting_person_id, and as person_reference_id
        for JobOrder/Placement/Opportunity, when identity resolves."""
        mock_client.add_note.return_value = {
            "changedEntityId": 88904,
            "changeType": "INSERT",
            "data": {"id": 88904},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "resolve_caller", return_value={"id": 99, "email": "me@firm.com"}):
            server.add_note("JobOrder", 22222, "General Note", "On hold")

        mock_client.add_note.assert_called_once_with(
            "JobOrder", 22222, "General Note", "On hold",
            commenting_person_id=99, person_reference_id=99,
        )

    def test_add_note_handles_identity_resolution_error(self, mock_client):
        """add_note falls back to the record owner as person_reference_id when identity
        resolution fails, and leaves commenting_person_id unset (CR40 A2)."""
        from bullhorn_mcp.identity import IdentityResolutionError
        mock_client.get.return_value = {"id": 33333, "owner": {"id": 142235}}
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
            "Placement", 33333, "General Note", "Started",
            commenting_person_id=None, person_reference_id=142235,
        )
        mock_client.get.assert_called_once_with("Placement", 33333, fields="id,owner(id)")

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

    def test_joborder_note_attaches_to_consultant(self, mock_client):
        """CR40: a JobOrder note's personReference is the logged-in consultant."""
        mock_client.add_note.return_value = {
            "changedEntityId": 2653713,
            "changeType": "INSERT",
            "data": {"id": 2653713},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "resolve_caller", return_value={"id": 142235}):
            server.add_note("JobOrder", 51437, "General Note", "test")

        mock_client.add_note.assert_called_once_with(
            "JobOrder", 51437, "General Note", "test",
            commenting_person_id=142235, person_reference_id=142235,
        )

    def test_person_id_override(self, mock_client):
        """CR40: person_id overrides the caller as person_reference_id, but the
        caller is still stamped as commentingPerson."""
        mock_client.add_note.return_value = {
            "changedEntityId": 2653733,
            "changeType": "INSERT",
            "data": {"id": 2653733},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "resolve_caller", return_value={"id": 142235}):
            server.add_note("JobOrder", 51437, "General Note", "test", person_id=172083)

        mock_client.add_note.assert_called_once_with(
            "JobOrder", 51437, "General Note", "test",
            commenting_person_id=142235, person_reference_id=172083,
        )

    def test_no_caller_falls_back_to_record_owner(self, mock_client):
        """CR40: when the caller cannot be resolved, the record owner is used
        as person_reference_id for JobOrder/Placement/Opportunity."""
        from bullhorn_mcp.identity import IdentityResolutionError
        mock_client.get.return_value = {"id": 51437, "owner": {"id": 142235}}
        mock_client.add_note.return_value = {
            "changedEntityId": 2653714,
            "changeType": "INSERT",
            "data": {"id": 2653714},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")):
            server.add_note("JobOrder", 51437, "General Note", "test")

        mock_client.get.assert_called_once_with("JobOrder", 51437, fields="id,owner(id)")
        mock_client.add_note.assert_called_once_with(
            "JobOrder", 51437, "General Note", "test",
            commenting_person_id=None, person_reference_id=142235,
        )

    def test_no_caller_and_no_owner_returns_no_linked_person(self, mock_client):
        """CR40: no caller and no record owner returns a structured error, never
        the raw Bullhorn 400 about a missing personReference."""
        from bullhorn_mcp.identity import IdentityResolutionError
        mock_client.get.return_value = {"id": 51437, "owner": None}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")):
            result = server.add_note("JobOrder", 51437, "General Note", "test")

        data = json.loads(result)
        assert data["error"] == "no_linked_person"
        assert "missing required property" not in result
        mock_client.add_note.assert_not_called()

    def test_company_target_rejected_with_contact_list(self, mock_client):
        """CR40: ClientCorporation is no longer a note target; add_note redirects
        to the company's contacts and makes no write."""
        mock_client.query.return_value = [
            {"id": 145635, "firstName": "Duke", "lastName": "Nukem",
             "occupation": "CTO", "email": "duke@example.com"},
        ]
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.add_note("ClientCorporation", 10666, "General Note", "test")

        data = json.loads(result)
        assert data["error"] == "company_notes_live_on_contacts"
        assert data["contacts"][0]["id"] == 145635
        assert data["contacts_truncated"] is False
        mock_client.add_note.assert_not_called()
        mock_client.query.assert_called_once_with(
            "ClientContact", "clientCorporation.id=10666 AND status<>'Archive'",
            fields="id,firstName,lastName,occupation,email", count=51,
            order_by="lastName",
        )

    def test_company_target_contact_list_truncated_at_50(self, mock_client):
        """CR40 review m1: more than 50 contacts returns the first 50 and
        flags the list as truncated."""
        mock_client.query.return_value = [{"id": i} for i in range(51)]
        with patch.object(server, "get_client", return_value=mock_client):
            result = server.add_note("ClientCorporation", 10666, "General Note", "test")

        data = json.loads(result)
        assert len(data["contacts"]) == 50
        assert data["contacts_truncated"] is True
        mock_client.add_note.assert_not_called()

    def test_person_id_ignored_for_person_targets(self, mock_client):
        """CR40: person_id is only meaningful for JobOrder/Placement/Opportunity;
        the server does not resolve a person at all for Candidate/ClientContact/Lead."""
        from bullhorn_mcp.identity import IdentityResolutionError
        mock_client.add_note.return_value = {
            "changedEntityId": 1,
            "changeType": "INSERT",
            "data": {"id": 1},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "resolve_caller", side_effect=IdentityResolutionError("no token")):
            server.add_note("Candidate", 11111, "General Note", "test", person_id=999)

        mock_client.get.assert_not_called()
        mock_client.add_note.assert_called_once_with(
            "Candidate", 11111, "General Note", "test",
            commenting_person_id=None, person_reference_id=None,
        )

    def test_add_note_docstring_drops_client_corporation(self):
        """CR40: the registered tool description and parameter schema (what the
        agent actually sees, not __doc__ -- FastMCP drops everything from Args:
        onward out of .description, into each parameter's own schema entry).
        person_id is documented and ClientCorporation is no longer a listed
        entity or example. Prose explaining the company redirect may still
        mention the name in the pre-Args description."""
        import asyncio
        tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
        tool = tools["add_note"]
        description = tool.description or ""
        entity_schema_description = tool.parameters["properties"]["entity"]["description"]

        assert "person_id" in description
        assert "person_id" in tool.parameters["properties"]
        assert '"ClientContact", "JobOrder"' in entity_schema_description
        assert "ClientCorporation" not in entity_schema_description
        assert 'add_note("ClientCorporation"' not in description


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
        assert "request_cv_upload" in tools
        assert "get_cv_upload" in tools
        assert "show_cv_upload_box" in tools

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

    def test_main_http_redacts_upload_tokens_in_access_log(self):
        """main() in HTTP mode adds the upload-token filter to uvicorn.access, once."""
        import logging
        access_logger = logging.getLogger("uvicorn.access")
        before = list(access_logger.filters)
        try:
            with patch.object(server, "_transport_mode", "http"):
                with patch.object(server.mcp, "run"):
                    server.main()
                    server.main()
            added = [f for f in access_logger.filters if isinstance(f, server._RedactUploadTokenFilter)]
            assert len(added) == 1
        finally:
            access_logger.filters[:] = before

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

    def test_create_candidate_dup_found_no_force(self, mock_client, mock_metadata, match_stub):
        """create_candidate returns duplicate_found (match list with reasons) and writes nothing on a high match."""
        mock_client.resolve_owner.return_value = {"id": 1}
        match_stub.match.return_value = _match_result([_match()])

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate({
                "firstName": "Jane", "lastName": "Doe", "owner": {"id": 1},
            })

        data = json.loads(result)
        assert data["duplicate_found"] is True
        assert data["matches"][0]["candidate_id"] == 50
        mock_client.create.assert_not_called()

    def _create(self, mock_client, mock_metadata, fields=None, **kwargs):
        """Run create_candidate against a client that can create; returns the parsed JSON."""
        mock_client.resolve_owner.return_value = {"id": 1}
        mock_client.create.return_value = {
            "changedEntityId": 111, "changeType": "INSERT",
            "data": {"id": 111, "firstName": "Jane", "lastName": "Doe"},
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            return json.loads(server.create_candidate(
                fields or {"firstName": "Jane", "lastName": "Doe", "owner": {"id": 1}}, **kwargs
            ))

    def test_match_candidates_called_once_per_create(self, mock_client, mock_metadata, match_stub):
        """One create runs one match check, on a profile built from the resolved fields and lists."""
        fields = {"firstName": "Jane", "lastName": "Doe", "email": "jane@example.com",
                  "companyName": "Acme", "owner": {"id": 1}}
        work = [{"companyName": "Acme", "title": "Engineer", "startDate": 1514764800000, "endDate": None}]

        self._create(mock_client, mock_metadata, fields, work_history=work)

        match_stub.match.assert_called_once()
        profile = match_stub.match.call_args.args[1]
        assert (profile.first_name, profile.last_name, profile.emails) == ("Jane", "Doe", ["jane@example.com"])
        assert len(profile.work_history) == 1
        assert match_stub.match.call_args.kwargs == {"caller": 1}

    def test_high_band_stops(self, mock_client, mock_metadata, match_stub):
        """A high-band match stops the create with duplicate_found and logs nothing."""
        match_stub.match.return_value = _match_result([_match(band="high")])

        data = self._create(mock_client, mock_metadata)

        assert data["duplicate_found"] is True
        assert data["match_check_id"] == "chk-new"
        mock_client.create.assert_not_called()
        match_stub.log.assert_not_called()

    def test_guaranteed_identifier_stops(self, mock_client, mock_metadata, match_stub):
        """A guaranteed_match flag stops the create even when the band is uncertain."""
        match_stub.match.return_value = _match_result(
            [_match(band="uncertain", percentage=60, flags=["guaranteed_match:email"])]
        )

        data = self._create(mock_client, mock_metadata)

        assert data["duplicate_found"] is True
        assert "possible_duplicates" not in data
        mock_client.create.assert_not_called()

    def test_uncertain_stops_and_lists(self, mock_client, mock_metadata, match_stub):
        """An uncertain match stops with possible_duplicates and lists every non-low match."""
        match_stub.match.return_value = _match_result([
            _match(candidate_id=50, band="uncertain", percentage=55),
            _match(candidate_id=51, name="J Doe", band="uncertain", percentage=45),
        ])

        data = self._create(mock_client, mock_metadata)

        assert data["possible_duplicates"] is True
        assert "duplicate_found" not in data
        assert [m["candidate_id"] for m in data["matches"]] == [50, 51]
        assert "force=True" in data["hint"] and "chk-new" in data["hint"]
        assert "update_record on Candidate 50" in data["hint"]
        mock_client.create.assert_not_called()

    def test_low_band_writes(self, mock_client, mock_metadata, match_stub):
        """No non-low match (or only a deleted match): the Candidate is created."""
        match_stub.match.return_value = _match_result(deleted_matches=[{"candidate_id": 9, "name": "Jane Doe"}])

        data = self._create(mock_client, mock_metadata)

        assert data["changedEntityId"] == 111
        mock_client.create.assert_called_once()

    def test_stop_response_has_reasons(self, mock_client, mock_metadata, match_stub):
        """A stop says who, the percentage and why; it also carries deleted matches and flags."""
        match_stub.match.return_value = _match_result(
            [_match(reasons=["Same email jane@example.com"])],
            deleted_matches=[{"candidate_id": 9, "name": "Jane Doe"}], flags=["lookup_failed"],
        )

        data = self._create(mock_client, mock_metadata)

        assert data["matches"][0]["breakdown"][0]["reason"] == "Same email jane@example.com"
        assert "Jane Doe (Candidate 50) 97% high: Same email jane@example.com" in data["message"]
        assert data["deleted_matches"] == [{"candidate_id": 9, "name": "Jane Doe"}]
        assert data["flags"] == ["lookup_failed"]

    def test_force_skips_check_and_logs_created_with_force(self, mock_client, mock_metadata, match_stub):
        """force=True runs no check; a given match_check_id gets created_with_force."""
        match_stub.match.return_value = _match_result([_match()])

        data = self._create(mock_client, mock_metadata, force=True, match_check_id="chk-earlier")

        assert data["changedEntityId"] == 111
        match_stub.match.assert_not_called()
        match_stub.log.assert_called_once_with("chk-earlier", "created_with_force", 111, caller=1)

    def test_force_without_id_logs_nothing(self, mock_client, mock_metadata, match_stub):
        """force=True with no match_check_id: no check and nothing logged."""
        self._create(mock_client, mock_metadata, force=True)

        match_stub.match.assert_not_called()
        match_stub.log.assert_not_called()

    def test_create_logs_created_new(self, mock_client, mock_metadata, match_stub):
        """A create that goes ahead logs created_new under the new check's id."""
        match_stub.match.return_value = _match_result(check_id="chk-77")

        self._create(mock_client, mock_metadata)

        match_stub.log.assert_called_once_with("chk-77", "created_new", 111, caller=1)

    def test_check_failure_does_not_block_create(self, mock_client, mock_metadata, match_stub):
        """A failed check creates anyway and says so in warnings; no outcome is logged."""
        match_stub.match.side_effect = BullhornAPIError("boom")

        data = self._create(mock_client, mock_metadata)

        assert data["changedEntityId"] == 111
        assert data["warnings"] == ["Duplicate check could not run: boom"]
        match_stub.log.assert_not_called()

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

        mock_caller.assert_called()  # also called by the match log's caller lookup
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
    # -- CR43 / T41.5: child records and skills on create_candidate -----------

    def _run_with_children(self, mock_client, mock_metadata, fields, **kwargs):
        mock_client.resolve_owner.return_value = {"id": 99}
        mock_client.search.return_value = []
        counter = iter(range(401, 450))

        def _create(entity, data):
            n = 400 if entity == "Candidate" else next(counter)
            return {"changedEntityId": n, "changeType": "INSERT", "data": {"id": n}}

        mock_client.create.side_effect = _create
        mock_client.add_association.return_value = {
            "changedEntityId": 400, "changeType": "ASSOCIATE", "associationName": "primarySkills",
        }
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}), \
             patch("bullhorn_mcp.server.get_candidate_defaults", return_value={}), \
             patch("bullhorn_mcp.server.get_mcp_source", return_value="Claude"):
            return json.loads(server.create_candidate(fields, **kwargs))

    _CHILD_FIELDS = {
        "firstName": "Jane", "lastName": "Doe", "owner": {"id": 99},
        "occupation": "Engineer", "companyName": "Acme",
    }

    def test_create_candidate_writes_children(self, mock_client, mock_metadata):
        """work_history and education are created after the Candidate with exact payloads and listed in written."""
        data = self._run_with_children(
            mock_client, mock_metadata, dict(self._CHILD_FIELDS),
            work_history=[{"companyName": "Acme", "title": "Engineer", "startDate": 1}],
            education=[{"school": "UCD", "major": "Accounting"}],
        )

        from unittest.mock import call
        assert mock_client.create.call_args_list == [
            call("Candidate", {
                "firstName": "Jane", "lastName": "Doe", "owner": {"id": 99},
                "occupation": "Engineer", "companyName": "Acme",
                "source": "Claude", "name": "Jane Doe",
            }),
            call("CandidateWorkHistory", {
                "companyName": "Acme", "title": "Engineer", "startDate": 1, "candidate": {"id": 400},
            }),
            call("CandidateEducation", {"school": "UCD", "major": "Accounting", "candidate": {"id": 400}}),
        ]
        assert data["changedEntityId"] == 400
        assert data["changeType"] == "INSERT"
        assert data["written"] == {
            "work_history": [{"id": 401, "companyName": "Acme", "title": "Engineer", "startDate": 1}],
            "education": [{"id": 402, "school": "UCD", "major": "Accounting"}],
            "skill_set": [],
            "primary_skills": [],
        }
        assert "warnings" not in data

    def test_create_candidate_links_primary_skills(self, mock_client, mock_metadata):
        """primary_skills are linked by one association PUT, not an entity update."""
        data = self._run_with_children(
            mock_client, mock_metadata, dict(self._CHILD_FIELDS), primary_skills=[1000125, 1000200],
        )

        mock_client.add_association.assert_called_once_with("Candidate", 400, "primarySkills", [1000125, 1000200])
        mock_client.update.assert_not_called()
        assert "primarySkills" not in mock_client.create.call_args_list[0].args[1]
        assert data["written"]["primary_skills"] == [1000125, 1000200]

    def test_create_candidate_merges_skills_into_skillset(self, mock_client, mock_metadata):
        """skills merge with a skillSet given in fields, go in the create payload, and need no separate update."""
        fields = {**self._CHILD_FIELDS, "skillSet": "Treasury"}

        data = self._run_with_children(
            mock_client, mock_metadata, fields, skills=["Python", "treasury", "IFRS"],
        )

        from unittest.mock import call
        assert mock_client.create.call_args_list == [call("Candidate", {
            "firstName": "Jane", "lastName": "Doe", "owner": {"id": 99},
            "occupation": "Engineer", "companyName": "Acme", "skillSet": "Treasury, Python, IFRS",
            "source": "Claude", "name": "Jane Doe",
        })]
        mock_client.update.assert_not_called()
        assert data["written"]["skill_set"] == ["Python", "IFRS"]

    def test_create_candidate_without_lists_response_unchanged(self, mock_client, mock_metadata):
        """With no child lists the response keeps its old keys and has no written block."""
        data = self._run_with_children(mock_client, mock_metadata, dict(self._CHILD_FIELDS))

        assert set(data.keys()) == {"changedEntityId", "changeType", "data"}
        assert data["changedEntityId"] == 400
        assert [c.args[0] for c in mock_client.create.call_args_list] == ["Candidate"]
        mock_client.add_association.assert_not_called()

    def test_create_candidate_exception_after_create_returns_id(self, mock_client, mock_metadata):
        """An unexpected failure writing children still returns the new id, with the error text."""
        with patch.object(server, "_write_candidate_children", side_effect=RuntimeError("kaboom")):
            data = self._run_with_children(
                mock_client, mock_metadata, dict(self._CHILD_FIELDS),
                work_history=[{"companyName": "Acme", "title": "Engineer"}],
            )

        assert data["changedEntityId"] == 400
        assert data["error"] == "Candidate 400 was created, but writing its child records failed: kaboom"
        assert data["written"] == {"work_history": [], "education": [], "skill_set": [], "primary_skills": []}

    def test_create_candidate_required_fields_hint(self, mock_client, mock_metadata):
        """A missing required field says to retry with the missing fields added to fields."""
        mock_client.resolve_owner.return_value = {"id": 99}
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}), \
             patch("bullhorn_mcp.server.get_candidate_required", return_value=["companyName"]):
            data = json.loads(server.create_candidate({"firstName": "Jane", "lastName": "Doe", "owner": {"id": 99}}))

        assert data["error"] == "required_fields_missing"
        assert data["fields"] == ["companyName"]
        assert data["hint"] == (
            "Call again with the missing fields added to fields. "
            "For companyName use the candidate's current employer you were given."
        )
        mock_client.create.assert_not_called()


class TestFindDuplicateCandidates:
    """Tests for find_duplicate_candidates tool (CR44: one match check, every signal)."""

    def test_find_dup_candidates_email_exact_match(self, mock_client, match_stub):
        """find_duplicate_candidates returns the match result as is, and builds the profile from the arguments."""
        result_in = _match_result([_match(flags=["guaranteed_match:email"])])
        match_stub.match.return_value = result_in

        with patch.object(server, "get_client", return_value=mock_client):
            data = json.loads(server.find_duplicate_candidates("Jane", "Doe", email="jane@example.com"))

        assert data == result_in
        profile = match_stub.match.call_args.args[1]
        assert (profile.first_name, profile.last_name, profile.emails) == ("Jane", "Doe", ["jane@example.com"])

    def test_find_dup_candidates_name_fuzzy_match(self, mock_client, match_stub):
        """A name-only query is a usable profile and its matches come back ranked."""
        match_stub.match.return_value = _match_result([
            _match(band="uncertain", percentage=52), _match(candidate_id=51, band="uncertain", percentage=40),
        ])

        with patch.object(server, "get_client", return_value=mock_client):
            data = json.loads(server.find_duplicate_candidates("Jane", "Doe"))

        assert [m["candidate_id"] for m in data["matches"]] == [50, 51]
        assert match_stub.match.call_args.args[1].emails == []

    def test_find_dup_candidates_no_match(self, mock_client):
        """No match: an empty list with a match_check_id."""
        with patch.object(server, "get_client", return_value=mock_client):
            data = json.loads(server.find_duplicate_candidates("Completely", "Unknown"))

        assert data["matches"] == []
        assert data["match_check_id"] == "chk-new"

    def test_find_dup_candidates_api_error(self, mock_client, match_stub):
        """find_duplicate_candidates returns ERROR: prefix on BullhornAPIError."""
        match_stub.match.side_effect = BullhornAPIError("Search failed")

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.find_duplicate_candidates("Jane", "Doe")

        assert result == "ERROR: Search failed"

    def test_tool_and_create_path_agree_on_same_fixture(self, mock_client, match_stub):
        """The tool and create_candidate build the same profile for the same person and call the same function."""
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        mock_client.resolve_owner.return_value = {"id": 1}
        mock_client.create.return_value = {"changedEntityId": 5, "changeType": "INSERT", "data": {"id": 5}}

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=meta), \
             patch.object(server, "get_candidate_required", return_value=[]), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            server.find_duplicate_candidates("Jane", "Doe", email="jane@example.com")
            server.create_candidate(
                {"firstName": "Jane", "lastName": "Doe", "email": "jane@example.com", "owner": {"id": 1}}
            )

        tool_call, create_call = match_stub.match.call_args_list
        assert tool_call.args[1] == create_call.args[1]

    def test_run_match_check_swallows_errors(self, mock_client, match_stub):
        """The create/parse wrapper returns None on a retrieval failure and reports the text; the tool reports ERROR:."""
        match_stub.match.side_effect = BullhornAPIError("Search failed")
        errors: list[str] = []

        assert server._run_match_check(mock_client, server.CandidateProfile(first_name="Jane"), errors) is None
        assert errors == ["Search failed"]

        match_stub.match.side_effect = AuthenticationError("expired")
        assert server._run_match_check(mock_client, server.CandidateProfile(first_name="Jane")) is None

        import httpx
        match_stub.match.side_effect = httpx.ReadTimeout("timed out")
        assert server._run_match_check(mock_client, server.CandidateProfile(first_name="Jane")) is None

    def test_run_match_check_does_not_hide_bugs(self, mock_client, match_stub):
        """Review M2: a programming error in retrieval or scoring surfaces instead of turning the check off."""
        match_stub.match.side_effect = KeyError("surname")

        with pytest.raises(KeyError):
            server._run_match_check(mock_client, server.CandidateProfile(first_name="Jane"), [])

    def test_requires_a_signal(self, mock_client, match_stub):
        """Nothing usable (blank strings, empty lists) is query_required; no check runs."""
        with patch.object(server, "get_client", return_value=mock_client):
            data = json.loads(server.find_duplicate_candidates(first_name="  ", phones=[], work_history=[]))

        assert data["error"] == "query_required"
        match_stub.match.assert_not_called()

    def test_all_signals_reach_the_profile(self, mock_client, match_stub):
        """Phones, LinkedIn, employer, work history and education all land on the profile."""
        with patch.object(server, "get_client", return_value=mock_client):
            server.find_duplicate_candidates(
                phones=["+353 87 123 4567"], linkedin_url="https://www.linkedin.com/in/jane-doe",
                current_company="Acme",
                work_history=[{"companyName": "Acme", "title": "Engineer", "startDate": 1514764800000}],
                education=[{"school": "UCD", "degree": "BA"}],
            )

        profile = match_stub.match.call_args.args[1]
        assert profile.phones == ["+353 87 123 4567"]
        assert profile.linkedin_url == "https://www.linkedin.com/in/jane-doe"
        assert profile.current_company == "Acme"
        assert len(profile.work_history) == 1 and len(profile.education) == 1

    @pytest.mark.usefixtures("clean_upload_store")
    def test_profile_from_upload_id(self, mock_client, match_stub, sample_parsed_resume):
        """upload_id uses the stored parse as the profile; given arguments override its parts."""
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        upload_id = _seed_upload()

        with _http_as(), patch.object(server, "get_client", return_value=mock_client):
            server.find_duplicate_candidates(upload_id=upload_id)
            server.find_duplicate_candidates(upload_id=upload_id, last_name="Smith", email="new@example.com")

        base, overridden = (c.args[1] for c in match_stub.match.call_args_list)
        cand = sample_parsed_resume["candidate"]
        assert (base.first_name, base.last_name) == (cand["firstName"], cand["lastName"])
        assert cand["email"] in base.emails and len(base.work_history) > 0
        assert (overridden.first_name, overridden.last_name, overridden.emails) == ("Jane", "Smith", ["new@example.com"])
        assert len(overridden.work_history) == len(base.work_history)
        mock_client.parse_resume_file.assert_called_once()  # the stored parse served the second call

    @staticmethod
    def _real_check(mock_client, match_stub, answer):
        """Run the real match check behind the tool (review m6); ``answer(query)`` answers each Candidate search."""
        from bullhorn_mcp import duplicate_retrieval as dr
        dr._reset_n_cache()
        match_stub.match.side_effect = dr.match_candidates

        def search(entity, query, **kw):
            if query.startswith("id:[1 TO *]"):
                return {"data": [{"id": 1}], "total": 70000}
            return answer(query) or {"data": [], "total": 0}

        mock_client.search_with_meta.side_effect = search
        mock_client.query_with_meta.side_effect = lambda entity, where, **kw: {"data": [], "total": 0}
        log = patch.object(dr, "match_log")
        return log

    def test_deleted_match_flagged(self, mock_client, match_stub):
        """A soft-deleted namesake comes back in deleted_matches, ids and names only, never scored."""
        def answer(query):
            if "isDeleted:1" in query and "lastName" in query:
                return {"data": [{"id": 9, "firstName": "Jane", "lastName": "Doe"}], "total": 1}
            return None

        with self._real_check(mock_client, match_stub, answer) as log, \
             patch.object(server, "get_client", return_value=mock_client):
            log.new_match_check_id.return_value = "chk-real"
            data = json.loads(server.find_duplicate_candidates("Jane", "Doe"))

        assert data["matches"] == []
        assert data["deleted_matches"] == [{"candidate_id": 9, "name": "Jane Doe"}]
        assert data["match_check_id"] == "chk-real"

    def test_response_has_reasons(self, mock_client, match_stub):
        """A scored match carries who, percentage, band and a reason naming the shared email."""
        def answer(query):
            if query.startswith("id:("):
                return {"data": [{"id": 50, "firstName": "Jane", "lastName": "Doe", "email": "jane@example.com"}], "total": 1}
            if "email:" in query and "isDeleted:1" not in query:
                return {"data": [{"id": 50}], "total": 1}
            return None

        with self._real_check(mock_client, match_stub, answer) as log, \
             patch.object(server, "get_client", return_value=mock_client):
            log.new_match_check_id.return_value = "chk-real"
            data = json.loads(server.find_duplicate_candidates("Jane", "Doe", email="jane@example.com"))

        [m] = data["matches"]
        assert (m["candidate_id"], m["name"]) == (50, "Jane Doe")
        assert m["band"] == "high" and isinstance(m["percentage"], (int, float))
        assert any("jane@example.com" in b["reason"] for b in m["breakdown"])

    def test_description_tells_claude_to_show_reasons(self):
        """The rendered description (before Args:) carries the show-the-reasons instruction (D8b)."""
        import asyncio
        tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
        text = tools["find_duplicate_candidates"].description
        assert "percentage" in text and "reasons" in text and "match_check_id" in text
        for name in ("create_candidate", "create_candidate_from_cv"):
            assert "reasons" in tools[name].description


# --- CR41: CV upload ticket helpers ------------------------------------------

_CV_BYTES = b"%PDF-1.4 fake"


@pytest.fixture
def clean_upload_store():
    """Empty the module-level upload store before and after each test."""
    from bullhorn_mcp import uploads
    uploads._reset_upload_store()
    yield
    uploads._reset_upload_store()


def _token_for(sub="user-a", email="user-a@example.com"):
    """A patched access token (use site: bullhorn_mcp.identity.get_access_token)."""
    token = Mock()
    token.claims = {"sub": sub, "email": email}
    return patch("bullhorn_mcp.identity.get_access_token", return_value=token)


def _http_as(sub="user-a"):
    """Context manager: HTTP transport mode plus a caller whose Entra sub is ``sub``."""
    import contextlib
    stack = contextlib.ExitStack()
    stack.enter_context(patch.object(server, "_transport_mode", "http"))
    stack.enter_context(_token_for(sub, f"{sub}@example.com"))
    return stack


def _seed_upload(sub="user-a", filename="Jane_Doe_CV.pdf", data=_CV_BYTES, candidate_id=None):
    """Create a ticket on the live server store and redeem it. Returns the upload_id."""
    upload_id, token, _ = server.upload_store.create(sub, filename, candidate_id)
    server.upload_store.redeem(token, "8655a252-" + filename, data)
    return upload_id


class _FakeClock:
    """Injectable clock for UploadStore expiry tests."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.mark.usefixtures("clean_upload_store")
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
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        mock_client.search.return_value = []

        upload_id = _seed_upload()

        with _http_as(), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.parse_cv(
                upload_id=upload_id,
            )

        data = json.loads(result)
        assert "parsed" in data
        assert data["parsed"]["candidate"]["firstName"] == "Jane"
        assert "duplicate_check" in data
        mock_client.create.assert_not_called()

    def test_parse_cv_dup_found_in_preview(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        """parse_cv includes the full match result as duplicate_check, checked on the parsed profile."""
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        match_stub.match.return_value = _match_result([_match(flags=["guaranteed_match:email"])], check_id="chk-parse")

        upload_id = _seed_upload()

        with _http_as(), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.parse_cv(
                upload_id=upload_id,
            )

        data = json.loads(result)
        assert data["duplicate_check"]["matches"][0]["candidate_id"] == 50
        assert data["duplicate_check"]["matches"][0]["breakdown"]
        profile = match_stub.match.call_args.args[1]
        assert (profile.first_name, profile.last_name) == ("Jane", "Doe")
        assert profile.emails == ["jane.doe@example.com"]

    @pytest.mark.usefixtures("clean_upload_store")
    def test_parse_cv_returns_match_check_id(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        """parse_cv's duplicate_check carries the match_check_id to pass to the write tools."""
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        match_stub.match.return_value = _match_result(check_id="chk-parse")
        upload_id = _seed_upload()

        with _http_as(), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            data = json.loads(server.parse_cv(upload_id=upload_id))

        assert data["duplicate_check"]["match_check_id"] == "chk-parse"

    @pytest.mark.usefixtures("clean_upload_store")
    def test_parse_cv_check_failure_gives_null(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        """A failed check does not fail the parse: duplicate_check is null."""
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        match_stub.match.side_effect = BullhornAPIError("boom")
        upload_id = _seed_upload()

        with _http_as(), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            data = json.loads(server.parse_cv(upload_id=upload_id))

        assert data["duplicate_check"] is None
        assert data["parsed"]["candidate"]["firstName"] == "Jane"

    def test_parse_cv_api_error(self, mock_client, mock_metadata):
        """parse_cv returns ERROR: prefix on BullhornAPIError from parse_resume_file."""
        mock_client.parse_resume_file.side_effect = BullhornAPIError("Parse failed")

        upload_id = _seed_upload()

        with _http_as(), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.parse_cv(
                upload_id=upload_id,
            )

        assert result.startswith("ERROR:")

    def test_parse_cv_upload_not_found(self, mock_client, mock_metadata):
        """parse_cv with an unknown upload_id returns upload_not_found and never calls Bullhorn."""
        with _http_as(), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.parse_cv(upload_id="upl_doesnotexist")

        data = json.loads(result)
        assert data["error"] == "upload_not_found"
        mock_client.parse_resume_file.assert_not_called()
        mock_client.search.assert_not_called()

    def test_parse_cv_uses_stored_bytes_and_original_filename(self, mock_client, mock_metadata, sample_parsed_resume):
        """parse_cv sends the stored bytes, the ticket filename and the parser format; upload stays received."""
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        mock_client.search.return_value = []
        upload_id = _seed_upload()

        with _http_as(), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            server.parse_cv(upload_id=upload_id)

        mock_client.parse_resume_file.assert_called_once_with(_CV_BYTES, "Jane_Doe_CV.pdf", "pdf")
        rec = server.upload_store.get(upload_id, "user-a")
        assert rec["status"] == "received"
        assert rec["data"] == _CV_BYTES

    def test_stdio_mode_cv_tools_return_uploads_require_http_mode(self, mock_client):
        """parse_cv, create_candidate_from_cv(upload_id) and attach_cv error out in stdio mode."""
        with patch.object(server, "_transport_mode", "stdio"), \
             patch.object(server, "get_client", return_value=mock_client):
            results = [
                server.parse_cv(upload_id="upl_x"),
                server.create_candidate_from_cv(upload_id="upl_x"),
                server.attach_cv(candidate_id=1, upload_id="upl_x"),
            ]

        for result in results:
            assert json.loads(result)["error"] == "uploads_require_http_mode"
        mock_client.parse_resume_file.assert_not_called()

    def test_file_b64_parameter_removed(self):
        """The registered schemas expose upload_id and no file_b64, filename or format parameter."""
        import asyncio
        tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}

        for name in ("parse_cv", "create_candidate_from_cv", "attach_cv"):
            props = tools[name].parameters["properties"]
            assert "upload_id" in props, name
            for gone in ("file_b64", "filename", "format"):
                assert gone not in props, f"{name} still has {gone}"
    def test_parse_cv_stores_parse_and_omits_description(self, mock_client, mock_metadata, sample_parsed_resume):
        """parse_cv returns the reviewable view without the HTML, and stores the full parse on the upload."""
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        mock_client.search.return_value = []
        upload_id = _seed_upload()
        cand = sample_parsed_resume["candidate"]

        with _http_as(), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            data = json.loads(server.parse_cv(upload_id=upload_id))
            json.loads(server.parse_cv(upload_id=upload_id))  # second review call

        assert data == {
            "parsed": {
                "confidenceScore": 0.87,
                "candidate": {k: v for k, v in cand.items() if k != "description"},
                "description_length": len(cand["description"]),
                "candidateWorkHistory": sample_parsed_resume["candidateWorkHistory"],
                "candidateEducation": sample_parsed_resume["candidateEducation"],
                "skillList": ["EXCEL", "ANNUAL BUDGET", "IFRS"],
                "primarySkills": [{"name": "IFRS", "id": 1000125}, {"name": "Python", "id": 1000200}],
            },
            "duplicate_check": _match_result(),
        }
        assert server.upload_store.get(upload_id, "user-a")["parsed"] == sample_parsed_resume
        mock_client.parse_resume_file.assert_called_once()  # the second call used the stored parse


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
    def test_parse_cv_text_returns_view(self, mock_client, mock_metadata, sample_parsed_resume):
        """parse_cv_text returns the same reviewable view as parse_cv, without the HTML description."""
        mock_client.parse_resume_text.return_value = sample_parsed_resume
        mock_client.search.return_value = []
        cand = sample_parsed_resume["candidate"]

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            data = json.loads(server.parse_cv_text(content="Jane Doe\nAccountant"))

        assert data["parsed"]["candidate"] == {k: v for k, v in cand.items() if k != "description"}
        assert data["parsed"]["description_length"] == len(cand["description"])
        assert set(data["parsed"]) == {
            "confidenceScore", "candidate", "description_length", "candidateWorkHistory",
            "candidateEducation", "skillList", "primarySkills",
        }
        assert data["parsed"]["skillList"] == ["EXCEL", "ANNUAL BUDGET", "IFRS"]
        assert data["duplicate_check"] == _match_result()


@pytest.mark.usefixtures("clean_upload_store")
class TestCvHelpers:
    """Tests for the CR43 shared CV helpers (stored parse, skill split, child writer, hints)."""

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        meta.get_fields.return_value = []
        return meta

    @staticmethod
    def _create_ids(mock_client, first_id=500):
        counter = iter(range(first_id, first_id + 50))

        def _create(entity, data):
            n = next(counter)
            return {"changedEntityId": n, "changeType": "INSERT", "data": {"id": n}}

        mock_client.create.side_effect = _create

    @staticmethod
    def _associate(ids, candidate_id=500):
        return {
            "changedEntityId": candidate_id, "changeType": "ASSOCIATE",
            "entityName": "Candidate", "associationName": "primarySkills", "associatedIds": ids,
        }

    # -- _split_parsed_skills ------------------------------------------------

    def test_split_skills_live_shape(self, sample_parsed_resume):
        """Strings in skillList become names, primarySkills objects give ids, order kept."""
        names, ids = server._split_parsed_skills(sample_parsed_resume)

        assert names == ["EXCEL", "ANNUAL BUDGET", "IFRS"]
        assert ids == [1000125, 1000200]

    def test_split_skills_tolerates_missing_keys_and_dict_entries(self):
        """Missing keys give empty lists; dict skillList entries, blanks and bad ids cannot crash it."""
        assert server._split_parsed_skills({}) == ([], [])
        assert server._split_parsed_skills({"skillList": None, "primarySkills": None}) == ([], [])

        parsed = {
            "skillList": [{"id": 9, "name": "Excel"}, "excel", "  ", None, 5, {"id": 1}, "IFRS"],
            "primarySkills": [{"id": 1}, {"name": "no id"}, 7, "8", True, {"id": 1}, "x"],
        }
        names, ids = server._split_parsed_skills(parsed)

        assert names == ["Excel", "IFRS"]
        assert ids == [1, 7, 8]

    # -- _parse_upload -------------------------------------------------------

    def test_parse_upload_parses_once_and_stores(self, mock_client, sample_parsed_resume):
        """The first call parses the bytes and stores the result; a second load reuses it."""
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        upload_id = _seed_upload()

        with _http_as():
            upload, error = server._load_received_upload(upload_id)
            assert error is None
            first = server._parse_upload(mock_client, upload)
            again, error = server._load_received_upload(upload_id)
            assert error is None
            second = server._parse_upload(mock_client, again)

        assert first == sample_parsed_resume
        assert second == sample_parsed_resume
        mock_client.parse_resume_file.assert_called_once_with(_CV_BYTES, "Jane_Doe_CV.pdf", "pdf")
        assert server.upload_store.get(upload_id, "user-a")["parsed"] == sample_parsed_resume

    def test_parse_upload_uses_stored_parse(self, mock_client, sample_parsed_resume):
        """An upload that already holds a parse is not sent to the parser at all."""
        upload_id = _seed_upload()
        server.upload_store.set_parsed(upload_id, "user-a", sample_parsed_resume)

        with _http_as():
            upload, error = server._load_received_upload(upload_id)
            assert error is None
            result = server._parse_upload(mock_client, upload)

        assert result == sample_parsed_resume
        mock_client.parse_resume_file.assert_not_called()

    # -- _cv_response_view ---------------------------------------------------

    def test_cv_view_omits_description_shows_length(self, sample_parsed_resume):
        """The view drops the HTML description, keeps its length, and keeps everything Claude reviews."""
        html = sample_parsed_resume["candidate"]["description"]

        view = server._cv_response_view(sample_parsed_resume)

        expected_candidate = {k: v for k, v in sample_parsed_resume["candidate"].items() if k != "description"}
        assert view == {
            "confidenceScore": 0.87,
            "candidate": expected_candidate,
            "description_length": len(html),
            "candidateWorkHistory": sample_parsed_resume["candidateWorkHistory"],
            "candidateEducation": sample_parsed_resume["candidateEducation"],
            "skillList": ["EXCEL", "ANNUAL BUDGET", "IFRS"],
            "primarySkills": [{"name": "IFRS", "id": 1000125}, {"name": "Python", "id": 1000200}],
        }
        assert "description" in sample_parsed_resume["candidate"]  # the stored parse is not mutated

    # -- _write_candidate_children ------------------------------------------

    def test_children_payloads_carry_given_values(self, mock_client, mock_metadata):
        """Each child is created with exactly the given values, candidate {id} set and no id key."""
        self._create_ids(mock_client, first_id=501)
        work_history = [
            {"id": 99, "companyName": "Acme", "title": "Engineer", "startDate": 1000, "endDate": 2000},
            {"title": "Analyst", "startDate": 500},
        ]
        education = [
            {"id": 98, "school": "UCD", "degree": "BComm", "major": "Accounting", "graduationDate": 3000},
            {"certification": "ACCA"},
        ]

        written, warnings = server._write_candidate_children(
            mock_client, mock_metadata, 500, work_history, education, [], [], "", [],
        )

        from unittest.mock import call
        assert mock_client.create.call_args_list == [
            call("CandidateWorkHistory", {
                "companyName": "Acme", "title": "Engineer", "startDate": 1000, "endDate": 2000,
                "candidate": {"id": 500},
            }),
            call("CandidateWorkHistory", {"title": "Analyst", "startDate": 500, "candidate": {"id": 500}}),
            call("CandidateEducation", {
                "school": "UCD", "degree": "BComm", "major": "Accounting", "graduationDate": 3000,
                "candidate": {"id": 500},
            }),
            call("CandidateEducation", {"certification": "ACCA", "candidate": {"id": 500}}),
        ]
        assert written == {
            "work_history": [
                {"id": 501, "companyName": "Acme", "title": "Engineer", "startDate": 1000, "endDate": 2000},
                {"id": 502, "title": "Analyst", "startDate": 500},
            ],
            "education": [
                {"id": 503, "school": "UCD", "degree": "BComm", "major": "Accounting", "graduationDate": 3000},
                {"id": 504, "certification": "ACCA"},
            ],
            "skill_set": [],
            "primary_skills": [],
        }
        assert warnings == []
        mock_client.update.assert_not_called()
        mock_client.add_association.assert_not_called()
        assert work_history[0]["id"] == 99  # caller's entries are not mutated

    def test_children_payload_truncated_against_meta(self, mock_client, mock_metadata):
        """Child text over the /meta maxLength is clipped before the write."""
        self._create_ids(mock_client)
        mock_metadata.get_fields.return_value = [{"name": "comments", "maxLength": 5}]

        server._write_candidate_children(
            mock_client, mock_metadata, 500, [{"title": "Engineer", "comments": "abcdefghij"}], [], [], [], "", [],
        )

        mock_client.create.assert_called_once_with(
            "CandidateWorkHistory", {"title": "Engineer", "comments": "abcde", "candidate": {"id": 500}}
        )
        mock_metadata.get_fields.assert_called_with("CandidateWorkHistory")

    def test_children_primary_skills_use_association_put(self, mock_client, mock_metadata):
        """primarySkills are linked with one add_association PUT; client.update never carries them."""
        mock_client.add_association.return_value = self._associate([1000125, 1000200])

        written, warnings = server._write_candidate_children(
            mock_client, mock_metadata, 500, [], [], [], [1000125, 1000200], "", [],
        )

        mock_client.add_association.assert_called_once_with("Candidate", 500, "primarySkills", [1000125, 1000200])
        for c in mock_client.update.call_args_list:
            assert "primarySkills" not in c.args[2]
        mock_client.update.assert_not_called()
        assert written["primary_skills"] == [1000125, 1000200]
        assert warnings == []

    @pytest.mark.parametrize("response", [
        {"changedEntityId": 500, "changeType": "ASSOCIATE", "messages": [{"detailMessage": "ATTEMPT_TO_SET_TO_MANY"}]},
        {"changedEntityId": 500, "changeType": "UPDATE"},
        {},
        None,
    ])
    def test_children_association_warning_reported_as_failure(self, mock_client, mock_metadata, response):
        """A response with messages, or without changeType ASSOCIATE, is a warning and nothing counts as linked."""
        mock_client.add_association.return_value = response

        written, warnings = server._write_candidate_children(
            mock_client, mock_metadata, 500, [], [], [], [1000125], "", [],
        )

        assert written["primary_skills"] == []
        assert len(warnings) == 1
        assert warnings[0].startswith("primarySkills link not confirmed by Bullhorn, nothing linked")

    def test_children_skillset_appends_not_replaces(self, mock_client, mock_metadata):
        """New names are appended to the existing skillSet text in one update."""
        written, warnings = server._write_candidate_children(
            mock_client, mock_metadata, 500, [], [], ["Excel", "IFRS"], [], "Python, SQL", [],
        )

        mock_client.update.assert_called_once_with("Candidate", 500, {"skillSet": "Python, SQL, Excel, IFRS"})
        assert written["skill_set"] == ["Excel", "IFRS"]
        assert "already_present" not in written
        assert warnings == []

    def test_children_skip_already_present_skills(self, mock_client, mock_metadata):
        """Names match the skillSet case-insensitively and linked ids are skipped; both are reported."""
        mock_client.add_association.return_value = self._associate([1, 3])

        written, warnings = server._write_candidate_children(
            mock_client, mock_metadata, 500, [], [], ["EXCEL", "IFRS", "Budget"], [1, 2, 3], "Excel,  ifrs", [2],
        )

        mock_client.update.assert_called_once_with("Candidate", 500, {"skillSet": "Excel,  ifrs, Budget"})
        mock_client.add_association.assert_called_once_with("Candidate", 500, "primarySkills", [1, 3])
        assert written["skill_set"] == ["Budget"]
        assert written["primary_skills"] == [1, 3]
        assert written["already_present"] == {"skill_set": ["EXCEL", "IFRS"], "primary_skills": [2]}
        assert warnings == []

    def test_children_everything_present_writes_nothing(self, mock_client, mock_metadata):
        """When every name and id is already on the record no update and no PUT is made."""
        written, warnings = server._write_candidate_children(
            mock_client, mock_metadata, 500, [], [], ["Excel"], [2], "excel", [2],
        )

        mock_client.update.assert_not_called()
        mock_client.add_association.assert_not_called()
        mock_client.create.assert_not_called()
        assert written["skill_set"] == []
        assert written["primary_skills"] == []
        assert written["already_present"] == {"skill_set": ["Excel"], "primary_skills": [2]}
        assert warnings == []

    def test_children_item_failure_is_best_effort(self, mock_client, mock_metadata):
        """A failing item becomes a warning; the other items, skills and links are still attempted."""
        boom_wh = BullhornAPIError("wh boom")
        boom_skill = BullhornAPIError("skill boom")
        boom_link = BullhornAPIError("link boom")

        def _create(entity, data):
            if data.get("title") == "Bad":
                raise boom_wh
            return {"changedEntityId": 77, "changeType": "INSERT", "data": {"id": 77}}

        mock_client.create.side_effect = _create
        mock_client.update.side_effect = boom_skill
        mock_client.add_association.side_effect = boom_link

        written, warnings = server._write_candidate_children(
            mock_client, mock_metadata, 500,
            [{"title": "Bad"}, {"title": "Good"}, "not an object"],
            [{"school": "UCD"}],
            ["Excel"], [1], "", [],
        )

        assert written == {
            "work_history": [{"id": 77, "title": "Good"}],
            "education": [{"id": 77, "school": "UCD"}],
            "skill_set": [],
            "primary_skills": [],
        }
        assert warnings == [
            "Work history entry failed: wh boom",
            "Work history entry failed: expected an object, got str",
            "skillSet update failed: skill boom",
            "primarySkills link failed: link boom",
        ]
        mock_client.add_association.assert_called_once_with("Candidate", 500, "primarySkills", [1])

    # -- _required_fields_missing_response ----------------------------------

    def test_required_fields_hint_mentions_companyname(self):
        """The hint names the retry argument and, for companyName, says where to get the employer."""
        cv = json.loads(server._required_fields_missing_response(["companyName", "email"], "fields_override", from_cv=True))
        assert cv["error"] == "required_fields_missing"
        assert cv["fields"] == ["companyName", "email"]
        assert cv["hint"] == (
            "Call again with the missing fields added to fields_override. "
            "For companyName use the candidate's current employer from the CV (the most recent work history entry)."
        )

        direct = json.loads(server._required_fields_missing_response(["companyName"], "fields", from_cv=False))
        assert direct["hint"] == (
            "Call again with the missing fields added to fields. "
            "For companyName use the candidate's current employer you were given."
        )

        other = json.loads(server._required_fields_missing_response(["email"], "fields", from_cv=False))
        assert other["hint"] == "Call again with the missing fields added to fields."
        assert "companyName" not in other["hint"]


@pytest.mark.usefixtures("clean_upload_store")
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

    @pytest.fixture(autouse=True)
    def cv_config(self):
        """No tenant required fields, defaults or source from .env, so payloads are exact."""
        with patch("bullhorn_mcp.server.get_candidate_required", return_value=[]), \
             patch("bullhorn_mcp.server.get_candidate_defaults", return_value={}), \
             patch("bullhorn_mcp.server.get_mcp_source", return_value="Claude"):
            yield

    @staticmethod
    def _candidate_payload(parsed, **extra):
        """The Candidate create payload a default run must send for the live fixture."""
        return {
            **parsed["candidate"],
            "owner": {"id": 1},
            "source": "Claude",
            "skillSet": "EXCEL, ANNUAL BUDGET, IFRS",
            "name": "Jane Doe",
            **extra,
        }

    def test_create_from_cv_binary_success(self, mock_client, mock_metadata, sample_parsed_resume):
        """create_candidate_from_cv binary path creates the candidate, children and skills from the live-shape parse."""
        self._wire_create(mock_client, sample_parsed_resume, first_id=200)
        upload_id = _seed_upload()

        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id))

        assert data["created"] is True
        assert data["candidate_id"] == 200
        assert [w["id"] for w in data["written"]["work_history"]] == [201, 202]
        assert [e["id"] for e in data["written"]["education"]] == [203, 204]
        assert data["written"]["file"] == {"file_id": 55, "name": "Jane_Doe_CV.pdf"}

        # The full derivation chain must be tested on the Candidate payload.
        from unittest.mock import call
        assert mock_client.create.call_args_list[0] == call(
            "Candidate", self._candidate_payload(sample_parsed_resume)
        )
        payload = mock_client.create.call_args_list[0].args[1]
        assert "title" not in payload         # stripped by _strip_contact_title
        assert payload["occupation"] == "Financial Accountant"

    def test_create_from_cv_text_success(self, mock_client, mock_metadata, sample_parsed_resume):
        """create_candidate_from_cv text path creates the candidate without a file attach or retry block."""
        self._wire_create(mock_client, sample_parsed_resume, first_id=210, text=True)

        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate_from_cv(content="Jane Doe\nEngineer")

        data = json.loads(result)
        assert data["created"] is True
        assert data["candidate_id"] == 210
        assert data["written"]["file"] is None  # text-only skips attach
        assert "cv_attach_retry" not in data
        mock_client.attach_file.assert_not_called()
        mock_client.parse_resume_text.assert_called_once_with("Jane Doe\nEngineer", "text/plain")

        from unittest.mock import call
        assert mock_client.create.call_args_list[0] == call(
            "Candidate", self._candidate_payload(sample_parsed_resume)
        )

    def test_create_from_cv_duplicate_found(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        """create_candidate_from_cv returns duplicate_found with the reviewable parse when a match is detected."""
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        match_stub.match.return_value = _match_result([_match()])

        upload_id = _seed_upload()

        with _http_as(), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate_from_cv(
                upload_id=upload_id,
            )

        data = json.loads(result)
        assert data["duplicate_found"] is True
        assert data["matches"][0]["candidate_id"] == 50
        assert f"attach_cv(candidate_id=50, upload_id='{upload_id}', match_check_id='chk-new')" in data["hint"]
        assert "description" not in data["parsed"]["candidate"]
        assert data["parsed"]["description_length"] == len(sample_parsed_resume["candidate"]["description"])
        mock_client.create.assert_not_called()

    def test_create_from_cv_force_bypasses_dup(self, mock_client, mock_metadata, sample_parsed_resume, sample_candidate):
        """create_candidate_from_cv force=True skips dup check and creates."""
        self._wire_create(mock_client, sample_parsed_resume, first_id=220)
        upload_id = _seed_upload()

        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id, force=True))

        assert data["created"] is True
        assert data["candidate_id"] == 220
        mock_client.search.assert_not_called()

    def test_create_from_cv_required_fields_missing(self, mock_client, mock_metadata, sample_parsed_resume):
        """create_candidate_from_cv returns required_fields_missing when env-required field absent."""
        # Remove email from parsed data so the required field is absent
        resume = dict(sample_parsed_resume)
        resume["candidate"] = {k: v for k, v in resume["candidate"].items() if k != "email"}
        mock_client.parse_resume_file.return_value = resume
        mock_client.search.return_value = []

        upload_id = _seed_upload()

        with _http_as(), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}), \
             patch("bullhorn_mcp.server.get_candidate_required", return_value=["email"]):
            result = server.create_candidate_from_cv(
                upload_id=upload_id,
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
        """create_candidate_from_cv includes warnings when child records and the skill link fail."""
        mock_client.parse_resume_file.return_value = sample_parsed_resume
        mock_client.search.return_value = []

        def create_side_effect(entity, data):
            if entity == "Candidate":
                return {"changedEntityId": 230, "changeType": "INSERT", "data": {"id": 230}}
            raise BullhornAPIError("Child record failed")

        mock_client.create.side_effect = create_side_effect
        mock_client.add_association.side_effect = BullhornAPIError("link failed")
        mock_client._guess_content_type.return_value = "application/pdf"
        mock_client.attach_file.return_value = {"fileId": 70}

        upload_id = _seed_upload()

        with _http_as(), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            result = server.create_candidate_from_cv(
                upload_id=upload_id,
            )

        data = json.loads(result)
        # Candidate was created despite child failures
        assert data["created"] is True
        assert data["candidate_id"] == 230
        # One warning per failed child (2 work history, 2 education) plus the skill link
        assert data["warnings"] == [
            "Work history entry failed: Child record failed",
            "Work history entry failed: Child record failed",
            "Education entry failed: Child record failed",
            "Education entry failed: Child record failed",
            "primarySkills link failed: link failed",
        ]
        assert data["written"]["work_history"] == []
        assert data["written"]["education"] == []
        assert data["written"]["primary_skills"] == []
        # The file is still attached after the child failures
        assert data["written"]["file"] == {"file_id": 70, "name": "Jane_Doe_CV.pdf"}

    def test_source_auto_stamped_when_not_provided(self, mock_client, mock_metadata, sample_parsed_resume):
        """create_candidate_from_cv stamps source=get_mcp_source() when caller omits source."""
        self._wire_create(mock_client, sample_parsed_resume, first_id=250, text=True)

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
        self._wire_create(mock_client, sample_parsed_resume, first_id=255, text=True)

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

    @staticmethod
    def _wire_create(mock_client, parsed, first_id=300, text=False):
        """Mock a full successful create (candidate, children, skill link, attach)."""
        counter = iter(range(first_id, first_id + 50))

        def _create(entity, data):
            n = next(counter)
            return {"changedEntityId": n, "changeType": "INSERT", "data": {"id": n}}

        if text:
            mock_client.parse_resume_text.return_value = parsed
        else:
            mock_client.parse_resume_file.return_value = parsed
        mock_client.search.return_value = []
        mock_client.create.side_effect = _create
        mock_client.update.return_value = {"changedEntityId": first_id, "changeType": "UPDATE", "data": {"id": first_id}}
        mock_client.get.return_value = {"id": first_id, "skillSet": ""}
        mock_client.add_association.return_value = {
            "changedEntityId": first_id, "changeType": "ASSOCIATE", "associationName": "primarySkills",
        }
        mock_client.attach_file.return_value = {"fileId": 55, "name": "Jane_Doe_CV.pdf"}
        mock_client._guess_content_type.return_value = "application/pdf"

    def _run_create(self, mock_client, mock_metadata, upload_id, sub="user-a", **kwargs):
        with _http_as(sub), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            return server.create_candidate_from_cv(upload_id=upload_id, **kwargs)

    def _run_text(self, mock_client, mock_metadata, **kwargs):
        with patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            return server.create_candidate_from_cv(content="Jane Doe\nAccountant", **kwargs)

    def test_create_attaches_under_original_filename(self, mock_client, mock_metadata, sample_parsed_resume):
        """attach_file gets the ticket's original filename, not the prefixed multipart name."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id))

        assert data["created"] is True
        mock_client.attach_file.assert_called_once_with(
            "Candidate", data["candidate_id"], _CV_BYTES, "Jane_Doe_CV.pdf", "application/pdf", file_type="CV"
        )
        mock_client.parse_resume_file.assert_called_once_with(_CV_BYTES, "Jane_Doe_CV.pdf", "pdf")

    def test_create_marks_attached_and_drops_bytes(self, mock_client, mock_metadata, sample_parsed_resume):
        """After a successful attach the store shows attached, no bytes, and the Bullhorn file id."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        self._run_create(mock_client, mock_metadata, upload_id)

        rec = server.upload_store.get(upload_id, "user-a")
        assert rec["status"] == "attached"
        assert rec["data"] is None
        assert rec["file_id"] == 55

    def test_create_duplicate_found_keeps_upload(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        """A duplicate stops before any write, so the upload and its bytes are kept."""
        self._wire_create(mock_client, sample_parsed_resume)
        match_stub.match.return_value = _match_result([_match()])
        upload_id = _seed_upload()

        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id))

        assert data["duplicate_found"] is True
        mock_client.create.assert_not_called()
        mock_client.attach_file.assert_not_called()
        rec = server.upload_store.get(upload_id, "user-a")
        assert rec["status"] == "received"
        assert rec["data"] == _CV_BYTES

    def test_create_attach_failure_keeps_upload(self, mock_client, mock_metadata, sample_parsed_resume):
        """If attach_file raises, the candidate is still created, a warning is returned and the bytes are kept."""
        self._wire_create(mock_client, sample_parsed_resume)
        mock_client.attach_file.side_effect = BullhornAPIError("attach boom")
        upload_id = _seed_upload()

        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id))

        assert data["created"] is True
        assert data["written"]["file"] is None
        assert any("CV file attachment failed" in w for w in data["warnings"])
        rec = server.upload_store.get(upload_id, "user-a")
        assert rec["status"] == "received"
        assert rec["data"] == _CV_BYTES

    def test_create_attach_failure_points_retry_at_attach_cv(self, mock_client, mock_metadata, sample_parsed_resume):
        """A failed attach says to retry with attach_cv on the new record, and that retry adds nothing twice."""
        self._wire_create(mock_client, sample_parsed_resume)
        mock_client.attach_file.side_effect = BullhornAPIError("attach boom")
        upload_id = _seed_upload()

        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id))

        candidate_id = data["candidate_id"]
        retry = data["cv_attach_retry"]
        assert retry["next_call"] == f"attach_cv(candidate_id={candidate_id}, upload_id='{upload_id}')"
        assert "Do not call create_candidate_from_cv again" in retry["message"]

        # Follow the retry exactly as given, against a record that now holds what was written.
        written_calls = mock_client.create.call_args_list
        candidate_payload = written_calls[0].args[1]
        children = {"CandidateWorkHistory": [], "CandidateEducation": []}
        for c in written_calls[1:]:
            children[c.args[0]].append(c.args[1])
        mock_client.get.return_value = {**candidate_payload, "id": candidate_id}
        mock_client.query.side_effect = lambda entity, **kw: children[entity]
        mock_client.get_association.return_value = [{"id": 1000125}, {"id": 1000200}]
        mock_client.attach_file.reset_mock()
        mock_client.attach_file.side_effect = None
        mock_client.attach_file.return_value = {"fileId": 56}
        creates_before = mock_client.create.call_count
        mock_client.update.reset_mock()
        mock_client.add_association.reset_mock()
        with _http_as(), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            retried = json.loads(server.attach_cv(candidate_id=candidate_id, upload_id=upload_id))

        assert retried["committed"] is True
        assert retried["written"]["file"] == {"file_id": 56, "name": "Jane_Doe_CV.pdf"}
        assert mock_client.create.call_count == creates_before
        mock_client.update.assert_not_called()
        mock_client.add_association.assert_not_called()
        mock_client.attach_file.assert_called_once()
        assert mock_client.attach_file.call_args.args[:2] == ("Candidate", candidate_id)
        assert server.upload_store.get(upload_id, "user-a")["status"] == "attached"
        mock_client.parse_resume_file.assert_called_once()  # the retry used the stored parse

    def test_create_retry_with_corrections_attaches_file_only(self, mock_client, mock_metadata, sample_parsed_resume):
        """CR43 review C1: the retry after a corrected create attaches only the file, never the raw parse."""
        self._wire_create(mock_client, sample_parsed_resume)
        mock_client.attach_file.side_effect = BullhornAPIError("attach boom")
        upload_id = _seed_upload()

        data = json.loads(self._run_create(
            mock_client, mock_metadata, upload_id,
            fields_override={"companyName": "Sample Gadgets Ireland"},
            work_history=[{"companyName": "Sample Gadgets Ireland", "title": "Financial Accountant"}],
            skills=["EXCEL", "IFRS"], primary_skills=[1000125],
        ))
        candidate_id = data["candidate_id"]
        assert "only attaches the file" in data["cv_attach_retry"]["message"]

        for m in (mock_client.create, mock_client.update, mock_client.add_association, mock_client.get, mock_client.query):
            m.reset_mock()
        mock_client.attach_file.reset_mock()
        mock_client.attach_file.side_effect = None
        mock_client.attach_file.return_value = {"fileId": 56}
        with _http_as(), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            retried = json.loads(server.attach_cv(candidate_id=candidate_id, upload_id=upload_id))

        assert retried == {
            "committed": True, "candidate_id": candidate_id,
            "written": {"fields": [], "work_history": [], "education": [], "skill_set": [],
                        "primary_skills": [], "file": {"file_id": 56, "name": "Jane_Doe_CV.pdf"}},
        }
        mock_client.create.assert_not_called()
        mock_client.update.assert_not_called()
        mock_client.add_association.assert_not_called()
        mock_client.get.assert_not_called()
        mock_client.attach_file.assert_called_once_with(
            "Candidate", candidate_id, _CV_BYTES, "Jane_Doe_CV.pdf", "application/pdf", file_type="CV"
        )
        assert server.upload_store.get(upload_id, "user-a")["status"] == "attached"

    def test_attach_after_successful_create_writes_nothing(self, mock_client, mock_metadata, sample_parsed_resume):
        """attach_cv on the created record after the file attached writes nothing and says corrections were ignored."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()
        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id))
        candidate_id = data["candidate_id"]

        for m in (mock_client.create, mock_client.update, mock_client.add_association, mock_client.attach_file):
            m.reset_mock()
        with _http_as(), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            again = json.loads(server.attach_cv(candidate_id=candidate_id, upload_id=upload_id, skills=["Python"]))

        assert again["written"]["file"] == {"file_id": 55, "name": "Jane_Doe_CV.pdf", "already_attached": True}
        assert "Corrections were ignored" in again["warnings"][0]
        for m in (mock_client.create, mock_client.update, mock_client.add_association, mock_client.attach_file):
            m.assert_not_called()

    def test_create_skill_set_written_omits_truncated_names(self, mock_client, mock_metadata, sample_parsed_resume):
        """CR43 review m1: names cut by the skillSet maxLength clip are not reported as written."""
        self._wire_create(mock_client, sample_parsed_resume, text=True)
        mock_metadata.get_fields.return_value = [{"name": "skillSet", "maxLength": 12}]

        data = json.loads(self._run_text(mock_client, mock_metadata, skills=["EXCEL", "IFRS", "ANNUAL BUDGET"]))

        assert mock_client.create.call_args_list[0].args[1]["skillSet"] == "EXCEL, IFRS,"
        assert data["written"]["skill_set"] == ["EXCEL", "IFRS"]

    def test_create_writes_repeated_list_entries_once(self, mock_client, mock_metadata, sample_parsed_resume):
        """CR43 review cycle 2 m1: an entry repeated in one work_history or education argument is written once."""
        self._wire_create(mock_client, sample_parsed_resume, text=True)
        wh = {"companyName": "Acme", "title": "Accountant"}
        edu = {"certification": "ACCA"}

        self._run_text(mock_client, mock_metadata, work_history=[wh, dict(wh)], education=[edu, dict(edu)])

        children = [c.args[0] for c in mock_client.create.call_args_list[1:]]
        assert children == ["CandidateWorkHistory", "CandidateEducation"]

    def test_create_success_has_no_retry_block(self, mock_client, mock_metadata, sample_parsed_resume):
        """A successful attach returns no cv_attach_retry."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id))

        assert data["written"]["file"] is not None
        assert "cv_attach_retry" not in data

    def test_create_refused_while_upload_in_use(self, mock_client, mock_metadata, sample_parsed_resume):
        """A second overlapping commit on one upload gets upload_in_use and writes nothing."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()
        server.upload_store.claim(upload_id, "user-a")  # another call holds it

        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id))

        assert data["error"] == "upload_in_use"
        mock_client.parse_resume_file.assert_not_called()
        mock_client.create.assert_not_called()
        from bullhorn_mcp.uploads import UploadInUse
        with pytest.raises(UploadInUse):
            server.upload_store.claim(upload_id, "user-a")  # the other call still holds it

    def test_create_releases_claim_on_duplicate(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        """Returning early (duplicate found) still releases the upload for the next call."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        match_stub.match.return_value = _match_result([_match(candidate_id=9)])
        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id))

        assert data["duplicate_found"] is True
        server.upload_store.claim(upload_id, "user-a")  # does not raise

    def test_upload_pending_error(self, mock_client, mock_metadata):
        """A ticket with no file redeemed yet returns upload_pending and does not parse."""
        upload_id, _token, _ = server.upload_store.create("user-a", "Jane_Doe_CV.pdf")

        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id))

        assert data["error"] == "upload_pending"
        mock_client.parse_resume_file.assert_not_called()
        mock_client.create.assert_not_called()

    def test_upload_expired_error(self, mock_client, mock_metadata):
        """A ticket left past its 15 minute window returns upload_expired."""
        from bullhorn_mcp.uploads import UploadStore
        clock = _FakeClock()
        store = UploadStore(clock=clock)
        with patch.object(server, "upload_store", store):
            upload_id, _token, _ = server.upload_store.create("user-a", "Jane_Doe_CV.pdf")
            clock.now += 16 * 60
            data = json.loads(self._run_create(mock_client, mock_metadata, upload_id))

        assert data["error"] == "upload_expired"
        mock_client.parse_resume_file.assert_not_called()

    def test_upload_already_attached_error(self, mock_client, mock_metadata):
        """Reusing an upload whose file was already attached returns upload_already_attached."""
        upload_id = _seed_upload()
        server.upload_store.mark_attached(upload_id, 55)

        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id))

        assert data["error"] == "upload_already_attached"
        mock_client.parse_resume_file.assert_not_called()

    def test_other_users_upload_not_found(self, mock_client, mock_metadata):
        """An upload made by user-a is upload_not_found for user-b (never 'forbidden')."""
        upload_id = _seed_upload(sub="user-a")

        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id, sub="user-b"))

        assert data["error"] == "upload_not_found"
        mock_client.parse_resume_file.assert_not_called()

    # -- CR43: Claude's corrections, stored parse, never hide the id ----------

    def test_create_uses_stored_parse_without_reparsing(self, mock_client, mock_metadata, sample_parsed_resume):
        """parse_cv then create: the parser is called exactly once in total."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        with _http_as(), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata), \
             patch.object(server, "resolve_caller", return_value={"id": 1}):
            parsed_view = json.loads(server.parse_cv(upload_id=upload_id))
            data = json.loads(server.create_candidate_from_cv(upload_id=upload_id))

        assert parsed_view["parsed"]["candidate"]["firstName"] == "Jane"
        assert data["created"] is True
        mock_client.parse_resume_file.assert_called_once_with(_CV_BYTES, "Jane_Doe_CV.pdf", "pdf")

    def test_create_without_prior_parse_parses_and_stores(self, mock_client, mock_metadata, sample_parsed_resume):
        """Without parse_cv the create parses the file once and stores the parse on the upload."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id))

        assert data["created"] is True
        mock_client.parse_resume_file.assert_called_once()
        assert server.upload_store.get(upload_id, "user-a")["parsed"] == sample_parsed_resume

    def test_create_writes_corrected_work_history(self, mock_client, mock_metadata, sample_parsed_resume):
        """work_history replaces the parsed list; the corrected entry is what is written."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()
        corrected = [{"companyName": "Sample Gadgets Ireland", "title": "Financial Accountant", "startDate": 1514764800000}]

        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id, work_history=corrected))

        from unittest.mock import call
        wh_calls = [c for c in mock_client.create.call_args_list if c.args[0] == "CandidateWorkHistory"]
        assert wh_calls == [call("CandidateWorkHistory", {
            "companyName": "Sample Gadgets Ireland", "title": "Financial Accountant",
            "startDate": 1514764800000, "candidate": {"id": 300},
        })]
        assert data["written"]["work_history"] == [{
            "id": 301, "companyName": "Sample Gadgets Ireland", "title": "Financial Accountant",
            "startDate": 1514764800000,
        }]
        assert len([c for c in mock_client.create.call_args_list if c.args[0] == "CandidateEducation"]) == 2  # parsed list kept

    def test_create_writes_corrected_education(self, mock_client, mock_metadata, sample_parsed_resume):
        """education replaces the parsed list; the corrected entries are what is written."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()
        corrected = [{"school": "UCD", "degree": "BComm", "major": "Accounting", "graduationDate": 1214870400000}]

        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id, education=corrected))

        from unittest.mock import call
        edu_calls = [c for c in mock_client.create.call_args_list if c.args[0] == "CandidateEducation"]
        assert edu_calls == [call("CandidateEducation", {
            "school": "UCD", "degree": "BComm", "major": "Accounting", "graduationDate": 1214870400000,
            "candidate": {"id": 300},
        })]
        assert data["written"]["education"] == [{
            "id": 303, "school": "UCD", "degree": "BComm", "major": "Accounting", "graduationDate": 1214870400000,
        }]
        assert len([c for c in mock_client.create.call_args_list if c.args[0] == "CandidateWorkHistory"]) == 2  # parsed list kept

    def test_create_empty_list_writes_none(self, mock_client, mock_metadata, sample_parsed_resume):
        """An empty work_history or education list writes no child of that kind."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id, work_history=[], education=[]))

        assert [c.args[0] for c in mock_client.create.call_args_list] == ["Candidate"]
        assert data["written"]["work_history"] == []
        assert data["written"]["education"] == []
        assert data["written"]["skill_set"] == ["EXCEL", "ANNUAL BUDGET", "IFRS"]  # omitted skills still use the parse

    def test_create_skillset_in_create_payload(self, mock_client, mock_metadata, sample_parsed_resume):
        """Skill names are merged with a given skillSet and sent in the create payload, with no skillSet update."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        data = json.loads(self._run_create(
            mock_client, mock_metadata, upload_id,
            skills=["Python", "treasury", "IFRS"], fields_override={"skillSet": "Treasury"},
        ))

        payload = mock_client.create.call_args_list[0].args[1]
        assert payload["skillSet"] == "Treasury, Python, IFRS"
        assert data["written"]["skill_set"] == ["Python", "IFRS"]
        assert data["written"]["fields"]["skillSet"] == "Treasury, Python, IFRS"
        mock_client.update.assert_not_called()

    def test_create_links_primary_skills_by_association(self, mock_client, mock_metadata, sample_parsed_resume):
        """primarySkills from the parse are linked with one association PUT, never with an entity update."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id))

        mock_client.add_association.assert_called_once_with("Candidate", 300, "primarySkills", [1000125, 1000200])
        mock_client.update.assert_not_called()
        assert "primarySkills" not in mock_client.create.call_args_list[0].args[1]
        assert data["written"]["primary_skills"] == [1000125, 1000200]

    def test_create_primary_skills_argument_replaces_parse(self, mock_client, mock_metadata, sample_parsed_resume):
        """primary_skills given by Claude replace the parsed ids."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id, primary_skills=[1000300]))

        mock_client.add_association.assert_called_once_with("Candidate", 300, "primarySkills", [1000300])
        assert data["written"]["primary_skills"] == [1000300]

    def test_create_description_override_ignored_with_warning(self, mock_client, mock_metadata, sample_parsed_resume):
        """A description in fields_override is dropped with a warning; the parsed HTML is written."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()
        html = sample_parsed_resume["candidate"]["description"]

        data = json.loads(self._run_create(
            mock_client, mock_metadata, upload_id, fields_override={"description": "my own text"},
        ))

        assert mock_client.create.call_args_list[0].args[1]["description"] == html
        assert data["warnings"] == [
            "fields_override 'description' was ignored: the description always comes from the parsed CV."
        ]
        assert data["written"]["description_length"] == len(html)
        assert "description" not in data["written"]["fields"]

    def test_create_from_cv_checks_corrected_profile(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        """The profile is built from the corrected fields and the corrected work history and education (P5)."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()
        work = [{"companyName": "Gamma Ltd", "title": "Controller", "startDate": 1514764800000}]

        self._run_create(
            mock_client, mock_metadata, upload_id,
            fields_override={"companyName": "Gamma Ltd"}, work_history=work, education=[],
        )

        match_stub.match.assert_called_once()
        profile = match_stub.match.call_args.args[1]
        assert profile.current_company == "Gamma Ltd"
        assert len(profile.work_history) == 1 and profile.education == []

    def test_match_candidates_called_once_per_create(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        self._wire_create(mock_client, sample_parsed_resume)
        self._run_create(mock_client, mock_metadata, _seed_upload())
        match_stub.match.assert_called_once()

    def test_high_band_stops(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        self._wire_create(mock_client, sample_parsed_resume)
        match_stub.match.return_value = _match_result([_match(band="high")])
        data = json.loads(self._run_create(mock_client, mock_metadata, _seed_upload()))
        assert data["duplicate_found"] is True
        mock_client.create.assert_not_called()
        match_stub.log.assert_not_called()

    def test_guaranteed_identifier_stops(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        self._wire_create(mock_client, sample_parsed_resume)
        match_stub.match.return_value = _match_result(
            [_match(band="uncertain", percentage=55, flags=["guaranteed_match:phone"])]
        )
        data = json.loads(self._run_create(mock_client, mock_metadata, _seed_upload()))
        assert data["duplicate_found"] is True
        mock_client.create.assert_not_called()

    def test_uncertain_stops_and_lists(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        self._wire_create(mock_client, sample_parsed_resume)
        match_stub.match.return_value = _match_result([
            _match(candidate_id=50, band="uncertain", percentage=55),
            _match(candidate_id=51, band="uncertain", percentage=45),
        ])
        data = json.loads(self._run_create(mock_client, mock_metadata, _seed_upload()))
        assert data["possible_duplicates"] is True
        assert [m["candidate_id"] for m in data["matches"]] == [50, 51]
        assert "force=True" in data["hint"]
        assert "parsed" in data
        mock_client.create.assert_not_called()

    def test_low_band_writes(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        self._wire_create(mock_client, sample_parsed_resume)
        match_stub.match.return_value = _match_result(deleted_matches=[{"candidate_id": 9, "name": "Jane Doe"}])
        data = json.loads(self._run_create(mock_client, mock_metadata, _seed_upload()))
        assert data["created"] is True
        assert data["duplicate_check"]["deleted_matches"] == [{"candidate_id": 9, "name": "Jane Doe"}]

    def test_stop_response_has_reasons(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        self._wire_create(mock_client, sample_parsed_resume)
        match_stub.match.return_value = _match_result([_match(reasons=["Same email jane@example.com"])])
        data = json.loads(self._run_create(mock_client, mock_metadata, _seed_upload()))
        assert "Jane Doe (Candidate 50) 97% high: Same email jane@example.com" in data["message"]
        assert data["matches"][0]["breakdown"][0]["reason"] == "Same email jane@example.com"

    def test_stop_hint_by_source(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        """Review m2: an upload stop names attach_cv with the upload_id; a text CV (no upload) names update_record."""
        self._wire_create(mock_client, sample_parsed_resume)
        mock_client.parse_resume_text.return_value = sample_parsed_resume
        match_stub.match.return_value = _match_result([_match(band="high")])
        upload_id = _seed_upload()

        upload_stop = json.loads(self._run_create(mock_client, mock_metadata, upload_id))
        text_stop = json.loads(self._run_text(mock_client, mock_metadata))

        assert f"attach_cv(candidate_id=50, upload_id='{upload_id}', match_check_id='chk-new')" in upload_stop["hint"]
        assert "attach_cv" not in text_stop["hint"]
        assert "update_record on Candidate 50" in text_stop["hint"]
        assert "force=True and match_check_id='chk-new'" in text_stop["hint"]

    def test_stop_hint_names_every_listed_candidate(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        """Review m7: with more than one listed match the hint says so instead of naming only the top id."""
        self._wire_create(mock_client, sample_parsed_resume)
        match_stub.match.return_value = _match_result([
            _match(candidate_id=50, band="uncertain", percentage=55),
            _match(candidate_id=51, band="uncertain", percentage=45),
        ])
        data = json.loads(self._run_create(mock_client, mock_metadata, _seed_upload()))
        assert data["hint"].startswith("2 candidates are listed; Candidate 50 is the top match.")

        match_stub.match.return_value = _match_result([_match(candidate_id=50, band="uncertain", percentage=55)])
        data = json.loads(self._run_create(mock_client, mock_metadata, _seed_upload()))
        assert "candidates are listed" not in data["hint"]

    def test_force_skips_check_and_logs_created_with_force(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        self._wire_create(mock_client, sample_parsed_resume, first_id=400)
        match_stub.match.return_value = _match_result([_match()])
        data = json.loads(self._run_create(
            mock_client, mock_metadata, _seed_upload(), force=True, match_check_id="chk-earlier",
        ))
        assert data["created"] is True and data["duplicate_check"] is None
        match_stub.match.assert_not_called()
        match_stub.log.assert_called_once_with("chk-earlier", "created_with_force", 400, caller=1)

    def test_force_without_id_logs_nothing(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        self._wire_create(mock_client, sample_parsed_resume)
        self._run_create(mock_client, mock_metadata, _seed_upload(), force=True)
        match_stub.match.assert_not_called()
        match_stub.log.assert_not_called()

    def test_create_logs_created_new(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        self._wire_create(mock_client, sample_parsed_resume, first_id=500)
        match_stub.match.return_value = _match_result(check_id="chk-77")
        self._run_create(mock_client, mock_metadata, _seed_upload())
        match_stub.log.assert_called_once_with("chk-77", "created_new", 500, caller=1)

    def test_check_failure_does_not_block_create(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        self._wire_create(mock_client, sample_parsed_resume)
        match_stub.match.side_effect = BullhornAPIError("boom")
        data = json.loads(self._run_create(mock_client, mock_metadata, _seed_upload()))
        assert data["created"] is True
        assert "Duplicate check could not run: boom" in data["warnings"]
        assert data["duplicate_check"] is None
        match_stub.log.assert_not_called()

    def test_create_dup_check_uses_corrected_names(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        """The match check runs on the corrected names and email, not the raw parse."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        data = json.loads(self._run_create(
            mock_client, mock_metadata, upload_id,
            fields_override={"firstName": "Janet", "lastName": "Doe-Smith", "email": "janet@example.com"},
        ))

        profile = match_stub.match.call_args.args[1]
        assert (profile.first_name, profile.last_name, profile.emails) == ("Janet", "Doe-Smith", ["janet@example.com"])
        assert mock_client.create.call_args_list[0].args[1]["name"] == "Janet Doe-Smith"
        assert data["created"] is True

    def test_create_unexpected_exception_after_create_returns_id(self, mock_client, mock_metadata, sample_parsed_resume):
        """Any exception after the Candidate exists still returns the id, the error and the attach retry."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        with patch.object(server, "_write_candidate_children", side_effect=RuntimeError("kaboom")):
            data = json.loads(self._run_create(mock_client, mock_metadata, upload_id))

        assert data["created"] is True
        assert data["candidate_id"] == 300
        assert data["error"] == "Candidate 300 was created, but a later step failed: kaboom"
        assert data["cv_attach_retry"]["next_call"] == f"attach_cv(candidate_id=300, upload_id='{upload_id}')"
        mock_client.attach_file.assert_not_called()
        rec = server.upload_store.get(upload_id, "user-a")
        assert rec["status"] == "received"
        assert rec["data"] == _CV_BYTES
        server.upload_store.claim(upload_id, "user-a")  # the claim was released

    def test_create_reports_everything_written(self, mock_client, mock_metadata, sample_parsed_resume):
        """The response lists every field, child, skill and the file that was written."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()
        cand = sample_parsed_resume["candidate"]

        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id))

        assert data == {
            "created": True,
            "candidate_id": 300,
            "written": {
                "fields": {
                    **{k: v for k, v in cand.items() if k != "description"},
                    "owner": {"id": 1},
                    "source": "Claude",
                    "skillSet": "EXCEL, ANNUAL BUDGET, IFRS",
                    "name": "Jane Doe",
                },
                "description_length": len(cand["description"]),
                "work_history": [
                    {"id": 301, "title": "Financial Accountant Sample Gadgets Ireland",
                     "startDate": 1514764800000, "endDate": 1717200000000},
                    {"id": 302, "companyName": "Beta Systems", "title": "Assistant Accountant",
                     "startDate": 1388534400000, "endDate": 1514764800000},
                ],
                "education": [
                    {"id": 303, "school": "University College Dublin", "major": "Accounting",
                     "graduationDate": 1214870400000},
                    {"id": 304, "certification": "ACCA"},
                ],
                "skill_set": ["EXCEL", "ANNUAL BUDGET", "IFRS"],
                "primary_skills": [1000125, 1000200],
                "file": {"file_id": 55, "name": "Jane_Doe_CV.pdf"},
            },
            "duplicate_check": _match_result(),
        }

    def test_create_marks_attached_with_candidate_id(self, mock_client, mock_metadata, sample_parsed_resume):
        """mark_attached records the new Candidate id and the stored parse is kept on the tombstone."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        data = json.loads(self._run_create(mock_client, mock_metadata, upload_id))

        rec = server.upload_store.get(upload_id, "user-a")
        assert rec["status"] == "attached"
        assert rec["attached_candidate_id"] == data["candidate_id"] == 300
        assert rec["file_id"] == 55
        assert rec["data"] is None
        assert rec["parsed"] == sample_parsed_resume

    def test_create_required_fields_hint(self, mock_client, mock_metadata, sample_parsed_resume):
        """A missing companyName gives the retry hint and writes nothing; supplying it then succeeds."""
        self._wire_create(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        with patch("bullhorn_mcp.server.get_candidate_required", return_value=["companyName"]):
            data = json.loads(self._run_create(mock_client, mock_metadata, upload_id))

        assert data["error"] == "required_fields_missing"
        assert data["fields"] == ["companyName"]
        assert data["hint"] == (
            "Call again with the missing fields added to fields_override. "
            "For companyName use the candidate's current employer from the CV (the most recent work history entry)."
        )
        mock_client.create.assert_not_called()
        assert server.upload_store.get(upload_id, "user-a")["status"] == "received"  # nothing consumed

        with patch("bullhorn_mcp.server.get_candidate_required", return_value=["companyName"]):
            retried = json.loads(self._run_create(
                mock_client, mock_metadata, upload_id, fields_override={"companyName": "Sample Gadgets Ireland"},
            ))

        assert retried["created"] is True
        assert mock_client.create.call_args_list[0].args[1]["companyName"] == "Sample Gadgets Ireland"
        mock_client.parse_resume_file.assert_called_once()  # the retry reused the stored parse

    def test_create_text_mode_accepts_corrections(self, mock_client, mock_metadata, sample_parsed_resume):
        """Text mode takes the same corrections; nothing is stored or attached."""
        self._wire_create(mock_client, sample_parsed_resume, first_id=400, text=True)
        corrected_wh = [{"companyName": "Sample Gadgets Ireland", "title": "Financial Accountant", "startDate": 1514764800000}]

        data = json.loads(self._run_text(
            mock_client, mock_metadata,
            fields_override={"companyName": "Sample Gadgets Ireland"},
            work_history=corrected_wh, skills=["Python"], primary_skills=[1000200],
        ))

        from unittest.mock import call
        assert mock_client.create.call_args_list[0] == call("Candidate", self._candidate_payload(
            sample_parsed_resume, companyName="Sample Gadgets Ireland", skillSet="Python",
        ))
        wh_calls = [c for c in mock_client.create.call_args_list if c.args[0] == "CandidateWorkHistory"]
        assert wh_calls == [call("CandidateWorkHistory", {**corrected_wh[0], "candidate": {"id": 400}})]
        assert len([c for c in mock_client.create.call_args_list if c.args[0] == "CandidateEducation"]) == 2
        mock_client.add_association.assert_called_once_with("Candidate", 400, "primarySkills", [1000200])
        mock_client.parse_resume_text.assert_called_once()
        mock_client.attach_file.assert_not_called()
        assert data["written"]["file"] is None
        assert "cv_attach_retry" not in data
        assert data["written"]["skill_set"] == ["Python"]


@pytest.mark.usefixtures("clean_upload_store")
class TestAttachCv:
    """Tests for attach_cv (CR43: additions written on every call, overwrites need confirm=True)."""

    CID = 67890
    DESC = "<html><body><p>Jane Doe</p><p>Financial Accountant with 8 years in group reporting.</p></body></html>"

    @pytest.fixture
    def mock_metadata(self):
        from unittest.mock import Mock
        from bullhorn_mcp.metadata import BullhornMetadata
        meta = Mock(spec=BullhornMetadata)
        meta.resolve_fields.side_effect = lambda entity, fields: fields
        meta.get_fields.return_value = []
        return meta

    def _existing(self, **over):
        """A Candidate that already matches the parse except phone/description (empty) and occupation (different)."""
        base = {
            "id": self.CID, "firstName": "Jane", "lastName": "Doe", "email": "jane.doe@example.com",
            "phone": None, "occupation": "Junior Developer", "description": None, "skillSet": "EXCEL",
        }
        base.update(over)
        return base

    def _prep(self, mock_client, parsed, existing=None, wh=None, edu=None, linked=None):
        mock_client.parse_resume_file.return_value = parsed
        mock_client.get.return_value = existing if existing is not None else self._existing()
        wh = wh or []
        edu = edu or []
        mock_client.query.side_effect = lambda entity, **kw: wh if entity == "CandidateWorkHistory" else edu
        mock_client.get_association.return_value = linked or []
        counter = iter(range(5000, 6000))
        mock_client.create.side_effect = lambda entity, payload: {"changedEntityId": next(counter)}
        mock_client.update.return_value = {"changedEntityId": self.CID, "changeType": "UPDATE"}
        mock_client.add_association.return_value = {"changeType": "ASSOCIATE"}
        mock_client.attach_file.return_value = {"fileId": 80, "name": "Jane_Doe_CV.pdf"}
        mock_client._guess_content_type.return_value = "application/pdf"

    def _attach(self, mock_client, mock_metadata, sub="user-a", **kwargs):
        kwargs.setdefault("candidate_id", self.CID)
        with _http_as(sub), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            return json.loads(server.attach_cv(**kwargs))

    # --- _plan_cv_update (pure) -------------------------------------------------

    def _plan(self, existing, proposed, fields_to_update=None):
        return server._plan_cv_update(existing, proposed, fields_to_update, [], [], [], [], [], [], "", [])

    def test_plan_empty_field_is_addition(self):
        for empty in (None, "", "   "):
            plan = self._plan({"phone": empty}, {"phone": "555-0001"})
            assert plan["additions"]["fields"] == {"phone": "555-0001"}
            assert plan["overwrites"] == []

    def test_plan_filled_field_is_overwrite(self):
        plan = self._plan({"occupation": "Junior Developer"}, {"occupation": "Financial Accountant"})
        assert plan["additions"]["fields"] == {}
        assert plan["overwrites"] == [
            {"field": "occupation", "current": "Junior Developer", "proposed": "Financial Accountant"}
        ]

    def test_plan_equal_after_trim_skipped(self):
        plan = self._plan({"occupation": " Financial Accountant "}, {"occupation": "Financial Accountant  "})
        assert plan["additions"]["fields"] == {}
        assert plan["overwrites"] == []

    def test_plan_blank_proposed_value_skipped(self):
        """A blank parse never clears a field, filled or empty."""
        plan = self._plan({"companyName": "Acme", "phone": None}, {"companyName": "", "phone": "  "})
        assert plan["additions"]["fields"] == {}
        assert plan["overwrites"] == []

    def test_plan_fields_to_update_limits_fields(self):
        existing = {"phone": None, "occupation": "Junior Developer", "email": None}
        proposed = {"phone": "555-0001", "occupation": "Financial Accountant", "email": "a@b.com"}
        plan = self._plan(existing, proposed, fields_to_update=["occupation"])
        assert plan["additions"]["fields"] == {}
        assert [c["field"] for c in plan["overwrites"]] == ["occupation"]

    def test_plan_description_overwrite_shows_lengths_only(self):
        plan = self._plan({"description": "<p>Old CV</p>"}, {"description": "<p>New CV here</p>"})
        assert plan["overwrites"] == [{"field": "description", "current_length": 13, "proposed_length": 18}]

    # --- education matching (live tenant shapes, 2026-10-02 sample) ---------------

    def _plan_edu(self, existing_edu, education):
        return server._plan_cv_update({}, {}, None, [], existing_edu, [], education, [], [], "", [])

    def test_plan_education_different_certifications_both_added(self):
        """Certification-only entries with different text never match (the old key merged them all)."""
        plan = self._plan_edu([{"id": 1, "certification": "ACCA"}], [{"certification": "CIMA"}, {"certification": "PMP"}])
        assert plan["additions"]["education"] == [{"certification": "CIMA"}, {"certification": "PMP"}]
        assert plan["already_present"]["education"] == 0

    def test_plan_education_certification_matches_degree_only(self):
        """A parsed certification matches an older record holding the same text as a bare degree."""
        plan = self._plan_edu([{"id": 1, "degree": "ACCA", "school": None}], [{"certification": " acca "}])
        assert plan["additions"]["education"] == []
        assert plan["already_present"]["education"] == 1

    def test_plan_education_missing_field_one_side_matches(self):
        """A field filled on one side only does not block the match."""
        existing = [{"id": 1, "school": "University College Dublin", "degree": "bachelors",
                     "major": "Accounting", "graduationDate": 1214870400000}]
        plan = self._plan_edu(existing, [{"school": "University College Dublin", "major": "accounting"}])
        assert plan["additions"]["education"] == []

    def test_plan_education_conflicting_field_not_matched(self):
        """Same school, different degree: a second qualification, so it is added."""
        existing = [{"id": 1, "school": "UCD", "degree": "bachelors"}]
        new = [{"school": "UCD", "degree": "masters"}]
        assert self._plan_edu(existing, new)["additions"]["education"] == new

    def test_plan_education_needs_shared_identity_field(self):
        """Only a shared graduationDate (no shared school/degree/major/certification) is not a match."""
        existing = [{"id": 1, "school": "UCD", "graduationDate": 1214870400000}]
        new = [{"degree": "MBA", "graduationDate": 1214870400000}]
        assert self._plan_edu(existing, new)["additions"]["education"] == new

    def test_plan_education_shared_generic_degree_alone_not_matched(self):
        """Live replay case: a shared degree value ("first class honours") is not enough to match."""
        existing = [{"id": 1, "degree": "First Class Honours", "major": "Econometrics"}]
        new = [{"school": "University of Delhi", "degree": "First Class Honours", "graduationDate": 1451667600000}]
        assert self._plan_edu(existing, new)["additions"]["education"] == new

    def test_plan_education_degree_with_school_is_not_a_credential(self):
        """'ACCA' as a degree at a school is a full entry, not a bare credential, so a bare certification does not match it."""
        existing = [{"id": 1, "school": "Griffith College", "degree": "ACCA"}]
        new = [{"certification": "ACCA"}]
        assert self._plan_edu(existing, new)["additions"]["education"] == new

    def test_plan_education_same_school_degree_vs_certification_both_kept(self):
        """CR43 review M1: a BComm and a later diploma at the same school are two qualifications."""
        existing = [{"id": 1, "school": "UCD", "degree": "BComm"}]
        new = [{"school": "UCD", "certification": "Professional Diploma in Tax"}]
        assert self._plan_edu(existing, new)["additions"]["education"] == new

    def test_plan_education_same_school_degree_vs_major_both_kept(self):
        """CR43 review M1: an MSc entry with only a major is not the BComm at the same school."""
        existing = [{"id": 1, "school": "UCD", "degree": "BComm"}]
        new = [{"school": "UCD", "major": "Finance"}]
        assert self._plan_edu(existing, new)["additions"]["education"] == new

    def test_plan_education_same_value_as_degree_and_certification_matches(self):
        """The same qualification text stored as a degree on one side and a certification on the other is one entry."""
        existing = [{"id": 1, "school": "Chartered Accountants Ireland", "degree": "ACA"}]
        new = [{"school": "Chartered Accountants Ireland", "certification": "aca"}]
        assert self._plan_edu(existing, new)["additions"]["education"] == []

    def test_plan_duplicates_within_given_lists_written_once(self):
        """CR43 review m3: identical entries in one work_history or education argument are added once."""
        wh = [{"companyName": "Acme", "title": "Accountant"}, {"companyName": " acme ", "title": "ACCOUNTANT"}]
        edu = [{"certification": "ACCA"}, {"certification": "ACCA"}]
        plan = server._plan_cv_update({}, {}, None, [], [], wh, edu, [], [], "", [])
        assert plan["additions"]["work_history"] == [wh[0]]
        assert plan["additions"]["education"] == [edu[0]]

    # --- Contract ---------------------------------------------------------------

    def test_attach_cv_logs_outcome_under_given_id(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        """A call that wrote something logs attached_to under the given match_check_id."""
        self._prep(mock_client, sample_parsed_resume)

        data = self._attach(mock_client, mock_metadata, upload_id=_seed_upload(), match_check_id="chk-9")

        assert data["committed"] is True
        match_stub.log.assert_called_once()
        assert match_stub.log.call_args.args == ("chk-9", "attached_to", self.CID)

    def test_attach_cv_logs_nothing_without_id(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        self._prep(mock_client, sample_parsed_resume)
        self._attach(mock_client, mock_metadata, upload_id=_seed_upload())
        match_stub.log.assert_not_called()

    def test_attach_cv_logs_nothing_when_nothing_written(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        """Review M3: a call that wrote nothing (record already holds it all, file attached) logs no outcome."""
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()
        self._attach(mock_client, mock_metadata, upload_id=upload_id)
        existing, wh, edu, linked = self._written_state(sample_parsed_resume)
        self._prep(mock_client, sample_parsed_resume, existing, wh, edu, linked)
        mock_client.update.reset_mock()

        data = self._attach(mock_client, mock_metadata, upload_id=upload_id, match_check_id="chk-9")

        mock_client.update.assert_not_called()  # the overwrite waits for confirm
        assert data["written"]["file"]["already_attached"] is True
        match_stub.log.assert_not_called()

    def test_attach_cv_created_upload_logs_outcome(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        """Review M3: the file-only path for the Candidate the upload created logs attached_to when the file goes on."""
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()
        server.upload_store.mark_created(upload_id, self.CID)

        data = self._attach(mock_client, mock_metadata, upload_id=upload_id, match_check_id="chk-9")

        assert data["written"]["file"] == {"file_id": 80, "name": "Jane_Doe_CV.pdf"}
        match_stub.log.assert_called_once()
        assert match_stub.log.call_args.args == ("chk-9", "attached_to", self.CID)

    def test_attach_cv_created_upload_already_attached_logs_nothing(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        """Review M3: the file-only path with the file already on the record writes nothing and logs nothing."""
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()
        server.upload_store.set_parsed(upload_id, "user-a", sample_parsed_resume)  # the create parsed it
        server.upload_store.mark_created(upload_id, self.CID)
        server.upload_store.mark_attached(upload_id, 80, self.CID)

        data = self._attach(mock_client, mock_metadata, upload_id=upload_id, match_check_id="chk-9")

        assert data["written"]["file"]["already_attached"] is True
        mock_client.attach_file.assert_not_called()
        match_stub.log.assert_not_called()

    def test_attach_cv_runs_no_check(self, mock_client, mock_metadata, sample_parsed_resume, match_stub):
        """attach_cv never runs the match check, with or without an id."""
        self._prep(mock_client, sample_parsed_resume)
        self._attach(mock_client, mock_metadata, upload_id=_seed_upload(), match_check_id="chk-9")
        match_stub.match.assert_not_called()

    def test_attach_without_confirm_writes_additions_only(self, mock_client, mock_metadata, sample_parsed_resume):
        """No confirm: the update payload has only the empty-field additions, never the overwrite field."""
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        data = self._attach(mock_client, mock_metadata, upload_id=upload_id)

        assert data["committed"] is True
        assert mock_client.update.call_args_list == [
            call("Candidate", self.CID, {"phone": "555-0001", "description": self.DESC}),
            call("Candidate", self.CID, {"skillSet": "EXCEL, ANNUAL BUDGET, IFRS"}),
        ]
        assert data["written"]["fields"] == ["phone", "description"]
        assert data["written"]["skill_set"] == ["ANNUAL BUDGET", "IFRS"]
        assert data["written"]["primary_skills"] == [1000125, 1000200]
        assert [w["title"] for w in data["written"]["work_history"]] == [
            "Financial Accountant Sample Gadgets Ireland", "Assistant Accountant",
        ]
        assert len(data["written"]["education"]) == 2
        assert data["written"]["file"] == {"file_id": 80, "name": "Jane_Doe_CV.pdf"}
        mock_client.add_association.assert_called_once_with("Candidate", self.CID, "primarySkills", [1000125, 1000200])
        mock_client.attach_file.assert_called_once_with(
            "Candidate", self.CID, _CV_BYTES, "Jane_Doe_CV.pdf", "application/pdf", file_type="CV"
        )
        assert "overwritten" not in data

    def test_attach_without_confirm_returns_pending_overwrites(self, mock_client, mock_metadata, sample_parsed_resume):
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        data = self._attach(mock_client, mock_metadata, upload_id=upload_id)

        assert data["pending_overwrites"] == [
            {"field": "occupation", "current": "Junior Developer", "proposed": "Financial Accountant"}
        ]
        assert "confirm=True" in data["hint"]

    def test_attach_fields_to_update_resolves_labels(self, mock_client, mock_metadata, sample_parsed_resume):
        """CR43 review m2: fields_to_update labels resolve like fields_override ("Job Title" -> occupation)."""
        mock_metadata.resolve_fields.side_effect = lambda entity, fields: {
            ("occupation" if k == "Job Title" else k): v for k, v in fields.items()
        }
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        data = self._attach(mock_client, mock_metadata, upload_id=upload_id, fields_to_update=["Job Title"])

        assert [c["field"] for c in data["pending_overwrites"]] == ["occupation"]
        assert "warnings" not in data

    def test_attach_fields_to_update_warning_names_field_as_sent(self, mock_client, mock_metadata, sample_parsed_resume):
        """CR43 review cycle 2 m2: an unknown label is reported as the caller typed it, not its API name."""
        mock_metadata.resolve_fields.side_effect = lambda entity, fields: {
            ("customText9" if k == "Notice Period" else k): v for k, v in fields.items()
        }
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        data = self._attach(mock_client, mock_metadata, upload_id=upload_id, fields_to_update=["Notice Period"])

        assert data["warnings"] == ["fields_to_update not in the parse or fields_override, ignored: ['Notice Period']"]

    def test_attach_truncated_addition_not_offered_as_overwrite(self, mock_client, mock_metadata, sample_parsed_resume):
        """CR43 review m4: a field written clipped by the additions call is equal on the confirm call."""
        mock_metadata.get_fields.return_value = [{"name": "phone", "maxLength": 4}]
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()
        first = self._attach(mock_client, mock_metadata, upload_id=upload_id)
        assert call("Candidate", self.CID, {"phone": "555-", "description": self.DESC}) in mock_client.update.call_args_list

        existing, wh, edu, linked = self._written_state(sample_parsed_resume)
        existing["phone"] = "555-"
        self._prep(mock_client, sample_parsed_resume, existing, wh, edu, linked)
        second = self._attach(mock_client, mock_metadata, upload_id=upload_id)

        assert [c["field"] for c in first["pending_overwrites"]] == ["occupation"]
        assert [c["field"] for c in second["pending_overwrites"]] == ["occupation"]

    def test_attach_pending_description_overwrite_shows_lengths(self, mock_client, mock_metadata, sample_parsed_resume):
        self._prep(mock_client, sample_parsed_resume, existing=self._existing(phone="555-0001", description="<p>Old</p>"))
        upload_id = _seed_upload()

        data = self._attach(mock_client, mock_metadata, upload_id=upload_id)

        change = next(c for c in data["pending_overwrites"] if c["field"] == "description")
        assert change == {"field": "description", "current_length": 10, "proposed_length": len(self.DESC)}
        assert call("Candidate", self.CID, {"description": self.DESC}) not in mock_client.update.call_args_list

    def _written_state(self, parsed):
        """Records the first attach call wrote, as the second call would read them back."""
        wh = [{"id": 1 + i, **e} for i, e in enumerate(parsed["candidateWorkHistory"])]
        edu = [{"id": 10 + i, **e} for i, e in enumerate(parsed["candidateEducation"])]
        existing = self._existing(phone="555-0001", description=self.DESC, skillSet="EXCEL, ANNUAL BUDGET, IFRS")
        linked = [{"id": 1000125}, {"id": 1000200}]
        return existing, wh, edu, linked

    def test_attach_confirm_writes_exactly_previewed_overwrites(self, mock_client, mock_metadata, sample_parsed_resume):
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()
        first = self._attach(mock_client, mock_metadata, upload_id=upload_id)
        previewed = [c["field"] for c in first["pending_overwrites"]]

        existing, wh, edu, linked = self._written_state(sample_parsed_resume)
        self._prep(mock_client, sample_parsed_resume, existing, wh, edu, linked)
        mock_client.update.reset_mock()
        second = self._attach(mock_client, mock_metadata, upload_id=upload_id, confirm=True)

        assert previewed == ["occupation"]
        mock_client.update.assert_called_once_with("Candidate", self.CID, {"occupation": "Financial Accountant"})
        assert second["overwritten"] == ["occupation"]
        assert "pending_overwrites" not in second

    def test_attach_confirm_after_additions_adds_nothing_twice(self, mock_client, mock_metadata, sample_parsed_resume):
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()
        self._attach(mock_client, mock_metadata, upload_id=upload_id)

        existing, wh, edu, linked = self._written_state(sample_parsed_resume)
        self._prep(mock_client, sample_parsed_resume, existing, wh, edu, linked)
        mock_client.attach_file.reset_mock()
        mock_client.create.reset_mock()
        mock_client.add_association.reset_mock()
        mock_client.update.reset_mock()
        second = self._attach(mock_client, mock_metadata, upload_id=upload_id, confirm=True)

        mock_client.create.assert_not_called()
        mock_client.add_association.assert_not_called()
        mock_client.attach_file.assert_not_called()
        assert second["written"]["work_history"] == []
        assert second["written"]["education"] == []
        assert second["written"]["skill_set"] == []
        assert second["written"]["primary_skills"] == []
        assert second["written"]["file"]["already_attached"] is True
        assert second["already_present"]["work_history"] == 2
        assert second["already_present"]["education"] == 2
        assert second["already_present"]["primary_skills"] == [1000125, 1000200]
        # only the overwrite was written; skillSet is not re-sent
        mock_client.update.assert_called_once_with("Candidate", self.CID, {"occupation": "Financial Accountant"})

    def test_attach_confirm_on_attached_upload_same_candidate_allowed(self, mock_client, mock_metadata, sample_parsed_resume):
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()
        self._attach(mock_client, mock_metadata, upload_id=upload_id)
        rec = server.upload_store.get(upload_id, "user-a")
        assert rec["status"] == "attached"
        assert rec["data"] is None
        assert rec["attached_candidate_id"] == self.CID

        second = self._attach(mock_client, mock_metadata, upload_id=upload_id, confirm=True)

        assert second["committed"] is True
        assert "error" not in second
        assert mock_client.parse_resume_file.call_count == 1  # tombstone parse reused
        server.upload_store.claim(upload_id, "user-a")  # claim released afterwards

    def test_attach_attached_upload_other_candidate_refused(self, mock_client, mock_metadata, sample_parsed_resume):
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()
        self._attach(mock_client, mock_metadata, upload_id=upload_id)
        mock_client.update.reset_mock()
        mock_client.create.reset_mock()
        mock_client.attach_file.reset_mock()

        data = self._attach(mock_client, mock_metadata, upload_id=upload_id, candidate_id=999, confirm=True)

        assert data["error"] == "upload_already_attached"
        mock_client.update.assert_not_called()
        mock_client.create.assert_not_called()
        mock_client.attach_file.assert_not_called()

    def test_attach_uses_stored_parse(self, mock_client, mock_metadata, sample_parsed_resume):
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()
        with _http_as(), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            mock_client.search.return_value = []
            server.parse_cv(upload_id=upload_id)
        data = self._attach(mock_client, mock_metadata, upload_id=upload_id)

        assert data["committed"] is True
        mock_client.parse_resume_file.assert_called_once_with(_CV_BYTES, "Jane_Doe_CV.pdf", "pdf")

    def test_attach_corrected_lists_replace_parse(self, mock_client, mock_metadata, sample_parsed_resume):
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()
        wh = [{"companyName": "Sample Gadgets Ireland", "title": "Financial Accountant", "startDate": 1514764800000}]
        edu = [{"school": "UCD", "degree": "BComm"}]

        data = self._attach(
            mock_client, mock_metadata, upload_id=upload_id,
            work_history=wh, education=edu, skills=["SAP"], primary_skills=[1000999],
        )

        assert data["committed"] is True
        assert mock_client.create.call_args_list == [
            call("CandidateWorkHistory", {**wh[0], "candidate": {"id": self.CID}}),
            call("CandidateEducation", {**edu[0], "candidate": {"id": self.CID}}),
        ]
        assert call("Candidate", self.CID, {"skillSet": "EXCEL, SAP"}) in mock_client.update.call_args_list
        mock_client.add_association.assert_called_once_with("Candidate", self.CID, "primarySkills", [1000999])

    def test_attach_empty_list_adds_none(self, mock_client, mock_metadata, sample_parsed_resume):
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        data = self._attach(
            mock_client, mock_metadata, upload_id=upload_id,
            work_history=[], education=[], skills=[], primary_skills=[],
        )

        assert data["committed"] is True
        mock_client.create.assert_not_called()
        mock_client.add_association.assert_not_called()
        assert mock_client.update.call_args_list == [
            call("Candidate", self.CID, {"phone": "555-0001", "description": self.DESC}),
        ]

    def test_attach_file_failure_is_warning_with_retry(self, mock_client, mock_metadata, sample_parsed_resume):
        self._prep(mock_client, sample_parsed_resume)
        mock_client.attach_file.side_effect = BullhornAPIError("file endpoint down")
        upload_id = _seed_upload()

        result = self._attach(mock_client, mock_metadata, upload_id=upload_id)

        assert result["committed"] is True
        assert result["written"]["file"] is None
        assert any("attach_cv" in w and "Retry" in w and "file endpoint down" in w for w in result["warnings"])
        rec = server.upload_store.get(upload_id, "user-a")
        assert rec["status"] == "received"
        assert rec["data"] == _CV_BYTES

    def test_attach_unexpected_exception_returns_partial(self, mock_client, mock_metadata, sample_parsed_resume):
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        with patch.object(server, "_write_candidate_children", side_effect=RuntimeError("boom")):
            data = self._attach(mock_client, mock_metadata, upload_id=upload_id)

        assert data["committed"] is True
        assert data["partial"] is True
        assert "boom" in data["error"]
        assert data["written"]["fields"] == ["phone", "description"]
        mock_client.update.assert_called_once_with("Candidate", self.CID, {"phone": "555-0001", "description": self.DESC})
        server.upload_store.claim(upload_id, "user-a")  # released

    def test_attach_removed_params_absent_from_schema(self):
        import asyncio
        tool = {t.name: t for t in asyncio.run(server.mcp.list_tools())}["attach_cv"]
        props = tool.parameters["properties"]
        for removed in ("include_work_history", "include_education", "include_skills", "force_all"):
            assert removed not in props
        for present in ("fields_to_update", "fields_override", "work_history", "education",
                        "skills", "primary_skills", "confirm"):
            assert present in props

    # --- Kept from the earlier flow, adapted -------------------------------------

    def test_attach_cv_commit_applies_selected_fields(self, mock_client, mock_metadata, sample_parsed_resume):
        """fields_to_update limits the fields considered, with confirm=True writing the overwrite."""
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        data = self._attach(mock_client, mock_metadata, upload_id=upload_id,
                            fields_to_update=["occupation"], confirm=True)

        assert data["committed"] is True
        assert data["overwritten"] == ["occupation"]
        assert data["written"]["fields"] == ["occupation"]
        assert mock_client.update.call_args_list[0] == call("Candidate", self.CID, {"occupation": "Financial Accountant"})

    def test_attach_cv_fields_to_update_unknown_warns(self, mock_client, mock_metadata, sample_parsed_resume):
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        data = self._attach(mock_client, mock_metadata, upload_id=upload_id, fields_to_update=["nope"])

        assert any("fields_to_update not in the parse" in w and "nope" in w for w in data["warnings"])
        assert "pending_overwrites" not in data

    def test_attach_cv_get_fetches_description(self, mock_client, mock_metadata, sample_parsed_resume):
        """The existing record is fetched with description so a filled one is never seen as empty (CR42 M1)."""
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload()

        self._attach(mock_client, mock_metadata, upload_id=upload_id)

        assert "description" in mock_client.get.call_args.kwargs["fields"].split(",")

    def test_attach_cv_refuses_other_candidate_than_ticket(self, mock_client, mock_metadata):
        """An upload started for Candidate 111 cannot be attached to Candidate 222."""
        upload_id = _seed_upload(candidate_id=111)

        data = self._attach(mock_client, mock_metadata, candidate_id=222, upload_id=upload_id, confirm=True)

        assert data["error"] == "upload_candidate_mismatch"
        assert "attach_cv(candidate_id=111" in data["hint"]
        mock_client.parse_resume_file.assert_not_called()
        mock_client.attach_file.assert_not_called()
        server.upload_store.claim(upload_id, "user-a")  # released

    def test_attach_cv_matching_ticket_candidate_proceeds(self, mock_client, mock_metadata, sample_parsed_resume):
        self._prep(mock_client, sample_parsed_resume)
        upload_id = _seed_upload(candidate_id=self.CID)

        data = self._attach(mock_client, mock_metadata, upload_id=upload_id)

        assert data["committed"] is True

    def test_attach_cv_refused_while_upload_in_use(self, mock_client, mock_metadata):
        """Every call claims now, so a call overlapping another on the same upload gets upload_in_use."""
        upload_id = _seed_upload()
        server.upload_store.claim(upload_id, "user-a")

        data = self._attach(mock_client, mock_metadata, upload_id=upload_id)

        assert data["error"] == "upload_in_use"
        mock_client.parse_resume_file.assert_not_called()

    def test_attach_cv_other_users_call_leaves_owners_claim(self, mock_client, mock_metadata):
        from bullhorn_mcp.uploads import UploadInUse
        upload_id = _seed_upload(sub="user-a")
        server.upload_store.claim(upload_id, "user-a")

        data = self._attach(mock_client, mock_metadata, sub="user-b", upload_id=upload_id, confirm=True)

        assert data["error"] == "upload_not_found"
        with pytest.raises(UploadInUse):
            server.upload_store.claim(upload_id, "user-a")

    def test_attach_cv_releases_claim_on_error(self, mock_client, mock_metadata):
        mock_client.parse_resume_file.side_effect = BullhornAPIError("Parse failed")
        upload_id = _seed_upload()

        with _http_as(), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.attach_cv(candidate_id=self.CID, upload_id=upload_id)

        assert result.startswith("ERROR:")
        server.upload_store.claim(upload_id, "user-a")  # does not raise

    def test_attach_cv_api_error(self, mock_client, mock_metadata):
        mock_client.parse_resume_file.side_effect = BullhornAPIError("Parse failed")
        upload_id = _seed_upload()

        with _http_as(), \
             patch.object(server, "get_client", return_value=mock_client), \
             patch.object(server, "get_metadata", return_value=mock_metadata):
            result = server.attach_cv(candidate_id=123, upload_id=upload_id)

        assert result.startswith("ERROR:")
        mock_client.update.assert_not_called()

    def test_attach_cv_recomputes_name_both_components(self, mock_client, mock_metadata, sample_parsed_resume):
        """Both name parts written: name is injected as 'Jane Doe', no extra client.get."""
        self._prep(mock_client, sample_parsed_resume, existing=self._existing(firstName="John", lastName="Smith"))
        upload_id = _seed_upload()

        data = self._attach(mock_client, mock_metadata, upload_id=upload_id,
                            fields_to_update=["firstName", "lastName"], confirm=True)

        assert data["committed"] is True
        assert mock_client.update.call_args_list[0] == call(
            "Candidate", self.CID, {"firstName": "Jane", "lastName": "Doe", "name": "Jane Doe"}
        )
        assert mock_client.get.call_count == 1

    def test_attach_cv_recomputes_name_single_component(self, mock_client, mock_metadata, sample_parsed_resume):
        """Only firstName changes: the lastName already fetched is combined, so name is 'Jane Smith'."""
        self._prep(mock_client, sample_parsed_resume, existing=self._existing(firstName="John", lastName="Smith"))
        upload_id = _seed_upload()

        data = self._attach(mock_client, mock_metadata, upload_id=upload_id,
                            fields_to_update=["firstName"], confirm=True)

        assert data["committed"] is True
        assert mock_client.update.call_args_list[0] == call(
            "Candidate", self.CID, {"firstName": "Jane", "name": "Jane Smith"}
        )
        assert mock_client.get.call_count == 1

    def test_attach_cv_upload_not_found(self, mock_client, mock_metadata):
        data = self._attach(mock_client, mock_metadata, candidate_id=123, upload_id="upl_doesnotexist")

        assert data["error"] == "upload_not_found"
        mock_client.parse_resume_file.assert_not_called()
        mock_client.attach_file.assert_not_called()

    def test_attach_cv_drops_bytes_and_keeps_parse(self, mock_client, mock_metadata, sample_parsed_resume):
        """The attach drops the bytes (NFR-9) and keeps the parse on the tombstone for a confirm call."""
        self._prep(mock_client, sample_parsed_resume)
        mock_client.attach_file.return_value = {"fileId": 82, "name": "Jane_Doe_CV.pdf"}
        upload_id = _seed_upload()

        data = self._attach(mock_client, mock_metadata, upload_id=upload_id)

        assert data["written"]["file"] == {"file_id": 82, "name": "Jane_Doe_CV.pdf"}
        rec = server.upload_store.get(upload_id, "user-a")
        assert rec["status"] == "attached"
        assert rec["data"] is None
        assert rec["file_id"] == 82
        assert rec["parsed"] == sample_parsed_resume


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

    def test_client_corporation_uses_client_contact_notes(self, mock_client):
        """CR40/T39.3: ClientCorporation reads clientContactNotes, not notes,
        because "notes" is a scalar field on ClientCorporation (500s otherwise)."""
        mock_client.get_association_with_meta.side_effect = None
        company_note = {
            "id": 2653713,
            "action": "General Note",
            "comments": "test",
            "dateAdded": 1758000000000,
            "isDeleted": False,
            "commentingPerson": {"id": 142235},
            "personReference": {"id": 145635, "firstName": "Duke", "lastName": "Nukem"},
        }
        mock_client.get_association_with_meta.return_value = {
            "data": [company_note],
            "start": 0,
            "count": 1,
        }

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.get_notes_for_entity("ClientCorporation", 10666, limit=1)

        call_args = mock_client.get_association_with_meta.call_args
        assert call_args.args[0] == "ClientCorporation"
        assert call_args.args[1] == 10666
        assert call_args.args[2] == "clientContactNotes"

        data = json.loads(result)
        assert data["data"][0]["id"] == 2653713
        # No "total" in the response, as on the live tenant, and a full page:
        # has_more falls back to the raw_page_count == limit heuristic.
        assert data["pagination"]["has_more"] is True
        assert data["pagination"]["next_start"] == 1

    def test_other_entities_still_use_notes(self, mock_client, sample_note_records):
        """CR40/T39.3: non-ClientCorporation entities keep using the notes association."""
        mock_client.get_association_with_meta.side_effect = None
        mock_client.get_association_with_meta.return_value = {
            "data": [sample_note_records[0]],
            "start": 0,
            "count": 1,
        }

        with patch.object(server, "get_client", return_value=mock_client):
            server.get_notes_for_entity("JobOrder", 51437)

        call_args = mock_client.get_association_with_meta.call_args
        assert call_args.args[2] == "notes"


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

    def test_entity_filter_client_corporation_uses_client_contact_notes(self, mock_client):
        """CR40/T39.3: entity_filter on ClientCorporation reads clientContactNotes,
        so it no longer 500s ("Unknown entity: String" on the scalar notes field)."""
        company_note = {
            "id": 2653713,
            "action": "General Note",
            "comments": "duke nukem test",
            "isDeleted": False,
        }
        mock_client.get_association.return_value = [company_note]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_notes(
                "duke", entity_filter={"type": "ClientCorporation", "id": 10666}
            )

        call_args = mock_client.get_association.call_args
        assert call_args.args[0] == "ClientCorporation"
        assert call_args.args[1] == 10666
        assert call_args.args[2] == "clientContactNotes"
        data = json.loads(result)
        assert data["data"][0]["id"] == 2653713

    def test_note_search_fields_are_note_default_fields(self):
        """_NOTE_SEARCH_DEFAULT_FIELDS is an alias for _NOTE_DEFAULT_FIELDS, not a copy."""
        assert server._NOTE_SEARCH_DEFAULT_FIELDS is server._NOTE_DEFAULT_FIELDS


class TestSearchNotesEmptyIndexWarning:
    """CR37 Change 2: distinguish "no matches" from "this route returns nothing"."""

    def test_search_notes_warns_when_index_empty(self, mock_client):
        """A zero-result Lucene search plus a zero-result probe must warn."""
        mock_client.search.return_value = []
        mock_client.note_search_returns_results.return_value = False

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_notes("Auto-added by Application Triage")

        data = json.loads(result)
        assert data["data"] == []
        assert data["pagination"]["total"] == 0
        assert "warnings" in data
        assert len(data["warnings"]) == 1
        mock_client.note_search_returns_results.assert_called_once()

    def test_search_notes_does_not_warn_when_probe_finds_documents(self, mock_client):
        """A usable route means an empty result is a genuine "no matches" — no warning."""
        mock_client.search.return_value = []
        mock_client.note_search_returns_results.return_value = True

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_notes("asdfghjkl")

        data = json.loads(result)
        assert data["data"] == []
        assert "warnings" not in data

    def test_search_notes_does_not_warn_when_probe_verdict_unknown(self, mock_client):
        """A failed probe is not evidence; do not assert anything about the route."""
        mock_client.search.return_value = []
        mock_client.note_search_returns_results.return_value = None

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_notes("asdfghjkl")

        assert "warnings" not in json.loads(result)

    def test_search_notes_does_not_probe_when_results_returned(self, mock_client, sample_note_records):
        """The probe costs an API call; only spend it on an ambiguous empty result."""
        mock_client.search.return_value = [sample_note_records[0]]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_notes("strong fit")

        mock_client.note_search_returns_results.assert_not_called()
        assert "warnings" not in json.loads(result)

    def test_entity_filter_path_never_warns(self, mock_client):
        """The association route is reliable, so an empty result there is a real answer."""
        mock_client.get_association.return_value = []
        mock_client.note_search_returns_results.return_value = False

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_notes(
                "nothing", entity_filter={"type": "Candidate", "id": 169020}
            )

        assert "warnings" not in json.loads(result)
        mock_client.note_search_returns_results.assert_not_called()

    def test_warning_names_nested_pattern_and_note_action(self, mock_client):
        """The warning is only useful if it routes the agent somewhere that works."""
        mock_client.search.return_value = []
        mock_client.note_search_returns_results.return_value = False

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_notes("anything")

        warning = json.loads(result)["warnings"][0]
        assert 'notes.action:"BD Call"' in warning
        assert "note_action" in warning
        assert "get_notes_for_entity" in warning
        assert "entity_filter" in warning

    @pytest.mark.parametrize("banned", ["broken", "misconfigured", "outage", "not enabled"])
    def test_warning_states_behaviour_without_diagnosing_bullhorn(self, banned):
        """CR37 wording constraint: state observed behaviour, attribute no fault."""
        text = server._NOTE_INDEX_EMPTY_WARNING.lower()
        assert banned not in text
        assert "contact bullhorn" not in text


class TestSearchEntitiesNoteEmptyIndexWarning:
    """search_entities(entity="Note") reaches the same route, so it must warn too."""

    def test_warns_on_empty_note_search(self, mock_client):
        """Otherwise the sibling path still renders an unusable route as an answer."""
        mock_client.search.return_value = []
        mock_client.note_search_returns_results.return_value = False

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_entities(entity="Note", query="comments:visa")

        data = json.loads(result)
        assert data["data"] == []
        assert data["pagination"]["total"] == 0
        assert data["warnings"] == [server._NOTE_INDEX_EMPTY_WARNING]
        mock_client.note_search_returns_results.assert_called_once()

    @pytest.mark.parametrize("entity", ["note", "  Note  "])
    def test_entity_name_match_is_case_and_space_insensitive(self, mock_client, entity):
        """The agent supplies this string free-form; casing must not lose the warning."""
        mock_client.search.return_value = []
        mock_client.note_search_returns_results.return_value = False

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_entities(entity=entity, query="comments:visa")

        assert "warnings" in json.loads(result)

    def test_does_not_warn_when_probe_finds_documents(self, mock_client):
        """A usable route means the empty result is a genuine "no matches"."""
        mock_client.search.return_value = []
        mock_client.note_search_returns_results.return_value = True

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_entities(entity="Note", query="comments:asdfghjkl")

        assert "warnings" not in json.loads(result)

    def test_does_not_warn_when_probe_verdict_unknown(self, mock_client):
        """A failed probe is not evidence; assert nothing about the route."""
        mock_client.search.return_value = []
        mock_client.note_search_returns_results.return_value = None

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_entities(entity="Note", query="comments:asdfghjkl")

        assert "warnings" not in json.loads(result)

    def test_other_entities_never_probe(self, mock_client):
        """An empty Candidate search is a real answer; do not spend a probe call."""
        mock_client.search.return_value = []

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_entities(entity="Candidate", query="status:Nonexistent")

        mock_client.note_search_returns_results.assert_not_called()
        assert "warnings" not in json.loads(result)

    def test_does_not_probe_when_note_results_returned(self, mock_client):
        """Only an empty result is ambiguous."""
        mock_client.search.return_value = [{"id": 1}]

        with patch.object(server, "get_client", return_value=mock_client):
            result = server.search_entities(entity="Note", query="comments:visa")

        mock_client.note_search_returns_results.assert_not_called()
        assert "warnings" not in json.loads(result)


class TestNoAdvancedNoteSearchingReferences:
    """CR37 Part 6 item B: the ATS UI note-search option has no bearing on REST."""

    def test_no_tool_docstring_mentions_the_ui_option(self):
        """It was the text the agent read, and it misdirected every note search."""
        offenders = []
        for name in dir(server):
            obj = getattr(server, name)
            doc = getattr(obj, "__doc__", None)
            if callable(obj) and doc and "advanced note searching" in doc.lower():
                offenders.append(name)
        assert offenders == []

    def test_server_module_source_is_clean(self):
        """Covers constants and comments, not just docstrings."""
        import inspect
        source = inspect.getsource(server).lower()
        assert "advanced note searching" not in source
        assert "contact bullhorn support" not in source


@pytest.mark.usefixtures("clean_upload_store")
class TestUploadRoute:
    """Tests for the POST /upload/{token} HTTP route (CR41)."""

    MCP_APP_ORIGIN = "https://abc123.claudemcpcontent.com"

    def test_access_log_filter_redacts_upload_token(self):
        """uvicorn's access line for /upload/<token> is logged with the token blanked."""
        import logging
        record = logging.LogRecord(
            "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
            ("1.2.3.4:5", "POST", "/upload/SECRETTOKEN", "1.1", 410), None,
        )
        assert server._RedactUploadTokenFilter().filter(record) is True
        assert "SECRETTOKEN" not in record.getMessage()
        assert "/upload/<redacted>" in record.getMessage()

    def test_access_log_filter_leaves_other_paths(self):
        """Lines for other paths are unchanged."""
        import logging
        args = ("1.2.3.4:5", "POST", "/mcp", "1.1", 200)
        record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "%s %s %s %s %d", args, None)
        server._RedactUploadTokenFilter().filter(record)
        assert record.args == args

    @pytest.fixture
    def http(self):
        from starlette.testclient import TestClient
        return TestClient(server.mcp.http_app())

    @staticmethod
    def _ticket(filename="Jane_Doe_CV.pdf", sub="user-a"):
        upload_id, token, _ = server.upload_store.create(sub, filename)
        return upload_id, token

    def test_upload_happy_path(self, http):
        """A valid POST returns 200 with the ticket's original filename and stores the bytes."""
        upload_id, token = self._ticket()

        resp = http.post(f"/upload/{token}", files={"file": ("8655a252-Jane_Doe_CV.pdf", _CV_BYTES)})

        assert resp.status_code == 200
        assert resp.json() == {"upload_id": upload_id, "filename": "Jane_Doe_CV.pdf", "size": len(_CV_BYTES)}
        rec = server.upload_store.get(upload_id, "user-a")
        assert rec["status"] == "received"
        assert rec["data"] == _CV_BYTES

    def test_unknown_token_404(self, http):
        """A token that was never issued answers 404."""
        resp = http.post("/upload/not-a-real-token", files={"file": ("cv.pdf", _CV_BYTES)})

        assert resp.status_code == 404
        assert resp.json()["error"] == "upload_not_found"

    def test_reused_token_410(self, http):
        """A second POST with the same token answers 410 upload_already_used."""
        _upload_id, token = self._ticket()
        first = http.post(f"/upload/{token}", files={"file": ("cv.pdf", _CV_BYTES)})
        second = http.post(f"/upload/{token}", files={"file": ("cv.pdf", b"other bytes")})

        assert first.status_code == 200
        assert second.status_code == 410
        assert second.json()["error"] == "upload_already_used"

    def test_expired_token_410(self, http):
        """A token used after its 15 minute window answers 410 upload_expired."""
        from bullhorn_mcp.uploads import UploadStore
        clock = _FakeClock()
        with patch.object(server, "upload_store", UploadStore(clock=clock)):
            _upload_id, token = self._ticket()
            clock.now += 16 * 60
            resp = http.post(f"/upload/{token}", files={"file": ("cv.pdf", _CV_BYTES)})

        assert resp.status_code == 410
        assert resp.json()["error"] == "upload_expired"

    def test_oversize_413(self, http):
        """Too large a body, or too large a file within the body allowance, both answer 413."""
        _upload_id, token = self._ticket()
        # Whole body over the route's cap: refused before parsing.
        with patch.object(server, "_UPLOAD_BODY_LIMIT", 1000):
            big_body = http.post(f"/upload/{token}", files={"file": ("cv.pdf", b"x" * 5000)})
        # File over the store's cap but body within the route's allowance.
        with patch("bullhorn_mcp.uploads.MAX_UPLOAD_BYTES", 100):
            big_file = http.post(f"/upload/{token}", files={"file": ("cv.pdf", b"x" * 200)})

        assert big_body.status_code == 413
        assert big_body.json()["error"] == "file_too_large"
        assert big_file.status_code == 413
        assert big_file.json()["error"] == "file_too_large"

    def test_bad_type_415(self, http):
        """A file whose extension differs from the ticket's answers 415."""
        _upload_id, token = self._ticket("Jane_Doe_CV.pdf")

        resp = http.post(f"/upload/{token}", files={"file": ("malware.exe", _CV_BYTES)})

        assert resp.status_code == 415
        assert resp.json()["error"] == "unsupported_file_type"

    def test_missing_file_field_400(self, http):
        """Multipart without a 'file' field, or a non-multipart body, answers 400 missing_file."""
        _upload_id, token = self._ticket()

        wrong_field = http.post(f"/upload/{token}", files={"other": ("cv.pdf", _CV_BYTES)})
        not_multipart = http.post(f"/upload/{token}", content=_CV_BYTES)

        assert wrong_field.status_code == 400
        assert wrong_field.json()["error"] == "missing_file"
        assert not_multipart.status_code == 400
        assert not_multipart.json()["error"] == "missing_file"

    def test_cors_preflight_allows_mcp_app_origin(self, http):
        """OPTIONS from the MCP App sandbox origin gets 204 and the origin echoed; POST carries it too."""
        _upload_id, token = self._ticket()

        pre = http.options(f"/upload/{token}", headers={
            "Origin": self.MCP_APP_ORIGIN,
            "Access-Control-Request-Method": "POST",
        })
        post = http.post(
            f"/upload/{token}",
            files={"file": ("cv.pdf", _CV_BYTES)},
            headers={"Origin": self.MCP_APP_ORIGIN},
        )

        assert pre.status_code == 204
        assert pre.headers["access-control-allow-origin"] == self.MCP_APP_ORIGIN
        assert "POST" in pre.headers["access-control-allow-methods"]
        assert post.status_code == 200
        assert post.headers["access-control-allow-origin"] == self.MCP_APP_ORIGIN

    def test_cors_rejects_other_origin(self, http):
        """Other origins, plain http, and look-alike domains are refused with no ACAO header."""
        _upload_id, token = self._ticket()
        bad_origins = [
            "https://evil.example.com",
            "http://x.claudemcpcontent.com",
            "https://claudemcpcontent.com.evil.com",
        ]

        for origin in bad_origins:
            resp = http.options(f"/upload/{token}", headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            })
            assert resp.status_code == 403, origin
            assert "access-control-allow-origin" not in resp.headers, origin

        # A real POST from a bad origin still works for curl-style callers but gets no CORS header.
        post = http.post(
            f"/upload/{token}",
            files={"file": ("cv.pdf", _CV_BYTES)},
            headers={"Origin": "https://evil.example.com"},
        )
        assert "access-control-allow-origin" not in post.headers

    def test_upload_makes_no_bullhorn_call(self, http):
        """The route only stores bytes; it never builds a Bullhorn client."""
        _upload_id, token = self._ticket()

        with patch.object(server, "get_client", side_effect=AssertionError("Bullhorn called")):
            resp = http.post(f"/upload/{token}", files={"file": ("cv.pdf", _CV_BYTES)})

        assert resp.status_code == 200

    def test_old_upload_cv_route_removed(self, http):
        """The CR27 /upload-cv route is gone."""
        resp = http.post("/upload-cv", files={"file": ("cv.pdf", _CV_BYTES)})

        assert resp.status_code in (404, 405)
        assert not hasattr(server, "_upload_cv_handler")

    def test_upload_rejected_file_does_not_consume_ticket(self, http):
        """A wrong-type or empty file is rejected, and the same token then accepts the right file."""
        upload_id, token = self._ticket("Jane_Doe_CV.pdf")

        wrong = http.post(f"/upload/{token}", files={"file": ("cv.exe", _CV_BYTES)})
        empty = http.post(f"/upload/{token}", files={"file": ("cv.pdf", b"")})
        good = http.post(f"/upload/{token}", files={"file": ("cv.pdf", _CV_BYTES)})

        assert wrong.status_code == 415
        assert empty.status_code == 400
        assert good.status_code == 200
        assert server.upload_store.get(upload_id, "user-a")["status"] == "received"

    def test_token_not_logged(self, http, caplog):
        """The upload token never appears in a log record, for accepted or rejected uploads."""
        import logging
        _upload_id, token = self._ticket()

        with caplog.at_level(logging.INFO, logger="bullhorn_mcp.server"):
            rejected = http.post(f"/upload/{token}", files={"file": ("cv.exe", _CV_BYTES)})
            accepted = http.post(f"/upload/{token}", files={"file": ("cv.pdf", _CV_BYTES)})
            http.post(f"/upload/{token}", files={"file": ("cv.pdf", _CV_BYTES)})  # reused

        assert rejected.status_code == 415
        assert accepted.status_code == 200
        assert caplog.records, "expected the route to log something at INFO"
        for record in caplog.records:
            assert token not in record.getMessage()
            assert token not in str(record.args)


@pytest.mark.usefixtures("clean_upload_store")
class TestRequestCvUpload:
    """Tests for the request_cv_upload tool (CR41)."""

    BASE = {"MCP_BASE_URL": "https://mcp.example.com"}

    def _request(self, filename="Jane_Doe_CV.pdf", sub="user-a", ui=False, base=None, **kwargs):
        with _http_as(sub), \
             patch.dict(os.environ, base or self.BASE), \
             patch.object(server, "_client_supports_ui", return_value=ui):
            return json.loads(server.request_cv_upload(filename, **kwargs))

    def test_url_built_from_mcp_base_url(self):
        """upload_url is MCP_BASE_URL + /upload/<token> (trailing slash tolerated) and the token redeems."""
        data = self._request(base={"MCP_BASE_URL": "https://mcp.example.com/"})

        prefix = "https://mcp.example.com/upload/"
        assert data["upload_url"].startswith(prefix)
        token = data["upload_url"][len(prefix):]
        assert "/" not in token and token
        result = server.upload_store.redeem(token, "cv.pdf", _CV_BYTES)
        assert result["upload_id"] == data["upload_id"]

    def test_ticket_bound_to_token_sub(self):
        """The ticket belongs to the caller's Entra sub: user-a can read it, user-b cannot."""
        data = self._request(sub="user-a")

        assert server.upload_store.get(data["upload_id"], "user-a")["status"] == "pending"
        from bullhorn_mcp.uploads import UploadNotFound
        with pytest.raises(UploadNotFound):
            server.upload_store.get(data["upload_id"], "user-b")

    def test_next_steps_offer_upload_box_when_ui_supported(self):
        """With MCP Apps support the fallback step points at show_cv_upload_box."""
        data = self._request(ui=True)

        text = " ".join(data["next_steps"])
        assert f"show_cv_upload_box(upload_id='{data['upload_id']}')" in text

    def test_next_steps_omit_upload_box_when_ui_unsupported(self):
        """Without MCP Apps support there is no mention of the box, and the agent is told to stop."""
        data = self._request(ui=False)

        text = " ".join(data["next_steps"])
        assert "show_cv_upload_box" not in text
        assert "stop" in text.lower()

    def test_next_steps_curl_line_contains_url(self):
        """The first next step is a curl command that includes the exact upload_url."""
        data = self._request()

        curl_line = data["next_steps"][0]
        assert "curl" in curl_line
        assert data["upload_url"] in curl_line

    def test_disallowed_extension_rejected(self):
        """A non-CV extension returns unsupported_file_type and creates nothing."""
        data = self._request(filename="payload.exe")

        assert data["error"] == "unsupported_file_type"
        assert server.upload_store._uploads == {}

    def test_stdio_mode_returns_uploads_require_http_mode(self):
        """request_cv_upload, get_cv_upload and show_cv_upload_box all refuse in stdio mode."""
        with patch.object(server, "_transport_mode", "stdio"):
            results = [
                server.request_cv_upload("Jane_Doe_CV.pdf"),
                server.get_cv_upload("upl_x"),
                server.show_cv_upload_box("upl_x"),
            ]

        for result in results:
            assert json.loads(result)["error"] == "uploads_require_http_mode"
        assert server.upload_store._uploads == {}

    def test_missing_sub_returns_identity_error(self):
        """A token without a sub claim returns identity_resolution_failed and creates nothing."""
        token = Mock()
        token.claims = {"email": "user-a@example.com"}
        with patch.object(server, "_transport_mode", "http"), \
             patch("bullhorn_mcp.identity.get_access_token", return_value=token), \
             patch.dict(os.environ, self.BASE):
            data = json.loads(server.request_cv_upload("Jane_Doe_CV.pdf"))

        assert data["error"] == "identity_resolution_failed"
        assert server.upload_store._uploads == {}
    def test_request_cv_upload_next_steps_mention_review(self):
        """next_steps tell the agent to parse_cv, review and correct the parse, then create or attach."""
        data = self._request()
        upload_id = data["upload_id"]

        text = " ".join(data["next_steps"])
        parse_at = text.index(f"parse_cv(upload_id='{upload_id}')")
        review_at = text.index("review the parse against the CV itself")
        create_at = text.index(f"create_candidate_from_cv(upload_id='{upload_id}', <your corrections>)")
        attach_at = text.index(f"attach_cv(candidate_id=..., upload_id='{upload_id}', <your corrections>)")
        assert parse_at < review_at < create_at
        assert review_at < attach_at
        assert "companyName" in text


@pytest.mark.usefixtures("clean_upload_store")
class TestGetCvUpload:
    """Tests for the get_cv_upload tool (CR41)."""

    def _get(self, upload_id, sub="user-a"):
        with _http_as(sub):
            return json.loads(server.get_cv_upload(upload_id))

    def test_get_status_pending_then_received(self):
        """Status moves from pending (no size) to received (size set) once the file arrives."""
        upload_id, token, _ = server.upload_store.create("user-a", "Jane_Doe_CV.pdf", 42)

        pending = self._get(upload_id)
        server.upload_store.redeem(token, "cv.pdf", _CV_BYTES)
        received = self._get(upload_id)

        assert pending["status"] == "pending"
        assert pending["size"] is None
        assert pending["candidate_id"] == 42
        assert received["status"] == "received"
        assert received["size"] == len(_CV_BYTES)
        assert received["filename"] == "Jane_Doe_CV.pdf"
        assert "file_id" not in received

    def test_get_attached_includes_file_id(self):
        """An attached upload reports the Bullhorn file id."""
        upload_id = _seed_upload()
        server.upload_store.mark_attached(upload_id, 77)

        data = self._get(upload_id)

        assert data["status"] == "attached"
        assert data["file_id"] == 77

    def test_get_other_users_upload_not_found(self):
        """Another user's upload id answers upload_not_found."""
        upload_id = _seed_upload(sub="user-a")

        data = self._get(upload_id, sub="user-b")

        assert data["error"] == "upload_not_found"


@pytest.mark.usefixtures("clean_upload_store")
class TestShowCvUploadBox:
    """Tests for the show_cv_upload_box tool and its MCP App resource (CR41)."""

    BOX_URI = "ui://bullhorn/cv-upload-box.html"

    def _show(self, upload_id, sub="user-a"):
        with _http_as(sub), patch.dict(os.environ, {"MCP_BASE_URL": "https://mcp.example.com"}):
            return json.loads(server.show_cv_upload_box(upload_id))

    def test_upload_box_tool_registered_with_ui_meta(self):
        """show_cv_upload_box links to the ui:// resource through its tool meta."""
        import asyncio
        tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}

        assert tools["show_cv_upload_box"].meta == {"ui": {"resourceUri": self.BOX_URI}}

    def test_upload_box_csp_connect_domain_is_base_url(self):
        """The CSP connect domain is the base URL origin; with no base URL no CSP is declared."""
        from fastmcp.apps.config import app_config_to_meta_dict
        with_url = app_config_to_meta_dict(server._upload_box_app_config("https://mcp.thepanel.com"))
        without = app_config_to_meta_dict(server._upload_box_app_config(None))

        assert with_url["csp"]["connectDomains"] == ["https://mcp.thepanel.com"]
        assert "csp" not in without
        assert "domain" not in without

    def test_upload_box_ui_domain_hash(self):
        """The app domain is sha256 of the MCP endpoint URL, 32 hex chars, on claudemcpcontent.com."""
        from fastmcp.apps.config import app_config_to_meta_dict
        # Literal, precomputed for the production endpoint, so the test does not
        # rebuild the formula it checks.
        expected = "8b033b271394feeafd205db9b9cd21d9.claudemcpcontent.com"

        plain = app_config_to_meta_dict(server._upload_box_app_config("https://mcp.thepanel.com"))
        slashed = app_config_to_meta_dict(server._upload_box_app_config("https://mcp.thepanel.com/"))

        assert plain["domain"] == expected
        assert slashed["domain"] == expected

    def test_upload_box_resource_serves_html(self):
        """The ui:// resource is registered as MCP App HTML and its page has no base64 path."""
        import asyncio
        resources = {str(r.uri): r for r in asyncio.run(server.mcp.list_resources())}

        assert self.BOX_URI in resources
        assert resources[self.BOX_URI].mime_type == "text/html;profile=mcp-app"
        html = server.cv_upload_box_resource()
        assert "ui/initialize" in html
        assert "fetch(" in html
        # The page comments mention base64 to say it is absent; check the code only.
        import re
        code = re.sub(r"<!--.*?-->", "", html, flags=re.S)
        assert "base64" not in code.lower()
        assert "btoa" not in code

        result = asyncio.run(server.mcp.read_resource(self.BOX_URI))
        assert "ui/initialize" in result.contents[0].content

    def test_upload_box_returns_fresh_url_and_old_token_dies(self):
        """The box gets a new single-use URL for the same ticket; the original token stops working."""
        from bullhorn_mcp.uploads import UploadNotFound
        with _http_as(), \
             patch.dict(os.environ, {"MCP_BASE_URL": "https://mcp.example.com"}), \
             patch.object(server, "_client_supports_ui", return_value=True):
            first = json.loads(server.request_cv_upload("Jane_Doe_CV.pdf"))
        old_token = first["upload_url"].rsplit("/", 1)[1]

        shown = self._show(first["upload_id"])

        assert shown["upload_id"] == first["upload_id"]
        assert shown["filename"] == "Jane_Doe_CV.pdf"
        assert shown["allowed_extensions"] == ["pdf"]
        new_token = shown["upload_url"].rsplit("/", 1)[1]
        assert shown["upload_url"].startswith("https://mcp.example.com/upload/")
        assert new_token != old_token
        with pytest.raises(UploadNotFound):
            server.upload_store.redeem(old_token, "cv.pdf", _CV_BYTES)
        result = server.upload_store.redeem(new_token, "cv.pdf", _CV_BYTES)
        assert result["upload_id"] == first["upload_id"]

    def test_upload_box_other_users_upload_rejected(self):
        """User-b cannot open a box for user-a's upload."""
        upload_id, _token, _ = server.upload_store.create("user-a", "Jane_Doe_CV.pdf")

        data = self._show(upload_id, sub="user-b")

        assert data["error"] == "upload_not_found"

    def test_upload_box_on_received_upload_errors(self):
        """A box for an upload that already holds its file says to carry on, not to start over."""
        upload_id = _seed_upload()

        data = self._show(upload_id)

        assert data["error"] == "upload_already_received"
        assert "create_candidate_from_cv" in data["hint"]
        assert "request_cv_upload" not in data["hint"]
        assert server.upload_store.get(upload_id, "user-a")["status"] == "received"

    def test_upload_box_on_attached_upload_says_start_over(self):
        """A box for an attached upload is refused and points at request_cv_upload."""
        upload_id = _seed_upload()
        server.upload_store.mark_attached(upload_id, 1)

        data = self._show(upload_id)

        assert data["error"] == "upload_already_used"
        assert "request_cv_upload" in data["hint"]


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


# ---------------------------------------------------------------------------
# Sprint 38: CR38 people_search_perplexity (external, not Bullhorn)
# ---------------------------------------------------------------------------

class TestPeopleSearchPerplexity:
    """people_search_perplexity validates before any HTTP call and never leaks the key."""

    API_KEY = "pplx-test-secret-key"

    @pytest.fixture(autouse=True)
    def _key(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", self.API_KEY)

    def _route(self, respx_mock, status=200, body=None):
        import httpx
        from bullhorn_mcp.perplexity import PERPLEXITY_SEARCH_URL
        if body is None:
            body = {"results": []}
        return respx_mock.post(PERPLEXITY_SEARCH_URL).mock(
            return_value=httpx.Response(status, json=body)
        )

    def test_happy_path_formats_results(self, respx_mock):
        long_snippet = "x" * 500
        route = self._route(respx_mock, body={"results": [
            {"title": "Jane Smith - FC", "url": "https://linkedin.com/in/js",
             "snippet": long_snippet, "last_updated": "2026-09-11", "extra_key": "tolerated"},
            {"title": "Tom Byrne", "url": "https://linkedin.com/in/tb",
             "snippet": "short", "last_updated": "2026-08-01", "date": "2025-07-17"},
        ]})

        out = json.loads(server.people_search_perplexity(["financial controller Dublin"]))

        assert route.called
        assert out["queries"] == ["financial controller Dublin"]
        assert out["count"] == 2
        assert "not Bullhorn" in out["note"]
        first, second = out["results"]
        assert first["snippet"] == "x" * 300 + "..."
        assert "date" not in first
        assert "extra_key" not in first
        assert first["last_updated"] == "2026-09-11"
        assert second["snippet"] == "short"
        assert second["date"] == "2025-07-17"

    def test_five_queries_accepted(self, respx_mock):
        route = self._route(respx_mock)
        queries = ["a", "b", "c", "d", "e"]

        out = json.loads(server.people_search_perplexity(queries))

        assert out["count"] == 0
        assert json.loads(route.calls.last.request.content)["query"] == queries

    def test_empty_queries_returns_error_no_http(self, respx_mock):
        route = self._route(respx_mock)
        out = json.loads(server.people_search_perplexity([]))
        assert out["error"] == "queries_required"
        assert route.called is False

    def test_six_queries_returns_error_no_http(self, respx_mock):
        route = self._route(respx_mock)
        out = json.loads(server.people_search_perplexity(["a", "b", "c", "d", "e", "f"]))
        assert out["error"] == "too_many_queries"
        assert route.called is False

    def test_blank_entry_returns_error_no_http(self, respx_mock):
        route = self._route(respx_mock)
        out = json.loads(server.people_search_perplexity(["financial controller", "   "]))
        assert out["error"] == "blank_query"
        assert route.called is False

    def test_missing_key_returns_error_no_http(self, respx_mock, monkeypatch):
        monkeypatch.delenv("PERPLEXITY_API_KEY")
        route = self._route(respx_mock)
        out = json.loads(server.people_search_perplexity(["financial controller Dublin"]))
        assert out["error"] == "perplexity_key_not_configured"
        assert route.called is False

    def test_upstream_401_surfaces_clean_error(self, respx_mock):
        self._route(respx_mock, status=401, body={
            "error": {"message": "Invalid API key provided.", "type": "invalid_api_key", "code": 401}
        })
        raw = server.people_search_perplexity(["financial controller Dublin"])
        out = json.loads(raw)
        assert out["error"] == "perplexity_error"
        assert "invalid_api_key" in out["message"]
        assert self.API_KEY not in raw

    def test_malformed_results_return_error_json_not_exception(self, respx_mock):
        self._route(respx_mock, body={"results": {"x": 1}})
        out = json.loads(server.people_search_perplexity(["financial controller Dublin"]))
        assert out["error"] == "perplexity_error"
        assert "invalid_response" in out["message"]

    def test_non_dict_entries_and_non_string_snippet_tolerated(self, respx_mock):
        self._route(respx_mock, body={"results": [
            "junk",
            {"title": "Jane Smith", "url": "https://linkedin.com/in/js", "snippet": 12345},
        ]})
        out = json.loads(server.people_search_perplexity(["financial controller Dublin"]))
        assert out["count"] == 1
        assert out["results"][0]["title"] == "Jane Smith"
        assert out["results"][0]["snippet"] == ""

    def test_max_results_clamped(self, respx_mock):
        route = self._route(respx_mock)
        server.people_search_perplexity(["q"], max_results=0)
        assert json.loads(route.calls.last.request.content)["max_results"] == 1
        server.people_search_perplexity(["q"], max_results=100)
        assert json.loads(route.calls.last.request.content)["max_results"] == 50
