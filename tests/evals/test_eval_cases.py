"""The evaluation set is well formed and covers the demos, paraphrases, follow-ups, adversarial and out-of-scope cases.
Running the cases against a model is scripts/run_evals.py (needs a live runtime); this test needs no model."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_cases_are_well_formed():
    data = json.loads((ROOT / "tests" / "evals" / "cases.json").read_text(encoding="utf-8"))
    cases = data["cases"]
    identities = {u["id"] for u in json.loads((ROOT / "fixtures" / "identities.json").read_text(encoding="utf-8"))["users"]}
    assert len(cases) == 30 and len({c["id"] for c in cases}) == 30
    assert all(c["identity"] in identities for c in cases)
    assert all(set(c["expect"]) == {"cites_evidence", "mentions", "must_not_claim", "sources"} for c in cases)
    kinds = Counter(c["kind"] for c in cases)
    assert kinds["demo"] == 3 and kinds["paraphrase"] >= 7 and kinds["follow-up"] >= 3
    assert sum(kinds[k] for k in ("prompt-injection", "tool-abuse", "cross-user", "entitlement")) >= 5
    goldens = {p.stem for p in (ROOT / "fixtures" / "goldens").glob("*.json")}
    assert len(goldens) == 3
    stories = {c["story"] for c in cases if c["kind"] == "demo"}
    assert stories == {"Executive", "Planner", "Conquest"}
