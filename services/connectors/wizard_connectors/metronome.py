"""Metronome: recurring extractions that Wizard sets up as Metronome Flows owned by Metronome's Wizard user.

Owner decision, 20 October 2026 (docs/decisions/2026-10-20-metronome-recurring-extractions.md). Gemini creates nothing:
wizard_schedule_extraction checks and test-runs the query and proposes a schedule, and only the person's click on
Create in Metronome reaches Metronome (wizard_api/metronome_client.py).

This module holds what both sides need and never talks to the network: the connection settings, the schedule and
recipient rules, the Flow definition Metronome's POST /api/flows accepts, and the extraction script. Metronome has no
SQL-query source, so a Flow is a Python-script Flow ("Produce a file" mode) whose script Wizard generates: the query, its
SHA-256 and a read-only runner. Metronome runs it with its own Python (psycopg2, openpyxl) and emails the file."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
FREQUENCIES = ("daily", "weekly", "monthly")
FORMATS = ("xlsx", "csv")
TIMEZONE = "Dubai time"  # Metronome keeps every schedule on Dubai's clock
MAX_RECIPIENTS = 20  # Metronome's own limit on an email step
MAX_EXTRACT_ROWS = 100_000
# Metronome keeps a client key of these characters, up to 128 (user_identity.clean_client_key); Wizard wants a long one.
CLIENT_KEY = re.compile(r"^[A-Za-z0-9_.:-]{24,128}$")
EMAIL = re.compile(r"^[^\s@,;<>\"']+@([A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+)$")
TIME = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
UNSAFE_NAME = re.compile(r"[^\w .,&()+-]+")  # letters of any language stay; quotes, slashes, : ? * < > | go


class MetronomeConfigError(ValueError):
    pass


@dataclass(frozen=True)
class MetronomeSettings:
    url: str  # an origin such as http://10.0.0.5:8000, reached directly on the office network
    client_key: str  # signed in to Metronome as `user` (scripts/metronome_link.py)
    user: str = "Wizard"  # the Metronome person every Flow belongs to


def origin(url: str) -> str:
    """Metronome's address as a bare http(s) origin; MetronomeConfigError for anything else."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password \
            or parts.path not in ("", "/") or parts.query or parts.fragment:
        raise MetronomeConfigError("WIZARD_METRONOME_URL must be Metronome's address, for example http://10.0.0.5:8000")
    try:
        parts.port  # noqa: B018 - raises ValueError for a bad port
    except ValueError:
        raise MetronomeConfigError("WIZARD_METRONOME_URL has an invalid port") from None
    return f"{parts.scheme}://{parts.netloc}"


def settings_from(url: str | None, client_key: str | None, user: str | None) -> MetronomeSettings | None:
    """None when no address is set. An address without a key, or a malformed one, is an error rather than a feature
    that silently stays off."""
    if not url:
        if client_key:
            raise MetronomeConfigError("WIZARD_METRONOME_CLIENT_KEY is set without WIZARD_METRONOME_URL")
        return None
    if not client_key:
        raise MetronomeConfigError("WIZARD_METRONOME_URL needs WIZARD_METRONOME_CLIENT_KEY, the key signed in to Metronome "
                                   "as its Wizard user (scripts/metronome_link.py makes one)")
    if not CLIENT_KEY.match(client_key):
        raise MetronomeConfigError("WIZARD_METRONOME_CLIENT_KEY must be 24-128 letters, digits or _ . : -")
    name = (user or "Wizard").strip()
    if not name or len(name) > 100:
        raise MetronomeConfigError("WIZARD_METRONOME_USER must be the name of a person in Metronome's Users")
    return MetronomeSettings(origin(url), client_key, name)


# Recipients ------------------------------------------------------------------------------------------------------------
def domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower()


def recipient_problems(recipients: list[str], allowed_domains: list[str]) -> list[str]:
    """What is wrong with the recipients, in words Gemini can pass on; empty when they may receive the file."""
    if not recipients:
        return ["Add at least one recipient."]
    if len(recipients) > MAX_RECIPIENTS:
        return [f"Metronome sends to at most {MAX_RECIPIENTS} recipients."]
    bad = [r for r in recipients if not EMAIL.match(r)]
    if bad:
        return [f"Not an email address: {', '.join(bad)}."]
    if not allowed_domains:
        return ["This Wizard does not know the company's email domains (WIZARD_GOOGLE_DOMAINS), so it cannot schedule "
                "email to anyone."]
    outside = [r for r in recipients if domain(r) not in allowed_domains]
    if outside:
        return [f"Only company addresses ({', '.join('@' + d for d in allowed_domains)}) can receive a recurring "
                f"extraction: {', '.join(outside)} is outside."]
    return []


