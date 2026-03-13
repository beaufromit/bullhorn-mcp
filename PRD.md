# PRD: Bullhorn MCP Server — Record Management Expansion

## 1. Overview

The existing Bullhorn MCP server provides read-only access to Bullhorn CRM data (jobs, candidates, placements, and generic entity search/query). This expansion adds record creation, updating, duplicate detection, note management, and field metadata resolution — primarily for ClientCorporation and ClientContact entities.

The MCP serves two classes of consumer:

- **Automated agents** (e.g. Twin.so) that discover hiring signals and push companies and contacts into Bullhorn in bulk.
- **Human users** working through a chat agent (e.g. Claude) who review, update, and enrich the records those agents create.

## 2. Problem Statement

Recruitment consultancies using Bullhorn CRM need to continuously discover and capture new business opportunities — companies showing hiring signals and their key contacts. Today, this discovery happens externally (via tools like Twin.so), but getting the results into Bullhorn is manual: consultants copy-paste records, risk creating duplicates, and lose time on data entry rather than relationship-building.

The existing open-source Bullhorn MCP server is read-only, so AI agents and chat-based workflows cannot write back to the CRM. There is no automated path from "opportunity discovered" to "record exists in Bullhorn, ready to work."

Until these records are in Bullhorn, downstream tools cannot act on them. Automated email sequences, Bullhorn Automation workflows, and other follow-up processes all depend on the contact and company existing in the CRM with correct ownership and data. The gap between discovery and CRM entry is the bottleneck this expansion removes.

## 3. Goals

- Enable automated agents to create ClientCorporation and ClientContact records in Bullhorn without human intervention.
- Prevent duplicate records through fuzzy matching with confidence-scored results.
- Allow consultants to review, update, and enrich records through a chat agent without opening the Bullhorn UI.
- Ensure all newly discovered opportunities are captured in Bullhorn so downstream automation tools (email sequences, Bullhorn Automation workflows, etc.) can trigger follow-up.
- Require and resolve consultant ownership on every new contact record, so that records enter Bullhorn with clear accountability from day one. The MCP resolves consultant names to Bullhorn user IDs internally.
- Resolve field names between API names and user-facing labels so agents and users can work naturally.
- Preserve all existing read-only MCP functionality.

## 4. Non-Goals

- Deleting, merging, or archiving records.
- Reassigning contacts between companies.
- Building the Twin.so agent or the chat agent that calls the MCP (those are separate projects).
- Creating new Bullhorn field types, custom objects, or note action types.
- Real-time sync or webhook-based triggers.
- Managing Candidate or JobOrder creation (existing read tools remain, but write scope is limited to ClientCorporation and ClientContact).

## 5. Context and Workflow

1. A Twin.so agent runs weekly, identifying companies showing signs of hiring and finding relevant contacts at those companies.
2. The agent sends companies and contacts to this MCP to be checked against existing Bullhorn records and added if missing.
3. A consultant within the business is alerted to new opportunities and works through a chat agent to review the new records, update fields (including custom fields), and add notes.

## 6. Functional Requirements

### FR-1: Create ClientCorporation Records

The MCP shall provide a tool to create a new ClientCorporation entity in Bullhorn. The tool accepts standard Bullhorn fields (name, status, phone, address, industry, etc.) and any custom fields. All mandatory Bullhorn fields that lack defaults must be provided by the caller. An owner (recruiterUserID) may optionally be provided. The tool returns the created record including its new Bullhorn ID.

### FR-2: Create ClientContact Records

The MCP shall provide a tool to create a new ClientContact entity in Bullhorn, linked to an existing ClientCorporation. The tool accepts standard Bullhorn fields (firstName, lastName, name, email, phone, occupation, etc.) and any custom fields. The caller must provide:

- A valid ClientCorporation ID to associate the contact with.
- An owner (consultant) — this is **required**. The caller may provide either a Bullhorn user ID or a consultant name. If a name is provided, the MCP resolves it to a Bullhorn CorporateUser ID internally by searching the CorporateUser entity. If the name resolves to multiple users, the MCP returns all matches with disambiguation information (email, department) and does not create the record until the caller specifies which user.

The tool returns the created record including its new Bullhorn ID.

### FR-3: Duplicate Detection — Company

The MCP shall provide a tool to check whether a company already exists in Bullhorn before creation. The tool:

