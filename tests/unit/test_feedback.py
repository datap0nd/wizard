"""Feedback and the quiz on the Cases site (owner, 12 Nov 2026; feedback.py, quiz_tools.py, site.py).

The site's pages send ratings, comments and quiz answers as issues in a feedback repository of its own, with a token
published beside them. Wizard publishes that token only when it is fine-grained and can do nothing but open and read
issues there; a token that could do more never reaches the site, and one already there comes off. A quiz task's Gemini
publishes one section of questions at a time, only in a task run."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.helpers import CEO_QUESTION, HEADERS, MemoryRecorder, ask, login, make_settings
from tests.unit.test_site import REPO, TOKEN, FakeHub
from tests.unit.test_tasks import NOTE, Worker, task_app

from wizard_api import feedback, provisioning, settings_pane
from wizard_api.config import ConfigError
from wizard_api.site import Site, SiteError
from wizard_connectors.entitlements import Identity, SystemRights
from wizard_connectors.portal_map import Published
from wizard_connectors.tools import ToolContext, build_registry, build_services
from wizard_connectors.tools.kb_tools import TASK_ONLY
from wizard_documents import kb

FEEDBACK = "github_pat_" + "f" * 40
FEEDBACK_REPO = "acme/wizard-feedback"


class FakeIssues:
    """The feedback repository's issues, and what GitHub answers the feedback token anywhere else."""

    def __init__(self, classic: bool = False, visibility: str = "private", writes: tuple[str, ...] = (),
                 has_issues: bool = True):
        self.classic, self.visibility, self.writes, self.has_issues = classic, visibility, writes, has_issues
        self.issues: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {FEEDBACK}"
        path = request.url.path.removeprefix("/api/v3/repos/")
        repo = "/".join(path.split("/")[:2])
        rest = path[len(repo):]
        if rest == "/git/refs" and request.method == "POST":  # the "can it change files" probe
            assert json.loads(request.content)["sha"] == "0" * 40
            return httpx.Response(422 if repo in self.writes else 403, json={"message": "nope"},
                                  headers={"x-github-request-id": "1"})
        if repo != FEEDBACK_REPO:
            return httpx.Response(404, json={"message": "Not Found"})
        headers = {"x-oauth-scopes": "repo"} if self.classic else {}
        if rest == "" and request.method == "GET":
            return httpx.Response(200, headers=headers, json={"private": self.visibility == "private",
                                                              "visibility": self.visibility, "has_issues": self.has_issues})
        if rest == "/issues" and request.method == "GET":
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=self.issues[(page - 1) * 100:page * 100])
        if rest == "/issues" and request.method == "POST":
            body = json.loads(request.content)
            self.issues.append({"number": len(self.issues) + 1, **body})
            return httpx.Response(201, json=self.issues[-1])
        raise AssertionError(f"unexpected {request.method} {path}")


def router(hub: FakeHub, issues: FakeIssues) -> httpx.Client:
    """One company GitHub: the write token reaches the knowledge base (FakeHub), the feedback token its issues."""
    def handle(request: httpx.Request) -> httpx.Response:
        return issues(request) if request.headers.get("authorization") == f"Bearer {FEEDBACK}" else hub(request)
    return httpx.Client(transport=httpx.MockTransport(handle))


def feedback_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hub: FakeHub, issues: FakeIssues, **env: str) -> TestClient:
    from wizard_api.app import create_app
    monkeypatch.setattr(kb, "_client", lambda proxy: router(hub, issues))
    settings = make_settings(tmp_path, WIZARD_SITE_REPO=REPO, WIZARD_KB_WRITE_TOKEN=TOKEN, WIZARD_FEEDBACK_TOKEN=FEEDBACK,
                             WIZARD_LOCAL_USER_EMAIL="owner@example.com", **env)
    settings.install_mode = True
    return TestClient(create_app(settings))


def publish_a_case(client: TestClient) -> dict[str, Any]:
    login(client, "local-owner")
    run = ask(client, CEO_QUESTION)
    published = client.post(f"/api/v1/conversations/{run['conversation_id']}/case", headers=HEADERS,
                            json={"title": "Marketing return by market", "takeaway": "", "run_ids": []})
    assert published.status_code == 200, published.text
    return dict(published.json())