# Schedules -------------------------------------------------------------------------------------------------------------
def schedule_problems(frequency: str, time: str, days: list[str], day_of_month: int | None) -> list[str]:
    problems = []
    if frequency not in FREQUENCIES:
        problems.append(f"frequency must be one of {', '.join(FREQUENCIES)}.")
    if not TIME.match(time):
        problems.append("time must be HH:MM on a 24-hour clock, e.g. 08:00.")
    if frequency == "weekly" and not days:
        problems.append("A weekly schedule needs its weekdays, e.g. ['monday'].")
    if any(d not in WEEKDAYS for d in days):
        problems.append(f"days must be weekday names: {', '.join(WEEKDAYS)}.")
    if frequency == "monthly" and not (isinstance(day_of_month, int) and 1 <= day_of_month <= 31):
        problems.append("A monthly schedule needs day_of_month from 1 to 31.")
    return problems


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def schedule_text(schedule: dict[str, Any]) -> str:
    """'Every Monday at 08:00 (Dubai time)': how the card and Gemini describe a schedule."""
    at = f"at {schedule['time']} ({TIMEZONE})"
    if schedule["frequency"] == "daily":
        return f"Every day {at}"
    if schedule["frequency"] == "monthly":
        day = int(schedule["day_of_month"])
        suffix = "th" if 10 <= day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        last = " (the last day in shorter months)" if day > 28 else ""
        return f"Every month on the {day}{suffix}{last} {at}"
    days = [d for d in WEEKDAYS if d in schedule["days"]]
    if days == list(WEEKDAYS[:5]):
        return f"Every weekday, Monday to Friday, {at}"
    return f"Every {_join([d.capitalize() for d in days])} {at}"


# The Flow --------------------------------------------------------------------------------------------------------------
def safe_title(title: str) -> str:
    """A title that is safe in a Flow name, a folder and a Windows file name."""
    return " ".join(UNSAFE_NAME.sub(" ", title).split())[:80].strip(" .") or "Extraction"


def flow_name(schedule: dict[str, Any]) -> str:
    return f"Wizard · {safe_title(schedule['title'])} · for {safe_title(schedule['requested_by']['name'])} · " \
           f"{schedule['ref']}"[:200]


def script_filename(schedule: dict[str, Any]) -> str:
    return f"wizard_extract_{schedule['ref']}.py"


def flow_definition(schedule: dict[str, Any], script_path: str, owner_person_id: int) -> dict[str, Any]:
    """The body of Metronome's POST /api/flows: an active Python-script Flow that writes the file and emails it."""
    fmt = schedule["file_format"]
    return {
        "name": flow_name(schedule),
        "source_type": "python",
        "python_scripts": [script_path],
        "python_run_mode": "outputs",
        "python_timeout_minutes": 30,
        "file_format": fmt,
        "filename_template": f"{safe_title(schedule['title'])} {{date}}.{fmt}",
        "output_mode": "run_folders",
        "enabled": True,
        "schedule_type": schedule["frequency"],
        "schedule_time": schedule["time"],
        "schedule_days": list(schedule["days"]) if schedule["frequency"] == "weekly" else [],
        "schedule_day": schedule["day_of_month"] if schedule["frequency"] == "monthly" else None,
        "sql_handoff_enabled": False,
        "email_delivery": {"enabled": True, "recipients": list(schedule["recipients"]),
                           "subject": schedule.get("subject") or safe_title(schedule["title"])},
        "owner_person_id": owner_person_id,
    }


