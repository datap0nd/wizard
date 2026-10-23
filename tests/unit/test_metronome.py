"""Recurring briefs in Metronome without Metronome: the settings, schedule and recipient rules, the Flow Wizard asks for,
the client against a fake Metronome with its real ownership rules (create, status, turning a Flow off), the generated
script run with fake database, Excel and matplotlib modules, and the one-time link script against a local HTTP
server."""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
from tests.helpers import WIZARD_KEY, FakeMetronome

from wizard_api.metronome_client import MetronomeClient, MetronomeError
from wizard_connectors import metronome
from wizard_connectors.metronome import MetronomeConfigError, MetronomeSettings, settings_from

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = MetronomeSettings("http://metronome.corp:8000", WIZARD_KEY, "Wizard")


def schedule(**overrides: Any) -> dict[str, Any]:
    base = {"ref": "a1b2c3d4", "title": "Weekly sell-out by market", "sql": "SELECT market, sum(units) AS units FROM "
            "bi_reporting.sell_out WHERE week_start >= date_trunc('week', CURRENT_DATE) - interval '7 days' GROUP BY 1",
            "database": None, "recipients": ["rafael@corp.test", "cfo@corp.test"], "frequency": "weekly",
            "time": "08:00", "days": ["monday"], "day_of_month": None, "file_format": "xlsx", "subject": None,
            "requested_by": {"id": "o", "name": "Rafael", "email": "rafael@corp.test"},
            "created_at": "2026-10-20T09:00:00+00:00"}
    return {**base, **overrides}


def test_settings_are_validated():
    assert settings_from(None, None, None) is None
    found = settings_from("http://10.0.0.5:8000/", WIZARD_KEY, None)
    assert found == MetronomeSettings("http://10.0.0.5:8000", WIZARD_KEY, "Wizard")
    for url, key, message in [("http://10.0.0.5:8000", None, "needs WIZARD_METRONOME_CLIENT_KEY"),
                              (None, WIZARD_KEY, "without WIZARD_METRONOME_URL"),
                              ("http://10.0.0.5:8000", "short", "24-128"),
                              ("http://10.0.0.5:8000/api", WIZARD_KEY, "Metronome's address"),
                              ("ftp://10.0.0.5", WIZARD_KEY, "Metronome's address"),
                              ("http://user:pw@10.0.0.5", WIZARD_KEY, "Metronome's address")]:
        with pytest.raises(MetronomeConfigError, match=message):
            settings_from(url, key, None)


def test_mailboxes_drop_the_sign_in_prefix():
    assert metronome.mail_address(" Rafael.C@AX.Samsung.com ") == "rafael.c@samsung.com"
    assert metronome.mail_address("cfo@samsung.com") == "cfo@samsung.com"
    assert metronome.mail_address("max@axis.com") == "max@axis.com", "only an 'ax.' label is the sign-in prefix"
    assert metronome.mail_address("not an address") == ""
    assert metronome.mail_domains(["ax.samsung.com"]) == ["ax.samsung.com", "samsung.com"]


def test_recipients_stay_in_the_company():
    assert metronome.recipient_problems(["a@corp.test"], ["corp.test"]) == []
    assert "outside" in metronome.recipient_problems(["a@corp.test", "x@gmail.com"], ["corp.test"])[0]
    assert "Not an email" in metronome.recipient_problems(["corp.test"], ["corp.test"])[0]
    assert "cannot schedule" in metronome.recipient_problems(["a@corp.test"], [])[0], "no known domain: nobody"
    assert "at most 20" in metronome.recipient_problems([f"a{i}@corp.test" for i in range(21)], ["corp.test"])[0]


def test_schedules_are_checked_and_described():
    assert metronome.schedule_problems("weekly", "08:00", [], None) == ["A weekly schedule needs its weekdays, e.g. ['monday']."]
    assert metronome.schedule_problems("monthly", "8:00", [], None) == [
        "time must be HH:MM on a 24-hour clock, e.g. 08:00.", "A monthly schedule needs day_of_month from 1 to 31."]
    assert metronome.schedule_problems("daily", "23:59", [], None) == []
    text = metronome.schedule_text
    assert text({"frequency": "daily", "time": "07:30"}) == "Every day at 07:30 (Dubai time)"
    assert text({"frequency": "weekly", "time": "08:00", "days": ["thursday", "monday"]}) == \
        "Every Monday and Thursday at 08:00 (Dubai time)"
    assert text({"frequency": "weekly", "time": "08:00", "days": list(metronome.WEEKDAYS[:5])}).startswith("Every weekday")
    assert text({"frequency": "monthly", "time": "06:00", "day_of_month": 2}) == "Every month on the 2nd at 06:00 (Dubai time)"
    assert "shorter months" in text({"frequency": "monthly", "time": "06:00", "day_of_month": 31})