def test_an_issues_only_token_is_published_with_the_cases_page_and_opens_the_edits_issue_once(tmp_path, monkeypatch):
    hub, issues = FakeHub(), FakeIssues()
    with feedback_app(tmp_path, monkeypatch, hub, issues) as client:
        first = publish_a_case(client)
        assert "fine-grained" in first["message"] and "opened the issue" in first["message"]
        site = json.loads(hub.files("gh-pages")["cases/feedback.json"])
        assert site == {"format": 1, "api": "https://github.sec.samsung.net/api/v3", "web": "https://github.sec.samsung.net",
                        "repo": FEEDBACK_REPO, "token": FEEDBACK, "edits_issue": 1,
                        "pin": hashlib.sha256(b"wizard-cases:2323").hexdigest()}
        assert "2323" not in hub.files("gh-pages")["cases/feedback.json"].decode()
        assert [i["title"] for i in issues.issues] == [feedback.EDITS_TITLE]
        publish_a_case(client)
        assert len(issues.issues) == 1, "found again, not opened twice"
    assert all(not w.startswith("POST /issues") for w in hub.writes), "the write token never opens issues"


@pytest.mark.parametrize("fake, expected", [
    (FakeIssues(classic=True), "classic token"),
    (FakeIssues(writes=(FEEDBACK_REPO,)), f"can change files in {FEEDBACK_REPO}"),
    (FakeIssues(writes=(REPO,)), f"can change files in {REPO}"),
    (FakeIssues(visibility="public"), "is public"),
    (FakeIssues(has_issues=False), "Issues are turned off"),
])
def test_a_token_that_could_do_more_is_never_published(fake: FakeIssues, expected: str):
    with pytest.raises(feedback.FeedbackError, match=expected):
        feedback.prepare(FEEDBACK_REPO, FEEDBACK, [REPO], client=router(FakeHub(), fake))
    assert fake.issues == [], "nothing is opened before every check passed"


def test_an_unsafe_token_already_on_the_site_comes_off_at_the_next_publish(tmp_path, monkeypatch):
    hub, issues = FakeHub(), FakeIssues()
    with feedback_app(tmp_path, monkeypatch, hub, issues) as client:
        publish_a_case(client)
        assert "cases/feedback.json" in hub.files("gh-pages")
        issues.writes = (FEEDBACK_REPO,)  # someone gave the token Contents: write
        again = publish_a_case(client)
        assert "Feedback is off on the site" in again["message"] and "can change files" in again["message"]
        assert "cases/feedback.json" not in hub.files("gh-pages")


def test_without_a_feedback_token_the_site_has_no_feedback_file(tmp_path, monkeypatch):
    from tests.unit.test_site import owner_app
    hub = FakeHub()
    with owner_app(tmp_path, monkeypatch, hub) as client:
        published = publish_a_case(client)
        assert "Feedback" not in published["message"] and "cases/feedback.json" not in hub.files("gh-pages")


def test_test_connection_turns_feedback_on_with_the_values_typed(tmp_path, monkeypatch):
    hub, issues = FakeHub(), FakeIssues()
    monkeypatch.setattr(kb, "_client", lambda proxy: router(hub, issues))
    settings = make_settings(tmp_path, WIZARD_SITE_REPO=REPO, WIZARD_KB_WRITE_TOKEN=TOKEN)
    nothing = settings_pane.test_site(settings, {})
    assert not nothing["ok"] and "feedback token" in nothing["message"] and hub.writes == []
    result = settings_pane.test_site(settings, {"WIZARD_FEEDBACK_TOKEN": FEEDBACK, "WIZARD_FEEDBACK_PIN": "9876"})
    assert result["ok"] and result["commit"] and "Feedback is on" in result["message"], result
    site = hub.files("gh-pages")
    assert {"cases/index.html", "cases/cases.json", "cases/feedback.json"} <= set(site)
    assert json.loads(site["cases/cases.json"])["cases"] == [], "an empty gallery, not a missing page"
    assert json.loads(site["cases/feedback.json"])["pin"] == hashlib.sha256(b"wizard-cases:9876").hexdigest()
    issues.classic = True
    refused = settings_pane.test_site(settings, {"WIZARD_FEEDBACK_TOKEN": FEEDBACK})
    assert not refused["ok"] and "classic token" in refused["message"]
    assert "cases/feedback.json" not in hub.files("gh-pages"), "the unsafe token came off the site"
    same = settings_pane.test_site(settings, {"WIZARD_FEEDBACK_TOKEN": FEEDBACK, "WIZARD_FEEDBACK_REPO": REPO})
    assert not same["ok"] and "one of its own" in same["message"]


