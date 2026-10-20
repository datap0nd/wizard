"""wizard_schedule_extraction: who may propose a recurring extraction, what it checks, the test run it records as live
evidence, and the proposal it leaves for the person to confirm. Nothing here reaches Metronome."""
from __future__ import annotations

from typing import Any

import pytest
from tests.helpers import WIZARD_KEY, MemoryRecorder
from tests.unit.test_postgres_query import SETTINGS, FakeSession, owner

from wizard_connectors.metronome import MetronomeSettings
from wizard_connectors.postgres_query import PostgresQuery
from wizard_connectors.tools import ToolContext, build_registry, build_services

ARGS = {"title": "Weekly sell-out by market", "recipients": ["O@corp.test", "cfo@corp.test", "o@corp.test"],
        "sql": "SELECT market, sum(units) AS units FROM bi_reporting.sell_out "
               "WHERE week_start >= date_trunc('week', CURRENT_DATE) - interval '7 days' GROUP BY 1;",
        "frequency": "weekly", "days": ["thursday", "monday"], "time": "08:00"}


@pytest.fixture
def setup():
    services = build_services()
    sessions: list[FakeSession] = []

    def connect(settings: Any, database: str) -> FakeSession:
        sessions.append(FakeSession())
        return sessions[-1]
    services.postgres = PostgresQuery(SETTINGS, connect=connect)
    services.metronome = MetronomeSettings("http://metronome.corp:8000", WIZARD_KEY, "Wizard")
    registry = build_registry(services)

    def call(args: dict[str, Any], identity: Any = None, recorder: MemoryRecorder | None = None) -> Any:
        ctx = ToolContext(identity=identity or owner(), run_id="r", recorder=recorder or MemoryRecorder(), services=services)
        return registry.execute("wizard_schedule_extraction", args, ctx)
    return services, sessions, call


def test_a_proposal_is_test_run_recorded_and_left_for_the_person(setup):
    services, sessions, call = setup
    recorder = MemoryRecorder()
    outcome = call(ARGS, recorder=recorder)
    assert outcome.ok, outcome.error_message
    data = outcome.data
    assert data["schedule"] == "R1" and data["status"] == "awaiting_confirmation" and data["cite_as"] == "[E1]"
    assert data["sends"] == "Every Monday and Thursday at 08:00 (Dubai time)"
    assert data["recipients"] == ["o@corp.test", "cfo@corp.test"], "addresses are compared without case and kept once"
    assert data["owner"] == "Metronome user Wizard" and "Nothing is scheduled yet" in data["note"]
    assert data["test_run"]["columns"] == ["market", "units", "amount", "amount_2", "week_start"]
    [session] = sessions
    assert session.statements[0] == "START TRANSACTION READ ONLY" and session.statements[-1] == "ROLLBACK"
    evidence = recorder.get_evidence("E1")
    assert evidence["tool"] == "wizard_schedule_extraction" and evidence["data_mode"] == "LIVE"
    assert evidence["request"]["sql"] == ARGS["sql"].rstrip(";"), "the schedule and its evidence hold the query as tested"
    [proposal] = recorder.schedules
    assert proposal["sql"] == ARGS["sql"].rstrip(";") and proposal["days"] == ["monday", "thursday"]
    assert proposal["requested_by"] == {"id": "o", "name": "O", "email": "o@corp.test"}
    assert proposal["metronome_user"] == "Wizard" and proposal["evidence_id"] == "E1" and len(proposal["ref"]) == 8
    assert proposal["file_format"] == "xlsx" and proposal["day_of_month"] is None and proposal["time"] == "08:00"


def test_by_default_it_goes_to_the_users_own_mailbox_at_eight(setup):
    _, _, call = setup
    recorder = MemoryRecorder()
    person = owner().model_copy(update={"email": "rafael@ax.corp.test"})
    outcome = call({"title": "Weekly sell-out", "sql": ARGS["sql"], "frequency": "weekly", "days": ["monday"]}, person, recorder)
    assert outcome.ok, outcome.error_message
    assert outcome.data["recipients"] == ["rafael@corp.test"], "the sign-in's ax. is not part of the mailbox"
    assert outcome.data["sends"] == "Every Monday at 08:00 (Dubai time)" and outcome.data["file"].endswith(".xlsx")
    named = call({**ARGS, "recipients": ["cfo@ax.corp.test", "cfo@corp.test"]}, person)
    assert named.ok and named.data["recipients"] == ["cfo@corp.test"], "a named sign-in address becomes its mailbox"
    nobody = owner().model_copy(update={"email": ""})
    unknown = call({"title": "x", "sql": ARGS["sql"], "frequency": "daily"}, nobody)
    assert unknown.error_code == "invalid_schedule" and "ask who should receive it" in unknown.error_message


@pytest.mark.parametrize(("change", "code", "message"), [
    ({"sql": "SELECT 1; DELETE FROM bi_reporting.sell_out"}, "invalid_sql", "one query"),
    ({"recipients": ["friend@gmail.com"]}, "invalid_schedule", "outside"),
    ({"days": []}, "invalid_schedule", "needs its weekdays"),
    ({"frequency": "monthly", "days": []}, "invalid_schedule", "day_of_month"),
    ({"time": "8am"}, "invalid_arguments", "time"),
    ({"recipients": [f"p{i}@corp.test" for i in range(21)]}, "invalid_arguments", "recipients"),
])
def test_what_cannot_be_scheduled_is_refused_before_any_query(setup, change, code, message):
    _, sessions, call = setup
    outcome = call({**ARGS, **change})
    assert outcome.error_code == code and message in outcome.error_message
    assert not sessions, "nothing runs for a refused schedule"


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
