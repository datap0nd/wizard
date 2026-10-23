"""wizard_schedule_brief: who may propose a recurring brief, what it checks, the test runs it records as live evidence,
and the proposal it leaves for the person to confirm. Nothing here reaches Metronome."""
from __future__ import annotations

from typing import Any

import pytest
from tests.helpers import WIZARD_KEY, MemoryRecorder
from tests.unit.test_postgres_query import SETTINGS, owner

from wizard_connectors.metronome import MetronomeSettings
from wizard_connectors.postgres_query import PostgresQuery
from wizard_connectors.tools import ToolContext, build_registry, build_services

TEXT, INT = 25, 20
# What each test query returns, found by the comment at its end.
RESULTS: dict[str, tuple[list[dict[str, Any]], list[list[Any]]]] = {
    "-- numbers": ([{"name": "units", "type_oid": INT}, {"name": "units_prev", "type_oid": INT}], [[48210, 45800]]),
    "-- markets": ([{"name": "market", "type_oid": TEXT}, {"name": "units", "type_oid": INT},
                    {"name": "units_prev", "type_oid": INT}],
                   [["UAE", 18420, 16980], ["Kuwait", 5310, 5620], ["Qatar", 4180, 3720]]),
    "-- models": ([{"name": "model", "type_oid": TEXT}, {"name": "units", "type_oid": INT}], [["Flagship", 6840]]),
    "-- period": ([{"name": "period", "type_oid": TEXT}], [["Week 43"]]),
}
ARGS = {
    "title": "Weekly sell-out by market", "recipients": ["O@corp.test", "cfo@corp.test", "o@corp.test"],
    "frequency": "weekly", "days": ["thursday", "monday"], "time": "08:00",
    "period_sql": "SELECT 'Week ' || to_char(CURRENT_DATE - 7, 'IW') AS period -- period",
    "sections": [
        {"kind": "numbers", "sql": "SELECT sum(units) AS units, sum(units_prev) AS units_prev FROM bi_reporting.sell_out "
                                   "-- numbers\n;",
         "items": [{"label": "Units sold", "value": "units", "previous": "units_prev", "compare": "vs last week"}],
         "highlights": [{"rule": "change", "value": "units", "previous": "units_prev", "noun": "sell-out", "lead": True}]},
        {"kind": "chart", "title": "Units by market", "chart": "bar", "x": "market", "series": ["units", "units_prev"],
         "change": True, "sql": "SELECT market, units, units_prev FROM bi_reporting.sell_out_by_market -- markets",
         "columns": [{"key": "units", "label": "This week"}, {"key": "units_prev", "label": "Last week"}],
         "highlights": [{"rule": "fell", "label": "market", "value": "units", "previous": "units_prev"}]},
        {"kind": "table", "title": "Top models", "max_rows": 5, "sql": "SELECT model, units FROM bi_reporting.models -- models"},
    ],
}


