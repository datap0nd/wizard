"""Command line for the documentation kit (run through scripts/wizard_docs.py, which sets up the paths).

  check                                     pywin32 and the Office applications on this PC
  convert <file> --out <folder> [--json]    one document -> <folder>/text.md (+ assets/, attachments/)
  extract <content>                         every document in <content>/inbox -> inbox/_text/ + manifest.csv
  outlook-folders                           list Outlook mail folders with item counts
  outlook-export <content> --folder Inbox/Projects --since 2026-01-01 [--match word ...] [--max 500]
  status <content> [--quizzes <folder>]     sources, digests, notes and quizzes so far
  next <content> [--limit 20]               the next sources that need a digest
  topics <content>                          topics found in the digests -> inbox/_digests/_topics.md
  coverage <content>                        sources no note cites yet -> register/documentation-coverage.md
  quiz-check <page.html> [--content <content>]
  quiz-answers <answered page or folder> [--quizzes <folder>]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from .common import ConversionError, mask_contacts
from .convert import Converter
from .inbox import Inbox
from .kit import KitError, check_quiz, coverage, knowledge_ids, next_sources, read_answers, status, topics
from .office import PROGIDS, OfficeSession, OfficeUnavailable, export_mail, mail_folders, pywin32_status


def office_status() -> list[str]:
    ok, detail = pywin32_status()
    lines = [f"{'PASS' if ok else 'BLOCKED'}  {detail}"]
    if sys.platform == "win32":
        import winreg
        for name, progid in PROGIDS.items():
            try:
                winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f"{progid}\\CLSID").Close()
                lines.append(f"PASS  {name.capitalize()} is installed ({progid})")
            except OSError:
                lines.append(f"INFO  {name.capitalize()} is not registered ({progid}): its files cannot be read here")
    return lines


def cmd_convert(args: argparse.Namespace) -> int:
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    result: dict[str, object]
    try:
        with Converter(args.office, args.slide_images, args.max_rows) as converter:
            converted = converter.convert(args.file, out / "assets", out / "attachments")
        text = converted.text if args.keep_contacts else mask_contacts(converted.text)
        (out / "text.md").write_text(text + "\n", encoding="utf-8")
        result = {"status": "ok" if text.strip() or converted.images else "empty", "method": converted.method,
                  "chars": len(text), "images": [p.name for p in converted.images],
                  "attachments": [p.name for p in converted.attachments], "notes": converted.notes,
                  "parts": converted.parts[:200]}
    except (ConversionError, OSError) as error:
        result = {"status": "failed", "note": str(error)[:400]}
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"{result['status']}: " + (f"{result.get('chars')} characters via {result.get('method')}"
                                         if result["status"] != "failed" else str(result.get("note"))))
    return 0 if result["status"] != "failed" else 1


def cmd_extract(args: argparse.Namespace) -> int:
    content = args.content.resolve()
    if not (content / "inbox").is_dir():
        print(f"No inbox folder in {content}. Put documents in {content / 'inbox'} first.")
        return 2
    with Converter(args.office, args.slide_images, args.max_rows) as converter:
        counts = Inbox(content, converter, args.keep_contacts, args.force).run()
    total = sum(counts.values())
    print(f"{total} file(s): " + (", ".join(f"{s} {n}" for s, n in sorted(counts.items())) or "none")
          + ". Text in inbox/_text/, list in inbox/_text/manifest.csv.")
    if counts.get("failed"):
        print(f"{counts['failed']} file(s) could not be read: see the 'note' column of the manifest.")
    return 1 if counts.get("failed") and counts["failed"] == total else 0


def cmd_outlook_folders(args: argparse.Namespace) -> int:
    with OfficeSession() as session:
        for path, count in mail_folders(session, args.depth):
            print(f"{count:>7}  {path}")
    return 0


def cmd_outlook_export(args: argparse.Namespace) -> int:
    since = dt.datetime.fromisoformat(args.since)
    until = dt.datetime.fromisoformat(args.until) + dt.timedelta(days=1) if args.until else dt.datetime.now()
    out = args.content.resolve() / "inbox" / "outlook"
    with OfficeSession() as session:
        result = export_mail(session, args.folder, out, since, until, args.match or [], args.max, args.include_private,
                             args.subfolders)
    print(f"Exported {result.exported} email(s) with {result.attachments} attachment(s) to inbox/outlook/ from "
          f"{len(result.folders)} folder(s). Already exported: {result.already}. Skipped: {result.private} private or "
          f"confidential, {result.unmatched} without the words, {result.other_items} non-mail items.")
    if result.exported >= args.max:
        print(f"Stopped at --max {args.max}; run again (already exported items are skipped) or narrow the dates.")
    print("Next: run extract to convert the emails and their attachments.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wizard_docs", description="Wizard documentation kit",
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    for name in ("convert", "extract"):
        sub = commands.add_parser(name)
        if name == "convert":
            sub.add_argument("file", type=Path)
            sub.add_argument("--out", type=Path, required=True)
            sub.add_argument("--json", action="store_true")
        else:
            sub.add_argument("content", type=Path)
            sub.add_argument("--force", action="store_true", help="convert everything again")
        sub.add_argument("--office", choices=("auto", "always", "never"), default="auto")
        sub.add_argument("--slide-images", choices=("auto", "all", "none"), default="auto")
        sub.add_argument("--max-rows", type=int, default=1000)
        sub.add_argument("--keep-contacts", action="store_true", help="do not mask email addresses and phone numbers")
    folders = commands.add_parser("outlook-folders")
    folders.add_argument("--depth", type=int, default=3)
    export = commands.add_parser("outlook-export")
    export.add_argument("content", type=Path)
    export.add_argument("--folder", action="append", required=True, help="e.g. Inbox, Sent Items, Inbox/Projects")
    export.add_argument("--since", required=True, help="YYYY-MM-DD")
    export.add_argument("--until", help="YYYY-MM-DD (default: today)")
    export.add_argument("--match", nargs="*", help="keep only emails whose subject or body contains one of these words")
    export.add_argument("--max", type=int, default=500)
    export.add_argument("--subfolders", action="store_true")
    export.add_argument("--include-private", action="store_true", help="also export items marked private/confidential")
    for name in ("status", "next", "topics", "coverage"):
        sub = commands.add_parser(name)
        sub.add_argument("content", type=Path)
        if name == "status":
            sub.add_argument("--quizzes", type=Path)
        if name == "next":
            sub.add_argument("--limit", type=int, default=20)
    quiz = commands.add_parser("quiz-check")
    quiz.add_argument("page", type=Path)
    quiz.add_argument("--content", type=Path)
    answers = commands.add_parser("quiz-answers")
    answers.add_argument("path", type=Path)
    answers.add_argument("--quizzes", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            print("\n".join(office_status()))
            return 0
        if args.command == "convert":
            return cmd_convert(args)
        if args.command == "extract":
            return cmd_extract(args)
        if args.command == "outlook-folders":
            return cmd_outlook_folders(args)
        if args.command == "outlook-export":
            return cmd_outlook_export(args)
        if args.command == "status":
            print(status(args.content.resolve(), args.quizzes))
        elif args.command == "next":
            print(next_sources(args.content.resolve(), args.limit))
        elif args.command == "topics":
            print(topics(args.content.resolve()))
        elif args.command == "coverage":
            print(coverage(args.content.resolve()))
        elif args.command == "quiz-check":
            known = set(knowledge_ids(args.content.resolve())) if args.content else set()
            errors, warnings = check_quiz(args.page.read_text(encoding="utf-8-sig"), known)
            for warning in warnings:
                print(f"WARNING {warning}")
            for error in errors:
                print(f"ERROR {error}")
            print(f"{'FAILED' if errors else 'OK'}: {args.page.name}, {len(errors)} error(s), {len(warnings)} warning(s).")
            return 1 if errors else 0
        elif args.command == "quiz-answers":
            pages = sorted(p for p in args.path.rglob("*") if p.suffix.lower() in (".html", ".htm", ".txt")) \
                if args.path.is_dir() else [args.path]
            for page in pages:
                print(read_answers(page, args.quizzes))
                print()
    except (OfficeUnavailable, ConversionError, KitError, ValueError) as error:
        print(f"ERROR: {error}")
        return 1
    return 0
