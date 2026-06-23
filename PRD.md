# PRD: Bullhorn MCP Server — Record Management Expansion

## 1. Overview

The existing Bullhorn MCP server provides read-only access to Bullhorn CRM data (jobs, candidates, placements, and generic entity search/query). This expansion adds record creation, updating, duplicate detection, note management, field metadata resolution, hosted HTTP access, authenticated-user owner stamping, first-class JobOrder create/update workflows, and JobSubmission (shortlist) write tools.

Subsequent change requests extended the scope to include: candidate creation and CV parsing (FR-15), note reading and full-text search (FR-16), email/UserMessage search (FR-17), single-record and pipeline read tools — `get_company`, `get_contact`, `get_job_submissions` (FR-18), a paginated-envelope response format across all list/search/query tools (FR-19), Candidate record updates via `update_record` (FR-20), and tearsheet (hotlist) management tools (FR-21).

The MCP serves two classes of consumer:

- **Automated agents** (e.g. Twin.so) that discover hiring signals and push companies and contacts into Bullhorn in bulk.
- **Human users** working through a chat agent (e.g. Claude) who review, update, and enrich the records those agents create.

## 2. Problem Statement

Recruitment consultancies using Bullhorn CRM need to continuously discover and capture new business opportunities — companies showing hiring signals and their key contacts. Today, this discovery happens externally (via tools like Twin.so), but getting the results into Bullhorn is manual: consultants copy-paste records, risk creating duplicates, and lose time on data entry rather than relationship-building.

The existing open-source Bullhorn MCP server is read-only, so AI agents and chat-based workflows cannot write back to the CRM. There is no automated path from "opportunity discovered" to "record exists in Bullhorn, ready to work."

Until these records are in Bullhorn, downstream tools cannot act on them. Automated email sequences, Bullhorn Automation workflows, and other follow-up processes all depend on the contact and company existing in the CRM with correct ownership and data. The gap between discovery and CRM entry is the bottleneck this expansion removes.

## 3. Goals

- Enable automated agents to create ClientCorporation and ClientContact records in Bullhorn without human intervention.
- Enable consultants and AI-assisted workflows to create and update JobOrder records with explicit, documented tools.
- Prevent duplicate records through fuzzy matching with confidence-scored results.
- Allow consultants to review, update, and enrich records through a chat agent without opening the Bullhorn UI.
- Ensure all newly discovered opportunities are captured in Bullhorn so downstream automation tools (email sequences, Bullhorn Automation workflows, etc.) can trigger follow-up.
- Ensure consultant ownership on every new contact/company record, either from an explicit owner supplied by the caller or by resolving the authenticated user to a Bullhorn CorporateUser.
- Resolve field names between API names and user-facing labels so agents and users can work naturally.
- Preserve all existing read-only MCP functionality.

## 4. Non-Goals

- Deleting, merging, or archiving records.
- Reassigning contacts between companies.
- Building the Twin.so agent or the chat agent that calls the MCP (those are separate projects).
- Creating new Bullhorn field types, custom objects, or note action types.
- Real-time sync or webhook-based triggers.
- Candidate deletion, merging, or archiving (creation and CV parsing are now in scope — see FR-15).
- JobOrder duplicate detection, bulk job import, deletion, merging, or archiving.

## 5. Context and Workflow

1. A Twin.so agent runs weekly, identifying companies showing signs of hiring and finding relevant contacts at those companies.
2. The agent sends companies and contacts to this MCP to be checked against existing Bullhorn records and added if missing.
3. A consultant within the business is alerted to new opportunities and works through a chat agent to review the new records, update fields (including custom fields), and add notes.

## 6. Functional Requirements

### FR-1: Create ClientCorporation Records

The MCP shall provide a tool to create a new ClientCorporation entity in Bullhorn. The tool accepts standard Bullhorn fields (name, status, phone, address, industry, etc.) and any custom fields. All mandatory Bullhorn fields that lack defaults must be provided by the caller. An owner may be provided explicitly; if omitted, the MCP resolves the authenticated user to a Bullhorn CorporateUser and auto-populates the owner. The tool returns the created record including its new Bullhorn ID.

### FR-2: Create ClientContact Records

The MCP shall provide a tool to create a new ClientContact entity in Bullhorn, linked to an existing ClientCorporation. The tool accepts standard Bullhorn fields (firstName, lastName, name, email, phone, occupation, etc.) and any custom fields. The caller must provide:

