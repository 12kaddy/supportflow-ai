# Customer MCP server

The official Python MCP SDK exposes three **read-only** tools: `lookup_order`,
`find_policy`, and `lookup_dispute`. They reuse the existing customer-bound tools
and database ownership checks. Case creation, review and execution are not exposed.
The transport is stdio; no unauthenticated MCP HTTP port is opened.

```powershell
pip install -e '.[dev,mcp]'
python -m scripts.mcp_login --email YOUR_CUSTOMER_EMAIL
$env:MCP_TOKEN_FILE = (Join-Path (Get-Location).Path '.local/mcp-token.json')
npx --yes @modelcontextprotocol/inspector@2.5.0 --cli .venv\Scripts\python.exe scripts/mcp_stdio.py --method tools/list --format json
npx --yes @modelcontextprotocol/inspector@2.5.0 --cli .venv\Scripts\python.exe scripts/mcp_stdio.py --method tools/call --tool-name lookup_order --tool-arg order_id=YOUR_OWN_ORDER_ID --format json
```

The login helper needs the local-mode API running, prompts privately for the
password, and saves only a short-lived customer token/lifetime. OIDC users can
use `scripts.login` instead. Every tool call rereads the token file and verifies
signature, expiry and customer role. Refresh it after expiry. Demo auth and
admin-only/reviewer-only tokens are rejected. Customer identity is not a tool
argument. The token inherits the existing stateless session-revocation limits.

Node 22.19+ is required for the tested Inspector. Omitting `--cli` and method flags
opens its web interface. Do not commit tokens or put them into screenshots/URLs.
Policy questions receive the common input attack/PII checks; returned scores are
rankings, not authorization. Model/retrieval initialization can slow the first
policy call. Stdout is protocol-only; diagnostics use stderr.

Desktop client entry (merge into existing configuration, substituting paths):

```json
{
  "mcpServers": {
    "supportflow": {
      "command": "C:/ABSOLUTE/PROJECT/.venv/Scripts/python.exe",
      "args": ["C:/ABSOLUTE/PROJECT/scripts/mcp_stdio.py"],
      "env": {"MCP_TOKEN_FILE": "C:/ABSOLUTE/PROJECT/.local/mcp-token.json"}
    }
  }
}
```

The launcher selects the repository working directory before loading `.env`.
The desktop configuration contains the private file's path, never its token.
Tools have typed structured results and read-only/idempotent annotations; backend
checks, not annotations, enforce access. Other MCP clients control their own model
prose; SupportFlow's output guard does not rewrite an external client's responses.

Validation: `pytest tests/test_mcp.py -q` covers official SDK sessions, actual stdio
startup, roles, ownership and token-file refresh/removal. Inspector 2.5.0 listed all
three tools. A real Inspector call with a synthetic customer token was denied
access to `ORD-1001`. The SDK is pinned to its maintained FastMCP 1.x API
(`>=1.28,<2`); Inspector 2 compatibility was tested. SDK 2.x migration is separate.

The application agent still uses direct tools. Optional MCP tool consumption via
`langchain-mcp-adapters` was not added. References: [Python SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x),
[Inspector](https://github.com/modelcontextprotocol/inspector).