- Accepts a company name (and optionally other identifying fields such as website or phone).
- Searches existing ClientCorporation records using broad search terms.
- Applies fuzzy string matching locally to compare results against the input, handling abbreviations (e.g. "BNY" vs "Bank of New York Mellon"), common suffixes (Ltd/Limited, Inc/Incorporated), and minor spelling variations.
- Returns results categorised by confidence: **exact match**, **likely match**, or **possible match**, each with a numeric confidence score.
- Returns the matched Bullhorn record IDs and key fields so the caller can decide whether to proceed with creation.

### FR-4: Duplicate Detection — Contact

The MCP shall provide a tool to check whether a contact already exists at a given company in Bullhorn. The tool:

- Accepts first name, last name, and a ClientCorporation ID (or company name).
- Searches existing ClientContact records at that company.
- Applies fuzzy matching on name fields.
- Returns results categorised by confidence (exact/likely/possible) with scores.
- Flags partial matches (e.g. same name but different email) for user review.

### FR-5: Bulk Import Workflow

The MCP shall provide a tool that accepts a batch of companies and contacts and processes them in sequence:

1. **Companies first**: For each company in the batch, run duplicate detection. If an exact match exists, use the existing record. If no match, create the company. If a likely/possible match exists, flag it and include it in the results for user review.
2. **Contacts second**: For each contact, resolve its company reference to a Bullhorn ClientCorporation ID (from step 1 results or by searching Bullhorn). If the referenced company does not exist in Bullhorn or in the batch, create the company with whatever information is available. Then run contact duplicate detection. If no match, create the contact linked to the resolved company. If a match exists, flag it.
3. **Error handling**: If a create operation fails, skip that record and continue. If 3 or more consecutive create errors occur, halt the batch and return results so far, with an explanation that consecutive errors suggest a systemic issue.
4. **Return a summary**: counts of created, skipped (duplicate), flagged (partial match), and failed records, plus detail for each record processed.

### FR-6: Update Records

The MCP shall provide a tool to update fields on existing ClientCorporation and ClientContact records. The tool:

- Accepts an entity type, entity ID, and a dictionary of field names to new values.
- Supports standard fields and custom fields.
- Resolves field labels to API field names (see FR-8) if the caller provides labels instead of API names.
- **Explicitly does not support** changing a ClientContact's associated ClientCorporation (company reassignment).
- Returns the full updated record after the change has been applied, confirming the new values.

### FR-7: Add Notes

The MCP shall provide a tool to add a Note entity associated with a ClientContact or ClientCorporation. The tool:

- Accepts the target entity type and ID, a note body (comments), and an action string.
- The action string must correspond to a valid note action that exists in the Bullhorn instance.
- Associates the note using `personReference` (for contacts) or `clientCorporation` association, and sets `commentingPerson` to automate the NoteEntity association.
- Returns the created Note record including its ID.

### FR-8: Field Metadata and Label Resolution

The MCP shall provide a tool to query Bullhorn's entity metadata and resolve between API field names and user-facing display labels. The tool:

- Accepts an entity type (e.g. ClientContact, ClientCorporation).
- Returns the field list with both the API name and the display label for each field.
- Supports resolution in both directions: given a label, return the API name; given an API name, return the label.
- This enables calling agents and users to reference fields by either name. For example, the user-facing "Consultant" field resolves to the API field `recruiterUserID`.
- Metadata responses are cached within a session to avoid repeated round-trips for the same entity type.

### FR-9: Convenience Tools — List Contacts and Companies

The MCP shall provide convenience tools (`list_contacts` and `list_companies`) that mirror the existing `list_jobs` and `list_candidates` patterns:

- Accept optional query, status filter, limit, and fields parameters.
- Default to sensible field sets for each entity.
- Sort by dateAdded descending by default.

### FR-10: Preserve Existing Functionality

All existing read-only tools (`list_jobs`, `list_candidates`, `get_job`, `get_candidate`, `search_entities`, `query_entities`) must continue to work without modification.

## 7. Non-Functional Requirements

### NFR-1: No Destructive Operations

The MCP shall not support deleting, merging, or archiving records. It is strictly create, read, and update.

### NFR-2: No Company Reassignment

The MCP shall explicitly reject any attempt to change a ClientContact's associated ClientCorporation, returning a clear error message explaining why this is not supported.

### NFR-3: Error Handling and Resilience

