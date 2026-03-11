"""Tests for bulk import orchestration (Sprint 7)."""

import pytest
import respx
import httpx

from bullhorn_mcp.bulk import BulkImporter
from bullhorn_mcp.client import BullhornClient, BullhornAPIError
from bullhorn_mcp.metadata import BullhornMetadata


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_session():
    """Provide a mock Bullhorn auth session."""

    class _Session:
        rest_url = "https://rest.bullhornstaffing.com/rest-services/abc"
        bh_rest_token = "test-token"

    class _Auth:
        session = _Session()

        def _refresh_session(self):
            pass

    return _Auth()


@pytest.fixture
def client(mock_session):
    return BullhornClient(mock_session)


@pytest.fixture
def metadata(client):
    return BullhornMetadata(client)


@pytest.fixture
def importer(client, metadata):
    return BulkImporter(client, metadata)


BASE_URL = "https://rest.bullhornstaffing.com/rest-services/abc"


# ---------------------------------------------------------------------------
# T7.2 — Company processing tests
# ---------------------------------------------------------------------------


@respx.mock
def test_process_companies_creates_new(importer):
    """When no search results, a new company is created."""
    # Search returns no results
    respx.get(f"{BASE_URL}/search/ClientCorporation").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    # meta endpoint for resolve_fields (returns no fields → passthrough)
    respx.get(f"{BASE_URL}/meta/ClientCorporation").mock(
        return_value=httpx.Response(200, json={"fields": []})
    )
    # Create call
    respx.put(f"{BASE_URL}/entity/ClientCorporation").mock(
        return_value=httpx.Response(200, json={"changedEntityId": 111, "changeType": "INSERT"})
    )
    # GET after create
    respx.get(f"{BASE_URL}/entity/ClientCorporation/111").mock(
        return_value=httpx.Response(200, json={"data": {"id": 111, "name": "NewCo"}})
    )

    result = importer.process([{"name": "NewCo", "status": "Prospect"}], [])

    assert result["halted"] is False
    assert result["summary"]["companies"]["created"] == 1
    assert result["details"]["companies"][0]["status"] == "created"
    assert result["details"]["companies"][0]["bullhorn_id"] == 111


@respx.mock
def test_process_companies_uses_existing(importer):
    """When an exact match is found, status is 'existing' and no create is called."""
    respx.get(f"{BASE_URL}/search/ClientCorporation").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"id": 999, "name": "Acme Holdings Ltd", "status": "Active", "phone": None}]},
        )
    )
    # PUT should NOT be called — if it is, respx will raise

    result = importer.process([{"name": "Acme Holdings Ltd"}], [])

    assert result["halted"] is False
    assert result["details"]["companies"][0]["status"] == "existing"
    assert result["details"]["companies"][0]["bullhorn_id"] == 999
    assert result["summary"]["companies"]["existing"] == 1


@respx.mock
def test_process_companies_flags_likely_match(importer):
    """When a likely (but not exact) match is found, status is 'flagged'."""
    respx.get(f"{BASE_URL}/search/ClientCorporation").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"id": 888, "name": "Acme Holdings", "status": "Active", "phone": None}]},
        )
    )

    # "Acme Corp" vs "Acme Holdings" — difflib gives ~0.73 (possible) or similar.
    # Use a name that fuzzy-scores in likely range against the candidate.
    result = importer.process([{"name": "Acme Holdings Group"}], [])

    company_result = result["details"]["companies"][0]
    # Could be flagged (likely/possible) — confirm it's NOT "created" or "existing"
    assert company_result["status"] == "flagged"
    assert company_result["bullhorn_id"] == 888
    assert result["summary"]["companies"]["flagged"] == 1


@respx.mock
def test_process_companies_halts_on_consecutive_errors(importer):
    """After 3 consecutive create errors, halted=True is returned."""
    # All searches return no results
    respx.get(f"{BASE_URL}/search/ClientCorporation").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get(f"{BASE_URL}/meta/ClientCorporation").mock(
        return_value=httpx.Response(200, json={"fields": []})
    )
    # All creates fail
    respx.put(f"{BASE_URL}/entity/ClientCorporation").mock(
        return_value=httpx.Response(400, json={"errorMessage": "Bad request"})
    )

    companies = [
        {"name": "Co1"},
        {"name": "Co2"},
        {"name": "Co3"},
    ]
    result = importer.process(companies, [])

    assert result["halted"] is True
    failed_count = sum(1 for d in result["details"]["companies"] if d["status"] == "failed")
    assert failed_count == 3
    assert result["summary"]["companies"]["failed"] == 3


# ---------------------------------------------------------------------------
# T7.3 — Contact processing tests
# ---------------------------------------------------------------------------


