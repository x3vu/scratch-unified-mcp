"""Unified Scratch MCP server app.

Merges three upstreams into one stdio MCP server:
  social_*, project_*  - vendored uukelele/scratch-mcp (scratchattach+goboscript)
  spy_*                - ScratchPy Studio headless core (blocks <-> real Python)
  sb3_*, sb3_git_*     - scratch4js Node sidecar proxy (lazy, degrades gracefully)

Import order matters: vendor_uu/server.py owns the single FastMCP app object
(vendored modules do `from .server import mcp`). This module re-exports it,
registers the extra tool families, and serves.
"""
from .vendor_uu.server import mcp

__all__ = ["mcp", "main"]

from .vendor_uu import projects, social  # noqa: F401 (register social_*/project_*)
from . import sb3_extra  # noqa: F401 (register sb3_git_*/cloud/studio tools)
from .node_bridge import register_sb3_tools
from .spy_tools import register_spy_tools

register_sb3_tools(mcp)
register_spy_tools(mcp)


def main(argv=None):
    """Restore persisted Scratch sessions and serve over stdio."""
    from .vendor_uu import utils

    utils._restore()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
