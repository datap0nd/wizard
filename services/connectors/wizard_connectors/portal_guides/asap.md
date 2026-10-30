# ASAP: a portal shell around MicroStrategy Web

What Metronome learned driving ASAP (data_governance `app/flow_worker.py`, `app/flow_replay.py`,
`docs/asap_export_options.md`), turned into what a script needs.

## Structure

- The shell page has a top menu of links; reports open inside **`iframe#content-frame`** (MicroStrategy Web). Use
  `frame: "content-frame"` in steps for the report itself. Some prompts and the export-view tabs render in the shell or
  in a nested frame: `look` lists every frame.
- Opening a report or pressing RUN **replaces** the content frame. After either, address the frame again (a fresh step
  with `frame: "content-frame"`, or `W.mstr.contentWindow()` in a script); an old reference fails with "frame was
  detached".
- Menu paths have two or three levels: top label → (group, shown on hover) → report. When a group and a report share a
  label, the report is the last visible match. Menu items appear late after a hover animation.
- The report title is the content frame's `<title>`.
- Some ASAP entries are plain HTML dashboards (for example M Tracker), not MicroStrategy: they have download links
  instead of the Export Wizard; read their tables or the data requests they make.

## The session and the menu, without clicking

- On the **signed-in start page** (before opening any report), the page defines `_COMMON_INFO` and `_SESSION`.
  `W.mstr.session()` returns `{web_base, main_menu_id, signed_in}`: MicroStrategy Web lives at the same host under
  `_COMMON_INFO.MSTR_CUSTOM_WEB_CONTEXT_PATH` (default `/mstr`). The session token
  (`_SESSION.MSTRWEB_AUTH_TOKEN_ENC`) stays inside the helpers: never return it, log it or put it in a parameter.
- `await W.mstr.reports()` walks the person's whole report menu through `POST {web_base}/menuInfo.do?folderId=<id>`
  (form fields `authToken`, `depth`) and returns `[{path: [top, group, report], id}]`. `await W.mstr.menu(folderId,
  depth)` reads one folder. Replies come as `{errorCode, data}` where `data` may be a JSON string, a list of children
  or a node; children are under `children` or `child`; names carry an ordering prefix like `03.` that the helper strips.
  Some builds need `depth=2` to show the root's children (the helper retries).
- Metronome uses the menu only for names and paths; it still opens reports by clicking the labels. A report's menu
  `id` is not known to open it directly: find the request the shell makes when you click it (`requests`).

## Prompts and RUN

- The loading overlay is `#loading-spinner-container, .loading-spinner-container, .loading-overlay` (in any frame):
  controls stay visible under it but clicks do not land. `W.mstr.loading(doc)` checks it; wait until it has been clear
  for about a second before each click.
- Export views are tabs labelled `Export Wizard (…)`; each has its own prompts. A view is ready when one of `RUN`,
  `Dimension:`, `Data Configuration:` or `Sell-out Week:` shows.
- Prompt controls: native `<select>` hidden behind Select2 (choose by option label: a `select` step on the select
  works); comboboxes (`[role=combobox]`, options `[role=option]` / `li.select2-results__option`); searchable member
  lists (a label, then "type to search" or "(N values)", then members; ignore "(All)"); Dimension / Measure / Category
  lists without ARIA (Category: Weekly / Daily). Dimension starts with a member selected: clear it before choosing.
  MicroStrategy can drop a fast second click: check the result after each click.
- **Weeks** are sent as `YYYYWW` (stored elsewhere as `YYYY-Www`). ASAP weeks run **Sunday to Saturday** with ISO week
  numbers: week W covers the Sunday before its Monday through the following Saturday, so a Sunday belongs to the next
  ISO week. Multi-week periods must be contiguous.
- Week / Date range sliders (Date in `YYYYMMDD`) have two handles (`[role=slider]`): move them with ArrowRight /
  ArrowLeft presses (one per week or day), the upper handle first when moving forward; Home / End jump to the limits.
  Never click by coordinates.
- **RUN**: role button named `RUN`, or `input[value='RUN' i]`, or the exact text `RUN`. Wait for the overlay first;
  never press RUN again while it shows.
- The report has rendered when **`Data rows:`** shows in a frame (`W.mstr.rendered(doc)`), or, for raw-data views,
  when a table of two or more rows shows next to "to download raw data". If the overlay clears and nothing renders for
  minutes, RUN once more.
- A plain `500` in the frame is a transient server error: go back and open the report again, once.

## Getting the rows

- Metronome always exported files (Export Wizard: Excel with plain text, CSV file format, Excel with formatting, HTML,
  Plain text). Downloads are off in Wizard's browser, so read the data instead:
  1. the rendered grid in the content frame: `read_table` with `frame: "content-frame"` (check `Data rows:` against
     the rows you got; large grids are paged);
  2. better, the request behind the grid or the export: after RUN, `requests` shows what MicroStrategy fetched; replay
     it with `W.replay` and parse the reply. Metronome replayed the export request successfully (same session, cookies
     from the browser), so the data requests can be called again; change only prompt values you understand (weeks as
     `YYYYWW`).
- Exported CSVs start with the report title and filter details, separated by blank lines: the data is the last
  rectangular block. Multi-week Excel views can have a two-level header ending in `Metrics`.
- If the shell also serves MicroStrategy's REST API (try `GET /MicroStrategyLibrary/api/status`), it may answer report
  requests directly; Metronome never used it, so treat it as unverified.
- MicroStrategy Web's own task and event URLs (`{web_base}/taskProc?taskId=reportExecute...`,
  `.../servlet/mstrWeb?evt=...`) are allowed like any other read: if the requests after RUN show one, map it and send
  it again with a `request` step or `W.replay`.

## Sign-in

`/expiredSession` followed by the company sign-in page means the session ended; a visible password field means a
sign-in page. Stop and ask the person to sign in again (general guide). Never type credentials.

## Never

Click logout, the toolbar's second icon next to RUN (subtotals), anything that saves, subscribes, schedules or shares a
report; press Export twice; close a popup that is downloading.