@respx.mock
def test_process_contacts_resolves_company_from_map(importer):
    """Contact with company_name present in pre-built map uses map ID without extra search."""
    # No ClientCorporation search should be made (company already in map)
    # Owner query
    respx.get(f"{BASE_URL}/query/CorporateUser").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 5, "firstName": "A", "lastName": "B"}]})
    )
    # Contact duplicate search (no existing)
    respx.get(f"{BASE_URL}/search/ClientContact").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get(f"{BASE_URL}/meta/ClientContact").mock(
        return_value=httpx.Response(200, json={"fields": []})
    )
    respx.put(f"{BASE_URL}/entity/ClientContact").mock(
        return_value=httpx.Response(200, json={"changedEntityId": 200, "changeType": "INSERT"})
    )
    respx.get(f"{BASE_URL}/entity/ClientContact/200").mock(
        return_value=httpx.Response(200, json={"data": {"id": 200, "firstName": "Jane"}})
    )

    # Pre-populate map; no ClientCorporation search routes registered
    company_id_map = {"Acme Ltd": 42}
    detail, halted = importer._process_single_contact(
        {
            "firstName": "Jane",
            "lastName": "Doe",
            "company_name": "Acme Ltd",
            "owner": "A B",
        },
        company_id_map,
    )

    assert halted is False
    assert detail["status"] == "created"
    assert detail["company_id"] == 42
    assert detail["bullhorn_id"] == 200


@respx.mock
def test_process_contacts_creates_company_on_the_fly(importer):
    """When company_name not in map and not in Bullhorn, company is created on-the-fly."""
    # Company search returns no results
    respx.get(f"{BASE_URL}/search/ClientCorporation").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get(f"{BASE_URL}/meta/ClientCorporation").mock(
        return_value=httpx.Response(200, json={"fields": []})
    )
    respx.put(f"{BASE_URL}/entity/ClientCorporation").mock(
        return_value=httpx.Response(200, json={"changedEntityId": 300, "changeType": "INSERT"})
    )
    respx.get(f"{BASE_URL}/entity/ClientCorporation/300").mock(
        return_value=httpx.Response(200, json={"data": {"id": 300, "name": "NewCo"}})
    )
    # Owner query
    respx.get(f"{BASE_URL}/query/CorporateUser").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 7, "firstName": "X", "lastName": "Y"}]})
    )
    # Contact duplicate search
    respx.get(f"{BASE_URL}/search/ClientContact").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get(f"{BASE_URL}/meta/ClientContact").mock(
        return_value=httpx.Response(200, json={"fields": []})
    )
    respx.put(f"{BASE_URL}/entity/ClientContact").mock(
        return_value=httpx.Response(200, json={"changedEntityId": 400, "changeType": "INSERT"})
    )
    respx.get(f"{BASE_URL}/entity/ClientContact/400").mock(
        return_value=httpx.Response(200, json={"data": {"id": 400, "firstName": "Hank"}})
    )

    company_id_map: dict = {}
    detail, halted = importer._process_single_contact(
        {
            "firstName": "Hank",
            "lastName": "Scorpio",
            "company_name": "NewCo",
            "owner": "X Y",
        },
        company_id_map,
    )

    assert halted is False
    assert detail["status"] == "created"
    assert detail["bullhorn_id"] == 400
    assert detail["company_id"] == 300
    # Company added to map
    assert company_id_map["NewCo"] == 300


@respx.mock
def test_process_contacts_skips_existing(importer):
    """When a contact with exact name match exists at the company, status is 'existing'."""
    respx.get(f"{BASE_URL}/query/CorporateUser").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 5, "firstName": "A", "lastName": "B"}]})
    )
    respx.get(f"{BASE_URL}/search/ClientContact").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"id": 500, "firstName": "Jane", "lastName": "Doe", "email": "j@acme.com"}]},
        )
    )

    company_id_map = {"Acme": 42}
    detail, halted = importer._process_single_contact(
        {
            "firstName": "Jane",
            "lastName": "Doe",
            "company_name": "Acme",
            "owner": "A B",
        },
        company_id_map,
    )

    assert halted is False
    assert detail["status"] == "existing"
    assert detail["bullhorn_id"] == 500


@respx.mock
def test_process_contacts_flags_ambiguous_owner(importer):
    """When owner resolves to multiple users, status is 'flagged' (not 'failed')."""
    respx.get(f"{BASE_URL}/query/CorporateUser").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"id": 1, "firstName": "John", "lastName": "Smith", "email": "js1@co.com", "department": "Sales"},
                    {"id": 2, "firstName": "John", "lastName": "Smith", "email": "js2@co.com", "department": "Ops"},
                ]
            },
        )
    )

    company_id_map = {"Acme": 42}
    detail, halted = importer._process_single_contact(
        {
            "firstName": "Jane",
            "lastName": "Doe",
            "company_name": "Acme",
            "owner": "John Smith",
        },
        company_id_map,
    )

    assert halted is False
    assert detail["status"] == "flagged"
    assert detail["reason"] == "owner_ambiguous"
    assert len(detail["owner_matches"]) == 2


@respx.mock
def test_process_contacts_fails_on_owner_not_found(importer):
    """When owner name matches zero CorporateUsers, status is 'failed'."""
    respx.get(f"{BASE_URL}/query/CorporateUser").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    company_id_map = {"Acme": 42}
    detail, halted = importer._process_single_contact(
        {
            "firstName": "Jane",
            "lastName": "Doe",
            "company_name": "Acme",
            "owner": "Nobody Here",
        },
        company_id_map,
    )

    assert halted is False
    assert detail["status"] == "failed"
    assert "Nobody Here" in detail["error"]


