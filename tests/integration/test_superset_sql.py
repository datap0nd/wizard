"""W.superset.sql in a real Chromium, against fake Superset servers on this machine: one that serves SQL Lab only at
the legacy address (POST /superset/sql_json/, Superset 1.x and 2.0), one only at the REST address
(POST /api/v1/sqllab/execute/, 3.0 on) and one at both (2.1). They answer the way those versions' source answers:
the same JSON shapes, the REST schema's field list, a 202 and a query to follow for a background query, its rows in a
results backend, Flask-WTF's CSRF refusal, FAB's 401 and 403, a typed table-access 403, an engine error as a 500 with
issue codes, and the router's 404. Everything here is synthetic: no host, table or row comes from a real instance.

Needs a Chromium or Chrome (WIZARD_TEST_BROWSER, Playwright's browser cache, or an installed Chrome); BLOCKED otherwise."""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from tests.helpers import TEST_TMP, MemoryRecorder
from tests.integration.test_portal_browser import BROWSER

from wizard_connectors.entitlements import Identity, SystemRights
from wizard_connectors.portal_browser import PortalBrowsers
from wizard_connectors.portals import settings_from, sql_problem
from wizard_connectors.tools import ToolContext, build_registry, build_services

pytestmark = [pytest.mark.browser,
              pytest.mark.skipif(BROWSER is None, reason="BLOCKED: no Chromium or Chrome for the portal browser tests "
                                                         "(set WIZARD_TEST_BROWSER)")]

LEGACY, API = "/superset/sql_json/", "/api/v1/sqllab/execute/"
# Superset's answer for an address its router does not have (the work PC saw this for /api/v1/sqllab/execute/).
NOT_FOUND = {"errors": [{"message": "404 Not Found: The requested URL was not found on the server. If you entered the URL "
                                    "manually please check your spelling and try again.",
                         "error_type": "GENERIC_BACKEND_ERROR", "level": "error",
                         "extra": {"issue_codes": [{"code": 1011, "message": "Issue 1011 - Superset encountered an "
                                                                             "unexpected error."}]}}]}
# ExecutePayloadSchema (Superset 2.1 to 6.0): marshmallow refuses any other field with a 400.
EXECUTE_FIELDS = {"database_id", "sql", "client_id", "queryLimit", "sql_editor_id", "catalog", "schema", "tab",
                  "ctas_method", "templateParams", "tmp_table_name", "select_as_cta", "json", "runAsync", "expand_data"}
ENGINE_ERROR = {"errors": [{"message": "bigquery error: 400 Unrecognized name: missing_col at [1:8]",
                            "error_type": "GENERIC_DB_ENGINE_ERROR", "level": "error",
                            "extra": {"engine_name": "Google BigQuery", "issue_codes": [
                                {"code": 1002, "message": "Issue 1002 - The database returned an unexpected error."}]}}]}
TABLE_ACCESS = {"errors": [{"message": "You need access to the following tables: `sales_daily`, `all_database_access` or "
                                       "`all_datasource_access` permission",
                            "error_type": "TABLE_SECURITY_ACCESS_ERROR", "level": "error",
                            "extra": {"issue_codes": [{"code": 1017, "message": "Issue 1017 - User doesn't have the "
                                                                                "proper permissions."}]}}]}


class SqlFailed(Exception):
    pass


