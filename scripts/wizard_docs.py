"""Wizard documentation kit: convert documents and Outlook mail to text, track progress, check and read expert quizzes.

  python scripts/wizard_docs.py --help

On a work-PC install, run it with the install's portable Python (the Gemini CLI tasks show the exact command):
  $c = Get-Content current.json -Raw | ConvertFrom-Json
  & $c.python (Join-Path $c.release 'scripts\\wizard_docs.py') status content"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in ("services/connectors", "services/documents", "vendor"):
    sys.path.insert(0, str(ROOT / entry))

from wizard_documents.cli import main  # noqa: E402

if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
