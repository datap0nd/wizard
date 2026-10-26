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

## Update 26 October 2026 — Download on the person's own PC saves into Downloads

**Context.** The owner: "when I try to download a file after it edited something, says: couldn't finish download in
chrome." Chromium shows "Couldn't finish download" when the server sends fewer bytes than it announced, when the
download cannot be written or renamed (a sharing violation, often a scanner or a protection agent holding the file),
or when the browser stops. The same download works in a plain Chromium, so it fails on the work PC, where Excel saves
the copy and protected (NASCA) workbooks open only where Office saved them.

**Decision.**
- **Where Wizard runs on the person's PC** (signed in locally, the page on the same PC, as for Outlook drafts),
  **Download** asks Wizard to save the copy in the person's Downloads folder itself (`POST
  /api/v1/attachments/{id}/save`). Excel writes the copy when Office runs there (opened read-only, `SaveCopyAs`), so a
  protected workbook opens where it lands; without Office, or when Excel cannot, the file is copied as it is, with a
  warning when Excel failed. An existing file is never overwritten: a taken name gets (1), (2)… as a browser does.
- **Open** then opens that saved copy with its application (`POST /api/v1/attachments/{id}/open`), only a copy Wizard
  saved since it started, on the person's click. Both are owner-only and audited (`attachment:save`,
  `attachment:open`).
- **Elsewhere** (behind a proxy, where Downloads would be the server's) the page keeps the browser download. The file
  is now read whole before the answer starts, so a file that cannot be read is an error, never a download cut short.
- No new tool: Gemini still only makes the copy; the person's click saves or opens it.

**Evidence.** `tests/unit/test_edit_attachment.py`: Excel writes the saved copy (fake COM: read-only open,
`SaveCopyAs`, Close without saving), never overwrites, copies as is without Office or when Excel fails; through the
API: saved in Downloads, the second save as "(1)", Open, the request header required, another user refused, a remote
page told to download through the browser, an unreadable file refused before any byte; names never leave Downloads.
Web: on this PC no browser download starts and the card says where the file was saved; elsewhere the browser downloads
it; a failure is shown in words. Real Excel and the work PC's Downloads folder are first exercised on the work PC.
