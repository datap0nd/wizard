"""Metronome: recurring briefs that Wizard sets up as Metronome Flows owned by Metronome's Wizard user.

Owner decisions, 20 and 23 October 2026 (docs/decisions/2026-10-20-metronome-recurring-extractions.md,
docs/decisions/2026-10-23-recurring-briefs.md). Gemini creates nothing: wizard_schedule_brief checks and test-runs the
brief's queries and proposes a schedule, and only the person's click on Create in Metronome reaches Metronome
(wizard_api/metronome_client.py).

This module holds what both sides need and never talks to the network: the connection settings, the schedule and
recipient rules, the Flow definition Metronome's POST /api/flows accepts, and the script. Metronome has no SQL-query
source, so a Flow is a Python-script Flow ("Produce a file" mode) whose script Wizard generates: the brief, its SHA-256,
a read-only runner and a copy of the email renderer (brief.py). Metronome runs it with its own Python (psycopg2,
openpyxl, matplotlib), sends the body.html it writes into METRONOME_FLOW_EMAIL_DIR and attaches the Excel file.

Few questions (owner, 20 October 2026): the Excel file is always attached, it goes to the person's own address unless
they name others, and it is sent at 08:00 unless they give a time. Only how often is asked, and only when they have not
said."""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from wizard_connectors import brief

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
FREQUENCIES = ("daily", "weekly", "monthly")
DEFAULT_TIME = "08:00"
# People sign in to Wizard as name@ax.company.com; their mailbox is name@company.com (owner, 20 October 2026).
SIGN_IN_PREFIX = "ax."
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


def mail_address(address: str) -> str:
    """The mailbox for an address: lower case, without the sign-in "ax." after the @. Empty when it is no address."""
    local, _, host = address.strip().lower().rpartition("@")
    return f"{local}@{host.removeprefix(SIGN_IN_PREFIX)}" if local and host else ""


def mail_domains(domains: list[str]) -> list[str]:
    """Company domains as mailboxes use them: each as given and without its sign-in "ax." prefix."""
    return sorted({d for given in domains for d in (given.lower(), given.lower().removeprefix(SIGN_IN_PREFIX))})


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
    return f"wizard_brief_{schedule['ref']}.py"