def test_the_flow_is_an_active_python_flow_that_emails_the_file():
    definition = metronome.flow_definition(schedule(title='Sell-out: "EG" / KSA?'), "C:\\M\\x.py", 7)
    assert definition["name"] == "Wizard · Sell-out EG KSA · for Rafael · a1b2c3d4"
    assert definition["source_type"] == "python" and definition["python_run_mode"] == "outputs"
    assert definition["python_scripts"] == ["C:\\M\\x.py"] and definition["enabled"] is True
    assert definition["owner_person_id"] == 7 and definition["sql_handoff_enabled"] is False
    assert (definition["schedule_type"], definition["schedule_time"], definition["schedule_days"],
            definition["schedule_day"]) == ("weekly", "08:00", ["monday"], None)
    assert definition["email_delivery"] == {"enabled": True, "recipients": ["rafael@corp.test", "cfo@corp.test"],
                                            "subject": "Sell-out EG KSA"}
    assert definition["file_format"] == "xlsx" and definition["filename_template"] == "Sell-out EG KSA {date}.xlsx"
    assert metronome.safe_title("مبيعات: الأسبوع/الماضي") == "مبيعات الأسبوع الماضي", "letters of any language stay"
    monthly = metronome.flow_definition(schedule(frequency="monthly", day_of_month=3, days=["monday"]), "/s.py", 7)
    assert monthly["schedule_days"] == [] and monthly["schedule_day"] == 3


def test_the_client_creates_the_flow_as_the_wizard_user():
    fake = FakeMetronome()
    flow = MetronomeClient(SETTINGS, fake.transport()).create(schedule())
    assert fake.calls == ["GET /api/me", "POST /api/flows/transform-script", "POST /api/flows"]
    assert flow["id"] == 41 and flow["owner"] == "Wizard" and flow["next_run_at"] == "2026-10-26T04:00:00Z"
    created = fake.flows[0]
    assert created["owner_person_id"] == 7 and created["owner_name"] == "Wizard"
    [(path, script)] = fake.scripts.items()
    assert created["python_scripts"] == [path] and path.endswith("wizard_brief_a1b2c3d4.py")
    assert repr(metronome.brief_json(schedule())) in script, "the brief travels inside the script as a literal"


@pytest.mark.parametrize(("key", "message"), [("wizard-" + "x" * 40, "not signed in"), ("rafael-" + "x" * 40, "as Rafael")])
def test_a_key_that_is_not_wizard_creates_nothing(key, message):
    fake = FakeMetronome()
    fake.keys["rafael-" + "x" * 40] = 1
    client = MetronomeClient(MetronomeSettings(SETTINGS.url, key, "Wizard"), fake.transport())
    with pytest.raises(MetronomeError, match=message) as error:
        client.create(schedule())
    assert not error.value.uncertain and fake.calls == ["GET /api/me"] and not fake.flows
    assert client.check()["ok"] is False


@pytest.mark.parametrize(("failure", "uncertain"), [("timeout", True), (500, True), (409, False)])
def test_an_unconfirmed_create_is_uncertain_and_a_refusal_is_not(failure, uncertain):
    fake = FakeMetronome()
    fake.fail_create = failure
    with pytest.raises(MetronomeError) as error:
        MetronomeClient(SETTINGS, fake.transport()).create(schedule())
    assert error.value.uncertain is uncertain
    assert ("may have been created" in error.value.message) is uncertain


def test_check_names_the_user_and_an_unreachable_metronome():
    assert MetronomeClient(SETTINGS, FakeMetronome().transport()).check() == {
        "ok": True, "message": "Connected to Metronome at http://metronome.corp:8000 as Wizard (user 7). Recurring "
                               "extractions Wizard creates belong to Wizard."}

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)
    found = MetronomeClient(SETTINGS, httpx.MockTransport(down)).check()
    assert found["ok"] is False and "not reachable" in found["message"]


