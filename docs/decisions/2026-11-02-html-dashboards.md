# 2026-11-02 — Dashboards: the team's HTML dashboards are a system Wizard reads first

**Owner:** project owner. **Status:** decided (2 November 2026).

**Context.** On 5 October the owner dropped Power BI: "standalone HTML reports (local files for now, fed from
PostgreSQL) are the reporting path" (`docs/build-report.md`, "HTML reports folder setting"). `WIZARD_HTML_REPORTS_DIR`
named the folder, but no tool read it, and a folder missing at start-up stopped Wizard (a `ConfigError`). The team's
dashboards live in a folder on a network share that the owner's PC maps as a drive letter. The owner:

- "I believe these dashboards should definitely be the first thing in the priority list as they are dashboards prepared
  combining logic and data that wizard will struggle to get right off the bat."
- "Y:\ is indeed a risk as it's mapped as that in my pc but might not be the same in another PC."
- "we now have ASAP, GSCM, AI Team Database: will we have a Dashboards?"

**Options.** (1) Two loose tools over the folder. (2) A system of its own, like the database and the portals: listed,
chosen or switched off per question, asked for, shown on the systems stage and in answers' sources. (3) Run the pages in
a browser and read what they draw: the portal browser exists, but it would run the pages' scripts and fetch what they
load, and it is only on single-person PCs. For the folder's path: keep the drive letter, or store the network path it
maps to. For the order: code that reads dashboards before the database, or guidance in the prompt.

**Decision.** Option 2, read from the files, the network path stored, the order in the prompt.
- **A system called Dashboards** (id `dashboards`; the name people see is `WIZARD_DASHBOARDS_NAME`, like
  `WIZARD_PG_NAME`, default "Dashboards"). When a folder is set it is listed first wherever the systems are: the
  systems picker, the systems stage and its logo, `wizard_list_sources`, Settings, and an answer's sources (one entry per
  dashboard, by its title, "data as of" its date). The person can switch it off for a question; its tools then refuse
  (`system_off`) and Gemini can ask for it with `wizard_ask_for_system`. With no folder set it is not listed; a folder
  this PC cannot reach is listed, as a database that does not answer is, and its tools say so.
- **The folder on every PC.** The setting keeps its key, `WIZARD_HTML_REPORTS_DIR`, and is called "Dashboards" in
  Settings and the docs. A mapped drive letter is resolved to the network path it stands for with `WNetGetConnectionW`
  (also a remembered, disconnected mapping) when the person saves it in Settings, when a provisioning file is made
  (`scripts/make_provision.py`) or exported (**Export settings…**), and again at load; off Windows nothing changes. The
  key is now a company setting a provisioning file may carry (it left `provisioning.LOCAL_ONLY`). Settings has a
  Dashboards section: paste a path (quotes allowed), **Find dashboards** shows the path Wizard will save and how many
  dashboards it finds, Save keeps it.
- **A folder that cannot be reached never stops Wizard.** The path is worked out without touching the disk at load.
  The tools, `wizard_list_sources` (connector status `BLOCKED`, with the reason) and `run.py --check` (a WARN, never a
  FAIL) say plainly that this PC cannot reach the dashboards folder and to ask for access to the share. A share that
  does not answer is cut short (10 seconds to reach it, 90 to list it, 100 to read a page).