- A valid ClientCorporation ID to associate the contact with.
- An owner may be provided as either a Bullhorn user ID or a consultant name. If omitted, the MCP resolves the authenticated user to a Bullhorn CorporateUser and auto-populates the owner. If a name is provided, the MCP resolves it to a Bullhorn CorporateUser ID internally by searching the CorporateUser entity. If the name resolves to multiple users, the MCP returns all matches with disambiguation information (email and available identity fields) and does not create the record until the caller specifies which user.

Before creating, the tool checks for existing contacts with the same name at the same company. Exact, likely, or possible matches are returned for review instead of creating a duplicate unless the caller explicitly sets a force/bypass option. The tool returns the created record including its new Bullhorn ID when creation proceeds.

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

### FR-11: HTTP Transport Mode for Remote Hosting

The MCP server shall support an HTTP transport mode (`streamable-http`) in addition to the existing stdio transport, so that it can be deployed on remote infrastructure and accessed by web-based AI clients (Claude.ai, ChatGPT, etc.) via a public HTTPS endpoint.

- The active transport shall be selectable via a `MCP_TRANSPORT` environment variable (`stdio` or `http`). The default shall remain `stdio` to preserve backward compatibility for all existing local deployments.
- The HTTP listening port shall be configurable via a `PORT` environment variable (default: `8000`).
- The HTTP bind host shall default to `0.0.0.0` in HTTP mode to allow external connections.
- The server shall log the active transport and port on startup.
- `uvicorn` (required by the MCP SDK's HTTP transport) shall be listed as a project dependency.
- `.env.example` shall document the new variables.
- `README.md` shall include a Hosted Deployment section.

### FR-12: Authenticated User Identity Resolution

For hosted HTTP deployments, the MCP shall authenticate users with Microsoft Entra OIDC and resolve the authenticated user's email claim to a Bullhorn CorporateUser record. Resolved identities shall be cached per authenticated user, not globally, so a shared HTTP server can safely serve multiple consultants. Identity resolution failures shall return clear errors when an operation needs the caller identity and no explicit owner was supplied.

### FR-13: First-class JobOrder Create and Update Tools

The MCP shall provide first-class tools for creating and updating JobOrder records:

- `create_job` shall create a Bullhorn JobOrder using explicit business inputs including `clientCorporation`, `clientContact`, `title`, `source`, `grade`, `fee`, `salary`, `website_sector_range`, `website_salary_range`, and `website_location`.
- `create_job` shall default `status` to `"Accepting Candidates"`, `isOpen` to `true`, `customText12` to `0`, and owner to the authenticated Bullhorn CorporateUser when owner is omitted.
- `create_job` shall validate required relationships (`clientCorporation` and `clientContact` objects with IDs) and reject unknown structured fields before calling Bullhorn.
- `update_job` shall update an existing JobOrder using only caller-supplied fields after metadata/alias resolution.
- JobOrder aliases shall include `"published description"` and `"public description"` resolving to `publicDescription`, and `"publish on website"` resolving to `customText12`.
- `update_job` shall not strip or block the `title` field; `title` is valid on JobOrder.

### FR-14: JobSubmission (Shortlist) Create Tools

The MCP shall provide tools for shortlisting candidates to jobs by creating `JobSubmission` records in Bullhorn:

- `shortlist_candidate` shall create a `JobSubmission` linking a candidate to a job at a configured status (default: `"Shortlisted"`, overridable via `BULLHORN_SHORTLIST_STATUS` env var or per-call `status=` parameter).
- `shortlist_candidate` shall auto-stamp `sendingUser` ("Added By") from the authenticated MCP user via the identity-resolution flow; if identity resolution is unavailable (stdio mode), fall through to the API service account with a logged warning.
- `shortlist_candidate` shall query for an existing `JobSubmission` on the same `(candidate, job)` pair before creation. If one exists, it shall return the existing record with a `duplicate: true` flag and shall not create a second record.
- `shortlist_candidates` shall accept a list of candidate IDs for the same job and apply the same logic per candidate, returning a structured response with per-candidate `status: "created" | "duplicate" | "error"` and a summary count.
- Both tools shall accept an optional `fields` dict for additional `JobSubmission` fields, with labels resolved via the metadata module.
- The server shall validate `BULLHORN_SHORTLIST_STATUS` against the JobSubmission status picklist on first use and log a warning (not error) if the configured value is absent.

### FR-7 Amendment: Add Notes — Extended Entity Support

The original FR-7 covers ClientContact and ClientCorporation. The `add_note` tool has since been extended (CR20) to support seven entity types: Candidate, ClientContact, ClientCorporation, JobOrder, Placement, Lead, and Opportunity. The tool also accepts a `commenting_person_id` parameter to explicitly identify the note author (stamped as `commentingPerson`). The valid note action list is validated against the Bullhorn Note picklist on first use and cached for the session.

### FR-15: Candidate Creation and CV Parsing

The MCP shall provide tools for creating Candidate records and processing CVs:

- `create_candidate` shall create a new Candidate entity in Bullhorn with the fields supplied by the caller. Required fields are configurable per deployment via the `BULLHORN_CANDIDATE_REQUIRED` environment variable. The `source` field is auto-stamped from `BULLHORN_MCP_SOURCE` (default `"Claude"`) when the caller omits it. `name` is auto-computed from `firstName`/`lastName` — any caller-supplied `name` value is stripped and replaced. The Candidate `title` field is invalid (unlike ClientContact where it is a salutation); `occupation` is the correct field for job title.
- `find_duplicate_candidates` shall check for existing Candidates matching first/last name or email, returning matches with confidence categories.
- `parse_cv` shall accept a base64-encoded file (PDF/DOCX/TXT) and return structured candidate field suggestions extracted by Bullhorn's CV-parsing endpoint, without writing any records.
- `parse_cv_text` shall accept raw CV text (as a string) and return the same structured field suggestions.
- `create_candidate_from_cv` shall parse a CV and create a Candidate in one operation, applying the same field-injection rules as `create_candidate`.
- `attach_cv` shall attach a CV file to an existing Candidate record using a two-call commit pattern: the first call returns a preview of parsed fields with `committed: false`; the second call (with `force_all=true` or a `fields_to_update` list) writes the fields and attaches the file.

### FR-16: Note Reading and Search

The MCP shall provide read tools for Bullhorn Note records:

- `get_notes_for_entity(entity, entity_id, count, start, fields)` shall return all notes associated with a given entity record, using the Bullhorn association endpoint `GET /entity/{Entity}/{id}/notes`. Responses are wrapped in the standard pagination envelope (FR-19). Callers must use `next_start` from the pagination block (not `start + count`) because server-side isDeleted filtering of association results is not possible — the `count` in the envelope may be smaller than the page size when deleted notes are filtered client-side.
- `search_notes(query, entity_filter, count, start, fields)` shall perform full-text Lucene search over Note records using `/search/Note`. The `entity_filter` parameter optionally restricts results to notes linked to a specific entity type and ID (applied client-side as a comment substring match when entity_filter is set). The Lucene path requires the Bullhorn "Advanced Note Searching" feature to be enabled on the tenant.
- `query_entities(entity="Note")` is explicitly refused with a helpful error; callers must use `get_notes_for_entity` or `search_notes`.

### FR-17: Email Search

The MCP shall provide a `search_emails` tool that searches `UserMessage` records in Bullhorn, representing emails tracked via the Bullhorn Email Integration:

- Accepts `query` (Lucene syntax), `contact_id`, `candidate_id`, `start`, `limit`, and `fields` parameters.
- Results are sorted by `smtpReceiveDate` descending (most recent first).
- `UserMessage` is excluded from the automatic `isDeleted` filter (it has no `isDeleted` field); this is handled via the `_ENTITIES_WITHOUT_ISDELETED` denylist in the client.
- Returns the standard pagination envelope (FR-19).

### FR-18: Single-Record and Pipeline Read Tools

Every primary entity shall have a dedicated by-ID read tool, and the job submission pipeline shall be fetchable by job ID:

- `get_company(company_id, fields)` — returns a single ClientCorporation by ID. Implemented (CR25).
- `get_contact(contact_id, fields)` — returns a single ClientContact by ID, with default fields `id,firstName,lastName,name,email,phone,occupation,status,clientCorporation,owner,dateAdded`. Implemented (CR29).
- `get_job_submissions(job_id, status, limit, start, fields)` — returns all JobSubmission records for a given JobOrder, filtered by `jobOrder.id` via `query_with_meta`. The optional `status` parameter appends `AND status="<value>"` to the SQL WHERE clause. Returns the standard pagination envelope. **Planned (CR30).**

All three tools delegate to existing `BullhornClient.get()` or `BullhornClient.query_with_meta()` with no new client-layer logic.

### FR-19: Pagination Metadata Envelope

All list, search, and query tools shall return responses wrapped in a standard pagination envelope instead of a bare list:

```json
{
  "data": [ ...records... ],
  "pagination": {
    "total": 1234,
    "start": 0,
    "count": 50,
    "has_more": true,
    "next_start": 50
  }
}
```

- `has_more` is `true` when `start + count < total`, or (when `total` is null) when the returned record count equals the requested page size.
- `next_start` is the `start` value to supply on the next call to retrieve the following page; omit the call when `has_more` is `false`.
- **Exception for `get_notes_for_entity`:** because Bullhorn's association endpoint cannot filter deleted notes server-side, `count` in the envelope may be smaller than `next_start - start`. Always use `next_start` directly rather than computing `start + count` yourself.
- The nine affected tools are: `list_jobs`, `list_candidates`, `list_contacts`, `list_companies`, `search_entities`, `query_entities`, `search_emails`, `search_notes`, and `get_notes_for_entity`.

### FR-20: Candidate Record Updates via update_record

The `update_record` tool shall support `"Candidate"` as a valid entity type, in addition to the existing `"ClientContact"` and `"ClientCorporation"` support documented in FR-6. The implementation already applies the correct field-stripping and name-recomputation logic for Candidate payloads; this requirement formalises the advertised interface.

- The tool docstring shall list `"Candidate"` as a valid value for the `entity` parameter, alongside an example.
- The `title` field is stripped from Candidate payloads with a warning (Candidate has no `title` field; `occupation` is correct for job title).
- `name` is auto-recomputed from `firstName`/`lastName` on Candidate updates, consistent with the ClientContact behaviour.

### FR-21: Tearsheet (Hotlist) Management

The MCP shall provide tools for managing Tearsheet (Hotlist) records in Bullhorn. Tearsheets are named candidate lists consultants build for client briefs and passive talent pools.

- `list_tearsheets(query, limit, start, fields)` shall search and list Tearsheet records using Lucene query syntax, returning the standard pagination envelope (FR-19).
- `get_tearsheet(tearsheet_id, candidate_limit, candidate_fields)` shall return a single Tearsheet record by ID together with its candidate members, fetched via the Bullhorn association endpoint. The candidate list is wrapped in the standard pagination envelope.
- `create_tearsheet(name, description, owner)` shall create a new Tearsheet entity. If `owner` is omitted, the authenticated user is resolved automatically via the identity-resolution flow (FR-12). If identity resolution fails and no explicit owner is provided, the tool returns an `identity_resolution_failed` error and does not create the record.
- `add_to_tearsheet(tearsheet_id, candidate_ids)` shall add one or more Candidate records to a Tearsheet using the Bullhorn association `PUT` endpoint (`/entity/Tearsheet/{id}/candidates/{ids}`). Multiple candidate IDs resolve to a single API call.
- `remove_from_tearsheet(tearsheet_id, candidate_ids)` shall remove one or more Candidate records from a Tearsheet using the Bullhorn association `DELETE` endpoint. Multiple candidate IDs resolve to a single API call.
- `BullhornClient` shall gain two new methods — `add_association` and `remove_association` — for generic TO_MANY association writes (PUT) and deletes (DELETE) on any entity/association pair.
- `Tearsheet` shall be registered in `descriptions.py` (`SUPPORTED_ENTITIES` and `TOOL_ENTITY_MAP`) so the startup field-reference enrichment covers all five tearsheet tools.

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

For ClientContact write payloads, the ambiguous `title` key shall be stripped with a warning because Bullhorn uses it for salutation/name prefix rather than job title. Callers should use `occupation` for job title or `namePrefix` for salutation. This stripping must not apply to JobOrder.

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

### NFR-8: Tool Description Context Budget

The startup tool-description enrichment (the `## Field reference` block appended to each tool from Bullhorn `/meta` at startup) shall be selective rather than maximalist, so that the total tool-description payload loaded into a model's context stays small enough to be acceptable on clients that load all tools eagerly (e.g. claude.ai), including conversations that never touch Bullhorn.

- The enriched payload shall preserve the genuinely useful parts of field discovery inline: live field names, required-field flags, inlined picklist values, and configured custom fields (those whose display label differs from the API name).
- Entity-specific tools shall carry a curated, capped field set for their own entity (full detail). Generic tools that span all entities (`search_entities`, `query_entities`, `update_record`, `get_entity_fields`) shall carry only a compact field-name subset per entity plus a pointer to `get_entity_fields` for the full list.
- Full per-entity field discovery shall remain available on demand via `get_entity_fields`; trimming the startup payload must not remove any capability.
- The guidance to call `get_entity_fields` for the full field list shall also appear in the static (pre-enrichment) docstrings of the generic tools, so it survives the enrichment's graceful-fallback path.

## 8. Constraints and Exclusions

- **No record deletion or merging** — out of scope and explicitly prohibited.
- **No company reassignment** — moving a contact from one company to another is not supported due to known Bullhorn data integrity issues.
- **No bulk API** — Bullhorn does not offer a bulk create endpoint; all creates are individual PUT requests to `/entity/{EntityType}`.
- **Entity scope** — create/update capabilities are for ClientCorporation, ClientContact, and JobOrder only. Existing generic search/query tools continue to work for all entity types.
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

**US-4: Owner is assigned when creating a contact**
As a system, I want every new ClientContact to be created with an assigned owner (consultant), so that records enter Bullhorn with clear accountability.
- **Acceptance**: If the caller omits owner, the MCP resolves the authenticated user to a Bullhorn CorporateUser and creates the contact with that owner. If identity resolution fails, the tool returns a clear `identity_resolution_failed` error and does not create the contact. Providing a consultant name (e.g. "Maryrose Lyons") resolves to the correct CorporateUser ID and the contact is created with that owner.

**US-5: Owner name resolves to user ID**
As an automated agent, I want to specify a consultant by name rather than Bullhorn user ID, so that I don't need to maintain a mapping of internal IDs.
- **Acceptance**: Providing `owner: "Maryrose Lyons"` resolves to the matching CorporateUser ID. If multiple users match, the response returns all matches with email and available disambiguation fields, and the contact is not created until the caller specifies which user.

### Duplicate Detection

**US-6: Check if a company already exists**
As an automated agent, before creating a company, I want to check whether it already exists in Bullhorn using fuzzy name matching, so that I avoid creating duplicate records.
- **Acceptance**: Checking "BNY" returns "Bank of New York Mellon" as a likely match with a confidence score between 0.75 and 0.95. Checking an exact name returns an exact match with confidence > 0.95.

**US-7: Check if a contact already exists at a company**
As an automated agent, before creating a contact, I want to check whether a person with the same name already exists at the same company in Bullhorn, so that I avoid creating duplicates.
- **Acceptance**: Checking "John Smith" at ClientCorporation ID 123 returns any existing "John Smith" contacts at that company with confidence scores. If no match exists, the response indicates no matches found.

**US-7A: Direct contact creation checks for duplicates**
As an automated agent, when I create a single contact, I want duplicate detection to run before creation so that retries after transient Bullhorn errors do not create silent duplicates.
- **Acceptance**: Calling `create_contact` for a contact whose name already matches a contact at the same company returns `duplicate_found: true` with the matched record and does not create a new record. Passing `force=true` bypasses the check and creates regardless.

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

**US-15A: Ambiguous ClientContact title field does not break writes**
As a consultant or agent, when I accidentally provide `title` for a ClientContact, I want the MCP to prevent Bullhorn write failures and tell me which field to use instead.
- **Acceptance**: `create_contact` or `update_record("ClientContact", ...)` strips `title` from the write payload, proceeds with remaining fields, and returns a warning explaining to use `occupation` for job title or `namePrefix` for salutation. JobOrder `title` is not stripped.

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

### Hosted Deployment

**US-22: Run the server in HTTP mode for remote clients**
As a system administrator, I want to start the MCP server in HTTP mode by setting `MCP_TRANSPORT=http`, so that web-based AI clients (Claude.ai, ChatGPT) can connect to it over HTTPS without requiring a local process spawn.
- **Acceptance**: Setting `MCP_TRANSPORT=http` and running the server causes it to bind on the configured `PORT` (default 8000) and respond to HTTP requests from an MCP client. Setting `MCP_TRANSPORT=stdio` (or leaving it unset) behaves identically to the current behaviour. The server logs the active transport and port on startup.

**US-23: Authenticated user resolves to Bullhorn owner**
As a hosted MCP user, I want the server to map my Entra-authenticated identity to my Bullhorn CorporateUser, so that records I create can be stamped with the correct owner automatically.
- **Acceptance**: With an Entra token containing an email claim, the MCP queries CorporateUser by email and caches the result per token subject. Different users in the same HTTP server process resolve to distinct Bullhorn users.

### JobOrder Writes

**US-24: Create a JobOrder**
As a consultant or AI-assisted workflow, I want to create a Bullhorn JobOrder from user-confirmed job details, so that new roles can be set up without manual Bullhorn entry.
- **Acceptance**: Calling `create_job` with valid company/contact references, title, source, grade, fee, salary, and website fields creates a JobOrder and returns `changedEntityId`, `changeType`, and the created record.

**US-25: JobOrder creation applies safe defaults**
As a consultant, I want common JobOrder defaults to be applied when omitted, so that created jobs have the expected initial state.
- **Acceptance**: Omitting `status`, `isOpen`, `customText12`, or owner causes `create_job` to send `"Accepting Candidates"`, `true`, `0`, and the authenticated user's Bullhorn owner respectively. Caller-provided owner always wins.

**US-26: Update a JobOrder**
As a consultant or AI-assisted workflow, I want to update JobOrder fields through a dedicated tool, so that reviewed job descriptions and website settings can be written back to Bullhorn.
- **Acceptance**: Calling `update_job(job_id, {"published description": "..."})` resolves the alias to `publicDescription`, updates the JobOrder, and returns the full updated record. Updating `title` on a JobOrder succeeds without ClientContact title stripping.

### JobSubmission Writes

**US-27: Shortlist a single candidate to a job**
As a recruiter, I want to shortlist a single candidate to a job through the connector, with the submission attributed to me as the Added By, so that my activity is recorded correctly in Bullhorn.
- **Acceptance**: Calling `shortlist_candidate(job_id=10, candidate_id=20)` creates a `JobSubmission` with `status="Shortlisted"` (or the configured default), `sendingUser` set to the authenticated caller's CorporateUser, and returns `changedEntityId`, `changeType`, and the created record. A second call with the same IDs returns `duplicate: true` with the existing record and does not create a second submission.

**US-28: Shortlist multiple candidates to the same job**
As a recruiter, I want to shortlist multiple candidates to the same job in one operation, with clear per-candidate success/duplicate/error reporting, so that I can efficiently process a search result set.
- **Acceptance**: Calling `shortlist_candidates(job_id=10, candidate_ids=[20, 21, 22])` returns a response with a `results` list (one entry per candidate with `status: "created"|"duplicate"|"error"`) and a `summary` dict with counts. Identity resolution runs exactly once for the batch regardless of list size.

### Candidate Creation and CV Parsing

**US-29: Create a candidate record**
As an automated agent or recruiter, I want to create a new Candidate record in Bullhorn, so that discovered candidates are captured in the CRM with the correct owner and source attribution.
- **Acceptance**: Calling `create_candidate` with required fields returns a response containing `changedEntityId` and `changeType: "INSERT"`. The `source` field is auto-stamped when omitted. The `name` field is auto-computed from `firstName`/`lastName`. Providing `occupation` sets the job title correctly.

**US-30: Detect duplicate candidates before creation**
As an automated agent, before creating a candidate, I want to check whether they already exist in Bullhorn by name or email, so that I avoid duplicate records.
- **Acceptance**: Calling `find_duplicate_candidates` with a name or email returns matches with confidence categories (exact/likely/possible). If no match exists, returns an empty matches list.

**US-31: Parse a CV and create or attach a candidate**
As a recruiter, I want to upload or paste a CV and have the MCP extract candidate fields and optionally create or update the candidate, so that CV processing is automated.
- **Acceptance**: `parse_cv` returns a structured field suggestion object from the base64-encoded file without creating any record. `create_candidate_from_cv` parses the CV and creates the candidate in one step. `attach_cv` first returns a preview (`committed: false`) with parsed field suggestions; on second call with `force_all=true` or `fields_to_update`, the fields are written and the file attached to the existing candidate.

### Note Reading and Search

**US-32: Read all notes for an entity**
As a consultant, I want to retrieve all notes attached to a specific contact, company, candidate, or job, so that I can review recent activity without opening the Bullhorn UI.
- **Acceptance**: `get_notes_for_entity("ClientContact", 54321)` returns a paginated envelope of notes for that contact. Pagination uses `next_start` from the response. Deleted notes are excluded client-side.

**US-33: Full-text search notes**
As a consultant, I want to search notes by keyword across all entities, optionally filtered to a specific entity, so that I can find relevant context quickly.
- **Acceptance**: `search_notes(query="Twin.so", entity_filter="ClientContact:54321")` returns notes mentioning "Twin.so" linked to contact 54321. Without `entity_filter`, returns matching notes across all entities (requires Advanced Note Searching to be enabled on the Bullhorn tenant).

### Email Search

**US-34: Search tracked emails for a contact or candidate**
As a recruiter, I want to search emails tracked in Bullhorn's Email Integration for a given contact or candidate, so that I can see recent email history without leaving the chat interface.
- **Acceptance**: `search_emails(contact_id=54321)` returns tracked emails for that contact, sorted by receive date descending, wrapped in the standard pagination envelope.

### Single-Record and Pipeline Read Tools

**US-35: Get a company by ID**
As a consultant or agent, I want to retrieve a single ClientCorporation record by its Bullhorn ID, so that I can inspect a specific company's details without constructing a search query.
- **Acceptance**: `get_company(98765)` returns the ClientCorporation record with default fields. A non-existent or inaccessible ID returns an `ERROR:` string.

**US-36: Get a contact by ID**
As a consultant or agent, I want to retrieve a single ClientContact record by its Bullhorn ID, so that I can inspect a specific contact's details without constructing a search query.
- **Acceptance**: `get_contact(54321)` returns the ClientContact record with fields including id, firstName, lastName, email, phone, occupation, status, clientCorporation, owner, and dateAdded. A non-existent ID or API error returns an `ERROR:` string.

**US-37: Get a job's candidate submission pipeline**
As a recruiter, I want to retrieve all candidate submissions (pipeline) for a specific job, optionally filtered by submission status, so that I can quickly review who is shortlisted without opening the Bullhorn UI.
- **Acceptance**: `get_job_submissions(job_id=12345)` returns a paginated envelope of JobSubmission records for job 12345, each with candidate name/email, status, dateAdded, and sendingUser. `get_job_submissions(job_id=12345, status="Shortlisted")` returns only shortlisted submissions. Pagination works via `start` and `limit` parameters.

### Candidate Updates

**US-39: Update a Candidate record**
As a consultant or automated agent, I want to update fields on an existing Candidate record through the `update_record` tool, so that I can correct or enrich candidate data without opening the Bullhorn UI.
- **Acceptance**: `update_record("Candidate", 11234, {"occupation": "Head of Engineering"})` returns the full updated record. Providing `title` strips it with a warning (Candidate has no `title` field). Updating `firstName` or `lastName` recomputes and saves `name` automatically.

### Tearsheet Management

**US-40: List tearsheets**
As a consultant, I want to list tearsheets from Bullhorn with optional filtering, so that I can quickly find existing candidate lists from the chat agent.
- **Acceptance**: `list_tearsheets()` returns a paginated envelope of Tearsheet records. `list_tearsheets(query="name:CFO*")` returns only matching tearsheets.

**US-41: Get a tearsheet and its candidates**
As a consultant, I want to retrieve a single tearsheet by ID including its candidate members, so that I can review who is on a shortlist without opening the Bullhorn UI.
- **Acceptance**: `get_tearsheet(55)` returns tearsheet metadata and a `candidates` block containing `data` (candidate list) and `pagination`. The candidate list is fetched via the association endpoint.

**US-42: Create a tearsheet**
As a consultant or AI-assisted workflow, I want to create a new tearsheet in Bullhorn with a name, optional description, and owner, so that I can start building a new candidate list.
- **Acceptance**: `create_tearsheet(name="CFO Candidates 2025")` creates a Tearsheet and returns `changedEntityId` and the created record. If `owner` is omitted, the authenticated user is resolved and stamped automatically. If identity resolution fails and no owner is provided, the tool returns `identity_resolution_failed` without creating the record.

**US-43: Add candidates to a tearsheet**
As a consultant, I want to add one or more candidates to a tearsheet in a single operation, so that I can efficiently build candidate shortlists.
- **Acceptance**: `add_to_tearsheet(tearsheet_id=55, candidate_ids=[101, 102, 103])` adds all three candidates to tearsheet 55 in one API call. The response confirms the tearsheet ID, added IDs, and count.

**US-44: Remove candidates from a tearsheet**
As a consultant, I want to remove one or more candidates from a tearsheet, so that I can keep shortlists clean and relevant.
- **Acceptance**: `remove_from_tearsheet(tearsheet_id=55, candidate_ids=[101])` removes the candidate from the tearsheet. The response confirms the tearsheet ID, removed IDs, and count.

### Pagination

**US-38: Page through large result sets**
As an agent or consultant, I want all list, search, and query responses to include pagination metadata, so that I can reliably retrieve all records when results exceed the page size.
- **Acceptance**: Any list/search/query response includes `data` (the records) and `pagination` with `total`, `start`, `count`, `has_more`, and `next_start`. When `has_more` is `true`, calling again with `start=next_start` returns the next page. When `has_more` is `false`, all records have been retrieved.

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

Note: `owner` accepts either a name string (resolved internally to a CorporateUser ID) or an object `{"id": 12345}`. If omitted in direct contact/company creation, the MCP resolves the authenticated user and auto-populates owner. Bulk imports still require owner per contact unless explicitly changed by a future requirement.

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

### Create JobOrder — Request

```json
{
  "clientCorporation": {"id": 98765},
  "clientContact": {"id": 54321},
  "title": "Senior Software Engineer",
  "source": "Email",
  "grade": "Senior",
  "fee": 25000,
  "salary": 90000,
  "website_sector_range": "Technology",
  "website_salary_range": "80000-100000",
  "website_location": "London",
  "publicDescription": "Public-facing job description text",
  "description": "Internal notes from email review"
}
```

If omitted, `status` defaults to `"Accepting Candidates"`, `isOpen` defaults to `true`, `customText12` defaults to `0`, and `owner` defaults to the authenticated Bullhorn CorporateUser.

### Create JobOrder — Response

```json
{
  "changedEntityId": 12345,
  "changeType": "INSERT",
  "data": {
    "id": 12345,
    "title": "Senior Software Engineer",
    "status": "Accepting Candidates",
    "isOpen": true,
    "customText12": 0,
    "clientCorporation": {"id": 98765, "name": "Acme Holdings Ltd"},
    "clientContact": {"id": 54321, "name": "Jane Doe"},
    "owner": {"id": 12345, "firstName": "Maryrose", "lastName": "Lyons"}
  }
}
```

### Update JobOrder — Request

```json
{
  "job_id": 12345,
  "fields": {
    "published description": "Updated public-facing job description text",
    "publish on website": 0
  }
}
```

### Update JobOrder — Response

```json
{
  "changedEntityId": 12345,
  "changeType": "UPDATE",
  "data": {
    "id": 12345,
    "title": "Senior Software Engineer",
    "publicDescription": "Updated public-facing job description text",
    "customText12": 0
  }
}
```

### Pagination Envelope — Response (all list/search/query tools)

All nine list, search, and query tools wrap their results in this envelope (FR-19 / CR28):

```json
{
  "data": [ ...records... ],
  "pagination": {
    "total": 1234,
    "start": 0,
    "count": 50,
    "has_more": true,
    "next_start": 50
  }
}
```

When `has_more` is `true`, call again with `start=next_start`. When `total` is `null` (some Bullhorn endpoints omit it), `has_more` is inferred from whether `count == limit`.

### Get ClientContact — Request

```
get_contact(contact_id=54321)
get_contact(contact_id=54321, fields="id,firstName,lastName,email,occupation")
```

### Get ClientContact — Response

```json
{
  "id": 54321,
  "firstName": "Jane",
  "lastName": "Doe",
  "name": "Jane Doe",
  "email": "jane.doe@acme.com",
  "phone": "+353 1 234 5679",
  "occupation": "VP of Engineering",
  "status": "Active",
  "clientCorporation": { "id": 98765, "name": "Acme Holdings Ltd" },
  "owner": { "id": 12345, "firstName": "Maryrose", "lastName": "Lyons" },
  "dateAdded": 1710000000000
}
```

### Get Job Submissions — Request

```
get_job_submissions(job_id=12345)
get_job_submissions(job_id=12345, status="Shortlisted", limit=10, start=0)
```

### Get Job Submissions — Response

```json
{
  "data": [
    {
      "id": 88001,
      "candidate": { "id": 20, "firstName": "Alice", "lastName": "Smith", "email": "alice@example.com" },
      "status": "Shortlisted",
      "dateAdded": 1710001000000,
      "sendingUser": { "id": 12345, "name": "Maryrose Lyons" }
    }
  ],
  "pagination": {
    "total": 1,
    "start": 0,
    "count": 1,
    "has_more": false,
    "next_start": 1
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
| User lookup by name returns multiple matches (e.g. two "John Smith" consultants) | Return all matches with email and available disambiguation fields; require caller to resolve before proceeding |
| Custom field names vary between Bullhorn instances | Use meta API at runtime to resolve labels; never hardcode custom field names |
| Hosted multi-user deployments stamp records with the wrong owner | Cache resolved identities per authenticated token subject, not in a single global slot |
| JobOrder custom fields vary between Bullhorn instances | Validate structured JobOrder fields against metadata/confirmed aliases before create; reject unknown structured fields clearly |
| Note action string doesn't match a valid Bullhorn action | Return Bullhorn's error response clearly so the caller can correct the action |
| Intermittent Bullhorn API errors on entity creation | Implement retry logic for known transient errors (e.g. "error persisting an entity" which Bullhorn support acknowledges as intermittent) |
| Bullhorn association DELETE returns 204 (not 200/201) | `_request()` currently accepts only 200/201 as success. Verify the actual response code for association DELETE during integration testing; add 204 to the accepted codes in `_request()` if needed. |
| Tearsheet entity may lack `isDeleted` field | If `list_tearsheets` queries fail with a Bullhorn API error, add `"Tearsheet"` to `_ENTITIES_WITHOUT_ISDELETED` (same fix applied previously for `ClientCorporation` and `UserMessage`). |
