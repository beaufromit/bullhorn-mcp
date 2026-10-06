# Bullhorn CRM MCP Server

A Python [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for querying and managing Bullhorn CRM data from AI clients.

It supports both local `stdio` transport for desktop and CLI MCP clients and hosted HTTP transport for remote deployments.

**Works with:** Claude Desktop, Claude Code, Cursor, Windsurf, Cline, Continue, Zed, and other MCP-compatible clients.

This project connects directly to the Bullhorn REST API with no third-party connector layer.

## What It Does

This server exposes Bullhorn workflows as MCP tools so AI assistants and automation agents can work with CRM data directly.

Typical use cases:

- Search and review Bullhorn records from an AI client
- Create and update `ClientCorporation` and `ClientContact` records
- Create and update `JobOrder` records with explicit job-specific tools
- Detect likely duplicates before creating new companies or contacts
- Bulk-import discovered companies and contacts into Bullhorn
- Host the MCP server remotely behind authenticated HTTP transport

## Features

- Bullhorn OAuth 2.0 authentication with automatic session refresh
- Support for Bullhorn regional auth redirects
- Read tools for jobs, candidates, contacts, companies, and arbitrary entities
- Create and update workflows for `ClientCorporation`, `ClientContact`, and `JobOrder`
- Duplicate detection for companies and contacts using fuzzy matching
- Bulk import orchestration for companies and contacts
- Bullhorn metadata lookup and field label resolution
- Note creation for supported entities
- Optional hosted HTTP mode with Microsoft Entra authentication
- Session-level metadata caching
- Per-user identity resolution for hosted multi-user deployments

## MCP Tools

42 tools, grouped by family below. Each tool's full parameter and field reference is in its live MCP description (enriched from Bullhorn `/meta` at startup), which is the authoritative interface.

### Read tools

- `list_jobs`
- `list_candidates`
- `list_contacts`
- `list_companies`
- `list_placements`
- `get_job`
- `get_candidate`
- `get_company`
- `get_contact`
- `get_job_submissions`
- `search_entities`
- `query_entities`
- `search_emails`
- `get_entity_fields`

### Note tools

- `add_note`
- `get_notes_for_entity`
- `search_notes`

### Write tools

- `create_company`
- `create_contact`
- `create_job`
- `create_candidate`
- `update_record`
- `update_job`
- `bulk_import`

### CV parsing tools

- `request_cv_upload`
- `get_cv_upload`
- `show_cv_upload_box`
- `parse_cv`
- `parse_cv_text`
- `create_candidate_from_cv`
- `attach_cv`

### Shortlist tools

- `shortlist_candidate`
- `shortlist_candidates`

### Tearsheet (hotlist) tools

- `list_tearsheets`
- `get_tearsheet`
- `create_tearsheet`
- `add_to_tearsheet`
- `remove_from_tearsheet`

### Duplicate detection tools

- `find_duplicate_companies`
- `find_duplicate_contacts`
- `find_duplicate_candidates`

### External sourcing tools

- `people_search_perplexity`: read-only search of Perplexity's people index for candidates not yet in Bullhorn. It makes no Bullhorn calls and needs `PERPLEXITY_API_KEY`.

## Supported Entity Scope

The server supports generic search and query operations for Bullhorn entities, but write operations are intentionally limited.

### Supported write targets

- `ClientCorporation`
- `ClientContact`
- `JobOrder`
- `Note`

### Explicitly not supported

- Deleting records
- Merging records
- Archiving records
- Reassigning a `ClientContact` to a different company
- JobOrder duplicate detection or bulk job import
- Automatic company or client-contact creation during JobOrder creation

## Requirements

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) recommended, or `pip`
- Bullhorn API credentials:
  - `BULLHORN_CLIENT_ID`
  - `BULLHORN_CLIENT_SECRET`
  - `BULLHORN_USERNAME`
  - `BULLHORN_PASSWORD`

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/osherai/bullhorn-mcp-python.git
cd bullhorn-mcp-python
```

### 2. Install dependencies

Using `uv`:

```bash
uv venv
uv pip install -e ".[dev]"
```

Using `pip`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuration

Create a `.env` file with your Bullhorn credentials:

```env
BULLHORN_CLIENT_ID=your_client_id
BULLHORN_CLIENT_SECRET=your_client_secret
BULLHORN_USERNAME=your_api_username
BULLHORN_PASSWORD=your_api_password
```

Optional Bullhorn endpoints:

```env
BULLHORN_AUTH_URL=https://auth.bullhornstaffing.com
BULLHORN_LOGIN_URL=https://rest.bullhornstaffing.com
```

## Running the Server

### Local `stdio` mode

`stdio` is the default transport and is intended for local MCP clients such as Claude Desktop, Claude Code, Cursor, Continue, Cline, and similar tools.

Start the server with:

```bash
.venv/bin/python -m bullhorn_mcp.server
```

Or via the console script:

```bash
.venv/bin/bullhorn-mcp
```

### Hosted HTTP mode

Set the transport to HTTP:

```env
MCP_TRANSPORT=http
PORT=8000
HOST=0.0.0.0
MCP_BASE_URL=https://your-domain.example.com
```

HTTP mode requires Microsoft Entra configuration:

```env
ENTRA_TENANT_ID=your-tenant-id
ENTRA_CLIENT_ID=your-client-id
ENTRA_CLIENT_SECRET=your-client-secret
```

Then start the server normally:

```bash
.venv/bin/python -m bullhorn_mcp.server
```

The MCP endpoint will be served over HTTP and protected by Entra authentication.

#### Session Persistence

The server automatically requests the `offline_access` scope during the Entra authorization flow. This causes Entra to issue a refresh token alongside the short-lived access token, allowing the MCP client to silently renew sessions without prompting the user to sign in again.

No configuration is required — `offline_access` is handled entirely by the server.

**Default token lifetime:** Microsoft Entra access tokens have a default lifetime of 1 hour. With `offline_access` in place, sessions are renewed silently before the user notices any interruption. If users are still being prompted to re-authenticate more frequently than expected (e.g. after idle periods exceeding the token lifetime), you can extend the access token lifetime via a Token Lifetime Policy in the Entra tenant.

Token Lifetime Policies are managed via Microsoft Graph — there is no Azure Portal UI for this. Using the Microsoft.Graph PowerShell module (requires tenant admin access):

```powershell
# Create a token lifetime policy extending access tokens to 8 hours
$policy = New-MgPolicyTokenLifetimePolicy -DisplayName "MCP Extended Session" `
    -Definition @('{"TokenLifetimePolicy":{"Version":1,"AccessTokenLifetime":"08:00:00"}}') `
    -IsOrganizationDefault $false

