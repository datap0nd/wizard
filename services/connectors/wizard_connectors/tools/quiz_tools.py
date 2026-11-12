"""The quiz on the Cases site (owner, 12 Nov 2026: "gemini is going to prepare 50 questions about the knowledge base that
are currently a bit uncertain ... it will have business intelligence section and a business section").

A quiz task (tasks/quiz-*.md, Settings → Tasks) has Gemini find what the knowledge base is unsure of and ask the people
who know: one section of questions per task, published to the Cases site with this PC's write token, where people answer
without signing in (the site's feedback, api/wizard_api/feedback.py). Each question says what the knowledge base holds
now, so people confirm or correct it; a question can offer choices, and people can always write their own answer.

`wizard_quiz_save` is the one write and runs only in a task run (runs.py, TASK_ONLY): it replaces that section of the
quiz and leaves the other alone. Questions hold the knowledge base's own terms, never a credential (checked before it is
published) and never a person's name or contact details (the task says so)."""
from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .registry import ToolContext, ToolError, ToolSpec

SECTIONS = {"bi": "Business intelligence", "business": "Business"}
NOTE_ID = r"^[a-z0-9][a-z0-9-]{0,80}$"


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Question(Args):
    topic: str = Field(min_length=2, max_length=60, description="A short label people scan by, e.g. 'Sell-out' or 'Fiscal weeks'.")
    question: str = Field(min_length=10, max_length=300, description="The question as people read it: one thing to answer, in plain words, ending with a question mark.")
    now: str = Field(min_length=10, max_length=600, description="What the knowledge base says now and why it is unsure (a draft, an UNKNOWN, two notes that disagree, a term with two meanings), in one or two sentences, so people can confirm or correct it.")
    choices: list[str] = Field(default_factory=list, max_length=6, description="Optional: 2 to 6 short answers to pick from (each at most 120 characters) when the plausible answers are known, e.g. from two notes that disagree. People can always write their own answer. Leave empty for an open question.")
    notes: list[str] = Field(default_factory=list, max_length=5, description="Ids of the knowledge notes the answer would settle, e.g. ['sell-out'].")

    @model_validator(mode="after")
    def _choices(self) -> Question:
        cleaned = [c.strip() for c in self.choices if c.strip()]
        if len(cleaned) == 1:
            raise ValueError("give 2 to 6 choices, or none for an open question")
        if any(len(c) > 120 for c in cleaned):
            raise ValueError("each choice is at most 120 characters")
        if len({c.lower() for c in cleaned}) != len(cleaned):
            raise ValueError("the choices repeat")
        self.choices = cleaned
        return self


class QuizArgs(Args):
    section: Literal["bi", "business"] = Field(description="bi: Business intelligence, technical questions (data sources, reports, tables and columns, how a measure is calculated, filters, refresh times, which source to use). business: concepts, terms and acronyms, processes, organisation and strategy.")
    intro: str = Field(default="", max_length=400, description="One or two sentences shown above this section's questions, e.g. what they are about.")
    questions: list[Question] = Field(min_length=5, max_length=50, description="The section's questions, the most useful first. They replace the section's questions on the site.")


def question_id(section: str, text: str) -> str:
    """The same question keeps its id when the quiz is prepared again, so answers stay with it."""
    return f"{section}-" + hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()[:10]


def save_quiz(ctx: ToolContext, args: QuizArgs) -> dict[str, Any]:
    writer = ctx.services.quiz_writer
    if writer is None:
        raise ToolError("not_configured", "This Wizard cannot publish the Cases site: it needs the knowledge base's write "
                                          "token (Settings → Knowledge base). Nothing was saved.")
    knowledge = ctx.services.knowledge
    questions, seen, warnings = [], set(), []
    for q in args.questions:
        qid = question_id(args.section, q.question)
        if qid in seen:
            raise ToolError("invalid_quiz", f"The question \"{q.question[:80]}\" is there twice. Nothing was saved.")
        seen.add(qid)
        notes = []
        for note_id in dict.fromkeys(q.notes):
            note = knowledge.by_id.get(note_id)
            if note is None:
                warnings.append(f"{note_id} is not a note: left out of \"{q.question[:60]}\"")
                continue
            notes.append({"id": note.id, "title": note.title})
        questions.append({"id": qid, "topic": q.topic.strip(), "question": q.question.strip(), "now": q.now.strip(),
                          "choices": q.choices, "notes": notes})
    result = writer({"id": args.section, "intro": args.intro.strip(), "questions": questions})
    if result.outcome == "failed":
        raise ToolError("publish_failed", f"Not published: {result.message}")
    return {"section": SECTIONS[args.section], "questions": len(questions), "outcome": result.outcome,
            "commit": result.commit, "message": result.message, "warnings": warnings or None,
            "note": "Published to the Cases site's quiz. People answer there without signing in; their answers reach the "
                    "admin pane, not the knowledge base."}


QUIZ_TOOLS = [
    ToolSpec("wizard_quiz_save",
             "Only in a task run (Settings → Tasks): publish one section of the quiz on the Cases site, the questions "
             "people answer to settle what the knowledge base is unsure of. It replaces that section's questions and "
             "leaves the other section alone. Each question says what the knowledge base holds now; people answer "
             "without signing in.", QuizArgs, save_quiz, "wizard", "present"),
]