def test_status_reads_each_flow_and_its_latest_runs():
    fake = FakeMetronome()
    client = MetronomeClient(SETTINGS, fake.transport())
    client.create(schedule())
    fake.run(41, "failed", email=None, error="relation bi_reporting.sell_out does not exist")
    fake.run(41)
    found = client.status([41, 99], runs=5)
    assert found[99] == {"missing": True}
    flow = found[41]
    assert flow["enabled"] is True and flow["owner"] == "Wizard" and flow["next_run_at"] == "2026-10-26T04:00:00Z"
    assert flow["last_status"] == "succeeded" and flow["last_run_at"] == "2026-10-26T04:01:10Z"
    assert [(r["status"], r["email"]) for r in flow["runs"]] == [("succeeded", "submitted"), ("failed", None)]
    assert flow["runs"][1]["error"].startswith("relation") and "run_folder" not in flow["runs"][0]
    fake.fail_sync = True
    with pytest.raises(MetronomeError, match="not reachable"):
        client.status([41])


def test_delete_only_turns_the_flow_off_and_only_as_wizard():
    fake = FakeMetronome()
    client = MetronomeClient(SETTINGS, fake.transport())
    client.create(schedule())
    assert client.deactivate(41) == {"missing": False, "enabled": False}
    assert fake.flows[0]["enabled"] is False and len(fake.flows) == 1, "Metronome keeps the Flow"
    assert fake.calls[-2:] == ["GET /api/me", "PATCH /api/flows/41/enabled"] and not any("DELETE" in c for c in fake.calls)
    assert client.deactivate(99) == {"missing": True, "enabled": False}
    fake.keys["rafael-" + "x" * 40] = 1
    other = MetronomeClient(MetronomeSettings(SETTINGS.url, "rafael-" + "x" * 40, "Wizard"), fake.transport())
    with pytest.raises(MetronomeError, match="as Rafael"):
        other.deactivate(41)
    fake.flows[0]["owner_person_id"] = 1
    with pytest.raises(MetronomeError, match="refused to turn the Flow off .403"):
        client.deactivate(41)


# The generated script, run as Metronome runs it, with fake psycopg2, openpyxl and matplotlib modules -------------------
FAKE_PSYCOPG2 = '''
import datetime, decimal, json, os
LOG = os.environ["FAKE_PG_LOG"]
ROWS = int(os.environ.get("FAKE_PG_ROWS", "0"))
# What each query returns, found by the comment at its end.
ANSWERS = {
    "-- numbers": ([("units",), ("units_prev",)], [(decimal.Decimal("48210"), 45800)]),
    "-- markets": ([("market",), ("units",), ("units_prev",)],
                   [("UAE", 18420, 16980), ("Kuwait", 5310, 5620), ("Qatar", 4180, 3720)]),
    "-- weeks": ([("week",), ("at",)], [(datetime.date(2026, 10, 12),
                                        datetime.datetime(2026, 10, 12, 8, tzinfo=datetime.timezone.utc))]),
    "-- period": ([("period",)], [("Week 43",)]),
}
def log(event, **data):
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": event, **data}, default=str) + "\\n")
class Cursor:
    def execute(self, sql):
        log("execute", sql=sql)
        self.description, self.rows = next(v for k, v in ANSWERS.items() if k in sql)
        if ROWS:
            self.rows = self.rows[:1] * ROWS
    def fetchmany(self, size):
        return self.rows[:size]
class Connection:
    def set_session(self, **options):
        log("set_session", **options)
    def cursor(self):
        return Cursor()
    def rollback(self):
        log("rollback")
    def close(self):
        log("close")
def connect(**options):
    log("connect", **options)
    return Connection()
'''
FAKE_OPENPYXL = '''
import json
class Sheet:
    def __init__(self, title):
        self.title, self.rows = title, []
    def append(self, row):
        self.rows.append(row)
class Workbook:
    def __init__(self, write_only=False):
        assert write_only
        self.sheets = []
    def create_sheet(self, title):
        self.sheets.append(Sheet(title))
        return self.sheets[-1]
    def save(self, path):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([{"title": s.title, "rows": [[repr(v) for v in row] for row in s.rows]} for s in self.sheets], handle)
'''
# Enough of matplotlib for brief.png: it records the drawing and writes a stand-in PNG.
FAKE_MATPLOTLIB = '''
rcParams = {}
def use(backend):
    assert backend == "Agg"
'''
FAKE_PYPLOT = '''
class Axes:
    def __init__(self):
        self.calls = []
    def __getattr__(self, name):
        return lambda *args, **kwargs: self.calls.append(name)
class Figure:
    def add_axes(self, box):
        self.axes = Axes()
        return self.axes
    def savefig(self, path, dpi, facecolor):
        assert dpi == 200 and "text" in self.axes.calls and "add_patch" in self.axes.calls
        with open(path, "wb") as handle:
            handle.write(b"\\x89PNG fake")
def figure(figsize, dpi):
    return Figure()
def close(figure):
    pass
'''
FAKE_PATCHES = '''
def Circle(*args, **kwargs): return ("circle", args)
def FancyBboxPatch(*args, **kwargs): return ("rect", args)
def Polygon(*args, **kwargs): return ("polygon", args)
'''


