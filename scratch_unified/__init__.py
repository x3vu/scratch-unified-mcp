"""Unified Scratch MCP server: uukelele/scratch-mcp + scratch4js + scratchpy-studio."""
from pathlib import Path

__version__ = "1.0.0"

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM_UU = ROOT / "upstream-scratch-mcp"
UPSTREAM_JS = ROOT / "upstream-scratch4js"
UPSTREAM_SPY = ROOT / "upstream-scratchpy-studio"
NODE_SERVER = UPSTREAM_JS / "packages" / "scratch-mcp" / "src" / "index.js"
SPY_FILE = UPSTREAM_SPY / "scratchpy_studio.py"