class FakeSuperset:
    """A Superset instance: which SQL Lab addresses it serves, how its sign-in and CSRF token behave, and a tiny engine
    over synthetic tables. Database 1 runs queries in the foreground, database 2 in the background (allow_run_async)."""

    def __init__(self, routes: tuple[str, ...], csrf: str = "ok", auth: str = "ok"):
        self.routes, self.csrf_mode, self.auth = set(routes), csrf, auth
        self.token, self.rotations = "csrf-1", 0
        self.hits: list[str] = []
        self.bodies: list[dict[str, Any]] = []
        self.queries: dict[str, dict[str, Any]] = {}
        self.results: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), SupersetHandler)
        self.server.superset = self  # type: ignore[attr-defined]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/"

    def posts(self) -> list[str]:
        return [h.split(" ", 2)[1] for h in self.hits if h.startswith("POST ")]

    def columns(self, names: list[tuple[str, str]]) -> list[dict[str, Any]]:
        # 1.x and 2.0 name a result column "name"; 3.0 on adds "column_name".
        rest = self.routes != {"legacy"}
        return [{**({"column_name": n} if rest else {}), "name": n, "type": t, "is_dttm": False} for n, t in names]

    def run(self, sql: str, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        text = " ".join(sql.split()).lower()
        if "missing_col" in text:
            raise SqlFailed
        if "slow" in text:
            time.sleep(4)
        if text == "select 1":
            return self.columns([("1", "INT64")]), [{"1": 1}]
        if "from sales_daily" in text:
            data = [{"market": "AE", "units": 120, "as_of": "2026-11-01"}, {"market": "SA", "units": None, "as_of": "2026-11-01"},
                    {"market": "KW", "as_of": "2026-11-01"}]
            return self.columns([("market", "STRING"), ("units", "INT64"), ("as_of", "DATE")]), data[:limit]
        if "from numbers" in text:  # a server that ignores the row limit
            return self.columns([("n", "INT64")]), [{"n": n} for n in range(1, 6)]
        return self.columns([("ok", "BOOL")]), [{"ok": True}]

    def to_dict(self, query: dict[str, Any]) -> dict[str, Any]:
        return {"id": query["client_id"], "queryId": query["id"], "state": query["state"], "startDttm": query["start"],
                "changedOn": query["start"], "resultsKey": query.get("key"), "errorMessage": query.get("error"),
                "limitingFactor": "NOT_LIMITED", "extra": {"errors": query.get("errors", [])}}

    def advance(self) -> None:
        """A background query is running on the first look and done on the second, as a Celery worker would be."""
        for query in self.queries.values():
            if query["state"] not in ("pending", "running"):
                continue
            query["looks"] += 1
            if query["looks"] < 2:
                query["state"] = "running"
                continue
            try:
                columns, data = self.run(query["sql"], query["limit"])
            except SqlFailed:
                query.update(state="failed", error=ENGINE_ERROR["errors"][0]["message"], errors=ENGINE_ERROR["errors"])
                continue
            query.update(state="success", key=f"rk-{query['client_id']}")
            self.results[query["key"]] = {"status": "success", "data": data, "columns": columns,
                                          "query": self.to_dict(query)}


class SupersetHandler(BaseHTTPRequestHandler):
    server: Any

    def log_message(self, *args: Any) -> None:
        pass

    def reply(self, status: int, body: Any, kind: str = "application/json") -> None:
        data = (json.dumps(body) if kind == "application/json" else body).encode()
        try:
            self.send_response(status)
            self.send_header("content-type", kind)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the browser gave up (a timeout test)

    def do_GET(self) -> None:  # noqa: N802 - http.server's name
        s: FakeSuperset = self.server.superset
        s.hits.append(f"GET {self.path}")
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        if path == "/sqllab/":
            self.reply(200, f"<title>Superset</title><input type=hidden id=csrf_token name=csrf_token value={s.token}>"
                            "<div id=app>SQL Lab</div>", "text/html")
        elif path == "/api/v1/security/csrf_token/":
            self.reply(401, {"message": "Not authorized"}) if s.auth == "401" else self.reply(200, {"result": s.token})
        elif path == "/api/v1/database/":
            self.reply(200, {"count": 2, "result": [
                {"id": 1, "database_name": "warehouse", "backend": "bigquery", "allow_dml": False, "allow_run_async": False},
                {"id": 2, "database_name": "warehouse (background)", "backend": "bigquery", "allow_dml": False,
                 "allow_run_async": True}]})
        elif "legacy" in s.routes and re.fullmatch(r"/superset/queries/\d+", path):
            with s.lock:
                s.advance()
                self.reply(200, {q["client_id"]: s.to_dict(q) for q in s.queries.values()})
        elif "api" in s.routes and path == "/api/v1/query/updated_since" and \
                re.fullmatch(r"\(last_updated_ms:\d+\)", (query.get("q") or [""])[0]):
            with s.lock:
                s.advance()
                self.reply(200, {"result": [s.to_dict(q) for q in s.queries.values()]})
        elif "legacy" in s.routes and (found := re.fullmatch(r"/superset/results/([^/]+)/", path)):
            self.results(unquote(found.group(1)), int((query.get("rows") or ["1000000"])[0]))
        elif "api" in s.routes and path == "/api/v1/sqllab/results/" and \
                (found := re.fullmatch(r"\(key:'([^']+)',rows:(\d+)\)", (query.get("q") or [""])[0])):
            self.results(found.group(1), int(found.group(2)))
        else:
            self.reply(404, NOT_FOUND)

    def results(self, key: str, rows: int) -> None:
        payload = self.server.superset.results.get(key)
        if payload is None:
            self.reply(410, {"errors": [{"message": "Data could not be retrieved from the results backend. You need to "
                                                    "re-run the original query.", "error_type": "RESULTS_BACKEND_ERROR",
                                         "level": "error", "extra": {}}]})
            return
        self.reply(200, {**payload, "data": payload["data"][:rows]})

    def do_POST(self) -> None:  # noqa: N802
        s: FakeSuperset = self.server.superset
        raw = self.rfile.read(int(self.headers.get("content-length") or 0)).decode()
        s.hits.append(f"POST {self.path} {raw[:200]}")
        route = {LEGACY: "legacy", API: "api"}.get(self.path)
        if route not in s.routes:
            self.reply(404, NOT_FOUND)
            return
        if s.auth == "401":
            self.reply(401, {"message": "Not authorized"})
            return
        if s.auth == "403":
            self.reply(403, {"message": "Forbidden"})
            return
        if self.headers.get("X-CSRFToken") != s.token or s.csrf_mode == "always" or \
                (s.csrf_mode == "expires_once" and not s.rotations):
            s.rotations += 1
            s.token = f"csrf-{s.rotations + 1}"
            self.reply(400, {"errors": [{"message": "400 Bad Request: The CSRF token has expired.",
                                         "error_type": "GENERIC_BACKEND_ERROR", "level": "error", "extra": {}}]})
            return
        if (self.headers.get("content-type") or "").split(";")[0] != "application/json":
            self.reply(400, {"message": "Request is not JSON"})
            return
        body = json.loads(raw)
        s.bodies.append(body)
        unknown = sorted(set(body) - EXECUTE_FIELDS)
        if route == "api" and (unknown or "database_id" not in body or "sql" not in body):
            self.reply(400, {"message": {name: ["Unknown field."] for name in unknown} or "Missing data for required field."})
            return
        if s.auth == "table":
            self.reply(403, TABLE_ACCESS)
            return
        with s.lock:
            number = len(s.queries) + 1
            query = {"id": number, "client_id": body["client_id"], "sql": body["sql"], "limit": body["queryLimit"],
                     "state": "pending", "looks": 0, "start": time.time() * 1000}
            s.queries[body["client_id"]] = query
        if body.get("runAsync") and body["database_id"] == 2:
            self.reply(202, {"query": s.to_dict(query)})
            return
        try:
            columns, data = s.run(body["sql"], int(body["queryLimit"]))
        except SqlFailed:
            query["state"] = "failed"
            self.reply(500, ENGINE_ERROR)
            return
        query["state"] = "success"
        self.reply(200, {"query_id": number, "status": "success", "data": data, "columns": columns,
                         "selected_columns": columns, "expanded_columns": [], "query": s.to_dict(query)})


@pytest.fixture(scope="module")
def setup() -> Iterator[tuple[Any, Any]]:
    TEST_TMP.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="superset-", dir=TEST_TMP))
    # Superset's address in Settings → Portals; each test's own Superset is another port on the same host.
    settings = settings_from({"WIZARD_PORTAL_BDP_URL": "http://127.0.0.1:9/sqllab/", "WIZARD_BROWSER_EXECUTABLE": BROWSER})
    assert settings is not None
    services = build_services()
    services.portals = PortalBrowsers(settings, lambda user_id: root / user_id)
    yield services, build_registry(services)
    services.portals.shutdown()
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture()
def superset() -> Iterator[Any]:
    made: list[FakeSuperset] = []

    def make(*routes: str, **behaviour: str) -> FakeSuperset:
        made.append(FakeSuperset(routes, **behaviour))
        return made[-1]
    yield make
    for instance in made:
        instance.server.shutdown()