def test_the_feedback_settings_stay_on_this_pc(tmp_path):
    settings = make_settings(tmp_path, WIZARD_SITE_REPO=REPO, WIZARD_FEEDBACK_TOKEN=FEEDBACK)
    assert (settings.feedback_repo, settings.feedback_pin) == (FEEDBACK_REPO, "2323"), "wizard-feedback beside the site"
    assert make_settings(tmp_path, WIZARD_SITE_REPO=REPO).feedback_repo is None
    with pytest.raises(ConfigError, match="WIZARD_FEEDBACK_REPO"):
        make_settings(tmp_path, WIZARD_SITE_REPO=REPO, WIZARD_FEEDBACK_REPO=REPO)
    with pytest.raises(ConfigError, match="WIZARD_FEEDBACK_PIN"):
        make_settings(tmp_path, WIZARD_FEEDBACK_PIN="23ab")
    with pytest.raises(provisioning.ProvisionError, match="WIZARD_FEEDBACK_TOKEN"):
        provisioning.parse(json.dumps({"wizard_provision": 1, "settings": {"WIZARD_FEEDBACK_TOKEN": FEEDBACK}}))
    field = settings_pane.BY_KEY["WIZARD_FEEDBACK_TOKEN"]
    assert field.secret and field.section == "site" and "Issues" in field.help


# The quiz ------------------------------------------------------------------------------------------------------------
def question(text: str, **extra: Any) -> dict[str, Any]:
    return {"topic": "Share", "question": text, "now": "The note is a draft and gives two definitions.", **extra}


QUESTIONS = [question(f"Which definition of market share is used in report {n}?") for n in range(5)]


def memory_site(tmp_path: Path) -> tuple[Site, dict[str, bytes]]:
    """A Site whose branch is a dict, written the way kb.update_branch writes it."""
    branch: dict[str, bytes] = {}

    def write(make: Any, message: str) -> str | None:
        files = make(set(branch), branch.get)
        changed = {p: d for p, d in files.items() if branch.get(p) != d and not (d is None and p not in branch)}
        for path, data in changed.items():
            if data is None:
                branch.pop(path, None)
            else:
                branch[path] = data
        return "c1" if changed else None

    settings = make_settings(tmp_path, WIZARD_SITE_REPO=REPO)
    return Site(settings, writer=write, pages_url=lambda: None), branch


def quiz_context(tmp_path: Path, site: Site | None) -> tuple[Any, ToolContext]:
    content = tmp_path / "content"
    (content / "knowledge" / "metrics").mkdir(parents=True)
    (content / "knowledge" / "metrics" / "market-share.md").write_text(NOTE, encoding="utf-8")
    services = build_services(knowledge=content / "knowledge")
    if site is not None:
        def publish(section: dict[str, Any]) -> Published:
            try:
                result = site.publish_quiz(section)
            except SiteError as error:
                return Published("failed", str(error))
            return Published(result.outcome, result.message, result.commit)
        services.quiz_writer = publish
    identity = Identity(id="owner", email="owner@example.com", name="Owner", role="Owner",
                        entitlements={"asap": SystemRights(reports=["*"], markets=["*"])})
    return build_registry(services), ToolContext(identity=identity, run_id="r", recorder=MemoryRecorder(), services=services)


