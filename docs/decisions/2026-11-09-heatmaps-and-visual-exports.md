# 2026-11-09 — Heatmaps, and visuals copied and downloaded for PowerPoint and Excel

**Owner:** project owner. **Status:** decided (9 November 2026).

**Context.** The owner: "I want wizard to be able to output 'heatmap' visuals. I also want to be able to download
visuals as they are, in a format excel and powerpoint-friendly ... I asked for a heatmap, and it created colored balls,
so it went around the problem, it was a nice little table-visual emulating a heatmap, but I couldn't copy paste to
powerpoint." Then: "cases has all the queries and steps instead of an expandable option for it. Also, I want that
'download' or copy button to be in Cases", and "it would be good if we could download the data BEHIND the visuals."
`wizard_render_visual` drew bar, line and scatter charts and tables; with no heatmap, Gemini wrote one as a Markdown
table of coloured emoji, which is text, not a visual, and nothing in Wizard copied or downloaded a visual.

**Decision.**
- **A heatmap is a visual of its own.** `wizard_render_visual` takes `kind: "heatmap"`: one row per row label (`x`),
  one numeric column per heatmap column (`series`, up to 11), all the same measure, type and unit (the tool refuses a
  mix), and an optional `scale`: sequential (one hue, light to dark, for amounts) or diverging (red below zero, grey at
  zero, blue above, for growth and change); without it the values' signs choose. Every cell prints its value, so colour
  is never the only way to read it; a missing value stays missing (white, "—"), never zero. The tool description and
  the system prompt tell Gemini to use it and never to imitate a chart or heatmap with text, emoji or Markdown.
- **Every visual copies and downloads as it is** (a menu on each visual, in Wizard, on report pages and in Cases):
  - *Copy picture*: a PNG of the visual with its title and source line, for PowerPoint, Word or an email.
  - *Copy table*: the cells as HTML with their shading (PowerPoint and Word paste a native table; Excel pastes cells,
    reading each number from `x:num` with Wizard's number format) and as tab-separated text.
  - *PowerPoint slide (.pptx)*: one 16:9 slide with a native, editable PowerPoint chart whose data opens in Excel (bar,
    line, scatter; a missing value is a gap), or a native table with the heatmap's shading and its legend; a long table
    continues on further slides, each with the title, legend and source line. The notes name the sources and queries.
  - *Excel workbook (.xlsx)*: the visual's values as numbers in Wizard's formats (a percent as a percent, currency with
    its unit), the heatmap's fills; a *Sources* sheet (evidence id, source, data label, as of, rows read, the query); and
    **in Wizard, the data behind it**: one sheet per cited source with the rows that source returned to Wizard (what the
    evidence drawer shows, within its retention). A case publishes no rows, so on the site the workbook holds the
    visual's own values and the sources sheet, and says so.
  - *Picture (.png)*.
  Each copy and file carries the answer's data label (SYNTHETIC says "SYNTHETIC test data, not corporate figures") and
  the evidence ids its values came from, as the visual does in the answer.
- **Built in the page, saved by Wizard on the person's PC.** The page builds every file from what it already shows
  (pptxgenjs for the slide, Wizard's own writer for the workbook, both loaded only when the person asks). Where Wizard
  runs on the person's own PC, Download hands the file to Wizard (`POST /api/v1/exports`), which saves it in their
  Downloads folder, never over a file, and offers **Open**, as Download does for edited copies
  ([decision](2026-10-23-edited-attachments.md)): a browser download can fail on the work PC. Wizard saves only .pptx,
  .xlsx and .png files that are what their name says (an Office file must hold its main part), up to 25 MB, under the
  name's own file name, and only for a page on the same PC. Elsewhere, and on the Pages site, the browser downloads it.
- **A case folds away how each answer was reached.** Under each answer of a case, one closed section, "How Wizard got
  this answer (N sources, M steps)", holds the sources (each still opens its query) and the steps. A citation in the
  answer still opens its query directly; one that names a source the case does not list opens the section.
- An email draft shades a heatmap's cells too.

**What this does not do.** Gemini has no export tool: the person clicks. Nothing is sent anywhere; the files go to the
person's own Downloads folder or their browser. The site still publishes no source's rows. The recurring brief's email
has no heatmap section yet.

**Evidence.** `apps/web/src/visualExport.test.ts` (the heatmap's scales and cells; the copied HTML and text; the
workbook's sheets, values, formats and fills, with and without rows; the slide's chart with its embedded workbook and
the heatmap's table; Downloads or the browser), `CaseFlow.test.tsx` (the fold, closed by default, opened by a citation
of an unlisted source), `tests/unit/test_tools.py` (a heatmap stored with its scale and a missing cell; mixed measures,
a row label as a series, more than six line series and a scale on a bar refused; the description), and
`tests/unit/test_exports.py` (saved in Downloads, never over a file, opened only by its person; other kinds, a slide
named .xlsx, a broken zip and a GIF named .png refused; folders in the name dropped; away from the PC the browser
downloads). The generated .xlsx and .pptx were opened with openpyxl and python-pptx and rendered with LibreOffice
(a bar chart, a line with a gap, a scatter, a 4-row and a 40-row heatmap); the built Cases page was driven in Chromium:
the heatmap, the menu, Copy table (HTML with `x:num`, number formats and fills on the clipboard), Copy picture (a PNG on
the clipboard), the three downloads, the fold, no console errors. Not run: pasting into PowerPoint and Excel themselves
and the save into Downloads in WizardBar's WebView2 on a work PC.
