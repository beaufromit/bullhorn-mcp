# Bullhorn CRM MCP Server

A Python [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that enables AI assistants to query your Bullhorn CRM data using natural language.

**Works with:** Claude Desktop, Claude Code, Cursor, Windsurf, Cline, Continue, Zed, and any MCP-compatible client.

This is an open-source alternative to paid connectors - it connects directly to Bullhorn's REST API with no additional subscriptions required.

> **Brought to you by [Osher Digital](https://osher.com.au)** - Specialist AI consultants helping businesses harness the power of artificial intelligence.

## Features

- **Direct API Access** - Connects to Bullhorn's REST API using OAuth 2.0
- **Natural Language Queries** - Ask questions like "Show me the last 10 open jobs"
- **6 Powerful Tools**:
  - `list_jobs` - List and filter job orders
  - `list_candidates` - List and filter candidates
  - `get_job` - Get detailed job information by ID
  - `get_candidate` - Get detailed candidate information by ID
  - `search_entities` - Search any Bullhorn entity with Lucene queries
  - `query_entities` - Query entities with SQL-like WHERE syntax
- **Automatic Token Management** - Handles OAuth token refresh automatically
- **Read-Only Access** - Safe to use, no risk of modifying your CRM data

## Prerequisites

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- Bullhorn CRM account with API access
- Bullhorn API credentials (Client ID, Client Secret, Username, Password)

## Getting Your Bullhorn API Credentials

You'll need four credentials from Bullhorn:

1. **Client ID** and **Client Secret** - OAuth application credentials
2. **API Username** and **API Password** - Service account for API access

To obtain these:

1. Contact your Bullhorn administrator or account manager
2. Request API access for your account
3. They will provide you with OAuth client credentials
4. Create or use an existing service account for API authentication

> **Note**: Your API username/password may be different from your regular Bullhorn login credentials.

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/osherai/bullhorn-mcp-python.git
cd bullhorn-mcp-python
```

### 2. Install Dependencies

Using uv (recommended):

```bash
uv venv && uv pip install -e .
```

Or using pip:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e .
```

### 3. Configure Credentials

Copy the example environment file and add your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your Bullhorn API credentials:

```env
BULLHORN_CLIENT_ID=your_client_id
BULLHORN_CLIENT_SECRET=your_client_secret
BULLHORN_USERNAME=your_api_username
BULLHORN_PASSWORD=your_api_password
```

### 4. Test the Connection

```bash
.venv/bin/python -c "
from bullhorn_mcp.config import BullhornConfig
from bullhorn_mcp.auth import BullhornAuth
from bullhorn_mcp.client import BullhornClient

config = BullhornConfig.from_env()
auth = BullhornAuth(config)
client = BullhornClient(auth)

jobs = client.search('JobOrder', 'isDeleted:0', count=3)
print(f'Successfully connected! Found {len(jobs)} jobs.')
"
```

## Client Configuration

This MCP server works with any MCP-compatible client. Below are setup instructions for popular clients.

> **Note**: Replace `/path/to/bullhorn-mcp-python` with your actual installation path in all examples below.

---

### Claude Desktop

Add to your Claude Desktop configuration file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

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

Restart Claude Desktop (fully quit and reopen) for changes to take effect.

---

### Claude Code (CLI)

Add the server using the Claude Code CLI:

```bash
claude mcp add bullhorn \
  -e BULLHORN_CLIENT_ID=your_client_id \
  -e BULLHORN_CLIENT_SECRET=your_client_secret \
  -e BULLHORN_USERNAME=your_username \
  -e BULLHORN_PASSWORD=your_password \
  -- /path/to/bullhorn-mcp-python/.venv/bin/python -m bullhorn_mcp.server
```

Or add to your `~/.claude/settings.json`:

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

---

### Cursor

Add to your Cursor MCP configuration:

**macOS**: `~/.cursor/mcp.json`
**Windows**: `%USERPROFILE%\.cursor\mcp.json`

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

Restart Cursor for changes to take effect.

---

### Windsurf (Codeium)

Add to your Windsurf MCP configuration:

**macOS**: `~/.codeium/windsurf/mcp_config.json`
**Windows**: `%USERPROFILE%\.codeium\windsurf\mcp_config.json`

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

Restart Windsurf for changes to take effect.

---

### VS Code with Cline Extension

Add to your Cline MCP settings:

**macOS**: `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`
**Windows**: `%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json`

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

---

### VS Code with Continue Extension

Add to your Continue configuration at `~/.continue/config.json`:

```json
{
  "experimental": {
    "modelContextProtocolServers": [
      {
        "transport": {
          "type": "stdio",
          "command": "/path/to/bullhorn-mcp-python/.venv/bin/python",
          "args": ["-m", "bullhorn_mcp.server"],
          "cwd": "/path/to/bullhorn-mcp-python"
        }
      }
    ]
  }
}
```

---

### Zed Editor

Add to your Zed settings at `~/.config/zed/settings.json`:

```json
{
  "context_servers": {
    "bullhorn": {
      "command": {
        "path": "/path/to/bullhorn-mcp-python/.venv/bin/python",
        "args": ["-m", "bullhorn_mcp.server"]
      },
      "settings": {}
    }
  }
}
```

---

### Example Queries

Once configured, you can ask natural language questions about your Bullhorn data:

- "List the last 10 open jobs"
- "Find candidates with Python experience"
- "Show me details for job #12345"
- "Search for active candidates added this month"
- "What placements were made last week?"

## Tools Reference

### list_jobs

List and filter job orders from Bullhorn CRM.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | No | Lucene search query |
| `status` | string | No | Filter by job status |
| `limit` | integer | No | Max results (default: 20, max: 500) |
| `fields` | string | No | Comma-separated fields to return |

**Examples:**
```
list_jobs()                                    # Recent jobs
list_jobs(query="isOpen:1")                   # Open jobs only
list_jobs(query="title:Engineer", limit=10)  # Engineer jobs
list_jobs(status="Accepting Candidates")      # By status
```

### list_candidates

List and filter candidates from Bullhorn CRM.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | No | Lucene search query |
| `status` | string | No | Filter by candidate status |
| `limit` | integer | No | Max results (default: 20, max: 500) |
| `fields` | string | No | Comma-separated fields to return |

**Examples:**
```
list_candidates()                              # Recent candidates
list_candidates(query="skillSet:Python")      # Python developers
list_candidates(status="Active", limit=50)    # Active candidates
```

### get_job

Get detailed information for a specific job order.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `job_id` | integer | Yes | The JobOrder ID |
| `fields` | string | No | Comma-separated fields to return |

### get_candidate

Get detailed information for a specific candidate.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `candidate_id` | integer | Yes | The Candidate ID |
| `fields` | string | No | Comma-separated fields to return |

### search_entities

Search any Bullhorn entity type using Lucene query syntax.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `entity` | string | Yes | Entity type (JobOrder, Candidate, Placement, etc.) |
| `query` | string | Yes | Lucene search query |
| `limit` | integer | No | Max results (default: 20, max: 500) |
| `fields` | string | No | Comma-separated fields to return |

**Supported Entities:**
- `JobOrder` - Job postings
- `Candidate` - Candidates/applicants
- `Placement` - Job placements
- `ClientCorporation` - Client companies
- `ClientContact` - Client contacts
- `JobSubmission` - Candidate submissions to jobs
- `Appointment` - Scheduled appointments
- `Note` - Notes and comments
- And many more...

### query_entities

Query Bullhorn entities using SQL-like WHERE syntax.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `entity` | string | Yes | Entity type |
| `where` | string | Yes | WHERE clause |
| `limit` | integer | No | Max results (default: 20, max: 500) |
| `fields` | string | No | Comma-separated fields to return |
| `order_by` | string | No | Sort order (e.g., "-dateAdded") |

**Examples:**
```
query_entities(entity="JobOrder", where="salary > 100000")
query_entities(entity="Candidate", where="status='Active'", order_by="-dateAdded")
```

## Query Syntax

### Lucene Search Syntax

Used by `list_jobs`, `list_candidates`, and `search_entities`:

```
title:Engineer                           # Field contains value
isOpen:1                                 # Boolean/numeric field
salary:[50000 TO 100000]                # Range query
firstName:"John"                         # Exact phrase
firstName:John AND lastName:Smith       # AND condition
status:Active OR status:Available       # OR condition
NOT status:Inactive                      # Negation
name:Acme*                              # Wildcard
```

### SQL-like WHERE Syntax

Used by `query_entities`:

```
salary > 100000                          # Comparison
status = 'Active'                        # Equality (use single quotes)
dateAdded > '2024-01-01'                # Date comparison
id IN (1, 2, 3, 4, 5)                   # IN clause
firstName = 'John' AND salary > 50000   # AND condition
```

> **Note**: The LIKE operator is not supported in Bullhorn's query endpoint.

## Default Fields

When `fields` is not specified, the following fields are returned:

**JobOrder:**
`id, title, status, employmentType, dateAdded, startDate, salary, clientCorporation, owner, description, numOpenings, isOpen`

**Candidate:**
`id, firstName, lastName, email, phone, status, dateAdded, occupation, skillSet, owner`

## Hosted Deployment

The server supports an HTTP transport mode for hosting on remote infrastructure (Proxmox, Azure, a VPS, etc.) and exposing via a reverse proxy or Cloudflare Tunnel so that web-based AI clients (Claude.ai, ChatGPT) can connect to it.

### 1. Set environment variables

```env
MCP_TRANSPORT=http
PORT=8000
```

Add your Bullhorn credentials to `.env` as normal.

### 2. Start the server

```bash
.venv/bin/python -m bullhorn_mcp.server
```

You should see a log line confirming HTTP mode and the bound port:

```
INFO  Starting Bullhorn MCP server in HTTP mode on 0.0.0.0:8000
```

The server binds on `0.0.0.0` by default in HTTP mode so it is reachable from outside the host.

### 3. Expose via reverse proxy or tunnel

Point a Cloudflare Tunnel (or nginx/caddy) at `http://localhost:8000` and expose it over HTTPS at a public domain, e.g. `https://bullhorn-mcp.example.com`.

### 4. Connect your AI client

In Claude.ai or ChatGPT, add a new MCP connector and set the server URL to:

```
https://bullhorn-mcp.example.com/mcp
```

> **Note:** Local clients (Claude Desktop, Claude Code, Cursor, etc.) continue to work without any changes — the default transport remains `stdio`.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BULLHORN_CLIENT_ID` | Yes | OAuth 2.0 Client ID |
| `BULLHORN_CLIENT_SECRET` | Yes | OAuth 2.0 Client Secret |
| `BULLHORN_USERNAME` | Yes | API Username |
| `BULLHORN_PASSWORD` | Yes | API Password |
| `BULLHORN_AUTH_URL` | No | Auth URL (default: https://auth.bullhornstaffing.com) |
| `BULLHORN_LOGIN_URL` | No | Login URL (default: https://rest.bullhornstaffing.com) |
| `MCP_TRANSPORT` | No | Transport mode: `stdio` (default) or `http` |
| `PORT` | No | HTTP listen port when `MCP_TRANSPORT=http` (default: 8000) |

## Project Structure

```
bullhorn-mcp-python/
├── pyproject.toml              # Project configuration and dependencies
├── .env.example                # Environment variables template
├── README.md                   # This file
├── LICENSE                     # MIT License
└── src/
    └── bullhorn_mcp/
        ├── __init__.py         # Package initialization
        ├── server.py           # MCP server with tool definitions
        ├── auth.py             # Bullhorn OAuth 2.0 authentication
        ├── client.py           # Bullhorn REST API client
        └── config.py           # Configuration management
```

## Troubleshooting

### "Missing required environment variables"

Ensure all required variables are set in your `.env` file or environment.

### Authentication Errors

1. Verify your credentials are correct
2. Check that your API user has appropriate permissions
3. Ensure your Bullhorn account has API access enabled

### "Connection refused" or timeout errors

1. Check your internet connection
2. Verify the auth/login URLs are correct for your Bullhorn datacenter
3. Some Bullhorn instances use regional URLs (e.g., `rest9.bullhornstaffing.com`)

### MCP server not appearing in your client

1. Ensure the config file path is correct for your client (see Client Configuration section)
2. Verify the Python path in the config points to the `.venv` directory
3. Fully quit and restart your client application
4. Check your client's logs for error messages
5. Test the server manually:
   ```bash
   cd /path/to/bullhorn-mcp-python
   .venv/bin/python -m bullhorn_mcp.server
   ```
   The server should start without errors (it will wait for input on stdin)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [Bullhorn](https://www.bullhorn.com/) for their REST API
- [Model Context Protocol](https://modelcontextprotocol.io/) for the MCP specification
- [Anthropic](https://www.anthropic.com/) for Claude and the MCP Python SDK
- The teams behind [Cursor](https://cursor.sh/), [Windsurf](https://codeium.com/windsurf), [Cline](https://github.com/saoudrizwan/claude-dev), [Continue](https://continue.dev/), and [Zed](https://zed.dev/) for MCP support

---

## About Osher Digital

This project is maintained by [Osher Digital](https://osher.com.au), specialist AI consultants based in Australia. We help businesses integrate AI solutions to streamline operations and drive growth.

**Need help with AI integration?** [Get in touch](https://osher.com.au)

## Disclaimer

This is an unofficial, community-maintained project. It is not affiliated with, officially maintained, or endorsed by Bullhorn.