def brief_schedule(**overrides: Any) -> dict[str, Any]:
    the_brief = {
        "title": "Weekly sell-out by market", "intro": None, "database": "analytics",
        "period_sql": "SELECT 'Week 43' AS period -- period", "cadence": "Every Monday at 08:00",
        "requested_by": "Rafael", "created_on": "20 Oct 2026",
        "sections": [
            {"kind": "numbers", "title": None, "subtitle": None, "sql": "SELECT units, units_prev FROM s -- numbers",
             "items": [{"label": "Units sold", "value": "units", "previous": "units_prev"}], "columns": [],
             "highlights": [{"rule": "change", "value": "units", "previous": "units_prev", "noun": "sell-out",
                             "lead": True}]},
            {"kind": "chart", "title": "Units by market", "subtitle": None, "chart": "bar", "x": "market",
             "series": ["units", "units_prev"], "change": True, "sql": "SELECT market, units, units_prev FROM m -- markets",
             "columns": [{"key": "units", "label": "This week"}], "highlights": [
                 {"rule": "fell", "label": "market", "value": "units", "previous": "units_prev"}]},
            {"kind": "table", "title": "Weeks", "subtitle": None, "sql": "SELECT week, at FROM w -- weeks",
             "columns": [], "max_rows": 10, "highlights": []},
        ]}
    return schedule(kind="brief", brief=the_brief, **overrides)


def run_script(tmp_path: Path, text: str, output: str, *, plots: bool = True, email: bool = True,
               **env: str) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
    fakes = tmp_path / "fakes"
    for name, source in (("psycopg2", FAKE_PSYCOPG2), ("openpyxl", FAKE_OPENPYXL)):
        (fakes / name).mkdir(parents=True, exist_ok=True)
        (fakes / name / "__init__.py").write_text(source, encoding="utf-8")
    (fakes / "matplotlib").mkdir(parents=True, exist_ok=True)
    (fakes / "matplotlib" / "__init__.py").write_text(
        FAKE_MATPLOTLIB if plots else "raise ImportError('No module named matplotlib')\n", encoding="utf-8")
    (fakes / "matplotlib" / "pyplot.py").write_text(FAKE_PYPLOT, encoding="utf-8")
    (fakes / "matplotlib" / "patches.py").write_text(FAKE_PATCHES, encoding="utf-8")
    script = tmp_path / "wizard_brief.py"
    script.write_text(text, encoding="utf-8")
    log = tmp_path / "pg.log"
    log.unlink(missing_ok=True)
    folder = tmp_path / "email"  # Metronome names it; the script creates it
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("PG", "WIZARD_EXTRACT_", "DG_", "METRONOME_"))}
    extra = {"METRONOME_FLOW_EMAIL_DIR": str(folder)} if email else {}
    done = subprocess.run([sys.executable, str(script), "--output", str(tmp_path / output)],
                          capture_output=True, text=True, timeout=120, check=False,
                          env={**clean, "PYTHONPATH": str(fakes), "FAKE_PG_LOG": str(log), **extra, **env})
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    return done, events


