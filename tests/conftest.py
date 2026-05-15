"""Shared test fixtures."""

import pytest
from bullhorn_mcp.config import BullhornConfig
from bullhorn_mcp.auth import BullhornAuth, BullhornSession
from bullhorn_mcp.client import BullhornClient


@pytest.fixture
def sample_config():
    """Create a sample configuration for testing."""
    return BullhornConfig(
        client_id="test_client_id",
        client_secret="test_client_secret",
        username="test_user",
        password="test_password",
        auth_url="https://auth.bullhornstaffing.com",
        login_url="https://rest.bullhornstaffing.com",
    )


@pytest.fixture
def mock_session():
    """Create a mock Bullhorn session."""
    import time
    return BullhornSession(
        bh_rest_token="test_token_123",
        rest_url="https://rest99.bullhornstaffing.com/rest-services/abc123",  # No trailing slash
        expires_at=time.time() + 600,
    )


@pytest.fixture
def sample_job():
    """Sample job order data."""
    return {
        "id": 12345,
        "title": "Software Engineer",
        "status": "Open",
        "employmentType": "Direct Hire",
        "dateAdded": 1704067200000,
        "salary": 150000,
        "isOpen": True,
        "numOpenings": 2,
        "description": "We are looking for a skilled software engineer...",
    }


@pytest.fixture
def sample_candidate():
    """Sample candidate data."""
    return {
        "id": 67890,
        "firstName": "John",
        "lastName": "Smith",
        "email": "john.smith@example.com",
        "phone": "555-1234",
        "status": "Active",
        "dateAdded": 1704067200000,
        "occupation": "Software Developer",
    }


@pytest.fixture
def sample_note_records():
    """Sample Note records as returned by /entity/Note/<ids>."""
    return [
        {
            "id": 1001,
            "action": "General Note",
            "comments": "Candidate is a strong fit.",
            "dateAdded": 1700000000000,
            "isDeleted": False,
            "commentingPerson": {"id": 10, "firstName": "Alice", "lastName": "Recruiter"},
            "personReference": {"id": 169020, "firstName": "John", "lastName": "Doe"},
            "jobOrder": None,
            "clientCorporation": None,
        },
        {
            "id": 1002,
            "action": "Phone Call",
            "comments": "Left voicemail. [cc:abcd1234-0000-0000-0000-000000000001,+61400000000,+61400000001,inbound]",
            "dateAdded": 1699000000000,
            "isDeleted": False,
            "commentingPerson": {"id": 10, "firstName": "Alice", "lastName": "Recruiter"},
            "personReference": {"id": 169020, "firstName": "John", "lastName": "Doe"},
            "jobOrder": None,
            "clientCorporation": None,
        },
        {
            "id": 1003,
            "action": "General Note",
            "comments": "Old deleted note.",
            "dateAdded": 1698000000000,
            "isDeleted": True,
            "commentingPerson": None,
            "personReference": {"id": 169020, "firstName": "John", "lastName": "Doe"},
            "jobOrder": None,
            "clientCorporation": None,
        },
    ]


@pytest.fixture
def sample_cc_telemetry_comment():
    """A comments string with an embedded click-to-call tag."""
    return "Left voicemail. [cc:abcd1234-0000-0000-0000-000000000001,+61400000000,+61400000001,inbound]"


@pytest.fixture
def sample_parsed_resume():
    """Realistic Bullhorn /resume/parseToCandidate response fixture."""
    return {
        "candidate": {
            "firstName": "Jane",
            "lastName": "Doe",
            "email": "jane.doe@example.com",
            "phone": "555-0001",
            "occupation": "Senior Software Engineer",
            "companyName": "Acme Corp",
            "skillSet": "",
            "address": {"city": "New York", "state": "NY", "zip": "10001"},
        },
        "candidateEducation": [
            {
                "school": "MIT",
                "degree": "Bachelor of Science",
                "major": "Computer Science",
                "startDate": 1072915200000,
                "endDate": 1199145600000,
            }
        ],
        "candidateWorkHistory": [
            {
                "companyName": "Acme Corp",
                "title": "Senior Software Engineer",
                "startDate": 1514764800000,
                "endDate": None,
                "comments": "Led platform team.",
            },
            {
                "companyName": "Beta Systems",
                "title": "Software Engineer",
                "startDate": 1388534400000,
                "endDate": 1514764800000,
                "comments": "Built internal tooling.",
            },
        ],
        "skillList": [
            {"id": 100, "name": "Python"},
            {"id": 101, "name": "PostgreSQL"},
            {"id": None, "name": "Obscure Framework"},
        ],
    }
