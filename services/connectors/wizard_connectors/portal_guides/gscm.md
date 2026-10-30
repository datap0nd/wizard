# GSCM: a TOBESOFT Nexacro application

What Metronome learned driving GSCM every day (data_governance `app/flow_gscm.py`, `docs/gscm_portal.md`), turned into
what a script needs. GSCM is not HTML pages: it is one Nexacro 17/21 client application. Read its **Datasets**, not the
screen.

## Structure

- `nexacro.getApplication()` is the root. A component's DOM `id` is its full path from `mainframe`, for example
  `mainframe.VFrameSet.MdiFrame.form.div_frameButton.form.btn_exceldown`. A `:text` / `:icontext` suffix is the
  rendered caption of the component before the colon. `W.nexacro.resolve(path)` turns a path into the component.
- `mainframe.VFrameSet`: `TopFrame` (top bar, the Setting gear `...TopFrame.form.div_main.form.btn_setting`),
  `MdiFrame` (the report toolbar, Excel `...MdiFrame.form.div_frameButton.form.btn_exceldown`), and one
  `WorkFrame<N>` per open report window (`...WorkFrame0.form...`). The number differs per window and per build: never
  hard-code it. `W.nexacro.activeForms()` lists the visible report forms; `W.nexacro.title(form)` reads the report
  title from its `sta_/lbl_/txt_…title` component.
- `document.getElementById('mainframe.VFrameSet')` existing means the client is up and signed in.
- `mainframe.waitwindow` is the busy overlay. `W.nexacro.busy()` says whether it shows; `await W.nexacro.idle()` waits
  until it has been hidden for six checks in a row. A stuck overlay is a known GSCM behaviour: if it never clears,
  read the datasets anyway.
- In some builds the DOM and `nexacro.getApplication()` live in different frames. If `W.nexacro.app()` throws "nexacro
  is not in this frame", run the same step with `frame` set to another frame from `look`.

## Reading data

- A report's numbers sit in the Dataset bound to its Grid. `W.nexacro.datasets(form)` lists every bound Dataset inside
  a form with the component's `path`, row count and columns; `W.nexacro.readGrid(path)` returns that grid's rows as
  `{columns, rows, total_rows}`, a table you can return as evidence. `W.nexacro.boundDataset(path)` gives the Dataset
  itself and `W.nexacro.read(dataset, {limit, columns})` reads any Dataset.
- Dataset API, as GSCM's build exposes it: `getRowCount()`, `getColumn(row, columnId)`; `getRowCountNF()` /
  `getColumnNF()` include rows a local filter hides (use only to inventory, never to choose a row); `filterstr`.
  `getColCount()` / `getColID(i)` are used by W but were not proven by Metronome on GSCM: if columns come back empty,
  read the grid's column ids from its cells or the SSV reply instead.
- Combos keep their options in `control.getInnerDataset()` with `codecolumn` / `datacolumn`; the current value is
  `control.value`.
- Example: the active report's biggest dataset as a table:
  ```js
  await W.nexacro.idle(60000).catch(() => null);
  const form = W.nexacro.activeForms()[0];
  const sets = W.nexacro.datasets(form).sort((a, b) => b.rows - a.rows);
  if (!sets.length) return {form, note: 'no bound dataset yet'};
  return W.nexacro.readGrid(sets[0].path);
  ```

## Background queries (better than the screen)

- GSCM's backend is Spring MVC `.do` routes speaking Nexacro **SSV**, not JSON (posting JSON makes the server fail).
  Each screen load and each search is one such POST. After a report opens or a search runs, `requests` (and
  `W.requests('.do')`) show them; `W.replay(i, {replace: [[old, new]]})` sends one again with changed parameters (a
  week, a market, a plan id) and `W.parse(reply.text)` returns its datasets. Change only values inside the captured
  body; keep its format exactly.