def query(setup: tuple[Any, Any], instance: FakeSuperset, *scripts: str, recorder: MemoryRecorder | None = None) -> Any:
    """portal_run on the Big Data Portal: open this Superset's SQL Lab, then one evaluate step per script."""
    services, registry = setup
    identity = Identity(id="owner", email="owner@example.com", name="Owner", role="Owner",
                        entitlements={"bdp": SystemRights(reports=["*"], markets=["*"])})
    context = ToolContext(identity=identity, run_id="run_t", recorder=recorder or MemoryRecorder(), services=services)
    steps = [{"action": "goto", "url": instance.url + "sqllab/"}]
    steps += [{"action": "evaluate", "script": script, "timeout_ms": 20_000} for script in scripts]
    return registry.execute("portal_run", {"system": "bdp", "title": "Superset query", "steps": steps}, context)


def run(setup: tuple[Any, Any], instance: FakeSuperset, sql: str, options: str = "{}", database: int = 1) -> Any:
    """The helper's own return value for one query (wrapped as JSON text so Wizard does not turn it into a table)."""
    outcome = query(setup, instance, f"return JSON.stringify(await W.superset.sql({database}, {json.dumps(sql)}, {options}));")
    assert outcome.ok and "stopped" not in outcome.data, outcome.error_message or outcome.data["stopped"]["message"]
    return json.loads(outcome.data["outputs"][-1]["value"])


