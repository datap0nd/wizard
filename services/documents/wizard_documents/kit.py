"""Deterministic helpers for the documentation work Gemini CLI does on the work PC: progress, the next sources to
digest, the topic overview, and expert quizzes (check a quiz page before it is emailed, read the answered pages that
come back). Gemini writes the digests, notes and questions; these functions only count, check and parse, so every run
gives the same result. Formats: content/schema/knowledge-standard.md and the quiz template's header comment."""
from __future__ import annotations

import base64
import contextlib
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from wizard_connectors.content import SECRET_PATTERNS, validate_knowledge
from wizard_connectors.knowledge import front_matter, parse_list, unquote

from .common import EMAIL_ADDRESS

WORTH = {"high": 3, "medium": 2, "low": 1, "none": 0}
READ_ORDER = {"slides": 0, "document": 1, "spreadsheet": 2, "pdf": 3, "email": 4, "text": 5, "image": 6}
QUIZ_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{2,80}$")
QUESTION_ID = re.compile(r"^q[0-9]{1,3}$")
TOPIC_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
KINDS = ("confirm", "choice", "multi", "text")
# JSON must follow the tag directly: the template's instructions comment mentions both tags too.
QUIZ_DATA = re.compile(r'<script type="application/json" id="quiz-data">\s*(\{.*?\})\s*</script>', re.DOTALL)
QUIZ_ANSWERS = re.compile(r'<script type="application/json" id="quiz-answers">\s*(\{.*?\})?\s*</script>', re.DOTALL)
TEMPLATE_MARK = 'data-wizard-quiz="1"'
BEGIN, END = "-----BEGIN WIZARD ANSWERS-----", "-----END WIZARD ANSWERS-----"
VERDICTS = {"correct": "Correct", "partly": "Partly correct", "wrong": "Wrong"}


class KitError(Exception):
    pass


def today() -> str:
    return date.today().isoformat()


# --- Sources and digests --------------------------------------------------------------------------------------------


def manifest(content: Path) -> list[dict[str, str]]:
    path = content / "inbox" / "_text" / "manifest.csv"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def digests(content: Path) -> dict[str, dict[str, Any]]:
    folder = content / "inbox" / "_digests"
    found: dict[str, dict[str, Any]] = {}
    for path in sorted(folder.glob("S-*.md")) if folder.is_dir() else []:
        parsed = front_matter(path.read_text(encoding="utf-8-sig"))
        meta = parsed[0] if parsed else {}
        found[path.stem] = {"title": unquote(meta.get("title", "")), "date": unquote(meta.get("date", "")),
                            "kind": meta.get("kind", ""), "worth": meta.get("worth", "").strip().lower(),
                            "topics": parse_list(meta.get("topics", "")), "experts": parse_list(meta.get("experts", "")),
                            "valid": parsed is not None}
    return found