- All tools must handle Bullhorn API errors gracefully and return informative error messages.
- Authentication errors must trigger session refresh and retry (existing behaviour).
- Bulk operations must be resilient to individual record failures (skip and continue), halting only on 3 consecutive errors.

### NFR-4: Field Name Flexibility

All tools that accept field names (create, update, query) should accept either API field names or user-facing labels, resolving via the metadata API where needed.

### NFR-5: Fuzzy Matching Quality

Duplicate detection must handle:

- Common abbreviations (BNY / Bank of New York).
- Legal suffixes (Ltd / Limited, Inc / Incorporated, PLC, Corp / Corporation).
- Case insensitivity.
- Minor typographical variations.

Confidence scoring should be consistent and meaningful enough for automated agents to make decisions (e.g. exact match > 0.95, likely match 0.75–0.95, possible match 0.5–0.75).

### NFR-6: Testability

All new functionality must have comprehensive unit tests using the existing `respx` mocking pattern. Integration with the existing test suite must be maintained.

### NFR-7: Performance

Bulk operations should process records as efficiently as possible given the one-at-a-time API constraint. Metadata queries should be cached within a session to avoid repeated round-trips for the same entity type.

## 8. Constraints and Exclusions

- **No record deletion or merging** — out of scope and explicitly prohibited.
- **No company reassignment** — moving a contact from one company to another is not supported due to known Bullhorn data integrity issues.
- **No bulk API** — Bullhorn does not offer a bulk create endpoint; all creates are individual PUT requests to `/entity/{EntityType}`.
- **Entity scope** — new create/update capabilities are for ClientCorporation and ClientContact only. Existing generic search/query tools continue to work for all entity types.
- **Note actions** — must correspond to valid actions in the target Bullhorn instance; the MCP does not create new action types.
- **Bullhorn meta API inconsistencies** — the meta endpoint's `required` and `optional` flags do not always reflect what the API actually enforces. The MCP should rely on Bullhorn's error responses to surface genuinely missing fields rather than pre-validating against metadata alone.

## 9. User Stories

### Record Creation

**US-1: Create a company record**
As an automated agent, I want to create a new ClientCorporation record in Bullhorn with standard and custom fields, so that discovered companies are captured in the CRM.
- **Acceptance**: Calling the create tool with a valid company name and fields returns a response containing `{"changedEntityId": <id>, "changeType": "INSERT"}`. The record is retrievable via `search_entities` or `list_companies` immediately after.

**US-2: Create a contact record linked to a company**
As an automated agent, I want to create a new ClientContact record linked to an existing ClientCorporation, so that discovered contacts are correctly associated with their employer.
- **Acceptance**: Calling the create tool with firstName, lastName, name, clientCorporation ID, and owner returns a response containing the new record ID. The record appears under the specified company when retrieved.

**US-3: Create a company on-the-fly for an unmatched contact**
As an automated agent, when I attempt to add a contact whose company does not yet exist in Bullhorn or in my current batch, I want the MCP to create the company first with available information and then create the contact linked to it.
- **Acceptance**: Submitting a contact with a company name that doesn't exist in Bullhorn results in both a ClientCorporation and ClientContact being created, with the contact linked to the new company. The response includes IDs for both.

**US-4: Owner is required when creating a contact**
As a system, I want every new ClientContact to be created with an assigned owner (consultant), so that records enter Bullhorn with clear accountability.
- **Acceptance**: Attempting to create a ClientContact without specifying an owner returns an error indicating owner is required. Providing a consultant name (e.g. "Maryrose Lyons") resolves to the correct CorporateUser ID and the contact is created with that owner.

**US-5: Owner name resolves to user ID**
As an automated agent, I want to specify a consultant by name rather than Bullhorn user ID, so that I don't need to maintain a mapping of internal IDs.
- **Acceptance**: Providing `owner: "Maryrose Lyons"` resolves to the matching CorporateUser ID. If multiple users match, the response returns all matches with email and department for disambiguation, and the contact is not created until the caller specifies which user.

### Duplicate Detection

**US-6: Check if a company already exists**
As an automated agent, before creating a company, I want to check whether it already exists in Bullhorn using fuzzy name matching, so that I avoid creating duplicate records.
- **Acceptance**: Checking "BNY" returns "Bank of New York Mellon" as a likely match with a confidence score between 0.75 and 0.95. Checking an exact name returns an exact match with confidence > 0.95.

