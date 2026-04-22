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
- Detect likely duplicates before creating new companies or contacts
- Bulk-import discovered companies and contacts into Bullhorn
- Host the MCP server remotely behind authenticated HTTP transport

## Features

- Bullhorn OAuth 2.0 authentication with automatic session refresh
- Support for Bullhorn regional auth redirects
- Read tools for jobs, candidates, contacts, companies, and arbitrary entities
- Create and update workflows for `ClientCorporation` and `ClientContact`
- Duplicate detection for companies and contacts using fuzzy matching
- Bulk import orchestration for companies and contacts
- Bullhorn metadata lookup and field label resolution
- Note creation for supported entities
- Optional hosted HTTP mode with Microsoft Entra authentication
- Session-level metadata caching
- Per-user identity resolution for hosted multi-user deployments

## MCP Tools

### Read tools

- `list_jobs`
- `list_candidates`
- `list_contacts`
- `list_companies`
- `get_job`
- `get_candidate`
- `search_entities`
- `query_entities`
- `get_entity_fields`

### Write tools

- `create_company`
- `create_contact`
- `update_record`
- `add_note`
- `bulk_import`

### Duplicate detection tools

- `find_duplicate_companies`
- `find_duplicate_contacts`

## Supported Entity Scope

The server supports generic search and query operations for Bullhorn entities, but write operations are intentionally limited.

### Supported write targets

- `ClientCorporation`
- `ClientContact`
- `Note`

### Explicitly not supported

- Deleting records
- Merging records
- Archiving records
- Reassigning a `ClientContact` to a different company

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

### Update a company

```text
update_record("ClientCorporation", 12345, {
  "status": "Active Account"
})
```

### Add a note

```text
add_note("ClientCorporation", 12345, "General Note", "Spoke with the client about hiring plans.")
```

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
  fuzzy.py      Duplicate matching helpers
  identity.py   Authenticated-user to CorporateUser resolution
  metadata.py   Field metadata and label resolution
  server.py     MCP server entry point and tool definitions

tests/
  test_auth.py
  test_bulk.py
  test_client.py
  test_config.py
  test_fuzzy.py
  test_identity.py
  test_metadata.py
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
