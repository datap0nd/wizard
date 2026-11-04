"""Run bounds: backstops against a runaway run that steer Gemini to answer, never a route to the answer."""
from __future__ import annotations

import time

from tests.helpers import make_settings

from wizard_api.runs import (
    LOOP_STOP,
    REPEAT_LIMIT,
    ActiveRun,
    RunManager,
    call_signature,
    evidence_summary,
    last_step_window,
    wrap_up_s,
    wrap_up_window,
)


def manager(tmp_path, **env: str) -> RunManager:
    return RunManager(make_settings(tmp_path, **env), None, None, None, None)  # type: ignore[arg-type]


def started_run(seconds_ago: float = 0.0, kind: str = "ask") -> ActiveRun:
    run = ActiveRun("run_1", None, "conv_1", kind, "q", None, "gemini-cli")  # type: ignore[arg-type]
    run.started = time.monotonic() - seconds_ago
    return run


def call(m: RunManager, run: ActiveRun, name: str, args: dict, category: str | None = "source"):
    run.tool_calls += 1
    return m._bound(run, name, args, category)


def test_defaults_leave_room_for_a_long_answer(tmp_path):
    settings = make_settings(tmp_path)
    assert settings.run_timeout_s == 1800 and settings.max_tool_calls == 150 and settings.max_concurrent_runs == 8


def test_an_identical_call_is_allowed_twice_then_refused(tmp_path):
    m, run = manager(tmp_path), started_run()
    sql = {"sql": "select market, sum(units) from share group by 1"}
    assert [call(m, run, "wizard_query_postgresql", sql) for _ in range(REPEAT_LIMIT)] == [None] * REPEAT_LIMIT
    refused = call(m, run, "wizard_query_postgresql", {"sql": "select market,\n   sum(units) from share  group by 1"})
    assert refused is not None and refused.error_code == "repeated_call", "reformatting the SQL does not make it a new call"
    assert call(m, run, "wizard_query_postgresql", {"sql": "select market from share"}) is None, "a changed call runs"


def test_a_run_that_keeps_repeating_is_told_to_answer_but_may_still_present(tmp_path):
    m, run = manager(tmp_path), started_run()
    for i in range(LOOP_STOP):
        for _ in range(REPEAT_LIMIT + 1):
            call(m, run, "wizard_lookup_definitions", {"query": f"share {i}"}, "knowledge")
    assert run.repeats_refused == LOOP_STOP
    stopped = call(m, run, "asap_run_report", {"report_id": "new"})
    assert stopped is not None and stopped.error_code == "loop_stopped"
    assert call(m, run, "wizard_render_visual", {"kind": "table", "title": "Share"}, "present") is None
    assert call(m, run, "wizard_calculate", {"expression": "1/3"}, "check") is None


def test_research_closes_near_the_time_limit_so_the_run_ends_with_an_answer(tmp_path):
    m = manager(tmp_path)
    timeout = m.settings.run_timeout_s
    assert call(m, started_run(timeout - wrap_up_s(timeout) - 30), "asap_run_report", {"report_id": "a"}) is None
    late = started_run(timeout - wrap_up_s(timeout) + 30)
    refused = call(m, late, "asap_run_report", {"report_id": "a"})
    assert refused is not None and refused.error_code == "time_nearly_up" and "minute" in (refused.error_message or "")
    assert call(m, late, "wizard_render_visual", {"kind": "bar", "title": "Share"}, "present") is None


def test_slow_steps_keep_more_time_back(tmp_path):
    # The owner's run (4 Nov 2026): about two minutes a model step. Four minutes kept back held the step that read the
    # refusal and none to write the answer, and the run was cut off without one.
    m = manager(tmp_path)
    timeout = m.settings.run_timeout_s
    assert wrap_up_window(timeout, 10) == wrap_up_s(timeout) and wrap_up_window(timeout, 120) == 270
    assert wrap_up_window(timeout, 900) == timeout / 3, "never more than a third of the run"
    slow = started_run(timeout - 260)
    assert call(m, slow, "asap_run_report", {"report_id": "a"}) is None, "a quick run still has time at 4 minutes 20"
    slow.slowest_step = 120
    refused = call(m, slow, "asap_run_report", {"report_id": "b"})
    assert refused is not None and refused.error_code == "time_nearly_up"
    assert last_step_window(timeout, 120) == 180 and last_step_window(timeout, 5) == 60


def test_the_answer_is_due_once_a_question_is_told_to_stop(tmp_path):
    m = manager(tmp_path)
    timeout = m.settings.run_timeout_s
    run = started_run(100)
    assert m.answer_now(run) is None
    run.started = time.monotonic() - (timeout - wrap_up_s(timeout) + 30)
    assert call(m, run, "asap_run_report", {"report_id": "a"}).error_code == "time_nearly_up"
    due = m.answer_now(run)
    assert due and "No more tools" in due and "first sentence" in due, "the next step writes the answer, tools off"
    looping = started_run(100)
    looping.repeats_refused = LOOP_STOP
    assert call(m, looping, "asap_run_report", {"report_id": "a"}).error_code == "loop_stopped"
    assert "kept repeating" in (m.answer_now(looping) or "")
    asked = started_run(100)
    asked.asked = True
    assert m.answer_now(asked) is None, "after asking, Gemini ends its turn itself: its tools refuse research"
    asked.started = time.monotonic() - (timeout - 50)
    assert "end your turn with it now" in (m.answer_now(asked) or "")


def test_a_task_may_still_save_until_its_last_step(tmp_path):
    m = manager(tmp_path)
    timeout = m.settings.run_timeout_s
    task = started_run(timeout - wrap_up_s(timeout) + 30, kind="task")
    assert call(m, task, "asap_run_report", {"report_id": "a"}).error_code == "time_nearly_up"
    assert m.answer_now(task) is None, "a task may still save its map and notes after research closes"
    task.started = time.monotonic() - (timeout - 50)
    assert "as the task asks" in (m.answer_now(task) or ""), "its last step is its final message"


def test_the_tool_call_backstop_still_applies(tmp_path):
    m, run = manager(tmp_path, WIZARD_MAX_TOOL_CALLS="2"), started_run()
    assert call(m, run, "a", {"n": 1}) is None and call(m, run, "a", {"n": 2}) is None
    refused = call(m, run, "a", {"n": 3})
    assert refused is not None and refused.error_code == "tool_budget_exhausted"


def test_signature_ignores_key_order_and_whitespace_only():
    assert call_signature("t", {"a": 1, "b": "x  y"}) == call_signature("t", {"b": "x y", "a": 1})
    assert call_signature("t", {"a": "X"}) != call_signature("t", {"a": "x"}), "case can matter inside SQL literals"
    assert call_signature("t", {}) != call_signature("u", {})


def test_an_evidence_summary_carries_what_names_its_source():
    # The run card groups evidence by the real source: the tables a query's SQL read, a report's module.
    query = {"id": "E1", "system": "postgresql", "report_name": "SQL query on meto_db", "folder_path": [], "rows": [[1]],
             "request": {"sql": "SELECT * FROM bi_reporting.sell_in_amt_mv", "database": "meto_db"}}
    assert evidence_summary(query)["sql"] == "SELECT * FROM bi_reporting.sell_in_amt_mv"
    assert "rows" not in evidence_summary(query) and "request" not in evidence_summary(query)
    report = {"id": "E2", "system": "gscm", "report_name": "Sell in", "folder_path": ["Biz Plan"], "request": {"filters": []}}
    assert evidence_summary(report)["sql"] is None and evidence_summary(report)["folder_path"] == ["Biz Plan"]