**US-7: Check if a contact already exists at a company**
As an automated agent, before creating a contact, I want to check whether a person with the same name already exists at the same company in Bullhorn, so that I avoid creating duplicates.
- **Acceptance**: Checking "John Smith" at ClientCorporation ID 123 returns any existing "John Smith" contacts at that company with confidence scores. If no match exists, the response indicates no matches found.

**US-8: Flag partial matches for human review**
As a consultant, when duplicate detection finds a likely or possible match (but not an exact match), I want those flagged for my review so that I can decide whether to proceed or merge information manually.
- **Acceptance**: Partial matches include the matched record's key fields (ID, name, email, phone, company) and a confidence category (likely/possible) so the reviewer has enough information to decide.

### Bulk Import

**US-9: Import a batch of companies and contacts**
As an automated agent, I want to submit a batch of companies and contacts for import, with companies processed first and contacts linked automatically, so that weekly discovery results flow into Bullhorn efficiently.
- **Acceptance**: Submitting a batch of 5 companies and 10 contacts processes all companies first (creating or matching), then processes contacts with correct company linkage. The response includes per-record outcomes.

**US-10: Receive an import summary**
As an automated agent, after a bulk import completes, I want a summary showing how many records were created, skipped as duplicates, flagged for review, or failed, so that I can report on the import outcome.
- **Acceptance**: The response includes `summary.companies` and `summary.contacts` each with counts for `created`, `existing`, `flagged`, and `failed`, plus a `details` array with per-record status.

**US-11: Halt on consecutive errors**
As an automated agent, if 3 or more consecutive record creation errors occur during a bulk import, I want the process to halt and return what it has done so far, so that systemic issues are surfaced quickly rather than silently failing across the entire batch.
- **Acceptance**: If records 4, 5, and 6 all fail to create, the process halts. The response includes all results up to that point plus a `halted` flag with the error details from the consecutive failures.

### Record Updates

**US-12: Update fields on a contact or company**
As a consultant, I want to update any standard or custom field on a ClientContact or ClientCorporation through a chat agent, so that I can enrich records without opening the Bullhorn UI.
- **Acceptance**: Updating `occupation` on ClientContact 67890 to "VP of Engineering" returns the full updated record with the new value confirmed.

**US-13: See the updated record after a change**
As a consultant, after updating a record, I want to see the full record with updated values returned to me, so that I can confirm the change was applied correctly.
- **Acceptance**: The update response includes all default fields for the entity type, reflecting the new values.

**US-14: Prevent company reassignment**
As a system, when an update request attempts to change a ClientContact's associated ClientCorporation, I want the MCP to reject the request with a clear explanation, so that data integrity issues are avoided.
- **Acceptance**: Attempting to update `clientCorporation` on a ClientContact returns an error message stating company reassignment is not supported, without modifying the record.

**US-15: Use field labels or API names interchangeably**
As a consultant, I want to reference fields by their user-facing label (e.g. "Consultant") or their API name (e.g. "recruiterUserID"), and have the MCP resolve the correct field, so that I don't need to know Bullhorn's internal schema.
- **Acceptance**: Updating `{"Consultant": {"id": 123}}` on a ClientContact is equivalent to updating `{"recruiterUserID": {"id": 123}}` — both succeed and modify the same field.

### Notes

**US-16: Add a note to a contact or company**
As an automated agent or consultant, I want to add a note with a specified action type to a ClientContact or ClientCorporation, so that activity and context is tracked in Bullhorn.
- **Acceptance**: Adding a note with `action: "General Note"` and `comments: "Discovered via Twin.so weekly scan"` to ClientContact 67890 creates a Note entity visible on that contact's Notes tab in Bullhorn. The response includes the new Note ID.

### Field Metadata

**US-17: Discover available fields and their labels**
As a calling agent, I want to query the available fields for an entity type and see both API names and display labels, so that I can correctly map data and present field names to users.
- **Acceptance**: Querying metadata for ClientContact returns a list including entries like `{"name": "recruiterUserID", "label": "Consultant", "type": "TO_ONE", "required": true}`.

**US-18: Resolve a field label to an API name**
As a calling agent, when a user refers to a field by its display label, I want to resolve that to the correct API field name so that I can make valid API requests.
- **Acceptance**: Resolving the label "Company" for entity ClientContact returns the API name `clientCorporation`. Resolving in the other direction also works.

