"""Absolute-path launcher for desktop MCP clients with an arbitrary working directory."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.mcp_server import main  # noqa: E402

if __name__ == "__main__":
    main()