def failure(setup: tuple[Any, Any], instance: FakeSuperset, sql: str, options: str = "{}", database: int = 1) -> str:
    outcome = query(setup, instance, f"return await W.superset.sql({database}, {json.dumps(sql)}, {options});")
    assert outcome.ok, "a failed query stops at its step: the run and the steps before it stand"
    assert outcome.data["stopped"]["code"] == "step_failed"
    return outcome.data["stopped"]["message"]


@pytest.mark.parametrize(("routes", "posted"), [
    (("legacy",), [API, LEGACY]),  # Superset 1.x / 2.0: the REST address is not there, so the legacy one answers
    (("api",), [API]),             # 3.0 on
    (("legacy", "api"), [API]),    # 2.1 serves both: the REST one is used, the query runs once
])
def test_select_1_runs_on_every_superset_version_and_the_address_that_answered_is_kept(setup, superset, routes, posted):
    instance = superset(*routes)
    assert run(setup, instance, "SELECT 1") == {"columns": ["1"], "rows": [[1]], "total_rows": 1}
    assert instance.posts() == posted
    assert run(setup, instance, "SELECT 1") == {"columns": ["1"], "rows": [[1]], "total_rows": 1}
    assert instance.posts() == posted + posted[-1:], "the next query, in a later call, goes straight to that address"
    for body in instance.bodies:
        assert body["runAsync"] is False and body["queryLimit"] == 1000 and body["select_as_cta"] is False
        assert len(body["client_id"]) <= 11 and set(body) <= EXECUTE_FIELDS, "the REST schema's fields only"


def test_a_superset_result_is_cited_as_live_evidence(setup, superset):
    recorder = MemoryRecorder()
    instance = superset("legacy")
    script = "return await W.superset.sql(1, 'SELECT market, units, as_of FROM sales_daily WHERE as_of = \\'2026-11-01\\'');"
    outcome = query(setup, instance, script, recorder=recorder)
    assert outcome.ok, outcome.error_message
    table = outcome.data["outputs"][-1]
    assert table["columns"] == ["market", "units", "as_of"]
    assert table["rows"] == [["AE", 120, "2026-11-01"], ["SA", None, "2026-11-01"], ["KW", None, "2026-11-01"]], \
        "column order, and null for a null or a missing value"
    assert table["cite_as"] == "[E1]" and recorder.evidence[0]["connector_status"] == "BROWSER_SESSION"