class BriefSession:
    """A read-only session whose query answers by the marker comment in the SQL."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        self.statements.append(sql)
        return []

    def query(self, sql: str) -> tuple[list[dict[str, Any]], list[list[Any]]]:
        self.statements.append(sql)
        return next(result for marker, result in RESULTS.items() if marker in sql)

    def close(self) -> None:
        pass


@pytest.fixture
def setup():
    services = build_services()
    sessions: list[BriefSession] = []

    def connect(settings: Any, database: str) -> BriefSession:
        sessions.append(BriefSession())
        return sessions[-1]
    services.postgres = PostgresQuery(SETTINGS, connect=connect)
    services.metronome = MetronomeSettings("http://metronome.corp:8000", WIZARD_KEY, "Wizard")
    registry = build_registry(services)

    def call(args: dict[str, Any], identity: Any = None, recorder: MemoryRecorder | None = None) -> Any:
        ctx = ToolContext(identity=identity or owner(), run_id="r", recorder=recorder or MemoryRecorder(), services=services)
        return registry.execute("wizard_schedule_brief", args, ctx)
    return services, sessions, call


def test_a_brief_is_test_run_recorded_and_left_for_the_person(setup):
    services, sessions, call = setup
    recorder = MemoryRecorder()
    outcome = call(ARGS, recorder=recorder)
    assert outcome.ok, outcome.error_message
    data = outcome.data
    assert data["schedule"] == "R1" and data["status"] == "awaiting_confirmation"
    assert data["evidence_ids"] == ["E1", "E2", "E3", "E4"] and data["cite_as"] == "[E1] [E2] [E3] [E4]"
    assert data["sends"] == "Every Monday and Thursday at 08:00 (Dubai time)"
    assert data["recipients"] == ["o@corp.test", "cfo@corp.test"], "addresses are compared without case and kept once"
    assert data["in_short"] == ["Sell-out rose 5.3% to 48,210, from 45,800."]
    assert data["sections"][1] == {"title": "Units by market", "kind": "chart", "rows_in_test": 3,
                                   "what_moved": ["Kuwait was the only one down: −5.5%, to 5,310."]}
    assert data["owner"] == "Metronome user Wizard" and "Nothing is scheduled yet" in data["note"] and not data["warnings"]
    assert len(sessions) == 4 and all(s.statements[0] == "START TRANSACTION READ ONLY" and s.statements[-1] == "ROLLBACK"
                                      for s in sessions), "every test query runs read-only and is rolled back"
    evidence = recorder.get_evidence("E1")
    assert evidence["tool"] == "wizard_schedule_brief" and evidence["data_mode"] == "LIVE"
    assert evidence["request"]["sql"].endswith("-- numbers"), "the evidence holds the query as tested, without its ';'"
    [proposal] = recorder.schedules
    assert proposal["kind"] == "brief" and proposal["days"] == ["monday", "thursday"] and len(proposal["ref"]) == 8
    assert proposal["requested_by"] == {"id": "o", "name": "O", "email": "o@corp.test"}
    assert proposal["metronome_user"] == "Wizard" and proposal["evidence_ids"] == data["evidence_ids"]
    assert proposal["file_format"] == "xlsx" and proposal["day_of_month"] is None and proposal["time"] == "08:00"
    the_brief = proposal["brief"]
    assert the_brief["cadence"] == "Every Monday and Thursday at 08:00" and the_brief["requested_by"] == "O"
    assert [s["sql"] for s in the_brief["sections"]] == [evidence["request"]["sql"], ARGS["sections"][1]["sql"],
                                                         ARGS["sections"][2]["sql"]]
    assert the_brief["period_sql"] == ARGS["period_sql"] and the_brief["sections"][1]["series"] == ["units", "units_prev"]
    assert proposal["preview"]["period"] == "Week 43" and len(proposal["preview"]["results"]) == 3
    assert proposal["preview"]["results"][1]["columns"] == ["market", "units", "units_prev"]


def test_by_default_it_goes_to_the_users_own_mailbox_at_eight(setup):
    _, _, call = setup
    recorder = MemoryRecorder()
    person = owner().model_copy(update={"email": "rafael@ax.corp.test"})
    small = {"title": "Weekly sell-out", "frequency": "weekly", "days": ["monday"], "sections": [ARGS["sections"][2]]}
    outcome = call(small, person, recorder)
    assert outcome.ok, outcome.error_message
    assert outcome.data["recipients"] == ["rafael@corp.test"], "the sign-in's ax. is not part of the mailbox"
    assert outcome.data["sends"] == "Every Monday at 08:00 (Dubai time)" and outcome.data["attachment"].endswith(".xlsx")
    named = call({**small, "recipients": ["cfo@ax.corp.test", "cfo@corp.test"]}, person)
    assert named.ok and named.data["recipients"] == ["cfo@corp.test"], "a named sign-in address becomes its mailbox"
    nobody = owner().model_copy(update={"email": ""})
    unknown = call({**small, "frequency": "daily", "days": []}, nobody)
    assert unknown.error_code == "invalid_schedule" and "ask who should receive it" in unknown.error_message


def section(index: int, **change: Any) -> list[dict[str, Any]]:
    sections = [dict(s) for s in ARGS["sections"]]
    sections[index] = {**sections[index], **change}
    return sections


@pytest.mark.parametrize(("change", "code", "message"), [
    ({"sections": section(2, sql="SELECT 1; DELETE FROM bi_reporting.sell_out")}, "invalid_sql", "one query"),
    ({"period_sql": "SELECT 1; SELECT 2"}, "invalid_sql", "one query"),
    ({"recipients": ["friend@gmail.com"]}, "invalid_schedule", "outside"),
    ({"days": []}, "invalid_schedule", "needs its weekdays"),
    ({"frequency": "monthly", "days": []}, "invalid_schedule", "day_of_month"),
    ({"time": "8am"}, "invalid_arguments", "time"),
    ({"recipients": [f"p{i}@corp.test" for i in range(21)]}, "invalid_arguments", "recipients"),
    ({"sections": section(0, items=[])}, "invalid_arguments", "one to four items"),
    ({"sections": section(1, x=None)}, "invalid_arguments", "needs chart"),
    ({"sections": section(1, highlights=[{"rule": "fell", "label": "market", "value": "units"}])}, "invalid_arguments",
     "needs previous"),
    ({"sections": section(1, highlights=[{"rule": "above", "label": "market", "value": "units"}])}, "invalid_arguments",
     "needs threshold"),
    ({"sections": section(1, highlights=[{"rule": "largest", "value": "units"}])}, "invalid_arguments", "needs label"),
    ({"sections": [ARGS["sections"][2]] * 9}, "invalid_arguments", "sections"),
    ({"sections": []}, "invalid_arguments", "sections"),
])
def test_what_cannot_be_scheduled_is_refused_before_any_query(setup, change, code, message):
    _, sessions, call = setup
    outcome = call({**ARGS, **change})
    assert outcome.error_code == code and message in outcome.error_message
    assert not sessions, "nothing runs for a refused brief"


def test_columns_the_queries_do_not_return_are_named(setup):
    _, sessions, call = setup
    recorder = MemoryRecorder()
    sections = section(1, series=["units", "last_week"], highlights=[{"rule": "largest", "label": "country",
                                                                       "value": "units"}])
    outcome = call({**ARGS, "sections": sections}, recorder=recorder)
    assert outcome.error_code == "invalid_brief" and sessions, "the queries ran: their columns decide"
    assert outcome.error_message.startswith("Section 2 (Units by market): country, last_week are not among its query's "
                                            "columns (market, units, units_prev).")
    assert not recorder.schedules, "no proposal for a brief that cannot be drawn"


def test_company_domains_decide_who_may_receive_it(setup):
    services, _, call = setup
    services.mail_domains = ["ax.company.example"]
    try:
        assert call(ARGS).error_code == "invalid_schedule", "WIZARD_GOOGLE_DOMAINS replaces the requester's own domain"
        assert call({**ARGS, "recipients": ["cfo@company.example"]}).ok, "a sign-in domain also allows its mailboxes"
    finally:
        services.mail_domains = []


def test_rights_and_connections(setup, identities):
    services, sessions, call = setup
    assert call(ARGS, identities.get("u-ceo")).error_code == "not_entitled"
    assert call(ARGS, owner(markets=["EG"])).error_code == "not_entitled", "a free query cannot be limited to markets"
    services.metronome = None
    assert call(ARGS).error_code == "metronome_unavailable"
    assert not sessions
