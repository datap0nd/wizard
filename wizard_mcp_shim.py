"""Launcher for the Wizard MCP stdio shim, started by Gemini CLI for each MCP server (asap, gscm, nerp, wizard).

Runs on the portable embeddable Python too, whose ._pth file ignores PYTHONPATH and the working directory: the paths
are added here from this file's location."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for entry in ("services/connectors", "vendor"):
    sys.path.insert(0, str(ROOT / entry))

from wizard_connectors.mcp_shim import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
