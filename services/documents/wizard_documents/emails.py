"""Read .eml messages and HTML with the standard library. Outlook .msg files need Outlook (see office.py)."""
from __future__ import annotations

import re
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

from .common import Converted, safe_name, tidy, unique


class _TextOfHtml(HTMLParser):
    BLOCKS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "table", "section", "blockquote", "ul", "ol"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "head", "title"):
            self.skip += 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "head", "title") and self.skip:
            self.skip -= 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def html_text(markup: str) -> str:
    parser = _TextOfHtml()
    parser.feed(markup)
    return tidy(re.sub(r"[ \t]+", " ", "".join(parser.parts)))


def people(value: str | None) -> str:
    """Display names only: 'Ana Silva <ana@corp>' -> 'Ana Silva'; bare addresses -> '<email>'."""
    return ", ".join(name or "<email>" for name, address in getaddresses([value or ""]) if name or address)


def email_header(subject: str, sender: str, to: str, cc: str, sent: str, attachments: list[str]) -> str:
    lines = [f"Subject: {subject}", f"From: {sender}", f"To: {to}"]
    if cc:
        lines.append(f"Cc: {cc}")
    lines += [f"Date: {sent}", f"Attachments: {', '.join(attachments) or 'none'}"]
    return "\n".join(lines)


def read_eml(path: Path, attachments: Path) -> Converted:
    with path.open("rb") as handle:
        message = BytesParser(policy=policy.default).parse(handle)
    assert isinstance(message, EmailMessage)
    try:
        sent = parsedate_to_datetime(str(message["date"])).strftime("%Y-%m-%d %H:%M") if message["date"] else ""
    except (TypeError, ValueError):
        sent = str(message["date"] or "")
    body_part = message.get_body(preferencelist=("plain", "html"))
    body = ""
    if body_part is not None:
        content = body_part.get_content()
        body = html_text(content) if body_part.get_content_type() == "text/html" else str(content)
    saved: list[Path] = []
    names = []
    for part in message.iter_attachments():
        rfc822 = part.get_content_type() == "message/rfc822"
        name = part.get_filename() or ("attached-message.eml" if rfc822 else "")
        if not name:
            continue
        names.append(name)
        if rfc822:
            inner = part.get_content()
            payload = inner.as_bytes() if isinstance(inner, EmailMessage) else b""
        else:
            raw = part.get_payload(decode=True)
            payload = raw if isinstance(raw, bytes) else b""
        if payload:
            attachments.mkdir(parents=True, exist_ok=True)
            target = unique(attachments / safe_name(name))
            target.write_bytes(payload)
            saved.append(target)
    header = email_header(str(message["subject"] or ""), people(message["from"]), people(message["to"]),
                          people(message["cc"]) if message["cc"] else "", sent, names)
    return Converted(header + "\n\n" + tidy(body), "eml", attachments=saved)
