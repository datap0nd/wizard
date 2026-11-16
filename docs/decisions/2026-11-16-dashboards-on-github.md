# 2026-11-16 — The dashboards are read from the company GitHub, and mapped from scratch

**Owner:** project owner. **Status:** decided (16 November 2026). Supersedes the dashboards folder of
[2026-11-02](2026-11-02-html-dashboards.md); the page reader, the evidence and the system of that decision stay.

**Context.** On 2 November the team's HTML dashboards were a folder on a network share (`WIZARD_HTML_REPORTS_DIR`),
and the knowledge base's `dashboards/` area held one note per dashboard file in that folder
([2026-11-02](2026-11-02-dashboards-area.md)). The owner: "In wizard, I want the dashboards part to be mapped from
scratch. Our dashboards are all in github enterprise, I want to map them and then I want wizard to reference them. I am
a collaborator on all of them." In a repository a dashboard comes with the code and SQL that build it and the workflow
that refreshes it, which is the business logic the dashboard notes are meant to hold.

**Options.** For finding them: (1) the person lists every repository; (2) every repository the token's account owns or
is a collaborator on (`GET /user/repos?affiliation=owner,collaborator`), narrowed by an optional list. For reading:
(a) the GitHub Pages sites, as a browser would; (b) the repositories' files through GitHub's API. For the map: (i) a map
file like the portal maps; (ii) the knowledge base's dashboard notes, written by a task, the only writer of notes.
For the folder: keep it beside GitHub, or retire it.

**Decision.** Option 2, (b) and (ii); the folder is retired.
- **The source.** Settings → Dashboards has a **Read-only token** (`WIZARD_DASHBOARDS_TOKEN`), **Repositories**
  (`WIZARD_DASHBOARDS_REPOS`: empty for every repository the token's account owns or is a collaborator on, else
  `owner/name` or `owner/*`; an address on the company GitHub is taken as its owner/name) and the name people see. The
  Dashboards system is on when the token is set. Wizard looks in each repository's default branch and, when it publishes
  a GitHub Pages site from a branch, in that branch's site folder, for `.html` and `.htm` pages; libraries, builds and
  hidden folders are skipped (`.github` is kept for its workflows). Wizard's own repositories (the knowledge base, the
  Pages site, the feedback repository) are never dashboards. A dashboard's id comes from its repository, branch and
  path; its link is its Pages address when it has one, else the file on the company GitHub.
- **Read only, inside the tool.** Only GET requests to the company GitHub's API (`wizard_connectors.github`), never a
  `Link` to another address; only those repositories, only files in their trees. Pages are parsed with the same reader
  (no script runs, nothing a page references is fetched), up to 50 MB; a parse is kept by the file's blob id, so a
  version is read once. GitHub's answers are kept with their ETags and asked again conditionally (an unchanged answer
  costs no rate limit). The token is a company setting a provisioning file may carry, stored with DPAPI; Settings says
  to make it read-only (fine-grained, Contents "Read-only"), and Find dashboards warns when it is a classic token, which
  can also write. Requests take the company GitHub's route (Settings → Network → Company GitHub proxy).
- **As-of.** The date the page states, else the file's last commit on its branch, else the repository's last push, and
  the evidence says which. Data mode `LIVE`, connector status `PREPARED_FILE`, never verified, as before.
- **Four tools.** `wizard_dashboards` (id, title, repository, path, as-of, links, and `note`: the knowledge note that
  maps it), `wizard_read_dashboard` (as before, with the repository, the links, the note and the page's source id),
  `wizard_dashboard_files` (the repositories, or one repository's files with their kind: sql, workflow, readme, page,
  text) and `wizard_dashboard_read_file` (a text file in parts of 30,000 characters, with its source id; a binary file is
  refused). Each read is evidence; a file read has no rows.
- **The map is the dashboard notes.** A packaged task, **Map the dashboards from scratch** (`tasks/map-dashboards.md`,
  repeats until done, up to 30 runs), reads every dashboard and the code that builds it and writes one note per
  dashboard in `dashboards/` to the knowledge standard's section 13, which now asks for `## Where it lives` (repository,
  branch, each page's path and Wizard's dashboard id, the Pages address) instead of `## File`, and for the page's and the
  code's source ids. It keeps an index note, `dashboards-index`, of every page with its note or why it is not a
  dashboard, rewrites or removes every note of the old folder map, points the metric notes' `## Where to get it` to the
  new notes, and ends with `Left: <number>`. A SIGNED note is never changed.
- **Wizard references them.** `wizard_dashboards` and `wizard_read_dashboard` name each dashboard's note: of the notes
  in `dashboards/` that name its id, the one that names the fewest dashboards (its own note before the index), else one
  that names its repository and path. The prompt says to read the note for the business logic, the dashboard for the
  figures and the code for what the note does not say, and to give the dashboard's link; the evidence's link opens it
  ("Open the dashboard on GitHub" in the sources).
- **The folder is retired.** `WIZARD_HTML_REPORTS_DIR` is no longer read, shown in Settings, written into a
  provisioning file or exported; `run.py --check` says so when a PC still has it. The drive-letter lookup
  (`WNetGetConnectionW`) and the folder walk are gone. A GitHub this PC cannot reach, or a token GitHub refuses, never
  stops Wizard: the tools, `wizard_list_sources` (`BLOCKED`, with the reason) and `run.py --check` (a WARN) say so, and
  a listing that failed is not tried again for 5 minutes unless the person asks.

**Consequences.** The owner enters the token on their PC (Settings → Dashboards), presses **Find dashboards**, then
runs **Map the dashboards from scratch** in Settings → Tasks; other PCs get the token from the company file. Until the
task has run, dashboards have no note (`note: null`) and the old notes still describe folder files. A dashboard whose
figures are built only in code (a query run at view time, data fetched from an address) shows what could not be read;
its note says how it is calculated, from its code. The GitHub API calls are tested against an invented server; their
first run against the company GitHub is on the owner's PC.

**Evidence.** `tests/unit/test_dashboards.py` (an invented company GitHub: finding the dashboards in the repositories
the account owns or collaborates on and only those, Pages branches and addresses, libraries and hidden folders
skipped, only GET requests, named repositories, the reader over invented HTML, limits, conditional requests and the
parse kept by version, a listing that did not finish, a GitHub that does not answer, a refused token and a gateway, the
four tools with evidence and links, the note that maps a dashboard, the code read as text and refusals outside the
repositories, Check my data, rights, the systems choice in question runs, Settings' Find dashboards and save,
provisioning and export without the retired folder, `run.py --check`, and the map task naming only tools Wizard has),
`tests/unit/test_workpc.py`, `tests/contract/test_contracts.py`, and the web tests (`SettingsDialog`,
`EvidenceDrawer`).