def readable(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Sources worth a digest: converted text or a file Gemini reads natively; one row per source id."""
    seen: set[str] = set()
    out = []
    for row in rows:
        if row["status"] in ("ok", "native") and row["source_id"] not in seen:
            seen.add(row["source_id"])
            out.append(row)
    return out


def pending(content: Path) -> list[dict[str, str]]:
    done = digests(content)
    todo = [r for r in readable(manifest(content)) if r["source_id"] not in done]
    short = [r for r in todo if r["kind"] == "email" and int(r["chars"] or 0) < 300]
    rest = sorted((r for r in todo if r not in short),
                  key=lambda r: (READ_ORDER.get(r["kind"], 9), [-ord(c) for c in r["modified"]]))
    return rest + short


def next_sources(content: Path, limit: int) -> str:
    if not manifest(content):
        return "No manifest yet: convert the inbox first (wizard_docs.py extract)."
    todo = pending(content)
    if not todo:
        return "Every readable source has a digest."
    lines = [f"{len(todo)} source(s) still need a digest. Next {min(limit, len(todo))}:", "",
             "| source id | kind | modified | characters | slide images | read this file |", "|---|---|---|---|---|---|"]
    lines += [f"| {r['source_id']} | {r['kind']} | {r['modified']} | {r['chars'] or '-'} | {r.get('images') or '-'} | "
              f"{r['text_path']} |" for r in todo[:limit]]
    return "\n".join(lines)


def knowledge_ids(content: Path) -> dict[str, str]:
    """Note id -> title for every note under content/knowledge."""
    found = {}
    knowledge = content / "knowledge"
    for path in knowledge.rglob("*.md") if knowledge.is_dir() else []:
        parsed = front_matter(path.read_text(encoding="utf-8-sig"))
        if parsed and parsed[0].get("id"):
            found[parsed[0]["id"]] = unquote(parsed[0].get("title", "")) or parsed[0]["id"]
    return found


def topics(content: Path) -> str:
    found = digests(content)
    by_topic: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for source_id, digest in found.items():
        if digest["worth"] != "none":
            for topic in digest["topics"]:
                by_topic[topic].append((source_id, digest))
    notes = knowledge_ids(content)

    def score(items: list[tuple[str, dict[str, Any]]]) -> int:
        return sum(WORTH.get(d["worth"], 1) for _, d in items)

    ranked = sorted(by_topic.items(), key=lambda item: (-score(item[1]), item[0]))
    lines = [f"# Topics found in {len(found)} digest(s)", "",
             f"Generated {today()} by wizard_docs.py topics. Score = sum of source worth (high 3, medium 2, low 1).", "",
             "| topic | score | sources | note | experts mentioned | source ids (best first) |", "|---|---|---|---|---|---|"]
    for topic, items in ranked:
        items.sort(key=lambda item: (-WORTH.get(item[1]["worth"], 1), item[1]["date"]))
        experts = Counter(e for _, d in items for e in d["experts"])
        ids = ", ".join(s for s, _ in items[:15]) + (" ..." if len(items) > 15 else "")
        lines.append(f"| {topic} | {score(items)} | {len(items)} | {'exists' if topic in notes else 'new'} | "
                     f"{'; '.join(e for e, _ in experts.most_common(4))} | {ids} |")
    target = content / "inbox" / "_digests" / "_topics.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"{len(ranked)} topic(s) from {len(found)} digest(s); table written to inbox/_digests/_topics.md."


def open_questions(body: str) -> int:
    count, inside = 0, False
    for line in body.splitlines():
        if line.startswith("## "):
            inside = line[3:].strip().lower().startswith("open question")
        elif inside and re.match(r"^\s*[-*]\s+\S", line):
            count += 1
    return count


def status(content: Path, quizzes: Path | None = None) -> str:
    rows = manifest(content)
    lines = [f"# Documentation status ({today()})", ""]
    if rows:
        statuses = Counter(r["status"] for r in rows)
        kinds = Counter(r["kind"] for r in readable(rows))
        found = digests(content)
        worth = Counter(d["worth"] or "?" for d in found.values())
        lines += [f"Sources: {len(rows)} file(s): " + ", ".join(f"{s} {n}" for s, n in sorted(statuses.items())),
                  "Readable by kind: " + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())),
                  f"Digests: {len(found)} written, {len(pending(content))} pending; worth: "
                  + (", ".join(f"{w} {n}" for w, n in sorted(worth.items())) or "-")]
        failed = [r for r in rows if r["status"] == "failed"]
        if failed:
            reasons = Counter(r["note"].split(":")[0][:80] for r in failed)
            lines.append(f"Could not read {len(failed)} file(s): " + "; ".join(f"{n}x {why}" for why, n in reasons.most_common(4)))
    else:
        lines.append("Sources: nothing converted yet (no inbox/_text/manifest.csv).")
    knowledge = content / "knowledge"
    notes = []
    for path in sorted(knowledge.rglob("*.md")) if knowledge.is_dir() else []:
        parsed = front_matter(path.read_text(encoding="utf-8-sig")) if path.name != "README.md" else None
        if parsed:
            notes.append((path, parsed[0], parsed[1]))
    if notes:
        areas = Counter(p.relative_to(knowledge).parts[0] if len(p.relative_to(knowledge).parts) > 1 else "general"
                        for p, _, _ in notes)
        signed = sum(1 for _, m, _ in notes if m.get("status") == "SIGNED")
        checked = sum(1 for _, m, _ in notes if m.get("status") != "SIGNED" and unquote(m.get("reviewed", "")))
        problems = validate_knowledge(knowledge, content)
        errors = [p for p in problems if p.level == "error"]
        lines += [f"Notes: {len(notes)} (" + ", ".join(f"{a} {n}" for a, n in sorted(areas.items())) + ")",
                  f"Signed {signed}, expert-checked {checked}, draft {len(notes) - signed - checked}; open questions "
                  f"{sum(open_questions(b) for _, _, b in notes)}",
                  f"Validator (notes): {len(errors)} error(s), {len(problems) - len(errors)} warning(s)"
                  + (f"; first error: {errors[0]}" if errors else "")]
    else:
        lines.append("Notes: none yet.")
    if quizzes and quizzes.is_dir():
        built = [p for p in quizzes.rglob("*.html") if not p.name.startswith("_")]
        lines.append(f"Quizzes: {len(built)} page(s) in {quizzes.name}/")
    return "\n".join(lines)


# --- Quizzes --------------------------------------------------------------------------------------------------------


def quiz_data(page: str) -> dict[str, Any]:
    found = QUIZ_DATA.search(page)
    if not found:
        raise KitError("no quiz-data block: start from the quiz template and replace only the JSON inside "
                       '<script type="application/json" id="quiz-data">')
    try:
        data = json.loads(found.group(1).replace("<\\/", "</"))
    except json.JSONDecodeError as error:
        raise KitError(f"the quiz JSON is invalid: {error.msg} (line {error.lineno}, column {error.colno})") from None
    if not isinstance(data, dict):
        raise KitError("the quiz JSON must be an object")
    return data


def check_quiz(page: str, known_topics: set[str]) -> tuple[list[str], list[str]]:
    """(errors, warnings) for one quiz page."""
    if TEMPLATE_MARK not in page:
        return ["this is not the Wizard quiz template (copy the template and fill in only the quiz-data JSON)"], []
    try:
        quiz = quiz_data(page)
    except KitError as error:
        return [str(error)], []
    errors: list[str] = []
    warnings: list[str] = []
    if quiz.get("quiz_version") != 1:
        errors.append("quiz_version must be 1")
    if not QUIZ_ID.match(str(quiz.get("id", ""))):
        errors.append("id must be lowercase letters, digits, - or _ (3-81 characters), e.g. finance__ana-silva")
    for key in ("area", "title", "intro"):
        if not str(quiz.get(key, "")).strip():
            errors.append(f"{key} is required")
    for person in ("stakeholder", "sender"):
        value = quiz.get(person)
        if not isinstance(value, dict) or not str(value.get("name", "")).strip():
            errors.append(f"{person}.name is required")
    if quiz.get("due") and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(quiz["due"])):
        errors.append("due must be YYYY-MM-DD")
    questions = quiz.get("questions")
    if not isinstance(questions, list) or not 1 <= len(questions) <= 25:
        return [*errors, "questions must be a list of 1 to 25 questions"], warnings
    if not 10 <= len(questions) <= 15:
        warnings.append(f"{len(questions)} questions: aim for 10 to 15")
    seen: set[str] = set()
    for number, question in enumerate(questions, start=1):
        where = f"question {number}"
        if not isinstance(question, dict):
            errors.append(f"{where} must be an object")
            continue
        qid, kind = str(question.get("id", "")), question.get("kind")
        if not QUESTION_ID.match(qid) or qid in seen:
            errors.append(f"{where}: id must be unique and look like q1, q2 ...")
        seen.add(qid)
        if kind not in KINDS:
            errors.append(f"{where}: kind must be one of {', '.join(KINDS)}")
        topic = str(question.get("topic", ""))
        if not TOPIC_ID.match(topic):
            errors.append(f"{where}: topic must be a note id such as fiscal-calendar")
        elif known_topics and topic not in known_topics:
            warnings.append(f"{where}: topic '{topic}' has no note yet (fine if the answers will start one)")
        if kind == "confirm" and not str(question.get("statement", "")).strip():
            errors.append(f"{where}: a confirm question needs the statement to check")
        if kind != "confirm" and not str(question.get("ask", "")).strip():
            errors.append(f"{where}: needs 'ask', the question text")
        if kind in ("choice", "multi"):
            options = question.get("options")
            if not isinstance(options, list) or not 2 <= len(options) <= 8 or not all(str(o).strip() for o in options):
                errors.append(f"{where}: a {kind} question needs 2 to 8 options")
        if len(str(question.get("statement", ""))) > 500 or len(str(question.get("ask", ""))) > 300:
            errors.append(f"{where}: keep statements under 500 and questions under 300 characters")
    text = json.dumps(quiz, ensure_ascii=False)
    errors += [f"contains what looks like a {name}" for name, pattern in SECRET_PATTERNS.items() if pattern.search(text)]
    if EMAIL_ADDRESS.search(text):
        errors.append("contains an email address: quizzes name people, never their contact details")
    return errors, warnings


def answers_of(page: str) -> dict[str, Any] | None:
    """The answers saved in a returned quiz page, or pasted from 'Copy my answers' (base64 between markers)."""
    found = QUIZ_ANSWERS.search(page)
    if found and found.group(1):
        data = json.loads(found.group(1).replace("<\\/", "</"))
    else:
        start, end = page.find(BEGIN), page.find(END)
        if start < 0 or end < start:
            return None
        payload = re.sub(r"[\s>]", "", page[start + len(BEGIN):end])
        try:
            data = json.loads(base64.b64decode(payload + "=" * (-len(payload) % 4)).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            raise KitError(f"the pasted answer block is damaged ({type(error).__name__}); ask for the saved page "
                           "instead, or read the readable lines above the block") from None
    if not isinstance(data, dict) or data.get("format") != "wizard-quiz-answers":
        raise KitError("the answers are not in the Wizard quiz format")
    return data


def describe(question: dict[str, Any], answer: dict[str, Any]) -> str:
    if not answer:
        return "(not answered)"
    if answer.get("unknown"):
        result = "Don't know"
    elif question.get("kind") == "confirm":
        result = VERDICTS.get(str(answer.get("verdict")), "(not answered)")
        if answer.get("correction"):
            result += f". Correct version: {answer['correction']}"
    elif question.get("kind") in ("choice", "multi"):
        picked = [str(c) for c in answer.get("choice", [])]
        if answer.get("other"):
            picked.append(f"Other: {answer['other']}")
        result = "; ".join(picked) or "(not answered)"
    else:
        result = str(answer.get("text", "")).strip() or "(not answered)"
    if answer.get("comment"):
        result += f". Comment: {answer['comment']}"
    return result


def read_answers(path: Path, quizzes: Path | None = None) -> str:
    page = path.read_text(encoding="utf-8-sig", errors="replace")
    data = answers_of(page)
    if data is None:
        quiz_id = re.search(r"\[quiz ([a-z0-9_-]+)\]", page)
        return (f"NO_ANSWERS in {path.name}: no saved answers in it. If the stakeholder replied in the email text, "
                "read the reply and match the answers to the question numbers"
                + (f" of quiz {quiz_id.group(1)}" if quiz_id else "") + ".")
    quiz_ref = str(data.get("quiz", ""))
    try:
        quiz = quiz_data(page)
    except KitError:  # pasted answers: find the quiz page they belong to
        quiz = {}
        for candidate in sorted(quizzes.rglob("*.html")) if quizzes and quizzes.is_dir() else []:
            with contextlib.suppress(KitError):
                found = quiz_data(candidate.read_text(encoding="utf-8-sig", errors="replace"))
                if found.get("id") == quiz_ref:
                    quiz = found
                    break
        if not quiz:
            raise KitError(f"cannot find quiz {quiz_ref} to match these answers to (pass --quizzes)") from None
    answers: dict[str, Any] = data["answers"] if isinstance(data.get("answers"), dict) else {}
    person: dict[str, Any] = data["stakeholder"] if isinstance(data.get("stakeholder"), dict) \
        else quiz.get("stakeholder") or {}
    stamp = str(data.get("answered_at", ""))[:10] or "unknown date"
    questions = [q for q in quiz.get("questions", []) if isinstance(q, dict)]
    answered = sum(1 for q in questions if answers.get(str(q.get("id"))))
    lines = [f"# Answers: {quiz.get('title', quiz.get('id'))}",
             f"Quiz {quiz.get('id')} · area {quiz.get('area', '?')} · from {person.get('name', '?')}"
             + (f", {person['role']}" if person.get("role") else "") + f" · answered {stamp} · file {path.name}",
             f"{answered} of {len(questions)} questions answered. Cite an answer in a note's sources as its answer id.", ""]
    for number, question in enumerate(questions, start=1):
        answer = answers.get(str(question.get("id")), {})
        lines += [f"## Q{number} · topic {question.get('topic')}", f"- Answer id: A-{quiz.get('id')}-{question.get('id')}"]
        if question.get("statement"):
            lines.append(f"- Statement checked: {question['statement']}")
        if question.get("ask"):
            lines.append(f"- Question: {question['ask']}")
        lines += [f"- Answer: {describe(question, answer if isinstance(answer, dict) else {})}", ""]
    for key, label in (("x_who_else", "Who else should we ask"), ("x_missing", "Anything missing or wrong")):
        value = answers.get(key, {})
        if isinstance(value, dict) and value.get("text"):
            lines += [f"## {label}", f"- Answer id: A-{quiz.get('id')}-{key}", f"- Answer: {value['text']}", ""]
    return "\n".join(lines)


SOURCE_REF = re.compile(r"\b(S-[0-9a-f]{8})\b")


def coverage(content: Path) -> str:
    """How completely the notes use the sources: valuable sources no note cites, topics without a note, unsourced notes."""
    found = digests(content)
    cited: set[str] = set()
    unsourced = []
    knowledge = content / "knowledge"
    for path in sorted(knowledge.rglob("*.md")) if knowledge.is_dir() else []:
        parsed = front_matter(path.read_text(encoding="utf-8-sig")) if path.name != "README.md" else None
        if not parsed:
            continue
        meta, body = parsed
        refs = set(parse_list(meta.get("sources", ""))) | set(SOURCE_REF.findall(body))
        cited |= refs
        if not refs and meta.get("status") != "SIGNED":
            unsourced.append(meta.get("id", path.stem))
    notes = knowledge_ids(content)
    valuable = {s: d for s, d in found.items() if d["worth"] in ("high", "medium")}
    missing = sorted((s for s in valuable if s not in cited), key=lambda s: (-WORTH[valuable[s]["worth"]], s))
    topics_without = sorted({t for d in valuable.values() for t in d["topics"]} - set(notes))
    used = len(valuable) - len(missing)
    lines = [f"# Documentation coverage ({today()})", "",
             f"{used} of {len(valuable)} high- or medium-worth sources are cited by at least one note "
             f"({round(100 * used / len(valuable)) if valuable else 0}%). {len(notes)} note(s), {len(unsourced)} without sources.",
             "", "## Valuable sources no note cites yet", ""]
    lines += [f"- {s} ({valuable[s]['worth']}): {valuable[s]['title'] or '(untitled)'}; topics: "
              f"{', '.join(valuable[s]['topics']) or '-'}" for s in missing[:200]] or ["- none"]
    lines += ["", "## Topics from the digests without a note", ""] + ([f"- {t}" for t in topics_without] or ["- none"])
    lines += ["", "## Notes without any source", ""] + ([f"- {n}" for n in unsourced] or ["- none"])
    target = content / "register" / "documentation-coverage.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "\n".join(lines[:3]) + f"\nFull list: register/documentation-coverage.md ({len(missing)} uncited, " \
                                  f"{len(topics_without)} topics without a note)."
