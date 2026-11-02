"""The document commands Wizard runs in a process of its own: convert a file to text, read how presentations look,
edit a copy of a workbook, save a copy, open an Outlook draft (wizard_documents/cli.py).

  python scripts/wizard_docs.py --help"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in ("services/agent", "services/connectors", "services/documents", "vendor"):
    sys.path.insert(0, str(ROOT / entry))

from wizard_documents.cli import main  # noqa: E402

if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