def test_the_row_limit_holds_when_superset_ignores_it(setup, superset):
    instance = superset("api")
    got = run(setup, instance, "SELECT n FROM numbers", "{limit: 3}")
    assert got == {"columns": ["n"], "rows": [[1], [2], [3]], "total_rows": 5, "limit_reached": True}
    assert instance.bodies[-1]["queryLimit"] == 3
    assert run(setup, instance, "SELECT n FROM numbers", "{limit: 10 ** 9}")["rows"][-1] == [5]
    assert instance.bodies[-1]["queryLimit"] == 50000, "never more than the rows a read keeps as evidence"


@pytest.mark.parametrize(("routes", "poll", "results"), [
    (("legacy",), "GET /superset/queries/", "GET /superset/results/rk-"),
    (("api",), "GET /api/v1/query/updated_since?q=", "GET /api/v1/sqllab/results/?q="),
])
def test_a_background_query_is_followed_and_its_rows_read_from_the_results_backend(setup, superset, routes, poll, results):
    instance = superset(*routes)
    got = run(setup, instance, "SELECT market, units, as_of FROM sales_daily", database=2)
    assert got["rows"][0] == ["AE", 120, "2026-11-01"] and got["total_rows"] == 3
    assert instance.bodies[-1]["runAsync"] is True, "database 2 runs in the background, as Superset's SQL Lab runs it"
    assert sum(h.startswith(poll) for h in instance.hits) == 2, "running, then success"
    assert sum(h.startswith(results) for h in instance.hits) == 1
    failed = failure(setup, instance, "SELECT missing_col FROM sales_daily", database=2)
    assert "failed in Superset GENERIC_DB_ENGINE_ERROR (issue 1002): bigquery error: 400 Unrecognized name: missing_col" in failed
    foreground = run(setup, instance, "SELECT 1", "{runAsync: false}", database=2)
    assert foreground["rows"] == [[1]] and instance.bodies[-1]["runAsync"] is False


def test_an_expired_csrf_token_is_refreshed_once_and_only_once(setup, superset):
    instance = superset("legacy", csrf="expires_once")
    assert run(setup, instance, "SELECT 1")["rows"] == [[1]]
    assert instance.posts() == [API, LEGACY, LEGACY], "the refused POST is sent again once, with a fresh token"
    stubborn = superset("api", csrf="always")
    message = failure(setup, stubborn, "SELECT 1")
    assert stubborn.posts() == [API, API]
    assert f"POST {API} answered 400 GENERIC_BACKEND_ERROR: 400 Bad Request: The CSRF token has expired." in message
    assert "refused its CSRF token twice" in message


def test_signed_out_and_no_permission_say_so(setup, superset):
    signed_out = superset("legacy", auth="401")
    message = failure(setup, signed_out, "SELECT 1")
    assert f"POST {API} (404), then at the fallback POST {LEGACY} (401): Not authorized" in message
    assert "Not signed in" in message and "Sign in to the portals" in message
    no_role = superset("legacy", "api", auth="403")
    message = failure(setup, no_role, "SELECT 1")
    assert f"refused at POST {API} (403), then at the fallback POST {LEGACY} (403): Forbidden" in message
    assert "No permission" in message
    no_table = superset("api", auth="table")
    message = failure(setup, no_table, "SELECT * FROM sales_daily")
    assert no_table.posts() == [API], "a refusal about the table is the answer: no other address is tried"
    assert f"POST {API} answered 403 TABLE_SECURITY_ACCESS_ERROR (issue 1017): You need access to the following tables" in message
    assert "information catalog" in message


def test_a_superset_without_sql_lab_names_both_addresses(setup, superset):
    message = failure(setup, superset(), "SELECT 1")
    assert f"not served at POST {API} (404), then at the fallback POST {LEGACY} (404): 404 Not Found: The requested URL" in message
    assert "Settings → Portals" in message


