# GSCM: a TOBESOFT Nexacro application

What Metronome learned driving GSCM every day (data_governance `app/flow_gscm.py`, `docs/gscm_portal.md`), turned into
what a script needs. GSCM is not HTML pages: it is one Nexacro 17/21 client application. Read its **Datasets**, not the
screen.

## Structure

- `nexacro.getApplication()` is the root. A component's DOM `id` is its full path from `mainframe`, for example
  `mainframe.VFrameSet.MdiFrame.form.div_frameButton.form.btn_exceldown`. A `:text` / `:icontext` suffix is the
  rendered caption of the component before the colon. `W.nexacro.resolve(path)` turns a path into the component.
- `mainframe.VFrameSet`: `TopFrame` (top bar, the application's Setting gear `...TopFrame.form.div_main.form.btn_setting`:
  settings and Favorite, not a report's Configuration),
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

- **The menu without clicking.** `W.nexacro.menu()` returns the menu tree as one table: every menu with its id, name,
  parent and level and the form it opens. On the work PC GSCM keeps it in the application Dataset `gds_topMenu`;
  `other_menu_datasets` names the others. "Which reports are there" is this one call after the client is up: `goto`
  the start page, `W.nexacro.idle()`, return `W.nexacro.menu()`. `W.nexacro.appDatasets()` lists every application
  Dataset with its columns when the menu is elsewhere. When mapping, save every report as `todo` with its path and
  menu id.
- **Opening a report directly.** `W.nexacro.functions()` lists the client's own functions (`gfn_*`, `fn_*`) on the
  application, the top, left and toolbar forms and the active report, with the start of each source. Look for the one
  the menu calls to open a menu id (open, menu, popup, link in its name) and open the report with
  `await W.nexacro.open('<that function>', '<menu id>')`: it waits until the client has started
  (`W.nexacro.ready()`), calls the function with its own form as `this` (`W.nexacro.call`), waits for the new
  WorkFrame and the overlay, and returns the form and its title. Never take a client function out of its form and call
  it bare: it fails with errors such as "this.gfn_isNull is not a function". Save the call that works as a topic and in
  each report's `open`: every later question then opens reports in one step.
- **Filters.** `W.nexacro.inputs()` lists the active report form's inputs: Combo, Calendar, Edit, Radio... with their
  value, and a combo's options from its inner Dataset as `code = label`. Note which request parameter each filter
  sets (compare the search request's body with the values on screen).
- **Read the report's code first.** `W.nexacro.transactions()` lists every data request the open report's functions
  can send, read from its code rather than from what the screen happened to send: each `transaction()` call (or a
  wrapper such as `gfn_transaction`) with its service id, address, input and output datasets, arguments and callback;
  every `.do` address in its code; and the application's wrappers, which show how an address is completed. Read a
  function whole with `W.nexacro.source('<name>')`, and an input dataset with `W.nexacro.read('<name>')`: its columns
  are the parameters the request carries (subsidiaries, dates, a dimension or level).
- **The data request.** After pressing the report's search button (Search, Retrieve, Inquiry...; never Save), the
  result's `requests` and `W.requests('.do')` show the transaction, its body in full. Its SSV body names the parameters
  (`name:string=value` units) and the datasets it fills. Save it with `{{param}}` placeholders, then **prove it with
  portal_prove_request**: Wizard sends it twice, with the screen's values and with one changed, and keeps it as proven
  only when both answers are clean, alike in shape, and the change changed the rows. Only that marks a request
  verified, and a report is mapped only once one of its requests is proven. A task with the person's own export then
  checks the proven reply against it, row by row (wizard_task_compare).

## Bookmarks (Setting > Favorite)

- The person's saved reports ("bookmarks") are in the application dataset `gds_bookmark`; `W.nexacro.bookmarks()`
  reads it as a table (`{columns, rows, total_rows}`, not an array). Columns: `userreportid` (the stable id, like `RC_123456`), `userreportname` (exact name, case and spaces
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
- Re-opening the start page tears down the whole Nexacro client and replays the sign-in, a minute or more, and calls
  made while it starts fail in different ways ("Execution context was destroyed", `getApplication()` undefined, a
  missing `gfn_` function). Stay on the page between calls; `goto` only when off the portal. Wizard does not reload a
  page whose client is running (the goto's result says `kept`); `reload: true` forces it, only for a stuck client.
- After any page load, start with `await W.nexacro.ready()` before calling the client: a check that only finds
  `mainframe` is not enough.

## A report's Configuration (the columns and breakdowns beyond its default view)

- A report shows more than its default view through its own **Configuration** button. This is not the top bar's
  Setting gear (`btn_setting`, the application's settings and Favorite). The button may sit in the report form or in the
  report toolbar (`MdiFrame`), which `W.nexacro.inputs()` does not search: find it anywhere on screen with
  `W.nexacro.find(/config/i)`, which returns each match's `selector` for a `click` step and says where it is.
- The dialog is a tree of choices: categories, then groups inside each, then the choices themselves. Proven on DB4009
  Daily Sell-out (the person's own clicks): **Configuration → Sales** (one of six categories) **→ Sales** (a group inside
  it) **→ ORG Sales** (the account: operator, retailer, customer), tick it, **Apply**, then search. The grid then shows a
  sub-total per account and one row per country under it.
- Read the dialog with `W.nexacro.options()` after it opens and again after each category or group you click: it lists
  the dialog's buttons, tabs and checkboxes with their state, and every list in it (its rows, which columns are check
  marks, which rows are ticked). Open every category and every group, and record every choice with what it is (an
  account, a country, a model, a channel...): a choice you have not opened is unknown, never absent.
- A choice can need a narrower search first. ORG Sales with no area chosen, or with a region (Middle East), is refused
  as too much granularity: choose the subsidiaries one by one in the search conditions (all of them is fine), then
  Apply. When Apply or Search answers with such a message (a popup or alert: read its text), narrow the filter it names
  and try again; record what it needed in the view's `requires`.
- **Apply** is allowed in GSCM; never Save or "Apply and save" in that dialog. After Apply and a search, compare the
  request (`W.requests('.do')`) with the one before: record whether the choice adds a request parameter (then a
  `request` step reads the account breakdown directly) or only columns of the reply. If the choice stays ticked when the
  report is opened again, it is saved for the person: untick it afterwards.

## Never

Click Save, Unselect, a row's pin, or anything that edits a bookmark or a filter set; change stored settings; click the
Excel button (downloads are off, and the datasets hold the same rows).
