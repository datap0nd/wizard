"""Command line for the documentation kit (run through scripts/wizard_docs.py, which sets up the paths).

  check                                     pywin32 and the Office applications on this PC
  convert <file> --out <folder> [--json]    one document -> <folder>/text.md (+ assets/, attachments/)
  extract <content>                         every document in <content>/inbox -> inbox/_text/ + manifest.csv
  outlook-folders                           list Outlook mail folders with item counts
  outlook-export <content> --folder Inbox/Projects --since 2026-01-01 [--match word ...] [--max 500]
  outlook-draft <draft.json>                open an unsent Outlook message ({"subject", "html"}) for the user to send
  status <content> [--quizzes <folder>]     sources, digests, notes and quizzes so far
  next <content> [--limit 20]               the next sources that need a digest
  topics <content>                          topics found in the digests -> inbox/_digests/_topics.md
  coverage <content>                        sources no note cites yet -> register/documentation-coverage.md
  postgres-check <content>                  connect read-only with the .env / PG* settings and report what is visible
  postgres-catalog <content> [--database D] [--schema S] [--structure-only]
                                            materialized views -> inbox/postgres/<database>/ (+ inbox/_postgres/*.json)
  bdp-check <content> [--url <Superset address>]
                                            anonymous checks of the Big Data Portal's Superset -> inbox/bdp/superset-check.md
  kb-publish <content> [--repo owner/name] [--dry-run]
                                            knowledge/ and contracts/sources/ -> the private knowledge-base repository
  kb-check <content> [--repo owner/name]   can the read-only token (the one users get) read that repository?
  quiz-check <page.html> [--content <content>]
  quiz-answers <answered page or folder> [--quizzes <folder>]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import httpx

from wizard_agent import outbound
from wizard_connectors.pg import read_env

from . import bdp
from .common import ConversionError, mask_contacts
from .convert import Converter
from .inbox import Inbox
from .kit import KitError, check_quiz, coverage, knowledge_ids, next_sources, read_answers, status, topics
from .office import PROGIDS, OfficeSession, OfficeUnavailable, export_mail, mail_folders, open_draft, pywin32_status
from .postgres import check as postgres_check
from .postgres import export as postgres_export
from .postgres import settings_from
from .tables import write as write_tables


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
        with Converter(args.office, args.slide_images, args.max_rows, tables=args.command == "convert" and args.tables) as converter:
            converted = converter.convert(args.file, out / "assets", out / "attachments")
        tables = write_tables(converted.tables, out) if converted.tables else []
        text = converted.text if args.keep_contacts else mask_contacts(converted.text)
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


def cmd_postgres(args: argparse.Namespace) -> int:
    content = args.content.resolve()
    settings = settings_from(args.env_file or content.parent / ".env")
    if args.command == "postgres-check":
        print("\n".join(postgres_check(settings)))
        return 0
    summary = postgres_export(content, settings, args.database or None, args.schema or None, not args.structure_only)
    for name, counts in summary["databases"].items():
        print(f"{name}: {counts['materialized_views']} materialized view(s), {counts['profiled']} profiled, "
              f"{counts['notes']} note(s) about skipped steps")
    for name, reason in summary["skipped"].items():
        print(f"{name}: skipped ({reason})")
    print("Written to inbox/postgres/<database>/ (one file per materialized view, plus 00-overview.md). "
          "Next: run extract so each file gets a source id.")
    return 0


def cmd_bdp_check(args: argparse.Namespace) -> int:
    content = args.content.resolve()
    env = read_env(args.env_file or content.parent / ".env")
    address = args.url or env.get("WIZARD_BDP_URL")
    if not address:
        print("Give the Superset address: bdp-check --url <the address of the browser tab where SQL Lab is open>")
        return 2
    result = bdp.check(address, proxy=env.get("WIZARD_PROXY"))
    saved = content / "inbox" / "bdp" / "superset-databases.json"
    if saved.is_file():
        try:
            result.lines += [f"INFO  {line}" for line in bdp.describe_databases(saved)]
        except ValueError as error:
            result.lines.append(f"WARN  {error}. Save the page again from the browser while signed in (task 40)")
    path = bdp.write(content, result)
    print("\n".join(result.lines))
    print(f"Written to {path.relative_to(content).as_posix()}. Next: run extract so it gets a source id.")
    return 1 if any(line.startswith("FAIL") for line in result.lines) else 0


def cmd_kb(args: argparse.Namespace) -> int:
    from . import kb
    content = args.content.resolve()
    env = {**read_env(args.env_file or content.parent / ".env"),
           **{k: v for k, v in os.environ.items() if k.startswith("WIZARD_KB_") and v}}
    # Not WIZARD_KB_REPO / WIZARD_KB_TOKEN: in this install's .env those would switch its own Wizard to the synced
    # knowledge base, which cannot be combined with its content\ folder (WIZARD_CONTENT_DIR).
    repo = args.repo or env.get("WIZARD_KB_PUBLISH_REPO")
    if not repo or "/" not in repo:
        print("Give the repository: --repo owner/name (or WIZARD_KB_PUBLISH_REPO=owner/name in .env)")
        return 2
    try:
        if args.command == "kb-check":
            token = env.get("WIZARD_KB_READ_TOKEN")
            if not token:
                print("FAIL  no WIZARD_KB_READ_TOKEN (the read-only token users get) in .env")
                return 2
            ok, text = kb.check_read(repo, token, args.branch or "main", proxy=env.get("WIZARD_PROXY"))
            print(("PASS  " if ok else "FAIL  ") + text)
            return 0 if ok else 1
        token = env.get("WIZARD_KB_PUBLISH_TOKEN")
        if not token:
            print("FAIL  no WIZARD_KB_PUBLISH_TOKEN (Contents read and write on the repository) in .env or the environment")
            return 2
        outcome = kb.publish(content, repo, token, branch=args.branch, message=args.message, dry_run=args.dry_run,
                             proxy=env.get("WIZARD_PROXY"))
    except kb.PublishError as error:
        print(f"FAIL  {error}")
        return 1
    except httpx.HTTPError as error:
        print(f"FAIL  {outbound.explain(error, kb.API, env.get('WIZARD_PROXY'))}")
        return 1
    print("\n".join(outcome.lines))
    for label, names in (("added", outcome.added), ("changed", outcome.changed), ("removed", outcome.removed)):
        for name in names[:40]:
            print(f"  {label:8} {name}")
        if len(names) > 40:
            print(f"  ... and {len(names) - 40} more {label}")
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
            sub.add_argument("--tables", action="store_true", help="also save spreadsheets and CSV as full tables "
                                                                   "(tables.json, tables/*.csv) for querying")
        else:
            sub.add_argument("content", type=Path)
            sub.add_argument("--force", action="store_true", help="convert everything again")
        sub.add_argument("--office", choices=("auto", "always", "never"), default="auto")
        sub.add_argument("--slide-images", choices=("auto", "all", "none"), default="auto")
        sub.add_argument("--max-rows", type=int, default=1000)
        sub.add_argument("--keep-contacts", action="store_true", help="do not mask email addresses and phone numbers")
    edit_parser = commands.add_parser("edit", help="apply operations (JSON) to a copy of a workbook")
    edit_parser.add_argument("file", type=Path)
    edit_parser.add_argument("--operations", type=Path, required=True)
    edit_parser.add_argument("--out", type=Path, required=True)
    edit_parser.add_argument("--office", choices=("auto", "always", "never"), default="auto")
    save_parser = commands.add_parser("save-copy", help="copy a workbook Wizard made to a new place (Excel writes it)")
    save_parser.add_argument("file", type=Path)
    save_parser.add_argument("--out", type=Path, required=True)
    save_parser.add_argument("--office", choices=("auto", "never"), default="auto")
    folders = commands.add_parser("outlook-folders")
    folders.add_argument("--depth", type=int, default=3)
    draft = commands.add_parser("outlook-draft")
    draft.add_argument("draft", type=Path)
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
    for name in ("postgres-check", "postgres-catalog"):
        sub = commands.add_parser(name)
        sub.add_argument("content", type=Path)
        sub.add_argument("--env-file", type=Path, help="Wizard's .env with WIZARD_PG_* (default: next to the content folder)")
        if name == "postgres-catalog":
            sub.add_argument("--database", action="append", help="only this database (repeatable; default: every one "
                                                                 "the account can connect to)")
            sub.add_argument("--schema", action="append", help="only this schema (repeatable)")
            sub.add_argument("--structure-only", action="store_true", help="catalog only: no row counts or profiles")
    check_bdp = commands.add_parser("bdp-check")
    check_bdp.add_argument("content", type=Path)
    check_bdp.add_argument("--url", help="Superset's address, e.g. copied from the SQL Lab tab (default: WIZARD_BDP_URL in .env)")
    check_bdp.add_argument("--env-file", type=Path, help="Wizard's .env (default: next to the content folder)")
    for name in ("kb-publish", "kb-check"):
        sub = commands.add_parser(name)
        sub.add_argument("content", type=Path)
        sub.add_argument("--repo", help="owner/name of the private knowledge-base repository (default: WIZARD_KB_PUBLISH_REPO "
                                        "in .env)")
        sub.add_argument("--branch", help="default: the repository's default branch (kb-check: main)")
        sub.add_argument("--env-file", type=Path, help="Wizard's .env (default: next to the content folder)")
        if name == "kb-publish":
            sub.add_argument("--message", help="commit message")
            sub.add_argument("--dry-run", action="store_true", help="show what would change; write nothing")
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
        if args.command == "edit":
            return cmd_edit(args)
        if args.command == "save-copy":
            return cmd_save_copy(args)
        if args.command == "outlook-folders":
            return cmd_outlook_folders(args)
        if args.command == "outlook-draft":
            return cmd_outlook_draft(args)
        if args.command == "outlook-export":
            return cmd_outlook_export(args)
        if args.command.startswith("postgres-"):
            return cmd_postgres(args)
        if args.command == "bdp-check":
            return cmd_bdp_check(args)
        if args.command in ("kb-publish", "kb-check"):
            return cmd_kb(args)
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