def test_the_script_runs_every_query_read_only_and_writes_excel_and_the_email(tmp_path):
    text = metronome.brief_script(brief_schedule())
    compile(text, "wizard_brief.py", "exec")
    done, events = run_script(tmp_path, text, "out.xlsx", PGHOST="db.corp", PGUSER="scanner", PGPASSWORD="pw",
                              DG_UPLOAD_PGUSER="uploader", WIZARD_EXTRACT_PGUSER="wizard_ro")
    assert done.returncode == 0, done.stderr
    connect = events[0]
    assert connect["event"] == "connect" and connect["user"] == "wizard_ro", "the dedicated account wins, never the uploader"
    assert connect["host"] == "db.corp" and connect["dbname"] == "analytics" and connect["password"] == "pw"
    assert "default_transaction_read_only=on" in connect["options"] and "statement_timeout" in connect["options"]
    assert events[1] == {"event": "set_session", "readonly": True, "autocommit": False}
    sent = [e["sql"] for e in events if e["event"] == "execute"]
    assert sent[0] == "SELECT * FROM (\nSELECT units, units_prev FROM s -- numbers\n) AS wizard_brief LIMIT 100001"
    assert len(sent) == 4 and sent[-1].startswith("SELECT * FROM (\nSELECT 'Week 43'"), "three sections, then the period"
    assert [e["event"] for e in events[-2:]] == ["rollback", "close"] and sum(e["event"] == "connect" for e in events) == 1
    book = json.loads((tmp_path / "out.xlsx").read_text(encoding="utf-8"))
    assert [sheet["title"] for sheet in book] == ["Section 1", "Units by market", "Weeks"]
    assert book[1]["rows"][0] == ["'Market'", "'This week'", "'Units prev'"] and len(book[1]["rows"]) == 4
    assert book[2]["rows"][1] == ["datetime.date(2026, 10, 12)", "datetime.datetime(2026, 10, 12, 8, 0)"], \
        "Excel gets plain values, without a time zone"
    body = (tmp_path / "email" / "body.html").read_text(encoding="utf-8")
    assert "Weekly sell-out by market" in body and "Week 43 · data read" in body
    assert "Sell-out rose 5.3% to 48,210, from 45,800." in body and "Kuwait was the only one down" in body
    assert 'src="cid:chart-2.png"' in body and (tmp_path / "email" / "chart-2.png").read_bytes().startswith(b"\x89PNG")
    assert "Wrote 5 rows in 3 sheets." in done.stdout


def test_without_matplotlib_or_an_email_folder_the_file_still_goes(tmp_path):
    text = metronome.brief_script(brief_schedule())
    done, _ = run_script(tmp_path, text, "out.xlsx", plots=False, PGHOST="db.corp", PGUSER="scanner")
    assert done.returncode == 0, done.stderr
    assert "matplotlib is not installed on this worker" in done.stderr
    body = (tmp_path / "email" / "body.html").read_text(encoding="utf-8")
    assert "cid:" not in body and ">Kuwait<" in body, "the chart goes in as its table"
    done, _ = run_script(tmp_path / "plain", text, "out.xlsx", email=False, PGHOST="db.corp", PGUSER="scanner")
    assert done.returncode == 0 and not (tmp_path / "plain" / "email" / "body.html").exists()
    assert (tmp_path / "plain" / "out.xlsx").exists(), "an older Metronome gets the Excel file as before"


def test_the_script_caps_rows(tmp_path):
    text = metronome.brief_script(brief_schedule(title='Sell-out """ injected'))
    assert text.startswith('"""Wizard recurring brief: Sell-out injected\n'), "a title cannot close the docstring"
    done, _ = run_script(tmp_path, text, "out.xlsx", email=False, PGHOST="db.corp", PGUSER="scanner",
                         FAKE_PG_ROWS="100001")
    assert done.returncode == 0, done.stderr
    assert "Only the first 100000 rows of a query were kept" in done.stderr
    book = json.loads((tmp_path / "out.xlsx").read_text(encoding="utf-8"))
    assert len(book[1]["rows"]) == 100_001, "a header and 100,000 rows"


def test_the_script_refuses_a_changed_brief_and_a_missing_account(tmp_path):
    text = metronome.brief_script(brief_schedule())
    changed = text.replace("FROM m -- markets", "FROM m UNION SELECT usename, 1, 1 FROM pg_user -- markets", 1)
    assert changed != text
    done, events = run_script(tmp_path, changed, "out.xlsx", PGHOST="db.corp", PGUSER="scanner")
    assert done.returncode == 1 and "changed after Wizard created it" in done.stderr and not events
    done, events = run_script(tmp_path, text, "out.xlsx", DG_UPLOAD_PGHOST="db.corp", DG_UPLOAD_PGUSER="uploader")
    assert done.returncode == 1 and "No read-only database account" in done.stderr and not events


