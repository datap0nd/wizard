"""Draft ASAP report documentation from ASAP's own metadata (Step 03/14), instead of writing ~50 entries by hand.

Walks Library folders from one or more root folder ids, reads each report's definition (attributes, metrics, prompts)
and writes a DRAFT source contract to artifacts/catalog-drafts/asap.draft.json. Every report is NAVIGATION_ONLY with
aggregation "none" and an empty business description: a person (the report owner) must review grain, units, aggregation
rules, caveats and descriptions, then merge approved entries into contracts/sources/. Drafts are never loaded by Wizard.

Metadata only: no report is executed and no rows are read.
  uv run python scripts/import_asap_catalog.py --url https://asap.corp/MicroStrategyLibrary --project <id> \
      --folder <root folder id> [--folder ...]      # identity token from WIZARD_ASAP_IDENTITY_TOKEN
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "connectors"))

from wizard_connectors.asap_library import AsapError, LibraryClient  # noqa: E402

FOLDER, REPORT, DOCUMENT = 8, 3, 55  # MicroStrategy object types


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")[:60] or "field"


def draft_report(client: LibraryClient, item: dict[str, Any], folder_id: str) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": f"asap-{item['id'].lower()[:32]}", "name": item["name"], "folder": folder_id,
        "type": "dossier" if item.get("type") == DOCUMENT else "report", "row_access": "NAVIGATION_ONLY", "file": None,
        "description": "", "grain": [], "as_of": None, "refresh": "Unknown", "dimensions": [], "measures": [],
        "attributes": [], "prompts": [],
        "caveats": [f"DRAFT imported from ASAP metadata (object {item['id']}): review before approval."],
        "sensitivity": "internal",
    }
    if item.get("type") != REPORT:
        return entry
    try:
        definition = client.report_definition(item["id"])
    except AsapError as error:
        entry["caveats"].append(f"Definition not readable for this account: {error.code}.")
        return entry
    grid = definition.get("definition", {}).get("grid", {})
    available = definition.get("definition", {}).get("availableObjects", {})
    attributes = available.get("attributes") or grid.get("rows", [])
    metrics = available.get("metrics") or [m for c in grid.get("columns", []) for m in c.get("elements", [])]
    entry["dimensions"] = [{"key": slug(a.get("name", "")), "label": a.get("name", ""), "type": "string"} for a in attributes]
    entry["measures"] = [{"key": slug(m.get("name", "")), "label": m.get("name", ""), "type": "number", "aggregation": "none"}
                         for m in metrics]
    entry["prompts"] = [{"key": slug(p.get("name", p.get("key", ""))), "label": p.get("name", ""), "multi": True}
                        for p in definition.get("prompts", []) or []]
    entry["description"] = definition.get("description", "") or ""
    return entry


def walk(client: LibraryClient, folder_id: str, name: str, parent: str | None, folders: list, reports: list, depth: int = 0) -> None:
    if depth > 8:
        return
    folders.append({"id": f"asap-f-{folder_id.lower()[:24]}", "name": name, "parent": parent})
    for item in client.folder(folder_id):
        if item.get("type") == FOLDER:
            walk(client, item["id"], item["name"], f"asap-f-{folder_id.lower()[:24]}", folders, reports, depth + 1)
        elif item.get("type") in (REPORT, DOCUMENT):
            reports.append(draft_report(client, item, f"asap-f-{folder_id.lower()[:24]}"))


def build(client: LibraryClient, roots: list[tuple[str, str]]) -> dict[str, Any]:
    folders: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    for folder_id, name in roots:
        walk(client, folder_id, name, None, folders, reports)
    return {"contract_version": 1,
            "system": {"id": "asap", "name": "ASAP", "description": "DRAFT imported catalog", "families": [],
                       "owner": "TBD", "connector": {"status": "NAVIGATION_ONLY", "data_mode": "LIVE_VERIFIED",
                                                     "transport": "library-rest", "live_interface": "MicroStrategy Library REST"},
                       "open_url_template": None},
            "folders": folders, "reports": reports}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--folder", action="append", required=True, help="root folder id (repeatable)")
    args = parser.parse_args()
    token = os.environ.get("WIZARD_ASAP_IDENTITY_TOKEN", "")
    if not token:
        print("Set WIZARD_ASAP_IDENTITY_TOKEN from the approved SSO/trusted-auth route.", file=sys.stderr)
        return 2
    client = LibraryClient(args.url, args.project)
    client.login_delegated(token)
    try:
        draft = build(client, [(f, f"Root {f}") for f in args.folder])
    finally:
        client.logout()
    out = ROOT / "artifacts" / "catalog-drafts" / "asap.draft.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"Drafted {len(draft['reports'])} reports in {len(draft['folders'])} folders → {out.relative_to(ROOT)} (review before merging).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
