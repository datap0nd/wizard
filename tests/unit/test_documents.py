"""Document converter: standard-library readers, sheet profiles, the bulk inbox (manifest, source ids, duplicates, email
attachments, masking, in-place folders), and the Office (COM) readers against fake Office objects."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from tests.office_files import docx, eml, pptx, xlsx

from wizard_documents import office
from wizard_documents.common import ConversionError, column_letter
from wizard_documents.convert import Converter, convert
from wizard_documents.inbox import Inbox
from wizard_documents.sheets import Sheet, header_row, render

ROOT = Path(__file__).resolve().parents[2]


def test_pptx_slides_tables_charts_notes_and_hidden_slides(tmp_path):
    result = convert(pptx(tmp_path / "deck.pptx"), tmp_path / "a", tmp_path / "b", office="never")
    assert result.method == "ooxml" and result.parts == ["Slide 1: Launch process", "Slide 2: Backup"]
    text = result.text
    assert "## Slide 1: Launch process" in text and "  - Owner: Product Marketing" in text
    assert "| G2 | Head of Sales |" in text and "Picture: Org chart of the GTM office" in text
    assert "Chart: Sell-out by quarter" in text and "| Q2 | 150 |" in text, "chart values are the slide's message"
    assert "Speaker notes:\n- The GTM office owns the gate calendar." in text
    assert "## Slide 2: Backup (hidden slide)" in text


def test_xlsx_small_sheets_whole_large_sheets_profiled_with_formulas(tmp_path):
    text = convert(xlsx(tmp_path / "book.xlsx"), tmp_path / "a", tmp_path / "b", office="never").text
    assert "| EG | Egypt |" in text, "a code list is shown whole"
    assert "## Sheet: Sales: 81 rows x 4 columns (A1:D81)" in text
    assert "| D | Revenue | number | 100% | 50 to 2025 | =B2*C2 (100% of rows) |" in text
    assert "| C | Price | number | 100% | 2.5 |" in text
    assert "First 16 rows:" in text and "| M1 | 160 |" in text and "| M2 | 170 |" not in text, "rows are a sample"
    assert "## Sheet: Old (hidden)" in text


def test_docx_headings_lists_and_tables(tmp_path):
    result = convert(docx(tmp_path / "doc.docx"), tmp_path / "a", tmp_path / "b", office="never")
    assert result.text.startswith("# Fiscal calendar") and "- Q1 is January to March" in result.text
    assert "| Q1 | Jan-Mar |" in result.text and result.parts == ["Fiscal calendar"]


def test_protected_or_legacy_files_need_office(tmp_path):
    protected = tmp_path / "nasca.xlsx"
    protected.write_bytes(b"\x01DRM wrapper, not a zip")
    with pytest.raises(ConversionError, match="protected"):
        convert(protected, tmp_path / "a", tmp_path / "b", office="never")
    legacy = tmp_path / "old.ppt"
    legacy.write_bytes(b"\xd0\xcf\x11\xe0 legacy")
    with pytest.raises(ConversionError, match="need the Office applications"):
        convert(legacy, tmp_path / "a", tmp_path / "b", office="never")


def test_office_parts_with_a_doctype_are_refused(tmp_path):
    import zipfile
    bomb = tmp_path / "bomb.docx"
    with zipfile.ZipFile(bomb, "w") as archive:
        archive.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY a "aaaa">]><w:document/>')
    with pytest.raises(ConversionError, match="DOCTYPE"):
        convert(bomb, tmp_path / "a", tmp_path / "b", office="never")


def test_sheet_header_detection_and_columns():
    assert header_row([[None, None], ["Market", "Units"], ["EG", 10.0]]) == 1
    assert header_row([[1.0, 2.0], [3.0, 4.0]]) is None
    assert column_letter(0) == "A" and column_letter(25) == "Z" and column_letter(26) == "AA"
    text = render(Sheet("Blank", [[None]], total_rows=1, total_columns=1))
    assert "(empty)" in text


def make_inbox(tmp_path: Path) -> Path:
    inbox = tmp_path / "content" / "inbox"
    (inbox / "files").mkdir(parents=True)
    deck = pptx(inbox / "files" / "deck.pptx")
    (inbox / "files" / "copy.pptx").write_bytes(deck.read_bytes())
    xlsx(inbox / "files" / "book.xlsx")
    (inbox / "email").mkdir()
    eml(inbox / "email" / "readiness.eml", deck)
    (inbox / "files" / "notes.txt").write_text("Contact ana.silva@example.com about launches.", encoding="utf-8")
    return tmp_path / "content"


def manifest(content: Path) -> dict[str, dict[str, str]]:
    with (content / "inbox" / "_text" / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        return {row["path"]: row for row in csv.DictReader(handle)}


def test_inbox_manifest_ids_duplicates_attachments_and_masking(tmp_path):
    content = make_inbox(tmp_path)
    with Converter("never") as converter:
        counts = Inbox(content, converter).run()
    rows = manifest(content)
    assert counts == {"ok": 4, "duplicate": 2}
    email = rows["email/readiness.eml"]
    attachment = next(r for p, r in rows.items() if p.startswith("_attachments/"))
    assert attachment["parent"] == email["source_id"] and attachment["path"] == f"_attachments/{email['source_id']}/deck.pptx"
    deck_ids = {rows["files/deck.pptx"]["source_id"], rows["files/copy.pptx"]["source_id"], attachment["source_id"]}
    assert len(deck_ids) == 1, "the same file is one source wherever it sits"
    assert sorted(r["status"] for r in rows.values() if r["source_id"] in deck_ids) == ["duplicate", "duplicate", "ok"]
    email_text = (content / email["text_path"]).read_text(encoding="utf-8")
    assert email_text.startswith(f"---\nsource_id: {email['source_id']}") and "From: Ana Silva" in email_text
    assert "<phone>" in email_text and "9876" not in email_text and "@example.com" not in email_text
    assert "<email>" in (content / rows["files/notes.txt"]["text_path"]).read_text(encoding="utf-8")
    with Converter("never") as converter:  # a second run reuses everything
        assert Inbox(content, converter).run() == counts
    assert manifest(content) == rows


def test_inbox_reads_listed_folders_in_place_and_records_failures(tmp_path):
    content = make_inbox(tmp_path)
    elsewhere = tmp_path / "Shared drive"
    elsewhere.mkdir()
    docx(elsewhere / "process.docx")
    (elsewhere / "protected.pptx").write_bytes(b"\x01NASCA")
    (content / "inbox" / "_sources.txt").write_text(f"# read in place\n{elsewhere}\n", encoding="utf-8")
    with Converter("never") as converter:
        Inbox(content, converter).run()
    rows = manifest(content)
    external = {p: r for p, r in rows.items() if p.startswith("_external/")}
    assert {Path(p).name for p in external} == {"process.docx", "protected.pptx"}
    process = next(r for p, r in external.items() if p.endswith("process.docx"))
    assert process["status"] == "ok" and str(elsewhere) in (content / process["text_path"]).read_text(encoding="utf-8")
    failed = next(r for p, r in external.items() if p.endswith("protected.pptx"))
    assert failed["status"] == "failed" and "protected" in failed["note"]


def test_cli_convert_prints_json(tmp_path):
    out = tmp_path / "out"
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "wizard_docs.py"), "convert", str(docx(tmp_path / "d.docx")),
                             "--out", str(out), "--json", "--office", "never"], capture_output=True, text=True, timeout=60)
    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert result.returncode == 0 and data["status"] == "ok" and data["method"] == "ooxml"
    assert (out / "text.md").read_text(encoding="utf-8").startswith("# Fiscal calendar")


# --- Office (COM) readers against fake Office objects ---------------------------------------------------------------


class Bag:
    def __init__(self, **values: Any):
        self.__dict__.update(values)


class Items(list):
    @property
    def Count(self) -> int:  # noqa: N802 - Office object model names
        return len(self)

    def Item(self, index: int) -> Any:  # noqa: N802
        return self[index - 1]


class ComError(Exception):
    pass


class FakeSession:
    pywintypes = Bag(com_error=ComError)

    def __init__(self, apps: dict[str, Any]):
        self.apps = apps

    def app(self, name: str) -> Any:
        return self.apps[name]

    def error(self, error: BaseException) -> ConversionError:
        return ConversionError(str(error))


class TextRange:
    def __init__(self, text: str):
        self.Text = text

    def Paragraphs(self, index: int, length: int) -> Bag:  # noqa: N802
        return Bag(IndentLevel=2 if index == 2 else 1)


def text_shape(text: str, top: float = 0, kind: int = 17) -> Bag:
    return Bag(Type=kind, Top=top, Left=0, HasTextFrame=-1, TextFrame=Bag(HasText=-1, TextRange=TextRange(text)))


class Chart:
    HasTitle = True
    ChartTitle = Bag(Text="Units by quarter")

    def SeriesCollection(self) -> Items:  # noqa: N802 - a method in late binding, like pywin32's
        return Items([Bag(Name="Units", Values=(120.0, 150.0), XValues=("Q1", "Q2"))])


class Table:
    Rows = Bag(Count=2)
    Columns = Bag(Count=2)

    def Cell(self, row: int, column: int) -> Bag:  # noqa: N802
        return Bag(Shape=text_shape([["Gate", "Approver"], ["G2", "Head of Sales"]][row - 1][column - 1]))


class Slide:
    def __init__(self, index: int, shapes: list[Bag], title: str, exports: list[str]):
        self.SlideIndex = index
        self.Shapes = Items(shapes)
        self.Shapes.HasTitle = -1  # type: ignore[attr-defined]
        self.Shapes.Title = text_shape(title)  # type: ignore[attr-defined]
        self.SlideShowTransition = Bag(Hidden=-1 if index == 2 else 0)
        self.NotesPage = Bag(Shapes=Bag(Placeholders=Items([Bag(PlaceholderFormat=Bag(Type=2), TextFrame=text_shape("Owner: GTM office").TextFrame)])))
        self.exports = exports

    def Export(self, path: str, kind: str, width: int, height: int) -> None:  # noqa: N802
        Path(path).write_bytes(b"png")
        self.exports.append(f"{Path(path).name} {kind} {width}x{height}")


def test_com_powerpoint_reader_reads_shapes_and_exports_visual_slides(tmp_path):
    exports: list[str] = []
    slide1 = Slide(1, [text_shape("Launch process", 0, 14), text_shape("Gate 1\rOwner: Product marketing", 100),
                       Bag(Type=19, Top=200, Left=0, HasTable=-1, Table=Table()),
                       Bag(Type=3, Top=300, Left=0, HasTable=0, HasChart=-1, Chart=Chart())], "Launch process", exports)
    slide2 = Slide(2, [Bag(Type=13, Top=0, Left=0, HasTable=0, HasChart=0, HasSmartArt=0, Width=900, Height=500,
                           AlternativeText="Picture 3")], "Org chart", exports)
    presentation = Bag(PageSetup=Bag(SlideWidth=960, SlideHeight=540), Slides=Items([slide1, slide2]), Close=lambda: None)
    opened: list[dict[str, Any]] = []
    app = Bag(Presentations=Bag(Open=lambda path, **options: opened.append(options) or presentation))
    result = office.read_powerpoint(FakeSession({"powerpoint": app}), tmp_path / "deck.pptx", tmp_path / "assets")
    assert opened == [{"ReadOnly": True, "Untitled": False, "WithWindow": False}], "read-only, no window"
    assert result.parts == ["Slide 1: Launch process", "Slide 2: Org chart"]
    assert "- Gate 1\n  - Owner: Product marketing" in result.text and "| G2 | Head of Sales |" in result.text
    assert "Chart: Units by quarter" in result.text and "| Q2 | 150 |" in result.text
    assert "Speaker notes:\n- Owner: GTM office" in result.text and "(hidden slide)" in result.text
    assert exports == ["slide-002.png PNG 1600x900"], "only the mostly-visual slide becomes a picture"
    assert "Picture\nSpeaker notes" in result.text, "a default picture name is not a description"


class Sheet1:
    Name = "Sales"
    Visible = -1
    UsedRange = Bag(Rows=Bag(Count=3), Columns=Bag(Count=3), Row=1, Column=1)

    def Cells(self, row: int, column: int) -> tuple[int, int]:  # noqa: N802
        return row, column

    def Range(self, start: tuple[int, int], end: tuple[int, int]) -> Bag:  # noqa: N802
        return Bag(Value=(("Market", "Units", "Revenue"), ("EG", 10.0, 25.0), ("SA", 20.0, 50.0)),
                   Formula=(("Market", "Units", "Revenue"), ("EG", "10", "=B2*2.5"), ("SA", "20", "=B3*2.5")))

    def PivotTables(self) -> Items:  # noqa: N802
        return Items([Bag(Name="PT1", SourceData="Sales!R1C1:R3C3", RowFields=Items([Bag(Name="Market")]),
                          ColumnFields=Items(), DataFields=Items([Bag(Name="Sum of Units")]), PageFields=Items())])

    def ChartObjects(self) -> Items:  # noqa: N802
        return Items([Bag(Chart=Chart())])


def test_com_excel_reader_profiles_values_formulas_pivots_and_names(tmp_path):
    opened: list[dict[str, Any]] = []
    workbook = Bag(Worksheets=Items([Sheet1()]), Charts=Items(), Close=lambda save: None,
                   Names=Items([Bag(Name="FY_Start", RefersTo="=Setup!$B$2", Visible=True),
                                Bag(Name="_xlnm.Print_Area", RefersTo="=Sales!$A$1", Visible=True)]))
    app = Bag(Workbooks=Bag(Open=lambda path, **options: opened.append(options) or workbook))
    result = office.read_excel(FakeSession({"excel": app}), tmp_path / "book.xlsx")
    assert opened == [{"UpdateLinks": 0, "ReadOnly": True, "IgnoreReadOnlyRecommended": True, "AddToMru": False}]
    assert "| SA | 20 | 50 |" in result.text and "=B2*2.5 (100% of rows)" in result.text
    assert "PT1 from Sales!R1C1:R3C3 (rows: Market; values: Sum of Units)" in result.text
    assert "Chart: Units by quarter" in result.text
    assert "- FY_Start: =Setup!$B$2" in result.text and "Print_Area" not in result.text


def test_com_errors_are_explained():
    assert "password-protected" in office.com_message(ComError(-2147352567, "Exception occurred.",
                                                              (0, "Microsoft Excel", "The password you supplied is not correct.", None, 0, 0), None))
    assert "not installed" in office.com_message(ComError(-2147221164, "Class not registered", None, None))


def test_pywin32_status_is_reported_honestly():
    ok, detail = office.pywin32_status()
    assert isinstance(ok, bool) and detail
    if sys.platform != "win32":
        assert not ok and "Windows" in detail


class FakeMail:
    def __init__(self, signature: str):
        self.Subject = ""
        self.HTMLBody = ""
        self.signature = signature
        self.calls: list[str] = []

    def Display(self, modal: bool) -> None:  # noqa: N802 - Outlook object model names
        self.calls.append(f"Display({modal})")
        self.HTMLBody = self.signature

    def Send(self) -> None:  # noqa: N802
        self.calls.append("Send")


def outlook_session(mail: FakeMail, kept: list[str]) -> Any:
    session = FakeSession({"outlook": Bag(CreateItem=lambda kind: mail)})
    session.keep_running = kept.append  # type: ignore[attr-defined]
    return session


def test_outlook_draft_opens_unsent_with_the_signature_kept():
    mail = FakeMail('<html><body lang="EN-US"><p>Best, Ana</p></body></html>')
    kept: list[str] = []
    office.open_draft(outlook_session(mail, kept), "Wizard: Sell in by market", "<p>Answer</p>")
    assert mail.Subject == "Wizard: Sell in by market" and mail.calls == ["Display(False)"], "shown, never sent"
    assert mail.HTMLBody == '<html><body lang="EN-US"><p>Answer</p><p>Best, Ana</p></body></html>'
    assert kept == ["outlook"], "a draft on screen must outlive the session"
    plain = FakeMail("")
    office.open_draft(outlook_session(plain, []), "Wizard: no signature", "<p>Answer</p>")
    assert plain.HTMLBody == "<p>Answer</p>"