# Assign the policy to the app's service principal (replace <service-principal-object-id>)
# Find the Object ID in Azure Portal → Enterprise applications → your app → Overview
$ref = @{ "@odata.id" = "https://graph.microsoft.com/v1.0/policies/tokenLifetimePolicies/$($policy.Id)" }
Invoke-MgGraphRequest -Method POST `
    -Uri "https://graph.microsoft.com/v1.0/servicePrincipals/<service-principal-object-id>/tokenLifetimePolicies/`$ref" `
    -Body $ref
```

See [Configure token lifetimes — Microsoft Learn](https://learn.microsoft.com/en-us/entra/identity-platform/configure-token-lifetimes) for full documentation.

### JobOrder Per-instance Configuration

Bullhorn custom field names vary between instances. Three optional environment variables allow operators to configure `create_job` for their specific setup without code changes.

| Variable | Format | Purpose |
|----------|--------|---------|
| `BULLHORN_JOBORDER_ALIASES` | JSON object | Map friendly names to API field names. Keys are lowercased. Env entries override hardcoded aliases on conflict. |
| `BULLHORN_JOBORDER_REQUIRED` | JSON array | Additional fields required beyond `title`, `clientCorporation`, `clientContact`. Entries may be aliases. |
| `BULLHORN_JOBORDER_DEFAULTS` | JSON object | Default values applied when caller omits a field. Caller values always win. |

Example (set in `.env` or environment):

```
BULLHORN_JOBORDER_ALIASES='{"sector": "customText1", "salary range": "customText10", "location": "customText11", "grade": "correlatedCustomText2", "fee": "feeArrangement"}'
BULLHORN_JOBORDER_REQUIRED='["source"]'
BULLHORN_JOBORDER_DEFAULTS='{"status": "Accepting Candidates", "isOpen": true, "customText12": 0}'
```

With these set, callers can use `"sector"`, `"salary range"`, and `"location"` as keys in `fields` and they resolve to the correct custom fields. Use `get_entity_fields("JobOrder")` to discover the API field names for your instance.

Invalid JSON in any of these variables logs a warning and falls back to the empty default. The server starts normally.

### Candidate Per-instance Configuration

Bullhorn custom field names vary between instances. Three optional environment variables allow operators to configure `create_candidate` and `create_candidate_from_cv` for their specific setup without code changes.

| Variable | Format | Purpose |
|----------|--------|---------|
| `BULLHORN_CANDIDATE_ALIASES` | JSON object | Map friendly names to API field names. Keys are lowercased. Env entries override hardcoded aliases on conflict. |
| `BULLHORN_CANDIDATE_REQUIRED` | JSON array | Additional fields required beyond `firstName` and `lastName`. Entries may be aliases. |
| `BULLHORN_CANDIDATE_DEFAULTS` | JSON object | Default values applied when caller omits a field. Caller values always win. |

Example (set in `.env` or environment):

```
BULLHORN_CANDIDATE_ALIASES='{"vertical": "customText1", "notice period": "customText2"}'
BULLHORN_CANDIDATE_REQUIRED='["source"]'
BULLHORN_CANDIDATE_DEFAULTS='{"status": "Active", "source": "Internal"}'
```

With these set, callers can use `"vertical"` and `"notice period"` as keys in `fields` and they resolve to the correct custom fields. Use `get_entity_fields("Candidate")` to discover the API field names for your instance.

Invalid JSON in any of these variables logs a warning and falls back to the empty default. The server starts normally.

### CV upload (Cowork)

CV files never travel through a tool argument. The server issues a single-use upload ticket, the file is sent to it with `curl`, and later tools refer to the file by `upload_id`. This works in hosted HTTP mode only.

**What the consultant does:** attach the CV in Cowork and ask Claude to add the candidate, or to attach the CV to an existing candidate. Nothing else.

**What Claude runs:**

1. `request_cv_upload(filename=<the CV's original name>, candidate_id=<optional>)` returns an `upload_id` and an `upload_url`. In Cowork the attachment sits at `/root/.claude/uploads/<session-uuid>/<8 hex>-<original name>`, so the model passes the original name (without the hex prefix) as `filename`.
2. `curl -sS -X POST -F file=@"<path>" <upload_url>` sends the file to the server.
3. `get_cv_upload(upload_id)` confirms the status is `received`.
4. `parse_cv(upload_id)` parses the CV once and keeps the parse with the upload. Claude checks it against the CV itself and notes corrections (names, the current employer in `companyName`, job titles with the employer merged in, dates, education, skills the CV does not mention). The HTML description is left out of the response; only its length is shown.
5. `create_candidate_from_cv(upload_id=..., <corrections>)` for a new candidate, or `attach_cv(candidate_id=..., upload_id=..., <corrections>)` for an existing one. Both use the stored parse (no second parser call) and take the same corrections: `fields_override` for Candidate fields, and `work_history`, `education`, `skills` (free-text names for `skillSet`) and `primary_skills` (Bullhorn Skill ids). A list that is passed replaces the parsed one; an omitted list uses the parse; an empty list writes none. The description always comes from the parse.

**New candidate:** `create_candidate_from_cv` writes everything in one call (the Candidate, work history, education, `skillSet`, the `primarySkills` links and the CV file) and returns exactly what was written, which Claude reports to the consultant. If any step after the create fails, the response still carries the new `candidate_id` and, when the file did not attach, a `cv_attach_retry` call.

**Existing candidate:** `attach_cv` writes additions straight away: the CV file, work history and education not already on the record, skill names not yet in `skillSet`, skills not yet linked, and fields that are empty on the record. A field that already holds a different value is not changed; it comes back in `pending_overwrites` (a description shows only both lengths). With a consultant present Claude shows these and, after a yes, calls `attach_cv` again with the same arguments and `confirm=True`, which writes exactly those overwrites and repeats nothing. Unattended callers pass `confirm=True` on the first call. The upload's parse is kept until the 30-minute purge, so the confirm call works after the first call attached the file. CR43 removed `attach_cv`'s `include_work_history`, `include_education`, `include_skills` and `force_all` parameters.

`create_candidate(fields, work_history=..., education=..., skills=..., primary_skills=...)` writes the same child records for a candidate found without a CV (LinkedIn, `people_search_perplexity`).

**Fallback:** if `curl` cannot reach the server, Claude calls `show_cv_upload_box(upload_id)`, which renders an upload box in the chat (an MCP App) when the client supports MCP Apps. The consultant picks the file there and says when it is uploaded. If the client does not support MCP Apps, Claude reports the failure and stops.

**Cowork egress setting:** set network egress to "Package managers only" and add `mcp.thepanel.com` to Additional allowed domains. This was verified sufficient on 2026-09-29.

**Limits and retention:**

- Maximum file size 10 MB (Bullhorn's attachment limit).
- Allowed types: `pdf`, `doc`, `docx`, `rtf`, `odt`, `txt`, `html`, `htm`.
- Tickets are single use and expire after 15 minutes. The token is stored only as a SHA-256 hash and is bound to the caller's Entra identity.
- The token is blanked in the server's own access log (`/upload/<redacted>`). If the reverse proxy (Caddy) has access logging turned on, it will record the full path, so keep Caddy's access log off for this site or filter `/upload/*` out of it.
- Each user can have at most 10 uploads open (pending or received) at once.
- Files are held in server memory only, never on disk. A file is deleted as soon as it is attached in Bullhorn, otherwise purged 30 minutes after upload. A server restart drops any in-flight uploads.
- The upload route never calls Bullhorn. Only the tools above do.
- CORS is allowed only for `https://*.claudemcpcontent.com` (the MCP App sandbox).

**stdio mode:** the upload tools return `uploads_require_http_mode`. Use `parse_cv_text` or `create_candidate_from_cv(content=...)` with pasted text instead.

CR41 removed the old CR27 upload endpoint, its shared secret, and the base64 file inputs on the CV tools.

---

## Hosted Authentication Model

When running in HTTP mode, the server requires Microsoft Entra authentication and resolves the authenticated caller to a Bullhorn `CorporateUser` by email.

This is used for:

- Protecting the hosted MCP endpoint
- Auto-populating record ownership when supported
- Ensuring per-user identity handling in multi-user deployments

If the authenticated user cannot be mapped to a Bullhorn `CorporateUser`, create operations that rely on implicit ownership will fail with a clear error.

## Environment Variables

| Variable                 | Required  | Description                                                               |
| ------------------------ | --------- | ------------------------------------------------------------------------- |
| `BULLHORN_CLIENT_ID`     | Yes       | Bullhorn OAuth 2.0 client ID                                              |
| `BULLHORN_CLIENT_SECRET` | Yes       | Bullhorn OAuth 2.0 client secret                                          |
| `BULLHORN_USERNAME`      | Yes       | Bullhorn API username                                                     |
| `BULLHORN_PASSWORD`      | Yes       | Bullhorn API password                                                     |
| `BULLHORN_AUTH_URL`      | No        | Auth URL, default `https://auth.bullhornstaffing.com`                     |
| `BULLHORN_LOGIN_URL`     | No        | Login URL, default `https://rest.bullhornstaffing.com`                    |
| `MCP_TRANSPORT`          | No        | Transport mode: `stdio` or `http`, default `stdio`                        |
| `PORT`                   | No        | HTTP listen port when `MCP_TRANSPORT=http`, default `8000`                |
| `HOST`                   | No        | HTTP bind host, default `0.0.0.0` in HTTP mode                            |
| `MCP_BASE_URL`           | HTTP only | Public base URL of the hosted server                                      |
| `ENTRA_TENANT_ID`        | HTTP only | Microsoft Entra tenant ID                                                 |
| `ENTRA_CLIENT_ID`        | HTTP only | Entra app registration client ID                                          |
| `ENTRA_CLIENT_SECRET`    | HTTP only | Entra app registration client secret                                      |
| `PERPLEXITY_API_KEY`     | No        | Perplexity API key, needed only by `people_search_perplexity`             |
| `BULLHORN_MATCH_LOG_DIR` | No        | Directory for the candidate match log, default `~/.local/state/bullhorn-mcp/match-log` |

## Client Configuration

This server works with any MCP-compatible client. Replace `/path/to/bullhorn-mcp-python` with your actual installation path in the examples below.

### Claude Desktop

Add to your Claude Desktop MCP config:

```json
{
  "mcpServers": {
    "bullhorn": {
      "command": "/path/to/bullhorn-mcp-python/.venv/bin/python",
      "args": ["-m", "bullhorn_mcp.server"],
      "cwd": "/path/to/bullhorn-mcp-python"
    }
  }
}
```

### Claude Code

Add the server with the CLI:

```bash
claude mcp add bullhorn \
  -e BULLHORN_CLIENT_ID=your_client_id \
  -e BULLHORN_CLIENT_SECRET=your_client_secret \
  -e BULLHORN_USERNAME=your_username \
  -e BULLHORN_PASSWORD=your_password \
  -- /path/to/bullhorn-mcp-python/.venv/bin/python -m bullhorn_mcp.server
```

### Cursor

Add to your Cursor MCP config:

```json
{
  "mcpServers": {
    "bullhorn": {
      "command": "/path/to/bullhorn-mcp-python/.venv/bin/python",
      "args": ["-m", "bullhorn_mcp.server"],
      "cwd": "/path/to/bullhorn-mcp-python"
    }
  }
}
```

## Example MCP Usage

### List recent companies

```text
list_companies()
```

### Search open job orders

```text
search_entities(entity="JobOrder", query="isOpen:1 AND title:Engineer")
```

### Create a company

```text
create_company({
  "name": "Northwind Analytics",
  "status": "Prospect",
  "phone": "+1 555 0100"
})
```

### Create a contact

```text
create_contact({
  "firstName": "Avery",
  "lastName": "Cole",
  "name": "Avery Cole",
  "email": "avery.cole@northwind.example",
  "occupation": "VP Engineering",
  "clientCorporation": {"id": 12345},
  "owner": "Jordan Patel"
})
```

### Create a job

```text
create_job(
  clientCorporation={"id": 12345},
  clientContact={"id": 67890},
  title="Senior Software Engineer",
  fields={
    "source": "Email",
    "salary": 90000,
    "publicDescription": "Public-facing job description...",
    "sector": "Technology",
    "salary range": "80000-100000",
    "location": "London"
  }
)
```

`clientCorporation`, `clientContact`, and `title` are the only Bullhorn-required fields. Everything else goes in `fields` using API names, metadata labels, or aliases configured in `BULLHORN_JOBORDER_ALIASES`. Use `get_entity_fields("JobOrder")` to discover available field names for your instance.

### Update a company

```text
update_record("ClientCorporation", 12345, {
  "status": "Active Account"
})
```

### Update a job

```text
update_job(12345, {
  "publicDescription": "Updated public-facing job description...",
  "customText12": 0
})
```

`publicDescription` is Bullhorn's published job description field. In this local Bullhorn configuration, `customText12` controls "Publish on website" and defaults to `0`, meaning not published. Existing generic `update_record` remains available for backward compatibility, but JobOrder callers should use `update_job`.

### Shortlist candidates to a job

Shortlist a single candidate:

```text
shortlist_candidate(job_id=10, candidate_id=20)
```

Shortlist multiple candidates in one call:

```text
shortlist_candidates(job_id=10, candidate_ids=[20, 21, 22])
```

Both tools:
- Auto-stamp **Added By** (`sendingUser`) to the authenticated MCP user.
- Pre-check for an existing `JobSubmission` on the same `(candidate, job)` pair. If one exists, it is returned with `duplicate: true` and no second record is created.
- Accept an optional `fields` dict for additional `JobSubmission` fields (`source`, `comments`, custom fields, etc.).

#### Shortlist Per-instance Configuration

| Env var | Purpose | Default |
|---|---|---|
| `BULLHORN_SHORTLIST_STATUS` | `JobSubmission` status used when shortlisting | `"Shortlisted"` |

The server logs a warning at startup if the configured status is not found in the JobSubmission status picklist for your instance.

```bash
BULLHORN_SHORTLIST_STATUS=Internal Review
```

### Add a note

```text
add_note("JobOrder", 12345, "General Note", "Spoke with the client about hiring plans.")
```

Notes on a job, placement or opportunity are attached to you (the logged-in consultant); pass `person_id` to attach one to a specific person instead. Bullhorn has no company-level note: add it to one of the company's contacts, or set the company's "Company Comments" field with `update_record`.

### Bulk import

```text
bulk_import(
  companies=[{"name": "Northwind Analytics", "status": "Prospect"}],
  contacts=[{
    "firstName": "Avery",
    "lastName": "Cole",
    "company_name": "Northwind Analytics",
    "email": "avery.cole@northwind.example",
    "owner": "Jordan Patel"
  }]
)
```

## Field Resolution

The server supports Bullhorn metadata lookup and can resolve user-facing labels to API field names.

Use:

```text
get_entity_fields("ClientContact")
```

to inspect available fields and labels for an entity.

## Duplicate Detection

The server provides duplicate detection before record creation:

- `find_duplicate_companies` performs fuzzy company-name matching
- `find_duplicate_contacts` checks contacts within a company

`create_contact` also performs duplicate detection unless explicitly forced.

### Candidate duplicate check

`find_duplicate_candidates` scores how likely it is that a person is already in Bullhorn. `create_candidate`, `create_candidate_from_cv`, `parse_cv` and `parse_cv_text` use the same check, so there is one answer everywhere.

Arguments: `first_name`, `last_name`, `email`, `phones`, `linkedin_url`, `current_company`, `work_history`, `education` and `upload_id`. With `upload_id`, the stored CV parse is the profile and any other argument overrides it. At least one usable signal is needed.

**Signals.** Email, phone and LinkedIn are identifiers. Each is guarded: a generic mailbox such as `info@`, an internal address, or an identifier shared by many records counts for less. Names (forename and surname, with common Irish equivalents and typos) and employers add evidence. Education is a tiebreaker only. A missing value is never evidence against a match. A value that is present and different is.

**Percentage and bands.** Each match gets a percentage and a list of reasons. High is 98 or more, low is under 20, and uncertain is anything between. Claude shows the consultant who matched, the percentage and the reasons.

**What stops a create.**

| Result | What happens |
| ------ | ------------ |
| High, or a guaranteed identifier match | The create stops with `duplicate_found`. Use `attach_cv` or `update_record` on the existing record instead. |
| Uncertain | The create stops with `possible_duplicates`, listing the candidates for the consultant to judge. |
| Low | The create goes ahead. |
| `force=True` | The check is skipped. |

Soft-deleted records that match are flagged in `deleted_matches` but never scored.

**`match_check_id` and outcomes.** Every check returns a `match_check_id`. Pass it to `create_candidate`, `create_candidate_from_cv` or `attach_cv` and the outcome is logged under it: `created_new`, `created_with_force` (only when `force=True` is passed together with a `match_check_id`) or `attached_to` the candidate id. `attach_cv` runs no check of its own.

**Tuning.** All weights and band limits live in the versioned `src/bullhorn_mcp/match_config.json`. A change to it is a reviewed change and bumps the version.

**Match log.** Each check and outcome is appended to a daily file, `match-YYYY-MM-DD.jsonl`, in `BULLHORN_MATCH_LOG_DIR` (default `~/.local/state/bullhorn-mcp/match-log`). Files older than 30 days are deleted. Identifiers and names are SHA-256 hashed, and no CV contents are written. A logging failure never breaks a tool call.

**Calibration.** `scripts/calibrate_match.py` is read-only. It prints aggregate counts only (population size, how many records hold a generic mailbox, common surname and employer totals) and no records. The totals feed the `u` values in `match_config.json`.

This is intended to reduce accidental duplicate CRM records during AI-assisted and bulk-import workflows.

## Testing

Run the full test suite:

```bash
.venv/bin/pytest
```

Run a single test file:

```bash
.venv/bin/pytest tests/test_auth.py
```

Run a single test:

```bash
.venv/bin/pytest tests/test_auth.py::TestBullhornAuth::test_full_auth_flow
```

## Project Layout

```text
src/bullhorn_mcp/
  auth.py       Bullhorn OAuth flow and REST login
  bulk.py       Bulk import orchestration
  client.py     Bullhorn REST API wrapper
  config.py     Environment-based configuration
  duplicate_retrieval.py  Candidate pool lookup for the duplicate check
  duplicates.py Candidate match scoring (weights in match_config.json)
  fuzzy.py      Duplicate matching helpers
  identity.py   Authenticated-user to CorporateUser resolution
  match_log.py  Daily match log for the duplicate check
  metadata.py   Field metadata and label resolution
  perplexity.py Perplexity people-search client (external, isolated from Bullhorn)
  server.py     MCP server entry point and tool definitions

tests/
  test_auth.py
  test_bulk.py
  test_client.py
  test_config.py
  test_fuzzy.py
  test_identity.py
  test_metadata.py
  test_perplexity.py
  test_server.py
```

## Design Notes

- Bullhorn authentication is non-standard and requires an auth-code step, token exchange, and a REST login to obtain `BhRestToken`
- The client automatically refreshes sessions and retries once on `401`
- Metadata is cached within a session
- Hosted identity resolution is cached per authenticated user
- `ClientContact.title` is intentionally stripped from write payloads to avoid confusion with `occupation`

## Limitations

- No delete or merge support
- No company reassignment for contacts
- No Bullhorn bulk-create endpoint exists, so bulk import is processed one record at a time
- Bullhorn metadata is not always reliable for required-field enforcement

## License

See [LICENSE](LICENSE).
