from __future__ import annotations

from tests.helpers import CEO_QUESTION, CONQUEST_QUESTION, HEADERS, PLANNER_QUESTION, ask, login, sse_events, wait_run

from wizard_api.outlook import DraftError


def test_three_stories_run_end_to_end_with_honest_labels(client):
    login(client, "u-ceo")
    for question, transcript in ((CEO_QUESTION, "ceo-investment-efficiency"), (PLANNER_QUESTION, "planner-sell-in-vs-sell-out"),
                                 (CONQUEST_QUESTION, "conquest-switchers")):
        run = ask(client, question)
        assert run["status"] == "succeeded", run
        assert run["runtime"] == "replay" and "not a live model" in run["runtime_label"]
        assert run["data_mode"] == "SYNTHETIC" and run["check_status"] == "NOT_CHECKED"
        assert run["stats"]["transcript"] == transcript
        assert "SYNTHETIC" in run["answer"]
        report = client.get(f"/api/v1/reports/{run['report_id']}").json()["report"]
        assert report["data_mode"] == "SYNTHETIC" and report["warnings"] == [], report["warnings"]
        assert report["runtime"]["kind"] == "replay" and report["evidence"] and report["visuals"]


def test_event_stream_mirrors_executed_tools(client):
    login(client, "u-ceo")
    started = client.post("/api/v1/runs", json={"question": CEO_QUESTION}, headers=HEADERS).json()
    events = sse_events(client, started["run_id"])
    types = [e["type"] for e in events]
    assert types[0] == "run_started" and types[-1] == "run_finished"
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)
    started_calls = [e["payload"]["call_id"] for e in events if e["type"] == "tool_started"]
    finished = [e["payload"] for e in events if e["type"] == "tool_finished"]
    assert started_calls == [f["call_id"] for f in finished] and len(finished) == 11
    assert {f["evidence"]["id"] for f in finished if "evidence" in f} == {"E1", "E2", "E3", "E4", "E5"}
    assert "note" in types and "visual_added" in types
    resumed = sse_events(client, started["run_id"], after=events[-3]["seq"])
    assert [e["seq"] for e in resumed] == [e["seq"] for e in events[-2:]]


def test_report_reopens_after_reload_and_conversation_restores(client):
    login(client, "u-ceo")
    run = ask(client, CEO_QUESTION)
    conversation = client.get(f"/api/v1/conversations/{run['conversation_id']}").json()
    assert conversation["conversation"]["title"].startswith("Which market gave us")
    restored = conversation["runs"][0]
    assert restored["answer"] == run["answer"] and restored["visuals"][0]["id"] == "V1"
    assert [e["id"] for e in restored["evidence"]] == ["E1", "E2", "E3", "E4", "E5"]
    assert any(e["type"] == "tool_finished" for e in restored["events"])
    evidence = client.get(f"/api/v1/conversations/{run['conversation_id']}/evidence/E1").json()["evidence"]
    assert evidence["report_id"] == "nerp-mkt-spend-quarterly" and evidence["rows"]
    listed = client.get("/api/v1/reports").json()["reports"]
    assert listed[0]["id"] == run["report_id"]


def test_check_my_data_follow_up_marks_original_answer(client):
    login(client, "u-ceo")
    run = ask(client, CEO_QUESTION)
    check = client.post(f"/api/v1/runs/{run['id']}/check", headers=HEADERS).json()
    checked = wait_run(client, check["run_id"])
    assert checked["status"] == "succeeded" and checked["kind"] == "check" and checked["check_status"] == "CHECKED"
    assert "6 of 6" in checked["check_summary"]
    original = client.get(f"/api/v1/runs/{run['id']}").json()
    assert original["check_status"] == "CHECKED" and original["answer"] == run["answer"], "a check never rewrites the answer"
    report = client.get(f"/api/v1/reports/{run['report_id']}").json()["report"]
    assert report["check"]["status"] == "CHECKED" and report["check"]["checked_by_run"] == check["run_id"]


