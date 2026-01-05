# Aircall MCP Server

An MCP (Model Context Protocol) server that provides read access to Aircall calls, transcripts, and summaries.

## Features

- **List and filter calls** - Search by date, direction, duration, and tags
- **Get call details** - Metadata, agent info, and phone number
- **Access transcripts** - Formatted with speaker labels (Agent/Customer/AI Assistant)
- **Get AI summaries** - Aircall-generated call summaries
- **Search transcripts** - Find specific content across multiple calls
- **Combined insights** - Get transcript + summary + metadata in one request

## Requirements

- **Python 3.10+** (required by MCP SDK)
- Aircall API credentials

## Installation

```bash
# Clone or create the project
cd aircall-mcp-server

# Create virtual environment (requires Python 3.10+)
python3.10 -m venv .venv
# OR if using pyenv:
# pyenv install 3.10 && pyenv local 3.10 && python -m venv .venv

source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install the package
pip install -e .

# Or install dependencies directly
pip install mcp httpx pydantic python-dotenv
```

## Configuration

Set your Aircall API credentials as environment variables:

```bash
export AIRCALL_API_ID=your_api_id
export AIRCALL_API_TOKEN=your_api_token
```

Or create a `.env` file:

```bash
cp .env.example .env
# Edit .env with your credentials
```

## Usage

### Test with MCP Inspector

```bash
npx @modelcontextprotocol/inspector python -m aircall_mcp.server
```

### Claude Desktop Configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "aircall": {
      "command": "python",
      "args": ["-m", "aircall_mcp.server"],
      "cwd": "/path/to/aircall-mcp-server",
      "env": {
        "AIRCALL_API_ID": "your_api_id",
        "AIRCALL_API_TOKEN": "your_api_token"
      }
    }
  }
}
```

### Claude Code Configuration

Add to your project's `.claude/settings.json`:

```json
{
  "mcpServers": {
    "aircall": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "aircall_mcp.server"],
      "env": {
        "AIRCALL_API_ID": "${env:AIRCALL_API_ID}",
        "AIRCALL_API_TOKEN": "${env:AIRCALL_API_TOKEN}"
      }
    }
  }
}
```

## Available Tools

### `aircall_list_calls`

List calls with filtering and pagination.

**Parameters:**
- `limit` (int): Maximum results (1-100, default: 20)
- `offset` (int): Pagination offset (default: 0)
- `direction` (str): Filter by "inbound" or "outbound"
- `from_date` (str): Start date (ISO format or Unix timestamp)
- `to_date` (str): End date (ISO format or Unix timestamp)
- `min_duration` (int): Minimum duration in seconds
- `tags` (list): Filter by tag names
- `response_format` (str): "markdown" or "json"

### `aircall_get_call`

Get detailed information about a specific call.

**Parameters:**
- `call_id` (int): The Aircall call ID
- `include_transcript` (bool): Include transcript (default: false)
- `include_summary` (bool): Include summary (default: false)
- `response_format` (str): "markdown" or "json"

### `aircall_get_transcript`

Get the formatted transcript for a call.

**Parameters:**
- `call_id` (int): The Aircall call ID
- `format` (str): "text", "structured" (with timestamps), or "raw"
- `speaker_labels` (str): "role" (Agent/Customer), "type", or "detailed"

### `aircall_search_transcripts`

Search across transcripts for specific content.

**Parameters:**
- `query` (str): Text to search for
- `call_ids` (list): Limit to specific calls (optional)
- `from_date` (str): Start date (optional)
- `to_date` (str): End date (optional)
- `limit` (int): Max calls to search (default: 10)
- `case_sensitive` (bool): Case-sensitive search (default: false)

### `aircall_get_summary`

Get the AI-generated summary for a call.

**Parameters:**
- `call_id` (int): The Aircall call ID
- `response_format` (str): "markdown" or "json"

### `aircall_get_call_insights`

Get combined metadata, transcript, and summary in one request.

**Parameters:**
- `call_id` (int): The Aircall call ID
- `response_format` (str): "markdown" or "json"

## Rate Limiting

The server implements client-side rate limiting to respect Aircall's 60 requests/minute limit. Requests are automatically queued when approaching the limit.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AIRCALL_API_ID` | Yes | - | Your Aircall API ID |
| `AIRCALL_API_TOKEN` | Yes | - | Your Aircall API token |
| `AIRCALL_BASE_URL` | No | `https://api.aircall.io/v1` | API base URL |
| `AIRCALL_RATE_LIMIT` | No | `60` | Requests per minute |
| `AIRCALL_TIMEOUT` | No | `30` | Request timeout in seconds |

## License

MIT
