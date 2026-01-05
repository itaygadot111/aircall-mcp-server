"""
Vercel serverless function for Aircall MCP Server.

This exposes the MCP server via HTTP using Streamable HTTP transport.
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from src.aircall_mcp.client import AircallClient
from src.aircall_mcp.tools import register_tools

# Configure transport security for Vercel deployment
# Allow requests from the Vercel domain
transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[
        "aircall-mcp-server.vercel.app",
        "localhost:3000",
        "localhost:*",
    ],
    allowed_origins=[
        "https://aircall-mcp-server.vercel.app",
        "http://localhost:3000",
        "http://localhost:*",
    ],
)

# Initialize FastMCP server
mcp = FastMCP(
    "aircall",
    instructions="Access Aircall calls, transcripts, and summaries",
    transport_security=transport_security,
)

# Global client instance
_client: AircallClient | None = None


def get_client() -> AircallClient:
    """Get or create the Aircall client."""
    global _client
    if _client is None:
        _client = AircallClient()
    return _client


# Register tools on module load
try:
    client = get_client()
    register_tools(mcp, client)
except Exception as e:
    # Log error but don't crash - credentials might not be set during build
    print(f"Warning: Could not initialize Aircall client: {e}")

# Create the Starlette ASGI app for Vercel
# streamable_http_app() returns a Starlette app that handles MCP over HTTP
app = mcp.streamable_http_app()
