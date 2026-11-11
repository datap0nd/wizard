# 2026-11-11 — Every table copies and downloads; the Korean report style

**Owner:** project owner. **Status:** decided (11 November 2026).

**Context.** The owner: "All wizard's visuals and tables should be copy pastable to powerpoint, and they should show up
nicely there ... Also, tables should be easily copy pastable to excel too. Can you look at the composer repo and try to
get 'korean style' excels too? That was an earlier project that I tried to reproduce korean tables with." Since
[9 November](2026-11-09-heatmaps-and-visual-exports.md) every visual Gemini renders has a Copy / download menu. Two
kinds of table had none: a table Gemini writes in its answer (Markdown) and the rows of a source in the evidence drawer.

**Decision.**
- **Every table has the menu a visual has.** A table in an answer is read from the answer as it is written
  (`answerTable.ts`): a column whose every cell is a number, a percent or a dollar amount is typed, so Excel receives
  numbers; each cell keeps its wording in a picture, a slide and a pasted PowerPoint table; a citation chip in a cell is
  where the value came from (the copy's source line), not part of the value. Bare whole numbers in the first column,
  years and codes with a leading zero stay text. The rows of a source in the evidence drawer have the menu too: the
  copy says they are the rows that source returned to Wizard, under that source's own data label, not "prepared by
  Gemini".
- **The Korean report style** is a second layout for *Copy table* and for the Excel workbook, taken from the owner's
  Composer project (`designer/generic_report.py`, `render/excel.py`), and built from the same values
  (`koreanTable.ts`): Malgun Gothic 9 pt; a dark header band, with neighbouring columns that name a group
  ("2026 · Actual", "2026 · Plan") under one merged cell and a lighter second header row; a label repeated on
  neighbouring rows merged downwards, inside the label to its left; total and subtotal rows (Total, Subtotal, 합계,
  소계...) bold and shaded; one "(Unit: USD)" line above the table when every amount shares a unit ("(단위: ...)" for a
  Korean table), else the unit in each header; a negative in red brackets, zero as "-", and a change column (growth,
  YoY, vs, 증감..., or a percent column with a negative) with a blue ▲ or a red ▼. In Excel the sheet is laid out as
  Composer lays one out: the title in B3, no gridlines, the header and labels frozen, one page wide.
- **What does not change.** The values: a missing value stays blank, never the "-" of a zero. A heatmap keeps its
  shading. Every copy and file still carries the data label and the evidence ids, and the workbook its Sources sheet
  and (in Wizard) the rows behind the visual. The style is layout only; nothing is added to a tool, the API or what
  Gemini reads. The PowerPoint slide and the picture stay in Wizard's own look.
- The clipboard's number formats are now escaped the way Excel writes its own (`mso-number-format`, a quote as
  `\0022`): a format with quoted text (a `$`, a unit) used to end the HTML attribute early.

**Not verified here.** Pasting into PowerPoint and Excel themselves (checked instead: the clipboard read back in
Chromium, the workbook opened with openpyxl and rendered with LibreOffice), and Malgun Gothic, which Windows has and
this Linux machine does not.
