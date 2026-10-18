"""Customer-scoped stdio MCP adapter. No unauthenticated HTTP port or write tools."""

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from app.core.config import get_settings
from app.core.security import identity
from app.guardrails.input import inspect_input
from app.tools.customer_tools import make_tools


def customer_subject():
    settings = get_settings()
    if settings.auth_mode == "demo" or not settings.mcp_token_file:
        raise ToolError("MCP requires local/OIDC customer authentication and MCP_TOKEN_FILE")
    try:
        path = Path(settings.mcp_token_file)
        if path.stat().st_size > 64000:
            raise ValueError()
        data = json.loads(path.read_text(encoding="utf-8"))
        token = data["access_token"]
        if not isinstance(token, str):
            raise ValueError()
        return identity(x_api_key="", x_customer_id="", authorization="Bearer " + token)
    except (HTTPException, OSError, ValueError, KeyError, TypeError):
        raise ToolError("A valid customer access token is required; log in again") from None


async def invoke(name, arguments):
    subject = customer_subject()  # Reread and validate expiry/role on every call.
    tools = {item.name: item for item in make_tools(subject)}
    try:
        return json.loads(await tools[name].ainvoke(arguments))
    except Exception:
        raise ToolError("Support tool failed; check server configuration") from None


def create_server():
    server = FastMCP(
        "SupportFlow",
        instructions="Read-only customer support tools. Proposals are not refund approval.",
    )
    annotations = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    )

    @server.tool(annotations=annotations)
    async def lookup_order(order_id: str) -> dict[str, Any]:
        """Read an order owned by the server's authenticated customer."""
        if not 1 <= len(order_id) <= 40:
            raise ToolError("Invalid order ID")
        return await invoke("lookup_order", {"order_id": order_id})

    @server.tool(annotations=annotations)
    async def find_policy(question: str) -> dict[str, Any]:
        """Retrieve official, versioned policy passages. Scores are rankings, not authorization."""
        verdict = inspect_input(question)
        if not 1 <= len(question) <= 4000 or verdict.blocked:
            raise ToolError("Use a normal policy question without embedded instructions")
        chunks = await invoke("find_policy", {"question": verdict.text})
        return {"passages": chunks}

    @server.tool(annotations=annotations)
    async def lookup_dispute(case_id: str) -> dict[str, Any]:
        """Read current case facts for the server's authenticated customer. Never executes a refund."""
        if not 1 <= len(case_id) <= 40:
            raise ToolError("Invalid case ID")
        return await invoke("lookup_dispute", {"case_id": case_id})

    return server


def main():
    # stdout belongs exclusively to the MCP transport. Diagnostics use stderr.
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
