"""Warnings for knowledge notes that the knowledge-base review of 2 November 2026 found and the validator missed.

Performance figures (knowledge standard section 4, rule 7), details that only make sense on one PC (section 6), an
owner field naming several owners or not in the standard's form (section 3), a metric note without `## Where to get
it` (section 11), a dataset note without `## Example query` (section 10) or with an empty `related` (section 11's
backlink step). Every one is a warning, never an error: a note with an error is left out at load and a synced commit
with errors is not applied, so a check that can be wrong must never drop a note.

The figure check is built for few false positives. It flags a percentage, a multiplier, a number with thousands
separators or a scale word (thousand, million, K, M, bn...) or a currency amount only when a measure word (share, rate,
units, sales, revenue, spend...) is in the same sentence, a few words away. It leaves out code, `## Columns`,
`## Example query`, worked equations ("32.0% - 31.2% = +0.8 pp"), unit constants ("per USD 1M", "per 1,000 devices"),
thresholds ("USD 600 or more", price bands, approval limits), counts of structural things ("1.2 million rows", "1,450
stores"), number formats ("1,234.5" where the sentence is about writing numbers) and, in dataset notes, value lists and
ranges. Dates, ids, years and version numbers never match. A question that names a measure and one specific period
("What was our share in Q1 2026?") asks for a figure, unless it asks where the measure is or how it is defined."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .knowledge import parse_list, unquote

CURRENCIES = ("USD|EUR|GBP|AED|SAR|EGP|MAD|KWD|QAR|OMR|BHD|JOD|IQD|LBP|DZD|TND|TRY|PKR|INR|KRW|CNY|JPY|CHF|ZAR|NGN|KES")
NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
SCALE = r"(?:thousand|million|billion|trillion|bn|mn|mln|K|k|M|B)\b"
FIGURE = re.compile(rf"""(?<![\w.,/])(?:
      (?:[$€£¥₩]|\b(?:{CURRENCIES})\s?)(?P<money>{NUMBER})(?:\s?{SCALE})?
    | (?P<number>{NUMBER})(?:
          \s?(?:%|percent\b|per\s?cent\b|pp\b|percentage\ points?\b|bps\b|basis\ points?\b)
        | [x×](?!\w)
        | \s?{SCALE}(?:\s?(?:{CURRENCIES})\b)?
        | \s?(?:{CURRENCIES})\b)
    | (?P<grouped>\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?)(?!\d))""", re.X)
MEASURE = re.compile(r"(?i)\b(?:shares?|rates?|attach(?:ed|es|ment)?|units?|sales|sold|selling|revenues?|spend(?:s|ing)?"
                     r"|growth|grew|grow(?:s|ing)?|margins?|prices?|priced|pricing|ASP|hosts?|users?|devices?"
                     r"|shipments?|shipped|sell-in|sell-out|sell-through|targets?|forecasts?|budgets?|costs?|profits?"
                     r"|volumes?|conversions?|penetration|activations?|turnover|GMV|market size"
                     r"|of (?:the |total )?market)\b")
# Not markets, regions or periods: "41.7% of the market" and "41.7% last quarter" are performance figures.
STRUCTURAL = re.compile(r"(?i)^(?:rows?|records?|columns?|fields?|tables?|views?|reports?|dashboards?|cities|city"
                        r"|stores?|outlets?|retailers?|partners?|distributors?|accounts?|subsidiaries|subsidiary"
                        r"|entities|entity|sites?|warehouses?|models?|brands?|skus?|categories|category|languages?"
                        r"|slides?|decks?|files?|pages?|steps?|teams?|people|employees?|staff|vat|tax(?:es)?"
                        r"|dut(?:y|ies))$")
FILLER = frozenset({"of", "the", "a", "an", "all", "our", "its", "their", "some", "about", "around"})
CLAUSE_END = re.compile(r"[,;:.()|\[\]]|\b(?:in|across|at|for|by|on|to|from|with|per|after|before|since|during|over"
                        r"|under|versus|vs|than|and|or|but|is|was|are|were|which|that|when|while)\b", re.I)
FORMAT_CUE = re.compile(r"(?i)\b(?:formats?|formatted|formatting|separators?|decimals?|decimal places?|rounded|rounding"
                        r"|round to|abbreviat\w*|notation|written as|write \w+ as|shown as|displayed as|how numbers"
                        r"|(?:in|for) (?:thousands|millions|billions))\b")
EXAMPLE_CUE = re.compile(r"(?i)\be\.g\.|\b(?:for example|such as|like)\b")
TERM = rf"[-+−]?\(?(?:[$€£]|\b(?:{CURRENCIES})\s?)?\d[\d.,]*\)?\s?(?:%|pp\b|[KMB]\b|(?:{CURRENCIES})\b)?"
EQUATION = re.compile(rf"{TERM}(?:\s*[-+−×*/÷]\s*{TERM})*\s*=\s*{TERM}")
UNIT_CONSTANT = re.compile(r"(?i)(?:\bper|\bevery|\bin|[/÷×*])\s*$")  # "per USD 1M", "per 1,000 devices", "÷ 1,000"
THRESHOLD_BEFORE = re.compile(r"(?i)(?:[<>≤≥]=?|\bat least|\bat most|\bup to)\s*$")
THRESHOLD_AFTER = re.compile(r"(?i)^\s*(?:\+|or more\b|or less\b|or above\b|or below\b|and above\b|and below\b)")
PRICE_BANDS = re.compile(r"(?i)\b(?:bands?|tiers?|segments?|brackets?|buckets?|price points?|price ranges?)\b")
COMPARED = re.compile(r"(?i)\b(?:above|below|over|under|exceed(?:s|ing)?|more than|less than|greater than|fewer than)"
                      r"\s*$")
RULE = re.compile(r"(?i)\b(?:counts? as|treated as|classed as|classified as|is called|defined as|means|flag(?:s|ged)?"
                  r"|thresholds?|cut-?offs?|alerts?|needs?|requires?|approv\w*)\b")
TAX = re.compile(r"(?i)\b(?:VAT|tax(?:es)?|dut(?:y|ies))(?:\s+rate)?\s*(?:of|at|is|=|:)?\s*$")
ABOUT_A_SOURCE = re.compile(r"(?i)^where\b|^which (?:reports?|tables?|views?|datasets?|sources?|dashboards?|portals?"
                            r"|objects?)\b|\b(?:defined|definition|calculated|computed|mean)\b")
VALUE_LIST = re.compile(r"(?i)\b(?:values?|one of|distinct|ranges?|bands?|tiers?|buckets?|brackets?|segments?"
                        r"|thresholds?|between|from \S+ to)\b")
PERIOD = re.compile(r"(?i)\b(?:Q[1-4]|H[12])\s*'?(?:20)?\d{2}\b|\b(?:19|20)\d{2}\s*[-/ ]?\s*(?:Q[1-4]|H[12])\b"
                    r"|\b(?:FY|CY)\s*'?\d{2,4}\b|\b(?:19|20)\d{2}-(?:0[1-9]|1[0-2])\b(?!-\d)"
                    r"|\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
                    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+(?:19|20)\d{2}\b"
                    r"|\b(?:in|for|of|during|by)\s+(?:19|20)\d{2}\b|\bW(?:eek)?\s?\d{1,2}\s+(?:of\s+)?(?:19|20)\d{2}\b")
SENTENCE = re.compile(r"(?<!\be\.g\.)(?<!\bi\.e\.)(?<![Vv]s\.)(?<=[.!?])\s+(?=[A-Z(\"'])|;\s+")
CLEAN = [re.compile(r"`[^`]*`"), re.compile(r"<!--.*?-->"), re.compile(r"\]\([^)]*\)"), re.compile(r"https?://\S+"),
         re.compile(r"\[(?:S-[0-9a-f]{8}|A-[\w-]+)(?:\s*[,;]\s*(?:S-[0-9a-f]{8}|A-[\w-]+))*\]"),
         re.compile(r"\b(?:S-[0-9a-f]{8}|A-[a-z0-9][\w-]*)\b")]
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
HEADING_LINE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
TABLE_RULE = re.compile(r"^\|?\s*:?-{3,}")
PC_SPECIFIC = [
    ("a server address", re.compile(r"(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?!\w|\.\d)"
                                    r"|\b(?:localhost|127\.0\.0\.1):\d{2,5}\b|://localhost\b|https?://[\w.-]+:\d{2,5}\b"
                                    r"|(?<![\w/.-])(?=[\w.-]*[A-Za-z])(?=[\w.-]*[\d._-])[A-Za-z][\w.-]{3,}:\d{2,5}\b")),
    ("a drive letter", re.compile(r"(?<![\w\\/])[A-Za-z]:[\\/][^\s`'\"]*|\b[A-Z]: ?drive\b")),
    ("a network share path", re.compile(r"\\\\[\w.$-]+\\[^\s\\`'\"]+")),
    ("a path into a PC's folders", re.compile(r"(?i)\bcontent[\\/](?:inbox|register|knowledge|contracts)\b[^\s`'\"]*"
                                              r"|(?<![\w/\\])inbox[\\/]_?(?:text|digests|postgres)\b"
                                              r"|%(?:USERPROFILE|APPDATA|LOCALAPPDATA|HOMEPATH|ONEDRIVE)%")),
    ("a local script", re.compile(r"(?i)(?<![\w/.-])[\w.-]+\.(?:bat|cmd|ps1|vbs)\b")),
]
OWNER_TBD = re.compile(r"^TBD\s*[-–—:]\s*(?P<role>[^()]*?)\s*(?:\([^()]*\))?$", re.I)
OWNER_NAMED = re.compile(r"^(?P<name>[A-Za-zÀ-ÿ' .-]+?),\s*(?P<role>[^,()][^()]*?)$")
TRAILING_NOTE = re.compile(r"\s*\([^()]*\)\s*$")
SEVERAL = re.compile(r"\w{2,}\s*/\s*\w{2,}|\s/\s|[;|]|\bor\b", re.I)


@dataclass
class Unit:
    section: str  # the `##` heading it sits under, lowercase
    text: str
    header: str = ""  # a table row's header row
    item: bool = False  # a list item


@dataclass
class Parsed:
    units: list[Unit] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)  # every `##` heading, lowercase


def parse(body: str) -> Parsed:
    """The note's prose, one unit per paragraph, list item, table row or heading. Fenced and indented code is left
    out, and `##` headings inside code do not count."""
    parsed = Parsed()
    block: list[str] = []
    section, fence, header, blank, code = "", "", "", True, False

    def flush() -> None:
        if block:
            parsed.units.append(Unit(section, " ".join(block), item=bool(LIST_ITEM.match(block[0]))))
            block.clear()

    for line in body.splitlines():
        stripped = line.strip()
        if fence:
            fence = "" if stripped.startswith(fence) else fence
            continue
        if stripped.startswith(("```", "~~~")):
            flush()
            fence, header = stripped[:3], ""
            continue
        if not stripped:
            flush()
            header, blank = "", True
            continue
        code = line.startswith(("    ", "\t")) and (blank or code) and not block
        blank = False
        if code:
            continue
        heading = HEADING_LINE.match(stripped)
        if heading:
            flush()
            if len(heading.group(1)) == 2:
                section = heading.group(2).lower()
                parsed.sections.append(section)
            parsed.units.append(Unit(section, heading.group(2)))
            header = ""
        elif stripped.startswith("|"):
            flush()
            if not header:
                header = stripped
                parsed.units.append(Unit(section, stripped))
            elif not TABLE_RULE.match(stripped):
                parsed.units.append(Unit(section, stripped, header=header))
        else:
            if LIST_ITEM.match(line):
                flush()
            block.append(stripped)
    flush()
    return parsed


def _clean(text: str) -> str:
    for pattern in CLEAN:
        text = pattern.sub(" ", text)
    return text


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][\w'-]*", text)


def _snippet(before: str, figure: str, after: str) -> str:
    left = re.search(r"(?:\S+\s+){0,3}\S*$", before)
    right = re.match(r"(?:\s*\S+){0,2}", after)
    text = (left.group() if left else "") + figure + (right.group() if right else "")
    return " ".join(text.split()).strip(" ,.;:()*|")[:60]


def _structural(after: str) -> bool:
    """The figure counts what something is made of (1.2 million rows, 1,450 retail stores): a structural fact, not a
    performance figure. Only the words right after it count, up to a preposition or punctuation."""
    clause = CLAUSE_END.split(after, maxsplit=1)[0]
    words = [w.lower().removesuffix("'s") for w in _words(clause) if w.lower() not in FILLER][:2]
    for word in words:
        if MEASURE.fullmatch(word):
            return False
        if STRUCTURAL.match(word):
            return True
    return False


def _value(number: str) -> float:
    try:
        return float(number.replace(",", ""))
    except ValueError:
        return -1.0


def _power_of_ten(number: str) -> bool:
    """1, 10, 1,000, 0.1...: the scale of a unit or a rounding step, not a measured value."""
    value = _value(number)
    return value > 0 and abs(math.log10(value) - round(math.log10(value))) < 1e-9


def _number_format(number: str, sentence: str, section: str) -> bool:
    """A sentence or section about how numbers are written (rounding, separators, K/M/B), or a format mask such as
    1,234.5 or 0.0% given as an example: how a number is written, not a value."""
    if FORMAT_CUE.search(sentence) or FORMAT_CUE.search(section):
        return True
    digits = re.sub(r"\D", "", number)
    mask = (len(digits) >= 3 and "1234567890".startswith(digits)) or set(digits) <= {"0"}
    return mask and EXAMPLE_CUE.search(sentence) is not None


def _exempt(match: re.Match[str], sentence: str, section: str, equations: list[tuple[int, int]]) -> bool:
    """A number that is not a performance figure, though it looks like one."""
    number = match.group("money") or match.group("number") or match.group("grouped")
    figure, before, after = match.group(), sentence[:match.start()], sentence[match.end():]
    price_point = bool(re.search(rf"[$€£¥₩]|\b(?:{CURRENCIES})\b", figure)) and not re.search(rf"\d\s?{SCALE}", figure)
    compared = COMPARED.search(before) is not None and (price_point or RULE.search(sentence) is not None)
    return (any(start <= match.start() and match.end() <= end for start, end in equations)  # 32.0% - 31.2% = +0.8 pp
            or ("%" in figure and _value(number) in (0.0, 100.0))  # shares add up to 100%
            or (_power_of_ten(number) and UNIT_CONSTANT.search(before) is not None)  # per USD 1M, per 1,000 devices
            or THRESHOLD_BEFORE.search(before) is not None or THRESHOLD_AFTER.match(after) is not None
            or compared  # a rule's limit: "spend above USD 50,000 needs approval", "below 0.1 pp counts as flat"
            or (price_point and PRICE_BANDS.search(sentence) is not None)  # price bands and tiers
            or TAX.search(before) is not None  # VAT at 15%
            or _number_format(number, sentence, section) or _structural(after))


def _asks_for_a_figure(sentence: str) -> bool:
    """A question that names a measure and one specific period ("What was our share in Q1 2026?"); a question about
    where a measure lives or how it is defined is not."""
    question = LIST_ITEM.sub("", sentence).strip()
    return (MEASURE.search(question) is not None and PERIOD.search(question) is not None
            and not ABOUT_A_SOURCE.search(question))


def figures(parsed: Parsed, kind: str, extra: list[str]) -> tuple[int, list[str]]:
    """(how many figures, up to 3 examples) in the note's prose and its questions."""
    count, examples = 0, []
    units = [Unit("", text) for text in extra if text] + parsed.units
    for unit in units:
        if unit.section.startswith(("columns", "example quer")):
            continue
        text = _clean(unit.text)
        for sentence in [text] if unit.header else SENTENCE.split(text):
            if kind == "dataset" and VALUE_LIST.search(sentence):
                continue  # value lists and ranges describe a dataset's coverage (standard section 10)
            equations = [(m.start(), m.end()) for m in EQUATION.finditer(sentence)]
            for match in FIGURE.finditer(sentence):
                before, after = sentence[:match.start()], sentence[match.end():]
                near = " ".join(_words(before)[-10:] + _words(after)[:10]) + " " + unit.header
                if MEASURE.search(near) and not _exempt(match, sentence, unit.section, equations):
                    count += 1
                    examples.append(_snippet(before, match.group().strip(), after))
            question = (unit.section.startswith("questions") and unit.item) or sentence.rstrip().endswith("?")
            if question and _asks_for_a_figure(sentence):
                count += 1
                examples.append(LIST_ITEM.sub("", sentence).strip()[:70])
    return count, examples[:3]