@pytest.mark.parametrize("routes", [("legacy",), ("api",)])
def test_a_sql_error_shows_supersets_message_and_is_not_retried(setup, superset, routes):
    instance = superset(*routes)
    route = LEGACY if routes == ("legacy",) else API
    message = failure(setup, instance, "SELECT missing_col FROM sales_daily")
    assert instance.posts().count(route) == 1
    assert (f"POST {route} answered 500 GENERIC_DB_ENGINE_ERROR (issue 1002): bigquery error: 400 Unrecognized name: "
            "missing_col at [1:8]") in message
    assert "Fix the SQL" in message


def test_a_query_that_takes_too_long_stops_and_the_browser_stays_usable(setup, superset):
    instance = superset("api")
    outcome = query(setup, instance, "return await W.superset.sql(1, 'SELECT 1');",
                    "return await W.superset.sql(1, 'SELECT slow FROM sales_daily', {timeout_ms: 1500});")
    assert outcome.ok and outcome.data["outputs"][1]["rows"] == [[1]], "the step before it keeps its rows"
    stopped = outcome.data["stopped"]
    assert stopped["code"] == "step_failed" and "Step 3" in stopped["message"]
    assert f"POST {API} got no answer in time." in stopped["message"] and "partition/date column" in stopped["message"]
    assert run(setup, instance, "SELECT 1")["rows"] == [[1]], "the next query runs in the same browser"


@pytest.mark.parametrize("sql", ["DELETE FROM sales_daily", "SELECT 1; DROP TABLE sales_daily",
                                 "WITH gone AS (DELETE FROM t RETURNING *) SELECT * FROM gone", "", "  ;  "])
def test_wizard_refuses_anything_but_one_select_before_sending(setup, superset, sql):
    instance = superset("legacy", "api")
    message = failure(setup, instance, sql)
    assert "Wizard refused the query before sending it: " + sql_problem(json.dumps({"sql": sql})) in message
    assert instance.posts() == [], "nothing reaches Superset"


CHECKED = [
    "SELECT 1", "select 1;", "SELECT 1;  -- done", "with x as (select 1) select * from x;", "  (SELECT 1)",
    "-- note; with semicolon\nSELECT ';' AS s", "SELECT 'it''s; fine', \"a;b\" FROM t", "SELECT e'a\\'; b' FROM t",
    "SELECT $$; drop$$ AS x", "SELECT /* nested /* ; */ */ 1", "SHOW TABLES", "DESCRIBE t", "EXPLAIN SELECT 1",
    "SELECT updated_at, delete_flag FROM t", "SELECT REPLACE(name, 'a', 'b'), comment FROM t",
    "SELECT * FROM `proj.dataset.sales` WHERE dt = '2026-11-01'", "DELETE FROM t", "SELECT 1; DROP TABLE t",
    "WITH gone AS (DELETE FROM t RETURNING *) SELECT * FROM gone", "SELECT * INTO copy FROM t",
    "EXPLAIN ANALYZE SELECT 1", "INSERT OVERWRITE TABLE t SELECT 1", "", "   ", ";", "SET x = 1", "CALL p()",
    "SELECT 1; SELECT 2", "SELECT 'unclosed", "update t set a = 1", "SELECT 1 -- ; DELETE", "VALUES (1)",
]


def test_the_page_reads_a_statement_exactly_as_wizards_guard_does(setup, superset):
    instance = superset("api")
    got = run_checks(setup, instance, CHECKED)
    assert got == [sql_problem(json.dumps({"sql": sql})) for sql in CHECKED]


def run_checks(setup: tuple[Any, Any], instance: FakeSuperset, corpus: list[str]) -> list[str | None]:
    outcome = query(setup, instance, f"return JSON.stringify({json.dumps(corpus)}.map(W.superset.check));")
    assert outcome.ok and "stopped" not in outcome.data, outcome.error_message or outcome.data["stopped"]["message"]
    return json.loads(outcome.data["outputs"][-1]["value"])
