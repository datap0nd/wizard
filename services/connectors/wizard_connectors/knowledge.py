"""Retrievable business definitions (metric notes, calendar, market and model terminology).

Definitions are context Gemini can look up when relevant, not a mandatory pipeline. Each note carries its approval status
so an unsigned draft is never presented as an owner-approved definition."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


@dataclass(frozen=True)
class Note:
    id: str
    title: str
    status: str
    owner: str
    tags: tuple[str, ...]
    body: str
    path: str


def parse_note(path: Path, root: Path) -> Note:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = FRONT_MATTER.match(text)
    if not match:
        raise ValueError(f"{path} has no front matter")
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    tags = tuple(t.strip() for t in meta.get("tags", "").strip("[]").split(",") if t.strip())
    return Note(id=meta["id"], title=meta["title"], status=meta["status"], owner=meta.get("owner", "TBD"), tags=tags,
                body=match.group(2).strip(), path=path.relative_to(root).as_posix())


class KnowledgeBase:
    def __init__(self, notes: list[Note]):
        self.notes = notes

    @classmethod
    def load(cls, directory: Path) -> KnowledgeBase:
        return cls([parse_note(p, directory.parent) for p in sorted(directory.rglob("*.md")) if p.name != "README.md"])

    def search(self, query: str, limit: int = 5) -> list[Note]:
        terms = [t for t in re.findall(r"[a-z0-9]+", query.casefold()) if len(t) > 1]
        scored = []
        for note in self.notes:
            haystack_title = f"{note.title} {' '.join(note.tags)} {note.id}".casefold()
            haystack_body = note.body.casefold()
            score = sum(3 * haystack_title.count(t) + haystack_body.count(t) for t in terms)
            if score:
                scored.append((score, note.id, note))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [note for _, _, note in scored[:limit]]
