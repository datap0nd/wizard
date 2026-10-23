# 2026-10-23 — Wizard edits a copy of an attached workbook and hands it back

**Owner:** project owner. **Status:** decided (23 October 2026).

**Context.** The owner attached an Excel file and asked for changes: "it didnt work. It gave me a pastable code block
basically. I want wizard to edit the file and spit back an edited file." Gemini had no way to change a file, so it
answered with code for the person to run.

**Decision.**
- **The tool.** `wizard_edit_attachment(file, operations, name?)` applies Gemini's operations to a copy of an attached
  workbook (.xlsx, .xlsm, .xls, .xlsb). The operations: set values and formulas, clear, insert or delete rows and
  columns, delete the rows that meet a condition, sort, format, column widths, find and replace, add, rename or delete
  sheets, freeze panes, filters.
- **Excel first.** On the work PC, Excel itself does the edit. It opens the original read-only, edits in memory and
  saves under a new name, so charts, pivots, formatting and NASCA protection survive, and formulas follow moved cells.
  Without Office, openpyxl edits .xlsx and .xlsm. It says when charts or pictures may be lost, or when formulas do not
  follow moved rows. Either way the edit runs in its own process with the attachments' time limit, and only one
  Office job runs at a time.
- **The original is never written.** The copy becomes a new file in the conversation (F2, F3…), converted like any
  attached file, so Gemini can read it back. Under the answer it shows with **Download**
  (`GET /api/v1/attachments/{id}/file`, owner only, audited as `attachment:download`). Editing the copy again
  continues from it.
- **Gemini is told** in the tool description and one line of the system prompt to edit the file, never to answer with
  code or steps. This is the measured failure AGENTS.md asks for before adding a rule.
- This writes no company system. The file is the person's own, and the copy stays in their Wizard until they
  download it.

**Evidence.** `tests/unit/test_edit_attachment.py`:
- values parsed as Excel would;
- every operation on a copy with openpyxl, with the original's hash unchanged;
- mistakes reported in words;
- Excel through fake COM objects: opened read-only, rows deleted bottom-up, native sort, BGR colours, SaveAs with the
  right file format, Close without saving;
- through the API: the edited copy as F2, read back, downloaded, refused to another user, failures as `edit_failed`.

Web: the made-file card with its download link, and the `file_made` event. Real Excel is first exercised on the work
PC.
