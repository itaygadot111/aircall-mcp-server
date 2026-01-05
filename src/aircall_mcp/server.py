#!/usr/bin/env python3
"""
Aircall MCP Server - Provides read access to Aircall calls, transcripts, and summaries.

Usage:
    python -m aircall_mcp.server

Environment Variables:
    AIRCALL_API_ID: Your Aircall API ID (required)
    AIRCALL_API_TOKEN: Your Aircall API token (required)
    AIRCALL_BASE_URL: API base URL (optional, default: https://api.aircall.io/v1)
"""

import sys

from mcp.server.fastmcp import FastMCP

from .client import AircallClient, AircallAPIError
from .tools import register_tools

# Initialize FastMCP server
mcp = FastMCP(
    "aircall",
    instructions="Access Aircall calls, transcripts, and summaries",
)

# Global client instance (initialized on first tool call)
_client: AircallClient | None = None


def get_client() -> AircallClient:
    """Get or create the Aircall client."""
    global _client
    if _client is None:
        _client = AircallClient()
    return _client


def main():
    """Main entry point for the MCP server."""
    try:
        # Validate credentials early
        client = get_client()

        # Register tools
        register_tools(mcp, client)

        # Run the server
        mcp.run()

    except AircallAPIError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        print("Please set AIRCALL_API_ID and AIRCALL_API_TOKEN environment variables.", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