- **Two read-only tools**, in every run kind when a folder is set (`tools/dashboard_tools.py`, `dashboards.py`):
  `wizard_dashboards` lists the dashboards (`.html`, `.htm`, subfolders included): a stable id from the relative path,
  the title (`<title>` or the first heading), the date the page states (else the file's modified time, and which),
  modified time, size, subfolder; optional find words over titles, paths and headings. `wizard_read_dashboard` reads
  one, by id or path: title, as-of, headings and visible text (hidden elements left out), tables as rows (headers from
  `<thead>` or header rows, spans laid out, figures such as `1,234`, `12.5%`, `(56)`, `AED 4,500` as numbers with their
  unit on the column), and the data in its scripts that parses as JSON: the arguments of `Plotly.newPlot`, ECharts'
  `setOption`, `new Chart`, `Highcharts.chart` and `vegaEmbed`, variables set to data (also written as loose
  JavaScript objects: unquoted keys, single quotes, trailing commas), JSON script blocks, `data-*` attributes and Plotly's
  binary arrays, with series names and chart and axis titles. A chart's points come as rows of series, x and y (and
  value for heat maps). It names what it did not read: data the page loads from an address (`fetch`, `d3.csv`, XHR, a
  Vega spec URL, script files other than chart libraries, embedded pages), script data that is not JSON (a function, a
  variable it never sets), and pictures. The first read is an overview with the start of the text and the first rows of
  each part; `part` (`text`, `T2`, `D1`, or a heading's words) and `offset` page through the rest, up to 500 rows a read.
- **The boundary is inside the tools.** Only files inside the folder: ids come from Wizard's own walk, which never
  follows a link or junction and skips hidden folders; a path with `..`, a drive or a leading slash is refused; the file
  is resolved again before it is read and must still be inside the folder. Pages are parsed with the standard library's
  `html.parser` and the JSON reader: no script runs, nothing a page references is fetched. Up to 50 MB a page. A parse is
  kept under `data\dashboards\` by path, size and modified time, so a page is read once per version. What a page says
  is data, never instructions.
- **Evidence and its data mode.** Each part read (the text, a table, a chart's data) is evidence with its rows (at most
  500), request (dashboard, path, part, offset, rows), digest and as-of, so figures are cited `[E3]` and Check my data
  recomputes them and reads the same part again (UNCHANGED, CHANGED, or UNAVAILABLE when the file is gone or the share
  is not reachable). The data mode is **LIVE**: a company source read now, as the dashboard shows it, as a portal's
  report page is (AGENTS.md: LIVE is what Wizard reads now from the company's own systems; USER_PROVIDED is a file a
  person attached; an approved snapshot needs an approval Wizard cannot see). A new connector status, **PREPARED_FILE**,
  says how: the figures are the dashboard's own, prepared by the team with its logic, not Wizard's query. The as-of is
  the date the page states (its title or text after words such as "as of", "updated", "data to"; else its metadata; else
  a date in its data or title), else the file's modified time, and the evidence says which; day/month order is read as
  day first when it is ambiguous, and said. Never verified. `PREPARED_FILE` (and `BROWSER_SESSION`, which was missing)
  are in the report schema; the web app shows a dashboard's part as "A team dashboard, read as it is".
- **The order is guidance.** The prompt's "Prepared dashboards" section says the dashboards combine the database's data
  with the business logic a fresh query may miss: when one covers the question, read it first and use the database or
  the portals for the detail it does not show; give its as-of date; when your own query disagrees, show both and say
  why they may differ. No code forces the order (AGENTS.md forbids a scripted tool order), as with "look in the portal
  map first".

**Consequences.** On a PC with a dashboards folder Gemini is offered two more tools; the tool catalog lists them (served
by the `wizard` MCP server). A provisioning file may now carry the folder, as a network path. Pages that build their
figures only in code (a calculation, data fetched from an address) show what they could not read instead of figures;
reading them would need a browser and is not done. A team that wants its dashboards read well puts the data in the page
as JSON (Plotly's and pyecharts' HTML exports do) or as tables. The WNetGetConnectionW call is mocked in tests and first
runs on a work PC; WizardBar is unchanged (Export settings… is built by the service).

**Evidence.** `tests/unit/test_dashboards.py` (the network path and the mocked lookup, start-up and `run.py --check`
with a folder this PC cannot reach, listing with links out and hidden folders, traversal attempts, invented dashboards
with a table, Plotly, ECharts, Chart.js, loose JavaScript, JSON scripts, data attributes and binary arrays, a page that
loads its data from an address, a huge page in pages, size and time limits, the cache, the tools with evidence and the
report schema, Check my data recomputing and replaying, rights, the systems choice on, off and asked for in question
runs, Settings' Find dashboards and save, provisioning and export), `tests/unit/test_workpc.py`,
`tests/contract/test_contracts.py`, and the web tests (`SettingsDialog`, `EvidenceDrawer`, `stage`, `sources`).