def pc_specific(text: str) -> list[tuple[str, str]]:
    found = []
    for kind, pattern in PC_SPECIFIC:
        match = pattern.search(text)
        if match:
            found.append((kind, match.group().strip().rstrip(".,;:)")[:50]))
    return found


def owner_problem(owner: str) -> str | None:
    owner = unquote(owner)
    if not owner:
        return None  # a missing owner is an error elsewhere
    main = TRAILING_NOTE.sub("", owner).strip()
    tbd = OWNER_TBD.match(owner)
    if SEVERAL.search(main) or main.count(",") > 2 or (tbd and "," in tbd.group("role")):
        return (f"owner '{owner[:80]}' names several owners or mixes the two forms: only one owner signs a note. Keep "
                "the one whose role fits the note's topic best, written `<Name>, <role>` or `TBD - <role> (ask the "
                "user)` (standard section 3)")
    if tbd and tbd.group("role"):
        return None
    if not owner.upper().startswith("TBD") and OWNER_NAMED.match(main):
        return None
    return (f"owner '{owner[:80]}' is not in the standard's form: `<Name>, <role>` when a person owns the note, "
            "otherwise `TBD - <role> (ask the user)` (standard section 3)")


def note_warnings(meta: dict[str, str], body: str, kind: str) -> list[str]:
    """The review's warnings for one note: figures, PC-specific details, owner, missing sections, empty `related`."""
    warnings: list[str] = []
    parsed = parse(body)
    summary, title = unquote(meta.get("summary", "")), unquote(meta.get("title", ""))
    count, examples = figures(parsed, kind, [title, summary])
    if count:
        shown = ", ".join(f'"{e}"' for e in examples)
        warnings.append(f"{count} performance figure(s), e.g. {shown}: notes hold no performance figures (standard "
                        "section 4, rule 7). Sales, spend, share, margins, targets and forecasts come from the data "
                        "sources, where Wizard can cite and check them; say what the source shows instead (the measure, "
                        "its unit, breakdown and period) and write questions with placeholders (\"What is our share in "
                        "<market> by quarter?\")")
    details = pc_specific(f"{summary}\n{body}")
    if details:
        shown = "; ".join(f"{k} ({v})" for k, v in details[:3])
        warnings.append(f"details that only work on one PC: {shown}. Replace each with what a reader on any PC can "
                        "use: the system's name and what it is, the team's shared drive, how to get access (by role); "
                        "Wizard's own settings hold the addresses it needs, never a note (standard section 6)")
    problem = owner_problem(meta.get("owner", ""))
    if problem:
        warnings.append(problem)
    if kind == "metric" and not any(s.startswith("where to get it") for s in parsed.sections):
        warnings.append("metric note without `## Where to get it`: end it with one block per database object or "
                        "mapped portal report that holds the measure (its filters, period and market columns, an "
                        "example query), written from the dataset notes and the portal maps (standard section 11)")
    if kind == "dataset" and not any(s.startswith("example quer") for s in parsed.sections):
        warnings.append("dataset note without `## Example query`: add one or two short SELECTs for the questions the "
                        "object answers most often, column names exactly as the export spells them and the filters "
                        "from `## Pitfalls` (standard section 10)")
    if kind == "dataset" and not parse_list(meta.get("related", "")):
        warnings.append("dataset note with an empty `related`: add the ids of the metric notes whose `## Where to get "
                        "it` names this object (standard section 11), and the measure's name to its aliases or tags")
    return warnings