def test_follow_up_shares_conversation_evidence(client):
    login(client, "u-ceo")
    first = ask(client, CEO_QUESTION)
    second = ask(client, CONQUEST_QUESTION, first["conversation_id"])
    assert [e["id"] for e in second["evidence"]][0] == "E6", "evidence ids continue across the conversation"


def test_unmatched_question_in_replay_mode_does_not_improvise(client):
    login(client, "u-ceo")
    run = ask(client, "What is the weather in Riyadh?")
    assert run["status"] == "succeeded" and "no recorded transcript" in run["answer"] and not run["evidence"]


def test_one_active_run_per_user_and_cancel(client):
    login(client, "u-ceo")
    manager = client.app.state.manager
    manager.runtime.delay_s = 0.05
    first = client.post("/api/v1/runs", json={"question": CEO_QUESTION}, headers=HEADERS).json()
    busy = client.post("/api/v1/runs", json={"question": CEO_QUESTION}, headers=HEADERS)
    assert busy.status_code == 429
    assert client.post(f"/api/v1/runs/{first['run_id']}/cancel", headers=HEADERS).json()["cancelled"]
    cancelled = wait_run(client, first["run_id"])
    assert cancelled["status"] == "cancelled" and cancelled["error_code"] == "cancelled"
    manager.runtime.delay_s = 0.0


def test_feedback_and_conversation_management(client):
    login(client, "u-ceo")
    run = ask(client, CEO_QUESTION)
    assert client.post(f"/api/v1/runs/{run['id']}/feedback", json={"category": "mismatched_period", "note": "x"},
                       headers=HEADERS).json()["ok"]
    assert client.patch(f"/api/v1/conversations/{run['conversation_id']}", json={"title": "ROI"}, headers=HEADERS).json()["ok"]
    assert client.get("/api/v1/conversations").json()["conversations"][0]["title"] == "ROI"
    assert client.delete(f"/api/v1/conversations/{run['conversation_id']}", headers=HEADERS).json()["ok"]
    assert client.get(f"/api/v1/runs/{run['id']}").status_code == 404


def test_email_opens_an_outlook_draft_only_where_wizard_runs_on_this_pc(client, monkeypatch):
    login(client, "u-ceo")
    run = ask(client, CEO_QUESTION)
    opened: list[tuple[str, str]] = []

    async def outlook(folder, subject, html, timeout_s=60):
        opened.append((subject, html))

    monkeypatch.setattr("wizard_api.app.open_outlook_draft", outlook)
    body = {"subject": "Wizard: best return on marketing", "html": "<p>Answer</p>"}
    assert client.post(f"/api/v1/runs/{run['id']}/email", json=body, headers=HEADERS).json() == {"ok": True}
    assert opened == [("Wizard: best return on marketing", "<p>Answer</p>")]
    assert client.post("/api/v1/runs/run_unknown/email", json=body, headers=HEADERS).status_code == 404

    async def no_outlook(*_args, **_kwargs):
        raise DraftError("Outlook could not open a draft: Outlook.Application is not registered")

    monkeypatch.setattr("wizard_api.app.open_outlook_draft", no_outlook)
    failed = client.post(f"/api/v1/runs/{run['id']}/email", json=body, headers=HEADERS)
    assert failed.status_code == 503 and failed.json()["code"] == "outlook_unavailable"
    settings = client.app.state.settings  # behind an SSO proxy Outlook would open on the server, not the user's PC
    settings.auth_mode, settings.trusted_proxies = "trusted-header", {"testclient"}
    remote = client.post(f"/api/v1/runs/{run['id']}/email", json=body,
                         headers={**HEADERS, settings.identity_header: "ceo@wizard.test"})
    assert remote.status_code == 409 and remote.json()["code"] == "outlook_not_local" and len(opened) == 1