### Convenience and Discovery

**US-19: List contacts with filters**
As a consultant, I want to list ClientContact records with optional search queries, status filters, and field selection, so that I can quickly find contacts from the chat agent.
- **Acceptance**: `list_contacts(status="Active", limit=10)` returns up to 10 active ClientContact records sorted by dateAdded descending, with default fields including id, firstName, lastName, email, phone, clientCorporation, and owner.

**US-20: List companies with filters**
As a consultant, I want to list ClientCorporation records with optional search queries, status filters, and field selection, so that I can quickly find companies from the chat agent.
- **Acceptance**: `list_companies(query="name:Acme*")` returns matching ClientCorporation records with default fields including id, name, status, phone, and address.

### Existing Functionality

**US-21: Existing read tools remain functional**
As any user, I want all existing MCP tools (list_jobs, list_candidates, get_job, get_candidate, search_entities, query_entities) to continue working as before, so that the expansion does not break current workflows.
- **Acceptance**: All existing tests pass without modification. Existing tool signatures and return formats are unchanged.

## 10. Input/Output Schemas

The following schemas are illustrative of the expected data shapes. Field sets may vary based on what the caller provides; these show the core structure.

### Create ClientCorporation — Request

```json
{
  "name": "Acme Holdings Ltd",
  "status": "Prospect",
  "phone": "+353 1 234 5678",
  "address": {
    "address1": "123 Main Street",
    "city": "Dublin",
    "state": "Leinster",
    "countryID": 2488
  },
  "industry": "Technology",
  "customText1": "PE-backed"
}
```

### Create ClientCorporation — Response

```json
{
  "changedEntityId": 98765,
  "changeType": "INSERT",
  "data": {
    "id": 98765,
    "name": "Acme Holdings Ltd",
    "status": "Prospect",
    "phone": "+353 1 234 5678",
    "address": {
      "address1": "123 Main Street",
      "city": "Dublin",
      "state": "Leinster",
      "countryID": 2488
    }
  }
}
```

### Create ClientContact — Request

```json
{
  "firstName": "Jane",
  "lastName": "Doe",
  "name": "Jane Doe",
  "email": "jane.doe@acme.com",
  "phone": "+353 1 234 5679",
  "occupation": "VP of Engineering",
  "clientCorporation": {"id": 98765},
  "owner": "Maryrose Lyons",
  "status": "New Lead"
}
```

Note: `owner` accepts either a name string (resolved internally to a CorporateUser ID) or an object `{"id": 12345}`.

### Create ClientContact — Response

```json
{
  "changedEntityId": 54321,
  "changeType": "INSERT",
  "data": {
    "id": 54321,
    "firstName": "Jane",
    "lastName": "Doe",
    "email": "jane.doe@acme.com",
    "phone": "+353 1 234 5679",
    "occupation": "VP of Engineering",
    "clientCorporation": {"id": 98765, "name": "Acme Holdings Ltd"},
    "owner": {"id": 12345, "firstName": "Maryrose", "lastName": "Lyons"}
  }
}
```

### Duplicate Detection — Company Response

```json
{
  "query": "BNY",
  "matches": [
    {
      "confidence": 0.88,
      "category": "likely",
      "record": {
        "id": 44321,
        "name": "Bank of New York Mellon",
        "status": "Active Account",
        "phone": "+1 212 495 1784"
      }
    },
    {
      "confidence": 0.52,
      "category": "possible",
      "record": {
        "id": 77654,
        "name": "BNY Logistics Ltd",
        "status": "Prospect",
        "phone": null
      }
    }
  ],
  "exact_match": false
}
```

### Duplicate Detection — Contact Response

```json
{
  "query": {
    "firstName": "John",
    "lastName": "Smith",
    "clientCorporation": {"id": 44321}
  },
  "matches": [
    {
      "confidence": 0.97,
      "category": "exact",
      "record": {
        "id": 11234,
        "firstName": "John",
        "lastName": "Smith",
        "email": "john.smith@bnymellon.com",
        "phone": "+1 212 495 2000",
        "clientCorporation": {"id": 44321, "name": "Bank of New York Mellon"}
      }
    }
  ],
  "exact_match": true
}
```

### Bulk Import — Request

