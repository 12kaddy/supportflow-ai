import json
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from app.api.v1 import routes
from app.core.config import get_settings
from app.core.local_tokens import issue_token
from app.mcp_server import create_server
from app.tools import customer_tools


@pytest.fixture
def mcp_server(setup, monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(
        settings, "local_auth_secret", "test-only-secret-at-least-thirty-two-characters"
    )
    token_file = tmp_path / "token.json"
    monkeypatch.setattr(settings, "mcp_token_file", str(token_file))
    token_file.write_text(
        json.dumps(
            {
                "access_token": issue_token(
                    SimpleNamespace(
                        id="alice", role="customer", email="alice@example.test", email_verified=True
                    )
                )
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(customer_tools, "SessionLocal", routes.SessionLocal)
    return create_server(), token_file


@pytest.mark.asyncio
async def test_desktop_launcher_initializes_over_stdio():
    root = Path(__file__).resolve().parents[1]
    parameters = StdioServerParameters(
        command=sys.executable, args=[str(root / "scripts/mcp_stdio.py")], cwd=str(root)
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(
            reader, writer, read_timeout_seconds=timedelta(seconds=30)
        ) as session:
            await session.initialize()
            assert len((await session.list_tools()).tools) == 3


@pytest.mark.asyncio
async def test_official_mcp_session_lists_only_read_tools_and_enforces_owner(mcp_server):
    server, _ = mcp_server
    async with create_connected_server_and_client_session(server) as session:
        listed = await session.list_tools()
        assert {tool.name for tool in listed.tools} == {
            "lookup_order",
            "find_policy",
            "lookup_dispute",
        }
        assert all(tool.annotations.readOnlyHint for tool in listed.tools)
        assert all("customer_id" not in tool.inputSchema["properties"] for tool in listed.tools)
        result = await session.call_tool("lookup_order", {"order_id": "order"})
        assert not result.isError, result.content
        assert result.structuredContent is not None, result.content
        assert result.structuredContent["id"] == "order"
        result = await session.call_tool("lookup_order", {"order_id": "not-owned"})
        assert result.structuredContent == {"error": "Order not found"}


@pytest.mark.asyncio
async def test_mcp_rereads_token_and_rejects_reviewer_or_missing_token(mcp_server, monkeypatch):
    server, token_file = mcp_server
    async with create_connected_server_and_client_session(server) as session:
        token_file.write_text(
            json.dumps(
                {
                    "access_token": issue_token(
                        SimpleNamespace(
                            id="reviewer",
                            role="admin",
                            email="admin@example.test",
                            email_verified=True,
                        )
                    )
                }
            ),
            encoding="utf-8",
        )
        assert (await session.call_tool("lookup_order", {"order_id": "order"})).isError
        token_file.unlink()
        assert (await session.call_tool("find_policy", {"question": "refund policy"})).isError
        monkeypatch.setattr(get_settings(), "auth_mode", "demo")
        assert (await session.call_tool("lookup_order", {"order_id": "order"})).isError