def flow_definition(schedule: dict[str, Any], script_path: str, owner_person_id: int) -> dict[str, Any]:
    """The body of Metronome's POST /api/flows: an active Python-script Flow that writes the Excel file and the email,
    which Metronome's Email step sends."""
    return {
        "name": flow_name(schedule),
        "source_type": "python",
        "python_scripts": [script_path],
        "python_run_mode": "outputs",
        "python_timeout_minutes": 30,
        "file_format": "xlsx",
        "filename_template": f"{safe_title(schedule['title'])} {{date}}.xlsx",
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
def brief_of(schedule: dict[str, Any]) -> dict[str, Any]:
    """The brief a schedule carries. A proposal made before briefs (one query for an Excel file) becomes a brief with one
    table section, so its Create still works."""
    if schedule.get("brief"):
        return schedule["brief"]
    return {"title": schedule["title"], "intro": None, "period_sql": None, "database": schedule.get("database"),
            "sections": [{"kind": "table", "title": schedule["title"], "subtitle": None, "sql": schedule["sql"],
                          "columns": [], "max_rows": 10, "highlights": []}],
            "cadence": schedule_text(schedule).removesuffix(f" ({TIMEZONE})"),
            "requested_by": schedule["requested_by"]["name"], "created_on": str(schedule["created_at"])[:10]}


SCRIPT_HEAD = '''"""Wizard recurring brief: {title}

Set up by Wizard for {requester} on {created}, as Metronome Flow "{flow}" owned by Metronome's Wizard user.
Metronome runs this script on the Flow's schedule. It runs the brief's queries, writes every row to the Excel file named
by --output (one sheet per section) and, when Metronome gives it METRONOME_FLOW_EMAIL_DIR, writes the email there:
body.html and its PNG charts. Metronome sends that email with the Excel file attached.

It changes nothing: each query runs as a subquery in a READ ONLY session and transaction that is rolled back, with
statement and lock timeouts, and at most {max_rows:,} rows are kept per query. It connects with the read-only account
in WIZARD_EXTRACT_PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD/PGSSLMODE when Metronome's .env sets them, otherwise with
Metronome's PG* scanner account; never with DG_UPLOAD_PG*, the uploader. It refuses to run if the brief below no longer
matches the SHA-256 Wizard recorded. To change the brief, ask Wizard for a new one.
"""
import argparse
import datetime
import decimal
import hashlib
import json
import os
import sys

BRIEF_JSON = {brief!r}
BRIEF_SHA256 = {digest!r}
MAX_ROWS = {max_rows}

# The email renderer, copied verbatim from Wizard (services/connectors/wizard_connectors/brief.py) ----------------------
'''

SCRIPT_TAIL = '''
# End of the copied renderer ---------------------------------------------------------------------------------------------


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


def run_queries(brief):
    """Every section's columns and rows, and the period line, read in one read-only transaction."""
    host, user = setting("PGHOST"), setting("PGUSER")
    if not host or not user:
        sys.exit("No read-only database account: set WIZARD_EXTRACT_PGHOST and WIZARD_EXTRACT_PGUSER (or PGHOST and "
                 "PGUSER) in Metronome's .env.")
    import psycopg2

    connection = psycopg2.connect(
        host=host, port=int(setting("PGPORT") or 5432), dbname=brief.get("database") or setting("PGDATABASE") or "postgres",
        user=user, password=setting("PGPASSWORD"), sslmode=setting("PGSSLMODE") or "prefer", connect_timeout=30,
        application_name="wizard-brief",
        options="-c default_transaction_read_only=on -c statement_timeout=900000 -c lock_timeout=2000")
    results, period = [], None
    try:
        connection.set_session(readonly=True, autocommit=False)
        cursor = connection.cursor()

        def query(sql):
            # The newlines keep a trailing -- comment from swallowing the closing parenthesis.
            cursor.execute("SELECT * FROM (\\n" + sql + "\\n) AS wizard_brief LIMIT " + str(MAX_ROWS + 1))
            columns = [column[0] for column in cursor.description]
            rows = [list(row) for row in cursor.fetchmany(MAX_ROWS + 1)]
            if len(rows) > MAX_ROWS:
                print("Only the first %d rows of a query were kept; it returns more." % MAX_ROWS, file=sys.stderr,
                      flush=True)
                rows = rows[:MAX_ROWS]
            return {"columns": columns, "rows": rows}

        for index, section in enumerate(brief["sections"]):
            print("::stage::Running query %d of %d" % (index + 1, len(brief["sections"])), flush=True)
            results.append(query(section["sql"]))
        if brief.get("period_sql"):
            found = query(brief["period_sql"])
            period = found["rows"][0][0] if found["rows"] and found["rows"][0] else None
    finally:
        try:
            connection.rollback()
        finally:
            connection.close()
    return results, period


def write_excel(brief, results, output):
    from openpyxl import Workbook

    book = Workbook(write_only=True)
    for name, section, result in zip(sheet_names(brief), brief["sections"], results):
        sheet = book.create_sheet(name)
        sheet.append([label_of(section, key) for key in result["columns"]])
        for row in result["rows"]:
            sheet.append([cell(value) for value in row])
    book.save(output)


def write_email(brief, results, period, folder):
    os.makedirs(folder, exist_ok=True)  # Metronome names the folder; the script creates it
    the_issue = issue(brief, results, period=period, read_at=datetime.datetime.now(datetime.timezone.utc))
    images = {}
    for entry in the_issue["sections"]:
        if not entry.get("drawing"):
            continue
        name = "chart-%d.png" % (entry["index"] + 1)
        try:
            png(entry["drawing"], os.path.join(folder, name))
        except ImportError:
            print("matplotlib is not installed on this worker: the charts go in as tables.", file=sys.stderr, flush=True)
            images = {}
            break
        images[entry["index"]] = "cid:" + name
    with open(os.path.join(folder, "body.html"), "w", encoding="utf-8") as handle:
        handle.write(render(brief, the_issue, images))


def main():
    parser = argparse.ArgumentParser(description="Wizard recurring brief")
    parser.add_argument("--output", required=True)
    output = parser.parse_args().output
    if hashlib.sha256(BRIEF_JSON.encode("utf-8")).hexdigest() != BRIEF_SHA256:
        sys.exit("The brief in this script was changed after Wizard created it. Ask Wizard for a new one.")
    brief = json.loads(BRIEF_JSON)
    results, period = run_queries(brief)
    print("::stage::Writing the Excel file", flush=True)
    write_excel(brief, results, output)
    folder = os.environ.get("METRONOME_FLOW_EMAIL_DIR")
    if folder:
        print("::stage::Writing the email", flush=True)
        write_email(brief, results, period, folder)
    total = sum(len(result["rows"]) for result in results)
    print("Wrote %d rows in %d sheets." % (total, len(results)), flush=True)


if __name__ == "__main__":
    main()
'''


def renderer_source() -> str:
    """brief.py as Metronome runs it: Wizard's own file, which needs only the standard library (and matplotlib for the
    PNG charts)."""
    return Path(brief.__file__).read_text(encoding="utf-8")


def brief_json(schedule: dict[str, Any]) -> str:
    return json.dumps(brief_of(schedule), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def brief_script(schedule: dict[str, Any]) -> str:
    """The Python file Metronome runs for this schedule. Every value from the conversation enters the file only as a
    Python string literal (repr) or inside the docstring after `safe_title`, never as code; the renderer is Wizard's
    own file, copied verbatim."""
    text = brief_json(schedule)
    head = SCRIPT_HEAD.format(
        title=safe_title(schedule["title"]), requester=safe_title(schedule["requested_by"]["name"]),
        created=str(schedule["created_at"])[:10], flow=flow_name(schedule), brief=text,
        digest=hashlib.sha256(text.encode("utf-8")).hexdigest(), max_rows=MAX_EXTRACT_ROWS)
    return head + renderer_source() + SCRIPT_TAIL


def preview_html(schedule: dict[str, Any]) -> str:
    """The email as it looked on the proposal's test run, with SVG charts in place of the PNGs Metronome draws."""
    preview = schedule.get("preview") or {}
    results = preview.get("results")
    if results is None:  # a proposal made before briefs: one query, its first rows
        results = [{"columns": preview.get("columns") or [], "rows": preview.get("rows") or []}]
    stamp = preview.get("read_at") or schedule.get("created_at")
    try:
        read_at = datetime.datetime.fromisoformat(str(stamp))
    except ValueError:
        read_at = None
    found = brief.issue(brief_of(schedule), results, period=preview.get("period"), read_at=read_at)
    images = {entry["index"]: "data:image/svg+xml;base64," + base64.b64encode(brief.svg(entry["drawing"]).encode()).decode()
              for entry in found["sections"] if entry.get("drawing")}
    return brief.render(brief_of(schedule), found, images)