```json
{
  "companies": [
    {
      "name": "Acme Holdings Ltd",
      "status": "Prospect",
      "phone": "+353 1 234 5678"
    },
    {
      "name": "Globex Corporation",
      "status": "Prospect"
    }
  ],
  "contacts": [
    {
      "firstName": "Jane",
      "lastName": "Doe",
      "name": "Jane Doe",
      "email": "jane.doe@acme.com",
      "occupation": "VP of Engineering",
      "company_name": "Acme Holdings Ltd",
      "owner": "Maryrose Lyons"
    },
    {
      "firstName": "Hank",
      "lastName": "Scorpio",
      "name": "Hank Scorpio",
      "email": "hank@globex.com",
      "occupation": "CEO",
      "company_name": "Globex Corporation",
      "owner": "Maryrose Lyons"
    }
  ]
}
```

### Bulk Import — Response

```json
{
  "halted": false,
  "summary": {
    "companies": {
      "created": 1,
      "existing": 1,
      "flagged": 0,
      "failed": 0
    },
    "contacts": {
      "created": 2,
      "existing": 0,
      "flagged": 0,
      "failed": 0
    }
  },
  "details": {
    "companies": [
      {
        "input_name": "Acme Holdings Ltd",
        "status": "created",
        "bullhorn_id": 98765
      },
      {
        "input_name": "Globex Corporation",
        "status": "existing",
        "bullhorn_id": 33210,
        "match_confidence": 0.98
      }
    ],
    "contacts": [
      {
        "input_name": "Jane Doe",
        "status": "created",
        "bullhorn_id": 54321,
        "company_id": 98765
      },
      {
        "input_name": "Hank Scorpio",
        "status": "created",
        "bullhorn_id": 54322,
        "company_id": 33210
      }
    ]
  }
}
```

### Update Record — Request

```json
{
  "entity": "ClientContact",
  "entity_id": 54321,
  "fields": {
    "occupation": "CTO",
    "customText1": "Hi Jane, congratulations on the recent funding Acme Holdings secured."
  }
}
```

### Update Record — Response

```json
{
  "changedEntityId": 54321,
  "changeType": "UPDATE",
  "data": {
    "id": 54321,
    "firstName": "Jane",
    "lastName": "Doe",
    "email": "jane.doe@acme.com",
    "occupation": "CTO",
    "customText1": "Hi Jane, congratulations on the recent funding Acme Holdings secured.",
    "clientCorporation": {"id": 98765, "name": "Acme Holdings Ltd"},
    "owner": {"id": 12345, "firstName": "Maryrose", "lastName": "Lyons"}
  }
}
```

### Add Note — Request

```json
{
  "entity": "ClientContact",
  "entity_id": 54321,
  "action": "General Note",
  "comments": "Discovered via Twin.so weekly scan. Company recently secured PE funding."
}
```

### Add Note — Response

```json
{
  "changedEntityId": 88901,
  "changeType": "INSERT",
  "data": {
    "id": 88901,
    "action": "General Note",
    "comments": "Discovered via Twin.so weekly scan. Company recently secured PE funding.",
    "personReference": {"id": 54321, "firstName": "Jane", "lastName": "Doe"},
    "dateAdded": 1710000000000
  }
}
```

## 11. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Fuzzy matching produces false positives (flags unrelated companies as duplicates) | Confidence scoring with clear thresholds; likely/possible matches flagged for human review rather than auto-skipped |
| Fuzzy matching misses true duplicates (abbreviations not covered by matching logic) | Support common patterns (legal suffixes, known abbreviations); design matching logic to be extensible over time |
| Bullhorn meta API reports inconsistent required/optional flags | Test actual creation requirements empirically; document known quirks; rely on Bullhorn's error responses to surface genuinely missing fields rather than pre-validating solely against metadata |
| Bullhorn API rate limiting during bulk imports | Add configurable delay between requests; respect rate limit headers if present; halt-on-consecutive-errors protects against runaway failures |
| User lookup by name returns multiple matches (e.g. two "John Smith" consultants) | Return all matches with disambiguation info (email, department); require caller to resolve before proceeding |
| Custom field names vary between Bullhorn instances | Use meta API at runtime to resolve labels; never hardcode custom field names |
| Note action string doesn't match a valid Bullhorn action | Return Bullhorn's error response clearly so the caller can correct the action |
| Intermittent Bullhorn API errors on entity creation | Implement retry logic for known transient errors (e.g. "error persisting an entity" which Bullhorn support acknowledges as intermittent) |