- SSV: records end with `\x1e`, units with `\x1f`, `\x03` is null; `Dataset:name`, then a `_RowType_` record with
  `COLUMN:TYPE(size)` units, then rows whose first unit is the row type (`N` normal). Parameters such as
  `ErrorCode:int=0` come first. A negative `ErrorCode` or an `ErrorMsg` means the server refused the request.
- Metronome itself never called these routes (it drove the screen and the Excel button), so they are unverified: check
  the first replay against what the screen shows for the same filters.

## Mapping GSCM (what the map needs, and the helpers that find it)

- **The menu without clicking.** `W.nexacro.appDatasets()` lists the application's own Datasets, biggest first, with
  their columns: the menu tree is one of them (a name like `gds_menu`, columns such as a menu id, its name, its parent
  and level, the form it opens). Read it with `W.nexacro.read(name)` and save every report as `todo` with its path and
  menu id.
- **Opening a report directly.** `W.nexacro.functions()` lists the client's own functions (`gfn_*`, `fn_*`) on the
  application, the top, left and toolbar forms and the active report, with the start of each source. Look for the one
  the menu calls to open a menu id (open, menu, popup, link in its name), call it in an `evaluate` step with a report's
  menu id, wait for the overlay (`W.nexacro.idle()`) and for the new WorkFrame (`W.nexacro.activeForms()`), and save
  the call that works as a topic: every later question then opens reports in one step.
- **Filters.** `W.nexacro.inputs()` lists the active report form's inputs: Combo, Calendar, Edit, Radio... with their
  value, and a combo's options from its inner Dataset as `code = label`. Note which request parameter each filter
  sets (compare the search request's body with the values on screen).
- **The data request.** After pressing the report's search button (Search, Retrieve, Inquiry...; never Save), the
  result's `requests` and `W.requests('.do')` show the transaction. Its SSV body names the parameters
  (`name:string=value` units) and the datasets it fills. Prove the route with a `request` step: the same url and body
  with one value changed must return the same dataset with the new values. Save it with `{{param}}` placeholders.

## Bookmarks (Setting > Favorite)

- The person's saved reports ("bookmarks") are in the application dataset `gds_bookmark`; `W.nexacro.bookmarks()`
  reads it. Columns: `userreportid` (the stable id, like `RC_123456`), `userreportname` (exact name, case and spaces
  matter), `publicscope` (Private / Public / Custom tab), `scope` (module code, `AS` = SCM, `MT` = MDM), `gbm`,
  `menuscope`, `menuid` (e.g. `AS470`), `menuname`, `menugroupid`, `menugroupname` (folder path).
- Rows of a scope tab load only after that tab is opened once in the Favorite dialog: an empty Public list may just
  mean the Public tab was never opened.
- The route: gear `btn_setting` (no text) → **Favorite** (left rail `...TopFrame.Setting<N>.form.btn_favorite`) → tab
  `...div_favorite.form.btn_private|btn_public|btn_custom` → the bookmark in grid `...div_favorite.form.grd_bookmark`
  → **Go >>** (`btn_openFavorite`, older builds `btn_go`). `Setting<N>` is `Setting0` now, was `Setting1` before.
- The Favorite grid shows only rows 0-8 (`gridrow_N`), recycled while scrolling: a row id is never a bookmark's
  identity. Choose a bookmark by `userreportid` and exact `userreportname` from the dataset.
- The home screen's "Favorite" widget shows only pinned entries: do not read it as the bookmark list.

## Popups and waiting

- Notices and alerts are components whose id contains `popup` or `pdv_`, or a segment `notice|alert|message|msg|confirm`;
  close them with their `close`/`x` control (never one named save/ok/apply). Escape closes a stray panel.
- After Go, a report can take a minute or more: wait for the overlay to clear, then for the report title in the
  active WorkFrame, then read its datasets.
- Re-opening the start page tears down the whole Nexacro client and replays the sign-in. Stay on the page between
  calls; `goto` only when off the portal.

## Never

Click Save, Unselect, a row's pin, or anything that edits a bookmark or a filter set; change stored settings; click the
Excel button (downloads are off, and the datasets hold the same rows).