def test_a_quiz_section_is_published_and_the_other_section_stays(tmp_path):
    site, branch = memory_site(tmp_path)
    registry, context = quiz_context(tmp_path, site)
    first = [question("Is market share measured in units or in value?", choices=["Units", "Value", "Both, by report"],
                      notes=["market-share", "not-a-note"]), *QUESTIONS]
    saved = registry.execute("wizard_quiz_save", {"section": "bi", "intro": "Data questions.", "questions": first}, context)
    assert saved.ok and saved.data["questions"] == 6, saved.error_message
    assert "not-a-note is not a note" in saved.data["warnings"][0]
    assert registry.execute("wizard_quiz_save", {"section": "business", "questions": QUESTIONS}, context).ok
    quiz = json.loads(branch["cases/quiz.json"])
    assert [(s["id"], s["title"], len(s["questions"])) for s in quiz["sections"]] == [
        ("bi", "Business intelligence", 6), ("business", "Business", 5)]
    asked = quiz["sections"][0]["questions"][0]
    assert asked["choices"] == ["Units", "Value", "Both, by report"]
    assert asked["notes"] == [{"id": "market-share", "title": "Market share and share gain"}]
    assert asked["id"].startswith("bi-") and len({q["id"] for q in quiz["sections"][0]["questions"]}) == 6
    # Prepared again: the section is replaced, the other one stays, and a question asked again keeps its id.
    again = registry.execute("wizard_quiz_save", {"section": "bi", "questions": [first[0], *QUESTIONS[:4]]}, context)
    assert again.ok
    quiz = json.loads(branch["cases/quiz.json"])
    assert [len(s["questions"]) for s in quiz["sections"]] == [5, 5]
    assert quiz["sections"][0]["questions"][0]["id"] == asked["id"]
    assert {"cases/index.html", "cases/cases.json"} <= set(branch) and json.loads(branch["cases/cases.json"])["cases"] == []


@pytest.mark.parametrize("questions, expected", [
    ([question("Which is right, one or the other?", choices=["Only one"]), *QUESTIONS[:4]], "2 to 6 choices"),
    (QUESTIONS[:4], "at least 5"),
    ([QUESTIONS[0], *QUESTIONS[:4]], "there twice"),
    ([question("Is the BDP password hunter2-secret-value right?", now="password = 'hunter22secret' in the note"),
      *QUESTIONS[:4]], "Not published"),
])
def test_a_quiz_that_breaks_a_rule_publishes_nothing(tmp_path, questions: list[dict[str, Any]], expected: str):
    site, branch = memory_site(tmp_path)
    registry, context = quiz_context(tmp_path, site)
    result = registry.execute("wizard_quiz_save", {"section": "bi", "questions": questions}, context)
    assert not result.ok and expected in (result.error_message or ""), result.error_message
    assert branch == {}


def test_without_the_write_token_the_quiz_is_not_published(tmp_path):
    registry, context = quiz_context(tmp_path, None)
    result = registry.execute("wizard_quiz_save", {"section": "business", "questions": QUESTIONS}, context)
    assert not result.ok and result.error_code == "not_configured"


class QuizWorker(Worker):
    async def run(self, request: Any, emit: Any, tools: Any, cancelled: Any) -> None:
        self.prompts.append(request.prompt)
        ok, text = await tools.call("wizard_quiz_save", {"section": "business", "questions": QUESTIONS})
        self.results.append((request.kind, ok, text))
        await asyncio.sleep(0)
        await emit("text_delta", {"text": "Published." if ok else "Answered."})


def test_only_a_task_publishes_the_quiz(tmp_path):
    assert "wizard_quiz_save" in TASK_ONLY
    runtime = QuizWorker()
    published: list[dict[str, Any]] = []
    with task_app(tmp_path, runtime) as client:
        services = client.app.state.manager.services
        services.quiz_writer = lambda section: (published.append(section), Published("published", "ok", "c1"))[1]
        login(client, "local-owner")
        ask(client, "Make a quiz for the business team")
        kind, ok, text = runtime.results[-1]
        assert kind == "ask" and not ok and "only in a task" in text and published == []
        assert client.post("/api/v1/tasks/tidy-notes/run", headers=HEADERS).status_code == 200
        from tests.unit.test_tasks import wait
        wait(client, lambda v: v["tasks"][0]["state"] == "done")
        assert runtime.results[-1][:2] == ("task", True) and published[0]["id"] == "business"
