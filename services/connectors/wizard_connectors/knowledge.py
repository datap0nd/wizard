"""Retrievable company knowledge: business definitions, platform guides and company notes (organisation, products,
processes, glossary).

Notes are context Gemini looks up when relevant, not a mandatory pipeline. Each note carries its approval status so an
unsigned draft is never presented as an owner-approved definition, and when an expert last confirmed it.
Search ranks sections (BM25 over `##` sections; glossary notes entry by entry) and boosts a note's title, aliases, tags
and summary, so a long note returns the part that matches instead of its whole body. The note format is documented in
templates/content/schema/knowledge-standard.md."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
NOTE_TYPES = ("overview", "entity", "concept", "process", "metric", "platform", "glossary", "faq", "decision", "dataset")
STOPWORDS = frozenset("""a about after all also an and any are as at be been before but by can could did do does each
for from had has have how i if in into is it its me more most my no not of on or our out over should so some such than
that the their them then there these they this those to under up us was we were what when where which while who why
will with would you your""".split())
WORD = re.compile(r"\w+")
HEADING = re.compile(r"^##\s+(.+?)\s*#*\s*$")
ENTRY = re.compile(r"^[-*]\s+\*\*(.+?)\*\*")
FULL_TEXT_CHARS = 3000  # a longer note returns its lead and matching sections, not its whole body
FIELD_WEIGHT = 1.5      # title, aliases, tags, id and summary weigh more than body text
EXACT_NAME_BONUS = 5.0  # the query is exactly a note's title, alias or id
K1, B = 1.2, 0.75


@dataclass(frozen=True)
class Note:
    id: str
    title: str
    status: str
    owner: str
    tags: tuple[str, ...]
    body: str
    path: str
    type: str = ""
    summary: str = ""
    aliases: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    updated: str = ""
    reviewed: str = ""
    reviewed_by: str = ""

    @property
    def area(self) -> str:
        """Top-level folder under knowledge/ (company, metrics, platforms...); notes at the top level are 'general'."""
        parts = Path(self.path).parts
        return parts[1] if len(parts) > 2 else "general"


@dataclass(frozen=True)
class Section:
    heading: str  # "" for the lead text before the first `##` heading; the term for a glossary entry
    text: str
    entry: bool = False

    def render(self) -> str:
        return self.text if self.entry or not self.heading else f"## {self.heading}\n{self.text}".rstrip()


@dataclass(frozen=True)
class Hit:
    note: Note
    score: float
    sections: tuple[Section, ...]  # matching sections, best first


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_list(value: str) -> tuple[str, ...]:
    """`[a, "b, c", d]` → ('a', 'b, c', 'd'). Front matter is flat: one `key: value` per line, lists in brackets."""
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    items: list[str] = []
    current, quote = "", ""
    for char in text:
        if quote:
            if char == quote:
                quote = ""
            else:
                current += char
        elif char in "\"'" and not current.strip():
            quote = char
        elif char == ",":
            items.append(current.strip())
            current = ""
        else:
            current += char
    items.append(current.strip())
    return tuple(item for item in items if item)


def front_matter(text: str) -> tuple[dict[str, str], str] | None:
    """Split a note into its front matter fields (raw strings) and body; None when there is no front matter."""
    match = FRONT_MATTER.match(text.lstrip("﻿").replace("\r\n", "\n"))
    if not match:
        return None
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, match.group(2).strip()


def parse_note(path: Path, root: Path) -> Note:
    parsed = front_matter(path.read_text(encoding="utf-8-sig"))
    if parsed is None:
        raise ValueError(f"{path} has no front matter")
    meta, body = parsed
    text = {key: unquote(meta.get(key, "")) for key in ("title", "owner", "type", "summary", "updated", "reviewed",
                                                        "reviewed_by")}
    return Note(id=meta["id"], title=text["title"], status=meta["status"], owner=text["owner"] or "TBD",
                tags=parse_list(meta.get("tags", "")), body=body, path=path.relative_to(root).as_posix(),
                type=text["type"], summary=text["summary"], aliases=parse_list(meta.get("aliases", "")),
                related=parse_list(meta.get("related", "")), sources=parse_list(meta.get("sources", "")),
                updated=text["updated"], reviewed=text["reviewed"], reviewed_by=text["reviewed_by"])


def split_sections(note: Note) -> list[Section]:
    """`##` sections in order (the lead first); in a glossary note every `- **Term**` bullet is its own entry."""
    blocks: list[tuple[str, list[str]]] = [("", [])]
    for line in note.body.splitlines():
        match = HEADING.match(line)
        if match:
            blocks.append((match.group(1), []))
        else:
            blocks[-1][1].append(line)
    sections: list[Section] = []
    for heading, lines in blocks:
        if note.type == "glossary":
            intro: list[str] = []
            entries: list[tuple[str, list[str]]] = []
            for line in lines:
                match = ENTRY.match(line)
                if match:
                    entries.append((match.group(1).strip(), [line]))
                elif entries and line.strip() and (line[:1].isspace() or not line.lstrip().startswith(("- ", "* "))):
                    entries[-1][1].append(line)
                else:
                    intro.append(line)
            if "\n".join(intro).strip() or (heading and not entries):
                sections.append(Section(heading, "\n".join(intro).strip()))
            sections += [Section(term, "\n".join(body).strip(), entry=True) for term, body in entries]
        else:
            text = "\n".join(lines).strip()
            if text or heading:
                sections.append(Section(heading, text))
    return sections


def stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def terms(text: str) -> list[str]:
    return [stem(w) for w in WORD.findall(text.casefold()) if w not in STOPWORDS and (len(w) > 1 or w.isdigit())]


def _phrase(text: str) -> str:
    return " ".join(WORD.findall(text.casefold()))


class KnowledgeBase:
    def __init__(self, notes: list[Note], areas: dict[str, str] | None = None):
        self.notes = notes
        self.areas = areas or {}
        self.by_id = {note.id: note for note in notes}
        self.sections = {note.id: split_sections(note) for note in notes}
        self._chunks: list[tuple[Note, Section, Counter[str], int]] = []
        for note in notes:
            for section in self.sections[note.id]:
                counts = Counter(terms(f"{section.heading} {section.text}"))
                self._chunks.append((note, section, counts, sum(counts.values())))
        chunk_df: Counter[str] = Counter(t for _, _, counts, _ in self._chunks for t in counts)
        total = max(len(self._chunks), 1)
        self._chunk_idf = {t: math.log(1 + (total - df + 0.5) / (df + 0.5)) for t, df in chunk_df.items()}
        self._average = sum(length for *_, length in self._chunks) / total or 1.0
        self._fields = {note.id: set(terms(" ".join((note.title, note.id.replace("-", " "), note.summary, *note.tags,
                                                     *note.aliases)))) for note in notes}
        self._names = {note.id: {_phrase(n) for n in (note.title, note.id.replace("-", " "), *note.aliases)}
                       for note in notes}
        self._vocabulary = {note.id: set(self._fields[note.id]) for note in notes}
        for note, _, counts, _ in self._chunks:
            self._vocabulary[note.id].update(counts)
        field_df: Counter[str] = Counter(t for fields in self._fields.values() for t in fields)
        count = max(len(notes), 1)
        self._field_idf = {t: math.log(1 + (count - df + 0.5) / (df + 0.5)) for t, df in field_df.items()}

    @classmethod
    def load(cls, directory: Path) -> KnowledgeBase:
        notes = [parse_note(p, directory.parent) for p in sorted(directory.rglob("*.md")) if p.name != "README.md"]
        areas = {}
        for readme in sorted(directory.glob("*/README.md")):
            parsed = front_matter(readme.read_text(encoding="utf-8-sig"))
            text = parsed[1] if parsed else readme.read_text(encoding="utf-8-sig")
            paragraph = next((p.strip() for p in re.split(r"\n\s*\n", text) if p.strip() and not p.lstrip().startswith("#")), "")
            areas[readme.parent.name] = " ".join(paragraph.split())[:240]
        return cls(notes, areas)

    def find(self, query: str, limit: int = 5) -> list[Hit]:
        wanted = list(dict.fromkeys(terms(query)))
        if not wanted:
            return []
        matched: dict[str, list[tuple[float, Section]]] = {}
        for note, section, counts, length in self._chunks:
            score = 0.0
            for term in wanted:
                frequency = counts.get(term, 0)
                if frequency:
                    score += self._chunk_idf[term] * frequency * (K1 + 1) / (frequency + K1 * (1 - B + B * length / self._average))
            if score:
                matched.setdefault(note.id, []).append((score, section))
        phrase = _phrase(query)
        hits = []
        for note in self.notes:
            fields = self._fields[note.id]
            score = FIELD_WEIGHT * sum(self._field_idf[t] for t in wanted if t in fields)
            if phrase in self._names[note.id]:
                score += EXACT_NAME_BONUS
            ranked = sorted(matched.get(note.id, []), key=lambda item: -item[0])
            if ranked:
                score += ranked[0][0] + 0.25 * sum(s for s, _ in ranked[1:])
            if score <= 0:
                continue
            covered = sum(1 for t in wanted if t in self._vocabulary[note.id])
            score *= 0.5 + 0.5 * covered / len(wanted)  # notes that cover more of the question rank higher
            hits.append(Hit(note, score, tuple(section for _, section in ranked)))
        hits.sort(key=lambda hit: (-hit.score, hit.note.id))
        return hits[:limit]

    def search(self, query: str, limit: int = 5) -> list[Note]:
        return [hit.note for hit in self.find(query, limit)]

    def excerpt(self, hit: Hit, max_chars: int = FULL_TEXT_CHARS) -> tuple[str, list[str]]:
        """The note's text for a search result: the whole body when short, else the lead plus the best-matching
        sections in document order. Also returns the headings left out, so Gemini knows what else the note covers."""
        note = hit.note
        if len(note.body) <= max_chars:
            return note.body, []
        sections = self.sections[note.id]
        chosen: list[Section] = [s for s in sections[:1] if not s.heading]
        budget = max_chars - sum(len(s.text) for s in chosen)
        for section in hit.sections:
            size = len(section.render())
            if section in chosen or (size > budget and len(chosen) > 1):
                continue
            chosen.append(section)
            budget -= size
            if budget <= 0:
                break
        order = {id(s): i for i, s in enumerate(sections)}
        text = "\n\n".join(s.render() for s in sorted(chosen, key=lambda s: order.get(id(s), 0)))
        left_out = [s.heading for s in sections if s.heading and s not in chosen]
        return text, left_out[:40]

    def index(self, area: str | None = None) -> list[Note]:
        return sorted((n for n in self.notes if area in (None, n.area)), key=lambda n: (n.area, n.title.casefold()))
