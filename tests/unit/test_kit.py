"""The documentation kit's deterministic helpers: digest progress, topics, coverage, and the expert quiz page (checked
before it is emailed, read back when it returns)."""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import pytest

from wizard_documents.kit import KitError, answers_of, check_quiz, coverage, next_sources, read_answers, status, topics

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = (ROOT / "workpc" / "templates" / "quiz-template.html").read_text(encoding="utf-8")
DATA = re.compile(r'(<script type="application/json" id="quiz-data">)\s*\{.*?\}\s*(</script>)', re.DOTALL)


def quiz_page(quiz: dict) -> str:
    return DATA.sub(lambda m: m.group(1) + json.dumps(quiz, ensure_ascii=False) + m.group(2), TEMPLATE, count=1)


QUIZ = {"quiz_version": 1, "id": "finance__ana-silva", "area": "Finance", "title": "Finance: close and calendar",
        "stakeholder": {"name": "Ana Silva", "role": "Finance controller"}, "sender": {"name": "Rafael"},
        "intro": "Please check what we wrote.", "due": "2026-10-20",
        "questions": [{"id": f"q{n}", "topic": "month-close", "kind": "confirm", "statement": f"Statement {n}."} for n in range(1, 11)]
        + [{"id": "q11", "topic": "month-close", "kind": "choice", "ask": "Which day?", "options": ["WD3", "WD5"], "comment": True}]}


def test_the_template_itself_is_a_valid_quiz():
    errors, warnings = check_quiz(TEMPLATE, set())
    assert errors == [] and warnings == ["4 questions: aim for 10 to 15"]


def test_quiz_check_catches_what_breaks_a_quiz():
    assert check_quiz(quiz_page(QUIZ), {"month-close"}) == ([], [])
    assert check_quiz("<html>no template</html>", set())[0][0].startswith("this is not the Wizard quiz template")
    broken = TEMPLATE.replace('"quiz_version": 1,', '"quiz_version": 1,,')
    assert "invalid" in check_quiz(broken, set())[0][0]
    bad = {**QUIZ, "stakeholder": {"name": "Ana", "email": "ana@corp.example"},
           "questions": [{"id": "q1", "topic": "Month Close", "kind": "poll", "ask": "?"},
                         {"id": "q1", "topic": "x", "kind": "choice", "ask": "One option?", "options": ["only"]},
                         {"id": "q3", "topic": "x", "kind": "confirm"}]}
    errors, _ = check_quiz(quiz_page(bad), set())
    joined = " | ".join(errors)
    for expected in ("kind must be one of", "topic must be a note id", "unique and look like q1", "2 to 8 options",
                     "needs the statement", "email address"):
        assert expected in joined
    _, warnings = check_quiz(quiz_page(QUIZ), {"other-note"})
    assert any("has no note yet" in w for w in warnings)


def answers() -> dict:
    return {"format": "wizard-quiz-answers", "version": 1, "quiz": "finance__ana-silva",
            "stakeholder": {"name": "Ana Silva", "role": "Finance controller"}, "answered_at": "2026-10-12T09:00:00Z",
            "answers": {"q1": {"verdict": "wrong", "correction": "It starts in April."}, "q2": {"unknown": True},
                        "q11": {"choice": ["WD5"], "comment": "Since 2026."}, "x_who_else": {"text": "Ask the controller"}}}


def test_answers_from_the_saved_page(tmp_path):
    page = quiz_page(QUIZ).replace('<script type="application/json" id="quiz-answers"></script>',
                                   '<script type="application/json" id="quiz-answers">' + json.dumps(answers()) + "</script>")
    saved = tmp_path / "finance__ana-silva__answered.html"
    saved.write_text(page, encoding="utf-8")
    report = read_answers(saved)
    assert "3 of 11 questions answered" in report
    assert "- Answer id: A-finance__ana-silva-q1\n- Statement checked: Statement 1.\n- Answer: Wrong. Correct version: It starts in April." in report
    assert "- Answer: Don't know" in report and "- Answer: WD5. Comment: Since 2026." in report
    assert "## Who else should we ask\n- Answer id: A-finance__ana-silva-x_who_else" in report


