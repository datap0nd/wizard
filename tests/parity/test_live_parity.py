"""Live source parity (Step 09-11). Never runs in ordinary CI and never passes without real evidence.

When configured on the pilot host, this compares one owner-approved ASAP report read through Wizard's Library REST client
with the owner's signed reference result (same user, same prompts, agreed precision). The reference file lives in the
approved private location; only its path is given here. Until then it is reported as BLOCKED, not passed."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

REQUIRED = ("WIZARD_PARITY_ASAP_URL", "WIZARD_PARITY_ASAP_PROJECT", "WIZARD_PARITY_ASAP_REPORT", "WIZARD_PARITY_IDENTITY_TOKEN",
            "WIZARD_PARITY_REFERENCE")
missing = [name for name in REQUIRED if not os.environ.get(name)]
pytestmark = [pytest.mark.live, pytest.mark.skipif(bool(missing), reason=f"BLOCKED: live ASAP parity not configured ({', '.join(missing)})")]


def test_asap_rows_match_signed_reference():
    from wizard_connectors.asap_library import LibraryClient
    reference = json.loads(Path(os.environ["WIZARD_PARITY_REFERENCE"]).read_text(encoding="utf-8"))
    client = LibraryClient(os.environ["WIZARD_PARITY_ASAP_URL"], os.environ["WIZARD_PARITY_ASAP_PROJECT"])
    client.login_delegated(os.environ["WIZARD_PARITY_IDENTITY_TOKEN"])
    try:
        grid = client.read_rows(os.environ["WIZARD_PARITY_ASAP_REPORT"], reference["prompt_answers"], max_rows=reference.get("max_rows", 500))
    finally:
        client.logout()
    assert grid.columns == reference["columns"]
    tolerance = float(reference.get("tolerance", 0))
    assert len(grid.rows) == len(reference["rows"])
    for got, expected in zip(grid.rows, reference["rows"], strict=True):
        for a, b in zip(got, expected, strict=True):
            assert (abs(float(a) - float(b)) <= tolerance) if isinstance(b, int | float) else a == b
