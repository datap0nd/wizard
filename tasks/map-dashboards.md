---
id: map-dashboards
title: Map the dashboards from scratch
summary: Reads every dashboard Wizard finds on the company GitHub, and the code that builds it, and writes one note per dashboard in the knowledge base (what it shows, its business logic, where its data comes from, where it lives), replacing the notes written for the old dashboards folder. Runs again until every dashboard is mapped.
added: 2026-11-16
repeat: until_done
max_runs: 30
---
The team's dashboards are HTML pages in repositories on the company GitHub. They combine the database's data with
business logic (definitions, filters, exclusions, adjustments) that a fresh query misses, so Wizard reads them first
when one covers a question. Wizard references a dashboard through its note in the knowledge base's `dashboards/` area:
the note says what the dashboard shows and how it gets each figure, and names the dashboard so Wizard can open it. Map
every dashboard from scratch: the notes already in `dashboards/` were written for a dashboards folder that is no longer
read, so each is rewritten from the dashboard on GitHub or removed.

At the start of each run:

1. Read wizard_kb_standard, above all section 13 (Dashboard notes) and section 11 (a metric's `## Where to get it`).
2. wizard_dashboards, every page of it (next_offset): each dashboard's id, title, repository, path, as-of, links and
   `note`, the note that maps it. `mapped` counts the dashboards that have one.
3. wizard_browse_knowledge(area="dashboards"): the notes there. A note is from this map when its `## Where it lives`
   names a dashboard id (`d` and 10 characters, from wizard_dashboards); every other note there is from the old map.
4. wizard_dashboard_files without a repository: the repositories, what each is for and how many dashboards it holds.

Then work through the dashboards that have no note yet, repository by repository, and finish each before the next:

1. Decide what is one dashboard. A repository may hold several dashboards, and one dashboard may be several pages
   (an index and its detail pages, the same page on the default branch and on its Pages site): those get one note that
   names each page. A page that is not a dashboard (a template that holds no figures, documentation, a test page, a
   site's 404 page) gets no note of its own; list it in the index note (below) with why.
2. Read the dashboard: wizard_read_dashboard for its overview, then the parts you need (tables, chart data, the text
   under a heading). Note what it shows, its as-of and where the page states it, and what Wizard could not read
   (`not_read`).
3. Read the code that builds it: wizard_dashboard_files(repository) lists the files with their kind (sql, workflow,
   readme, page, text). Read the README, the SQL, the script or notebook that produces the page, and the workflow that
   refreshes it with wizard_dashboard_read_file. When the figures are computed in the page itself, read the page's own
   source with wizard_dashboard_read_file (its path). From the code, write down how each figure is calculated: the
   tables and columns it reads, its filters, exclusions, joins, period logic and adjustments, and what is typed in by
   hand. Find the dataset notes for those tables (wizard_lookup_definitions, wizard_browse_knowledge(area="datasets"))
   and the metric notes for its measures.
4. Write its note to section 13, `type: entity`, in `knowledge/dashboards/`, with `## Where it lives`: the repository
   (owner/name), the branch when it is not the default, each page's path and Wizard's dashboard id, and the Pages
   address when it has one. Cite what the page shows with the page's source id and what the code says with the file's
   ([S-xxxxxxxx], from wizard_read_dashboard and wizard_dashboard_read_file), and put those ids in `sources`. Logic you
   cannot see in the page or its code is `UNKNOWN (ask: <role>)`, never guessed. Never a figure's value: the dashboard
   is the live source.
5. An old note that describes this dashboard: write the new note over it (keep its id when it fits section 13, else
   rename it with `moves`), and keep what it says that the dashboard and its code confirm or do not contradict, marked
   `(from the earlier note)`. An old note filed in another area (`datasets/`, `platforms/`) that describes a dashboard
   moves to `dashboards/` the same way.
6. Each metric note whose measure the dashboard shows names the dashboard's note in its `## Where to get it` (section
   11): change only that section, and add the dashboard note's id to its `related`.

Keep one index note, `knowledge/dashboards/dashboards-index.md` (`type: overview`, title "Dashboards on the company
GitHub"): one table row per repository and page, with the page's dashboard id, the note that maps it, and for a page
that is not a dashboard why. Update it in the same save as the notes it lists.

Save as you go, after each repository or every two or three dashboards: wizard_kb_save_notes with the notes, moves and
removes, message "Map the dashboards: <repository>". A refused save says why: fix it and save again.

When every dashboard has a note, finish the old map: remove each old note in `dashboards/` that describes no
dashboard on GitHub (`removes`; when another note's `related` names it, save that note without the link in the same
call), and change the text of notes that still name a removed or renamed note. A SIGNED note is never changed, moved
or removed: put what you would change in your summary for its owner.

Do not change what is not about the dashboards: other notes' text outside their `## Where to get it` and `related`,
the portal maps, the source order. Do not copy a dashboard's figures, tokens, people's names or addresses other than
the dashboard's own GitHub and Pages links into a note.

End with a summary: the dashboards mapped in this run (by note), the repositories done, the pages that are not
dashboards, the old notes removed or rewritten, and what is UNKNOWN and whom to ask. Its last line is `Left: <number>`:
the dashboards that still have no note plus the old notes not yet rewritten or removed (`Left: 0` when the map is
complete).
