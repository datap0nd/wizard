"""The document commands Wizard runs in a process of its own (scripts/wizard_docs.py, which sets up the paths), one at a
time and time-limited, so a stuck Office dialog cannot hang the server. Each prints one JSON line per result.

  convert <file> --out <folder> --json [--tables]   one document -> <folder>/text.md (+ assets/, attachments/,
                                                    tables/): attached files (attachments.py), task files (tasks.py)
  design <deck> [<deck> ...]                        how presentations look (theme, fonts, layouts): wizard_task_design
  edit <workbook> --operations <ops.json> --out <copy>   wizard_edit_attachment's edited copy
  save-copy <workbook> --out <file>                 Download on the person's own PC, written by Excel
  outlook-draft <draft.json>                        the Email button: an unsent Outlook message ({"subject", "html"})
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .common import ConversionError, mask_contacts
from .convert import Converter
from .office import OfficeSession, OfficeUnavailable, open_draft
from .tables import write as write_tables


def cmd_convert(args: argparse.Namespace) -> int:
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    result: dict[str, object]
    try:
        with Converter(args.office, args.slide_images, tables=args.tables) as converter:
            converted = converter.convert(args.file, out / "assets", out / "attachments")
        tables = write_tables(converted.tables, out) if converted.tables else []
        text = mask_contacts(converted.text)
        (out / "text.md").write_text(text + "\n", encoding="utf-8")
        result = {"status": "ok" if text.strip() or converted.images else "empty", "method": converted.method,
                  "chars": len(text), "images": [p.name for p in converted.images],
                  "attachments": [p.name for p in converted.attachments], "notes": converted.notes,
                  "parts": converted.parts[:200],
                  "tables": [{"sheet": t["sheet"], "rows": t["rows"], "columns": len(t["columns"])} for t in tables]}
    except (ConversionError, OSError) as error:
        result = {"status": "failed", "note": str(error)[:400]}
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"{result['status']}: " + (f"{result.get('chars')} characters via {result.get('method')}"
                                         if result["status"] != "failed" else str(result.get("note"))))
    return 0 if result["status"] != "failed" else 1


def cmd_design(args: argparse.Namespace) -> int:
    """How presentations look (design.py), for a presentation guide: one JSON line per file, in the order given."""
    from .design import profile
    failed = 0
    with Converter(args.office) as converter:
        for path in args.files:
            result: dict[str, object]
            try:
                result = {"file": str(path), "status": "ok", "profile": profile(path, converter.session())}
            except (ConversionError, OSError) as error:
                result = {"file": str(path), "status": "failed", "note": str(error)[:400]}
                failed += 1
            print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
    return 1 if failed and failed == len(args.files) else 0


def cmd_edit(args: argparse.Namespace) -> int:
    """Wizard's attached-file editing: apply the operations in a JSON file to a copy of the workbook."""
    from .edit import edit
    try:
        operations = json.loads(args.operations.read_text(encoding="utf-8"))
        result: dict[str, object] = edit(args.file, operations, args.out, args.office)
    except (ConversionError, OSError, ValueError) as error:
        result = {"status": "failed", "note": str(error)[:600]}
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result["status"] == "ok" else 1


def cmd_save_copy(args: argparse.Namespace) -> int:
    """Wizard's Download on the person's own PC: a copy of a workbook it made, written by Excel when it runs here."""
    from .edit import save_copy
    try:
        result: dict[str, object] = save_copy(args.file, args.out, args.office)
    except (ConversionError, OSError) as error:
        result = {"status": "failed", "note": str(error)[:600]}
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result["status"] == "ok" else 1


def cmd_outlook_draft(args: argparse.Namespace) -> int:
    """Wizard's Email button: one JSON line, status ok or failed with a note a person can act on."""
    try:
        draft = json.loads(args.draft.read_text(encoding="utf-8"))
        with OfficeSession() as session:
            open_draft(session, str(draft["subject"]), str(draft["html"]))
        print(json.dumps({"status": "ok"}))
    except (OfficeUnavailable, OSError, ValueError, KeyError) as error:
        print(json.dumps({"status": "failed", "note": str(error)[:500]}))
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wizard_docs", description="Wizard's document commands",
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    convert = commands.add_parser("convert")
    convert.add_argument("file", type=Path)
    convert.add_argument("--out", type=Path, required=True)
    convert.add_argument("--json", action="store_true")
    convert.add_argument("--tables", action="store_true", help="also save spreadsheets and CSV as full tables "
                                                               "(tables.json, tables/*.csv) for querying")
    convert.add_argument("--office", choices=("auto", "always", "never"), default="auto")
    convert.add_argument("--slide-images", choices=("auto", "all", "none"), default="auto")
    design = commands.add_parser("design", help="how presentations look (theme, fonts, layouts, recurring elements), "
                                                "one JSON line per file")
    design.add_argument("files", type=Path, nargs="+")
    design.add_argument("--office", choices=("auto", "always", "never"), default="auto")
    edit_parser = commands.add_parser("edit", help="apply operations (JSON) to a copy of a workbook")
    edit_parser.add_argument("file", type=Path)
    edit_parser.add_argument("--operations", type=Path, required=True)
    edit_parser.add_argument("--out", type=Path, required=True)
    edit_parser.add_argument("--office", choices=("auto", "always", "never"), default="auto")
    save_parser = commands.add_parser("save-copy", help="copy a workbook Wizard made to a new place (Excel writes it)")
    save_parser.add_argument("file", type=Path)
    save_parser.add_argument("--out", type=Path, required=True)
    save_parser.add_argument("--office", choices=("auto", "never"), default="auto")
    draft = commands.add_parser("outlook-draft")
    draft.add_argument("draft", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "convert":
            return cmd_convert(args)
        if args.command == "design":
            return cmd_design(args)
        if args.command == "edit":
            return cmd_edit(args)
        if args.command == "save-copy":
            return cmd_save_copy(args)
        return cmd_outlook_draft(args)
    except (OfficeUnavailable, ConversionError, ValueError) as error:
        print(f"ERROR: {error}")
        return 1