# ---------------------------------------------------------------------------
# T7.4 — Summary generation
# ---------------------------------------------------------------------------


def test_build_summary_correct_counts(importer):
    """_build_summary correctly aggregates status counts."""
    company_details = [
        {"status": "created"},
        {"status": "existing"},
        {"status": "created"},
        {"status": "flagged"},
        {"status": "failed"},
    ]
    contact_details = [
        {"status": "created"},
        {"status": "existing"},
        {"status": "flagged"},
        {"status": "flagged"},
        {"status": "failed"},
        {"status": "failed"},
    ]

    summary = importer._build_summary(company_details, contact_details)

    assert summary["companies"] == {"created": 2, "existing": 1, "flagged": 1, "failed": 1}
    assert summary["contacts"] == {"created": 1, "existing": 1, "flagged": 2, "failed": 2}


# ---------------------------------------------------------------------------
# Sprint 7 End-to-End tests
# ---------------------------------------------------------------------------


@respx.mock
def test_sprint7_e2e_full_batch_import(importer):
    """Full batch: 2 companies + 2 contacts all created successfully."""
    # Company searches — no existing records
    respx.get(f"{BASE_URL}/search/ClientCorporation").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get(f"{BASE_URL}/meta/ClientCorporation").mock(
        return_value=httpx.Response(200, json={"fields": []})
    )
    # Company creates
    create_company_responses = [
        httpx.Response(200, json={"changedEntityId": 101, "changeType": "INSERT"}),
        httpx.Response(200, json={"changedEntityId": 102, "changeType": "INSERT"}),
    ]
    respx.put(f"{BASE_URL}/entity/ClientCorporation").mock(
        side_effect=create_company_responses
    )
    respx.get(f"{BASE_URL}/entity/ClientCorporation/101").mock(
        return_value=httpx.Response(200, json={"data": {"id": 101, "name": "Acme"}})
    )
    respx.get(f"{BASE_URL}/entity/ClientCorporation/102").mock(
        return_value=httpx.Response(200, json={"data": {"id": 102, "name": "Globex"}})
    )

    # Owner queries — both resolve to single user
    respx.get(f"{BASE_URL}/query/CorporateUser").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 5, "firstName": "Mary", "lastName": "Lyons"}]})
    )
    # Contact duplicate searches — no existing
    respx.get(f"{BASE_URL}/search/ClientContact").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get(f"{BASE_URL}/meta/ClientContact").mock(
        return_value=httpx.Response(200, json={"fields": []})
    )
    # Contact creates
    create_contact_responses = [
        httpx.Response(200, json={"changedEntityId": 201, "changeType": "INSERT"}),
        httpx.Response(200, json={"changedEntityId": 202, "changeType": "INSERT"}),
    ]
    respx.put(f"{BASE_URL}/entity/ClientContact").mock(
        side_effect=create_contact_responses
    )
    respx.get(f"{BASE_URL}/entity/ClientContact/201").mock(
        return_value=httpx.Response(200, json={"data": {"id": 201, "firstName": "Jane"}})
    )
    respx.get(f"{BASE_URL}/entity/ClientContact/202").mock(
        return_value=httpx.Response(200, json={"data": {"id": 202, "firstName": "Hank"}})
    )

    result = importer.process(
        companies=[
            {"name": "Acme", "status": "Prospect"},
            {"name": "Globex", "status": "Prospect"},
        ],
        contacts=[
            {"firstName": "Jane", "lastName": "Doe", "company_name": "Acme", "owner": "Mary Lyons"},
            {"firstName": "Hank", "lastName": "Scorpio", "company_name": "Globex", "owner": "Mary Lyons"},
        ],
    )

    assert result["halted"] is False
    assert result["summary"]["companies"]["created"] == 2
    assert result["summary"]["contacts"]["created"] == 2
    assert len(result["details"]["companies"]) == 2
    assert len(result["details"]["contacts"]) == 2


@respx.mock
def test_sprint7_e2e_halt_on_consecutive_errors(importer):
    """Three consecutive company create failures trigger halt."""
    respx.get(f"{BASE_URL}/search/ClientCorporation").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get(f"{BASE_URL}/meta/ClientCorporation").mock(
        return_value=httpx.Response(200, json={"fields": []})
    )
    respx.put(f"{BASE_URL}/entity/ClientCorporation").mock(
        return_value=httpx.Response(400, json={"errorMessage": "Server error"})
    )

    result = importer.process(
        companies=[{"name": "A"}, {"name": "B"}, {"name": "C"}, {"name": "D"}],
        contacts=[],
    )

    assert result["halted"] is True
    # At least 3 failed records recorded before halt
    failed = [d for d in result["details"]["companies"] if d["status"] == "failed"]
    assert len(failed) >= 3
    # Contacts not processed
    assert result["details"]["contacts"] == []
