"""Repository locations, overridable for tests and packaged installs."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("WIZARD_ROOT") or Path(__file__).resolve().parents[3])
CONTRACTS = ROOT / "contracts"
SOURCE_CONTRACTS = CONTRACTS / "sources"
FIXTURES = ROOT / "fixtures"
SYNTHETIC = FIXTURES / "synthetic"
KNOWLEDGE = ROOT / "knowledge"
