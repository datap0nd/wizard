"""Tiny Office Open XML files built by hand for the document converter tests (no Office needed): only the parts the
standard-library reader opens, with the namespaces Office writes."""
from __future__ import annotations

import zipfile
from pathlib import Path

NS_P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
NS_A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
NS_R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
NS_C = 'xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"'
RELS = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'
TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _zip(path: Path, parts: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in parts.items():
            archive.writestr(name, text)
    return path


def _shape(text_xml: str, placeholder: str = "") -> str:
    ph = f'<p:nvPr><p:ph type="{placeholder}"/></p:nvPr>' if placeholder else "<p:nvPr/>"
    return f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="s"/><p:cNvSpPr/>{ph}</p:nvSpPr><p:txBody>{text_xml}</p:txBody></p:sp>'


def _para(text: str, level: int = 0) -> str:
    return f'<a:p><a:pPr lvl="{level}"/><a:r><a:t>{text}</a:t></a:r></a:p>'


def pptx(path: Path) -> Path:
    slide1 = (f'<p:sld {NS_P} {NS_A} {NS_R}><p:cSld><p:spTree>'
              + _shape(_para("Launch process"), "title")
              + _shape(_para("Gate 1: concept approval") + _para("Owner: Product Marketing", 1))
              + '<p:graphicFrame><a:graphic><a:graphicData><a:tbl>'
                '<a:tr><a:tc><a:txBody><a:p><a:r><a:t>Gate</a:t></a:r></a:p></a:txBody></a:tc>'
                '<a:tc><a:txBody><a:p><a:r><a:t>Approver</a:t></a:r></a:p></a:txBody></a:tc></a:tr>'
                '<a:tr><a:tc><a:txBody><a:p><a:r><a:t>G2</a:t></a:r></a:p></a:txBody></a:tc>'
                '<a:tc><a:txBody><a:p><a:r><a:t>Head of Sales</a:t></a:r></a:p></a:txBody></a:tc></a:tr>'
                '</a:tbl></a:graphicData></a:graphic></p:graphicFrame>'
              + '<p:pic><p:nvPicPr><p:cNvPr id="5" name="Picture 4" descr="Org chart of the GTM office"/></p:nvPicPr></p:pic>'
              + '</p:spTree></p:cSld></p:sld>')
    slide2 = (f'<p:sld {NS_P} {NS_A} {NS_R} show="0"><p:cSld><p:spTree>'
              + _shape(_para("Backup"), "title") + '</p:spTree></p:cSld></p:sld>')
    chart = (f'<c:chartSpace {NS_C} {NS_A}><c:chart><c:title><c:tx><c:rich><a:p><a:r><a:t>Sell-out by quarter</a:t>'
             '</a:r></a:p></c:rich></c:tx></c:title><c:plotArea><c:barChart><c:ser>'
             '<c:tx><c:strRef><c:strCache><c:pt idx="0"><c:v>Units</c:v></c:pt></c:strCache></c:strRef></c:tx>'
             '<c:cat><c:strRef><c:strCache><c:pt idx="0"><c:v>Q1</c:v></c:pt><c:pt idx="1"><c:v>Q2</c:v></c:pt>'
             '</c:strCache></c:strRef></c:cat><c:val><c:numRef><c:numCache><c:pt idx="0"><c:v>120</c:v></c:pt>'
             '<c:pt idx="1"><c:v>150</c:v></c:pt></c:numCache></c:numRef></c:val></c:ser></c:barChart></c:plotArea>'
             '</c:chart></c:chartSpace>')
    notes = (f'<p:notes {NS_P} {NS_A}><p:cSld><p:spTree>' + _shape(_para("The GTM office owns the gate calendar."), "body")
             + '</p:spTree></p:cSld></p:notes>')
    return _zip(path, {
        "ppt/presentation.xml": f'<p:presentation {NS_P} {NS_R}><p:sldIdLst><p:sldId id="256" r:id="rId2"/>'
                                '<p:sldId id="257" r:id="rId3"/></p:sldIdLst></p:presentation>',
        "ppt/_rels/presentation.xml.rels": f'<Relationships {RELS}><Relationship Id="rId2" Type="{TYPE}/slide" '
                                           'Target="slides/slide1.xml"/><Relationship Id="rId3" Type="{TYPE}/slide" '
                                           'Target="slides/slide2.xml"/></Relationships>'.replace("{TYPE}", TYPE),
        "ppt/slides/slide1.xml": slide1,
        "ppt/slides/slide2.xml": slide2,
        "ppt/slides/_rels/slide1.xml.rels": f'<Relationships {RELS}><Relationship Id="rId1" Type="{TYPE}/notesSlide" '
                                            'Target="../notesSlides/notesSlide1.xml"/><Relationship Id="rId2" '
                                            f'Type="{TYPE}/chart" Target="../charts/chart1.xml"/></Relationships>',
        "ppt/notesSlides/notesSlide1.xml": notes,
        "ppt/charts/chart1.xml": chart,
    })


def xlsx(path: Path, data_rows: int = 80) -> Path:
    shared = ["Code", "Market", "Units", "Share", "Egypt", "Saudi Arabia", "Market", "Units", "Price", "Revenue"]
    strings = "".join(f"<si><t>{s}</t></si>" for s in shared)
    small = ('<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
             '<row r="2"><c r="A2" t="inlineStr"><is><t>EG</t></is></c><c r="B2" t="s"><v>4</v></c></row>'
             '<row r="3"><c r="A3" t="inlineStr"><is><t>SA</t></is></c><c r="B3" t="s"><v>5</v></c></row>')
    big = ['<row r="1"><c r="A1" t="s"><v>6</v></c><c r="B1" t="s"><v>7</v></c><c r="C1" t="s"><v>8</v></c>'
           '<c r="D1" t="s"><v>9</v></c></row>']
    for n in range(2, data_rows + 2):
        big.append(f'<row r="{n}"><c r="A{n}" t="inlineStr"><is><t>M{n % 5}</t></is></c><c r="B{n}"><v>{n * 10}</v></c>'
                   f'<c r="C{n}"><v>2.5</v></c><c r="D{n}"><f>B{n}*C{n}</f><v>{n * 25}</v></c></row>')
    sheet = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    return _zip(path, {
        "xl/workbook.xml": f'<workbook {sheet} {NS_R}><sheets><sheet name="Markets" sheetId="1" r:id="rId1"/>'
                           '<sheet name="Sales" sheetId="2" r:id="rId2"/><sheet name="Old" sheetId="3" r:id="rId3" '
                           'state="hidden"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<Relationships {RELS}><Relationship Id="rId1" Type="{TYPE}/worksheet" '
                                      'Target="worksheets/sheet1.xml"/><Relationship Id="rId2" '
                                      f'Type="{TYPE}/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" '
                                      f'Type="{TYPE}/worksheet" Target="/xl/worksheets/sheet3.xml"/></Relationships>',
        "xl/sharedStrings.xml": f'<sst {sheet}>{strings}</sst>',
        "xl/worksheets/sheet1.xml": f'<worksheet {sheet}><sheetData>{small}</sheetData></worksheet>',
        "xl/worksheets/sheet2.xml": f'<worksheet {sheet}><sheetData>{"".join(big)}</sheetData></worksheet>',
        "xl/worksheets/sheet3.xml": f'<worksheet {sheet}><sheetData/></worksheet>',
    })


def docx(path: Path) -> Path:
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

    def p(text: str, style: str = "", numbered: bool = False) -> str:
        props = ""
        if style or numbered:
            props = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + ("<w:numPr/>" if numbered else "") + "</w:pPr>"
        return f"<w:p>{props}<w:r><w:t>{text}</w:t></w:r></w:p>"

    def tc(text: str) -> str:
        return f"<w:tc>{p(text)}</w:tc>"

    body = (p("Fiscal calendar", "Heading1") + p("The fiscal year starts in January.") + p("Q1 is January to March", numbered=True)
            + f"<w:tbl><w:tr>{tc('Quarter')}{tc('Months')}</w:tr><w:tr>{tc('Q1')}{tc('Jan-Mar')}</w:tr></w:tbl>")
    return _zip(path, {"word/document.xml": f"<w:document {w}><w:body>{body}</w:body></w:document>"})


def eml(path: Path, attachment: Path | None = None) -> Path:
    from email.message import EmailMessage
    message = EmailMessage()
    message["Subject"] = "Launch readiness"
    message["From"] = "Ana Silva <ana.silva@example.com>"
    message["To"] = "Rafael <rafael@example.com>"
    message["Date"] = "Mon, 14 Sep 2026 09:30:00 +0000"
    message.set_content("Hi, the readiness review moved to week 32. Call me on +55 11 9876-5432.\nAna")
    if attachment is not None:
        message.add_attachment(attachment.read_bytes(), maintype="application", subtype="octet-stream",
                               filename=attachment.name)
    path.write_bytes(bytes(message))
    return path