def test_a_proposal_from_before_briefs_still_runs(tmp_path):
    old = schedule()
    assert metronome.brief_of(old)["sections"][0]["sql"] == old["sql"]
    assert metronome.brief_of(old)["cadence"] == "Every Monday at 08:00"
    assert 'id="' not in metronome.preview_html({**old, "preview": {"columns": ["market"], "rows": [["EG"]]}})
    assert ">EG<" in metronome.preview_html({**old, "preview": {"columns": ["market"], "rows": [["EG"]]}})


def test_the_preview_is_the_email_with_svg_charts():
    page = metronome.preview_html({**brief_schedule(), "preview": {
        "results": [{"columns": ["units", "units_prev"], "rows": [[48210, 45800]]},
                    {"columns": ["market", "units", "units_prev"], "rows": [["UAE", 18420, 16980], ["Kuwait", 5310, 5620]]},
                    {"columns": ["week", "at"], "rows": []}],
        "period": "Week 43", "read_at": "2026-10-23T05:00:00+00:00"}})
    assert 'src="data:image/svg+xml;base64,' in page and "data read 23 Oct 2026, 09:00 Dubai time" in page
    assert "Sell-out rose 5.3%" in page and "No rows this time." in page


# The link script ---------------------------------------------------------------------------------------------------------
@pytest.fixture
def metronome_server():
    fake = FakeMetronome()

    class Handler(BaseHTTPRequestHandler):
        def _answer(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            request = httpx.Request(self.command, f"http://metronome{self.path}", headers=dict(self.headers),
                                    content=self.rfile.read(length) if length else b"")
            response = fake.handler(request)
            self.send_response(response.status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(response.content)

        do_GET = do_POST = _answer

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield fake, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def link(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "metronome_link.py"), *args], capture_output=True,
                          text=True, timeout=60, check=False, env={**os.environ, "HTTP_PROXY": "http://127.0.0.1:9"})


def test_the_link_script_signs_a_new_key_in_as_wizard(metronome_server):
    fake, url = metronome_server
    done = link("--url", url)
    assert done.returncode == 0, done.stderr
    key = done.stdout.split("WIZARD_METRONOME_CLIENT_KEY=", 1)[1].strip()
    assert metronome.CLIENT_KEY.match(key) and fake.keys[key] == 7, "the printed key is signed in as Wizard"
    assert "Signed in to Metronome as Wizard (user 7)" in done.stdout


def test_the_link_script_explains_what_is_missing(metronome_server):
    fake, url = metronome_server
    done = link("--url", url, "--user", "Robot")
    assert done.returncode == 1 and "no user named Robot" in done.stderr
    fake.keys["rafael-" + "x" * 40] = 1
    done = link("--url", url, "--key", "rafael-" + "x" * 40)
    assert done.returncode == 1 and "409" in done.stderr and "host PC" in done.stderr
    assert fake.keys["rafael-" + "x" * 40] == 1, "a computer signed in as someone else stays theirs"


def test_values_reach_the_script_only_as_literals():
    hostile = brief_schedule(title='x"""; import os #')
    hostile["brief"]["sections"][2]["sql"] = "SELECT '\"\"\"; import os; os.system(\"x\") #' AS s -- weeks"
    hostile["brief"]["database"] = "db'); import os #"
    text = metronome.brief_script(hostile)
    namespace: dict[str, Any] = {"__name__": "not_main"}
    exec(compile(text, "s.py", "exec"), namespace)  # noqa: S102 - the point: running it defines only literals and functions
    assert json.loads(namespace["BRIEF_JSON"]) == hostile["brief"] and namespace["MAX_ROWS"] == metronome.MAX_EXTRACT_ROWS
    assert namespace["cell"](dt.datetime(2026, 1, 1, tzinfo=dt.UTC)).tzinfo is None and namespace["cell"](Decimal(1)) == 1
    assert metronome.renderer_source() in text, "the renderer is Wizard's own file, verbatim"