def test_answers_pasted_into_an_email_reply(tmp_path):
    quizzes = tmp_path / "quiz-questions" / "finance"
    quizzes.mkdir(parents=True)
    (quizzes / "finance__ana-silva.html").write_text(quiz_page(QUIZ), encoding="utf-8")
    block = base64.b64encode(json.dumps(answers()).encode()).decode()
    lines = [block[i:i + 76] for i in range(0, len(block), 76)]
    reply = tmp_path / "reply.txt"
    reply.write_text("Hi!\n> -----BEGIN WIZARD ANSWERS-----\n" + "\n".join(f"> {line}" for line in lines)
                     + "\n> -----END WIZARD ANSWERS-----\n", encoding="utf-8")
    assert "Correct version: It starts in April." in read_answers(reply, tmp_path / "quiz-questions")
    with pytest.raises(KitError, match="cannot find quiz"):
        read_answers(reply, tmp_path / "elsewhere")
    damaged = tmp_path / "damaged.txt"
    damaged.write_text("-----BEGIN WIZARD ANSWERS-----\n!!!notbase64\n-----END WIZARD ANSWERS-----", encoding="utf-8")
    with pytest.raises(KitError, match="damaged"):
        answers_of(damaged.read_text(encoding="utf-8"))
    plain = tmp_path / "plain.txt"
    plain.write_text("Q1: correct, Q2: no idea [quiz finance__ana-silva]", encoding="utf-8")
    assert read_answers(plain).startswith("NO_ANSWERS") and "finance__ana-silva" in read_answers(plain)


def digest(content: Path, source_id: str, worth: str, topics_: str) -> None:
    folder = content / "inbox" / "_digests"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{source_id}.md").write_text(f"---\nsource_id: {source_id}\ntitle: Doc {source_id}\ndate: 2026-09-01\n"
                                            f"kind: slides\nworth: {worth}\ntopics: [{topics_}]\nexperts: [\"Ana Silva (Finance)\"]\n"
                                            "sensitive: no\n---\nSummary: x\n", encoding="utf-8")


def test_progress_topics_and_coverage(tmp_path):
    content = tmp_path / "content"
    text = content / "inbox" / "_text"
    text.mkdir(parents=True)
    rows = ["source_id,path,kind,status,method,chars,images,modified,bytes,sha256,text_path,parent,note",
            "S-00000001,files/a.pptx,slides,ok,office,900,2,2026-09-01,1,x,inbox/_text/files/a.pptx.md,,",
            "S-00000002,files/b.docx,document,ok,office,900,0,2026-09-02,1,x,inbox/_text/files/b.docx.md,,",
            "S-00000003,email/c.md,email,ok,text,120,0,2026-09-03,1,x,inbox/_text/email/c.md.md,,",
            "S-00000004,files/d.xlsx,spreadsheet,failed,,0,0,2026-09-04,1,x,,,protected file"]
    (text / "manifest.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert "3 source(s) still need a digest" in next_sources(content, 10)
    digest(content, "S-00000001", "high", "month-close, glossary-finance")
    digest(content, "S-00000002", "medium", "month-close")
    listing = next_sources(content, 10)
    assert "1 source(s) still need a digest" in listing and "S-00000003" in listing
    assert "2 topic(s) from 2 digest(s)" in topics(content)
    table = (content / "inbox" / "_digests" / "_topics.md").read_text(encoding="utf-8")
    assert "| month-close | 5 | 2 | new | Ana Silva (Finance) | S-00000001, S-00000002 |" in table
    notes = content / "knowledge" / "processes"
    notes.mkdir(parents=True)
    (notes / "month-close.md").write_text("---\nid: month-close\ntitle: Month close\nstatus: DRAFT_UNSIGNED\nowner: x\n"
                                          "tags: [a]\nsources: [S-00000001]\n---\nLead.\n\n## Open questions\n- UNKNOWN: who signs\n",
                                          encoding="utf-8")
    report = coverage(content)
    assert "1 of 2 high- or medium-worth sources are cited" in report
    written = (content / "register" / "documentation-coverage.md").read_text(encoding="utf-8")
    assert "- S-00000002 (medium)" in written and "- glossary-finance" in written
    summary = status(content)
    assert "Digests: 2 written, 1 pending" in summary and "open questions 1" in summary and "1x protected file" in summary