# The script Metronome runs ---------------------------------------------------------------------------------------------
SCRIPT = '''"""Wizard recurring extraction: {title}

Set up by Wizard for {requester} on {created}, as Metronome Flow "{flow}" owned by Metronome's Wizard user.
Metronome runs this script on the Flow's schedule and emails the file it writes to --output.

It runs one query and changes nothing: the query runs as a subquery in a READ ONLY session and transaction that is
rolled back, with statement and lock timeouts, and at most {max_rows:,} rows are written. It connects with the
read-only account in WIZARD_EXTRACT_PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD/PGSSLMODE when Metronome's .env sets
them, otherwise with Metronome's PG* scanner account; never with DG_UPLOAD_PG*, the uploader. It refuses to run if the
query below no longer matches the SHA-256 Wizard recorded. To change the query, ask Wizard for a new schedule.
"""
import argparse
import csv
import datetime
import decimal
import hashlib
import os
import sys

SQL = {sql!r}
SQL_SHA256 = {digest!r}
DATABASE = {database!r}
TITLE = {sheet!r}
MAX_ROWS = {max_rows}


def setting(name):
    return os.environ.get("WIZARD_EXTRACT_" + name) or os.environ.get(name) or None


def cell(value):
    if isinstance(value, datetime.datetime) and value.tzinfo is not None:
        return value.replace(tzinfo=None)  # Excel has no time zones
    if value is None or isinstance(value, (str, int, float, decimal.Decimal, datetime.date, datetime.time)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "<%d bytes>" % len(bytes(value))
    return str(value)


def main():
    parser = argparse.ArgumentParser(description="Wizard recurring extraction")
    parser.add_argument("--output", required=True)
    output = parser.parse_args().output
    if hashlib.sha256(SQL.encode("utf-8")).hexdigest() != SQL_SHA256:
        sys.exit("The query in this script was changed after Wizard created it. Ask Wizard for a new schedule.")
    host, user = setting("PGHOST"), setting("PGUSER")
    if not host or not user:
        sys.exit("No read-only database account: set WIZARD_EXTRACT_PGHOST and WIZARD_EXTRACT_PGUSER (or PGHOST and "
                 "PGUSER) in Metronome's .env.")
    import psycopg2

    print("::stage::Running the query", flush=True)
    connection = psycopg2.connect(
        host=host, port=int(setting("PGPORT") or 5432), dbname=DATABASE or setting("PGDATABASE") or "postgres",
        user=user, password=setting("PGPASSWORD"), sslmode=setting("PGSSLMODE") or "prefer", connect_timeout=30,
        application_name="wizard-extract",
        options="-c default_transaction_read_only=on -c statement_timeout=900000 -c lock_timeout=2000")
    try:
        connection.set_session(readonly=True, autocommit=False)
        cursor = connection.cursor()
        # The newlines keep a trailing -- comment from swallowing the closing parenthesis.
        cursor.execute("SELECT * FROM (\\n" + SQL + "\\n) AS wizard_extract LIMIT " + str(MAX_ROWS + 1))
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchmany(MAX_ROWS + 1)
    finally:
        try:
            connection.rollback()
        finally:
            connection.close()
    if len(rows) > MAX_ROWS:
        print("Only the first %d rows were written; the query returns more." % MAX_ROWS, file=sys.stderr, flush=True)
        rows = rows[:MAX_ROWS]
    print("::stage::Writing %d rows" % len(rows), flush=True)
    if output.lower().endswith(".xlsx"):
        from openpyxl import Workbook

        book = Workbook(write_only=True)
        sheet = book.create_sheet(TITLE)
        sheet.append(columns)
        for row in rows:
            sheet.append([cell(value) for value in row])
        book.save(output)
    else:
        with open(output, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            writer.writerows([[cell(value) for value in row] for row in rows])
    print("Wrote %d rows." % len(rows), flush=True)


if __name__ == "__main__":
    main()
'''


def extraction_script(schedule: dict[str, Any]) -> str:
    """The Python file Metronome runs for this schedule. Every value from the conversation enters the file only as a
    Python string literal (repr) or inside the docstring after `safe_title`, never as code."""
    sql = schedule["sql"]
    return SCRIPT.format(
        title=safe_title(schedule["title"]), requester=safe_title(schedule["requested_by"]["name"]),
        created=str(schedule["created_at"])[:10], flow=flow_name(schedule), sql=sql,
        digest=hashlib.sha256(sql.encode("utf-8")).hexdigest(), database=schedule.get("database"),
        sheet=safe_title(schedule["title"])[:31], max_rows=MAX_EXTRACT_ROWS)
