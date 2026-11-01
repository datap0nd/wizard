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


def designed_pptx(path: Path, title: str = "Quarterly business review", accent: str = "1428A0") -> Path:
    """A deck with a theme, a master (logo top right, a confidentiality label, the slide number), two layouts, and
    slides that use them with explicit fonts, sizes, colors, a filled shape, a column chart and a table."""
    theme = (f'<a:theme {NS_A} name="Company Theme"><a:themeElements><a:clrScheme name="Company">'
             '<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1><a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
             '<a:dk2><a:srgbClr val="1F1F1F"/></a:dk2><a:lt2><a:srgbClr val="F2F2F2"/></a:lt2>'
             f'<a:accent1><a:srgbClr val="{accent}"/></a:accent1><a:accent2><a:srgbClr val="00B3E3"/></a:accent2>'
             '<a:accent3><a:srgbClr val="A5A5A5"/></a:accent3><a:accent4><a:srgbClr val="FFC000"/></a:accent4>'
             '<a:accent5><a:srgbClr val="5B9BD5"/></a:accent5><a:accent6><a:srgbClr val="70AD47"/></a:accent6>'
             '<a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink></a:clrScheme>'
             '<a:fontScheme name="Company"><a:majorFont><a:latin typeface="Company Sans Bold"/><a:ea typeface="Company Gothic"/>'
             '</a:majorFont><a:minorFont><a:latin typeface="Company Sans"/><a:ea typeface="Company Gothic"/></a:minorFont>'
             '</a:fontScheme></a:themeElements></a:theme>')

    def box(x: int, y: int, cx: int, cy: int) -> str:
        return f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm></p:spPr>'

    master = (f'<p:sldMaster {NS_P} {NS_A} {NS_R}><p:cSld><p:spTree>'
              f'<p:pic><p:nvPicPr><p:cNvPr id="2" name="Logo"/></p:nvPicPr>{box(10_500_000, 200_000, 1_400_000, 400_000)}</p:pic>'
              f'<p:sp><p:nvSpPr><p:cNvPr id="3" name="Label"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>{box(300_000, 6_400_000, 2_000_000, 300_000)}'
              '<p:txBody><a:p><a:r><a:t>Confidential - internal use only</a:t></a:r></a:p></p:txBody></p:sp>'
              f'<p:sp><p:nvSpPr><p:cNvPr id="4" name="Number"/><p:cNvSpPr/><p:nvPr><p:ph type="sldNum"/></p:nvPr></p:nvSpPr>{box(11_000_000, 6_400_000, 800_000, 300_000)}'
              '<p:txBody><a:p><a:fld type="slidenum"><a:t>1</a:t></a:fld></a:p></p:txBody></p:sp>'
              '</p:spTree></p:cSld><p:txStyles><p:titleStyle><a:lvl1pPr><a:defRPr sz="2800" b="1"><a:solidFill><a:schemeClr val="accent1"/>'
              '</a:solidFill><a:latin typeface="+mj-lt"/></a:defRPr></a:lvl1pPr></p:titleStyle><p:bodyStyle><a:lvl1pPr><a:defRPr sz="1600">'
              '<a:solidFill><a:schemeClr val="tx1"/></a:solidFill><a:latin typeface="+mn-lt"/></a:defRPr></a:lvl1pPr><a:lvl2pPr>'
              '<a:defRPr sz="1400"/></a:lvl2pPr></p:bodyStyle></p:txStyles></p:sldMaster>')

    def layout(name: str) -> str:
        return f'<p:sldLayout {NS_P} {NS_A} {NS_R}><p:cSld name="{name}"><p:spTree/></p:cSld></p:sldLayout>'

    def slide(heading: str, body: str, extra: str = "") -> str:
        return (f'<p:sld {NS_P} {NS_A} {NS_R}><p:cSld><p:spTree>'
                + _shape(f'<a:p><a:r><a:rPr sz="2800" b="1"><a:solidFill><a:schemeClr val="accent1"/></a:solidFill></a:rPr><a:t>{heading}</a:t></a:r></a:p>', "title")
                + _shape(f'<a:p><a:r><a:rPr sz="1400"><a:latin typeface="Company Sans"/></a:rPr><a:t>{body}</a:t></a:r></a:p>')
                + extra + '</p:spTree></p:cSld></p:sld>')

    filled = ('<p:sp><p:nvSpPr><p:cNvPr id="9" name="Box"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:solidFill>'
              '<a:schemeClr val="accent1"/></a:solidFill></p:spPr></p:sp>'
              '<p:graphicFrame><a:graphic><a:graphicData><a:tbl><a:tr><a:tc><a:txBody><a:p><a:r><a:t>Market</a:t></a:r>'
              '</a:p></a:txBody></a:tc></a:tr></a:tbl></a:graphicData></a:graphic></p:graphicFrame>')
    chart = (f'<c:chartSpace {NS_C} {NS_A}><c:chart><c:plotArea><c:barChart><c:barDir val="col"/></c:barChart></c:plotArea>'
             '</c:chart></c:chartSpace>')
    rel = lambda rid, kind, target: f'<Relationship Id="{rid}" Type="{TYPE}/{kind}" Target="{target}"/>'  # noqa: E731
    return _zip(path, {
        "ppt/presentation.xml": f'<p:presentation {NS_P} {NS_R}><p:sldIdLst><p:sldId id="256" r:id="rId2"/><p:sldId id="257" '
                                'r:id="rId3"/></p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/></p:presentation>',
        "ppt/_rels/presentation.xml.rels": f'<Relationships {RELS}>{rel("rId1", "slideMaster", "slideMasters/slideMaster1.xml")}'
                                           f'{rel("rId2", "slide", "slides/slide1.xml")}{rel("rId3", "slide", "slides/slide2.xml")}</Relationships>',
        "ppt/slideMasters/slideMaster1.xml": master,
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": f'<Relationships {RELS}>{rel("rId1", "theme", "../theme/theme1.xml")}'
                                                        f'{rel("rId2", "slideLayout", "../slideLayouts/slideLayout1.xml")}'
                                                        f'{rel("rId3", "slideLayout", "../slideLayouts/slideLayout2.xml")}</Relationships>',
        "ppt/theme/theme1.xml": theme,
        "ppt/slideLayouts/slideLayout1.xml": layout("Title Slide"),
        "ppt/slideLayouts/slideLayout2.xml": layout("Title and Content"),
        "ppt/slides/slide1.xml": slide(title, "Prepared by the strategy office"),
        "ppt/slides/_rels/slide1.xml.rels": f'<Relationships {RELS}>{rel("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml")}</Relationships>',
        "ppt/slides/slide2.xml": slide("Sell-out grew in every market", "Growth came from the mid-range line-up", filled),
        "ppt/slides/_rels/slide2.xml.rels": f'<Relationships {RELS}>{rel("rId1", "slideLayout", "../slideLayouts/slideLayout2.xml")}'
                                            f'{rel("rId2", "chart", "../charts/chart1.xml")}</Relationships>',
        "ppt/charts/chart1.xml": chart,
    })
