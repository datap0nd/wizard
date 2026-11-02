---
id: kb-review-0-dashboards
title: Knowledge review 0: describe the HTML dashboards (run this first)
summary: The team's HTML dashboards combine the data with business logic Wizard would struggle to rebuild. This reads every dashboard and writes one note per dashboard in the dashboards area - what it shows, the breakdowns and periods it covers, and how each figure is calculated - and moves the older dashboard notes out of the datasets area.
added: 2026-11-02
repeat: until_done
---
The team's HTML dashboards (the Dashboards system) are the first source in the owner's source order: they combine the
company data with business logic (definitions, filters, exclusions, adjustments) that a fresh query may miss. Wizard
decides whether a dashboard is enough for a question from its note in the `dashboards/` area: what it shows, which
breakdowns, markets, periods and granularity it covers, and how each figure is calculated. Write those notes.

1. Read wizard_kb_standard: sections 1, 4, 11 and 13 (dashboard notes).
2. wizard_dashboards: every dashboard in the folder. If the tool says the folder is not set or this PC cannot reach
   it, stop and say: set it in Settings → Dashboards, then run this task again.
3. Find the notes that already describe dashboards: wizard_browse_knowledge(area=dashboards), (area=datasets) and
   (area=platforms), and wizard_lookup_definitions with "dashboard". A note in `datasets/` that describes a dashboard,
   not a database object, moves to `dashboards/` in the same call that rewrites it to section 13
   (wizard_kb_save_notes with `moves`; a new file name in the standard's id form `<what it shows>-dashboard` renames it,
   and Wizard updates every other note's `related`). A platform note about the dashboards as a whole stays where it is.
4. For each dashboard, read it with wizard_read_dashboard: the overview first, then the parts that say how it is built
   (`part`: its text, its tables, its chart data). Then write or update its note, `knowledge/dashboards/<id>.md`,
   `type: entity`, `status: DRAFT_UNSIGNED`, `owner: TBD - <the team that maintains it> (ask the user)`, with the
   sections of section 13:
   - `## What it shows`: a table of each measure with its unit and every breakdown (market, product, channel, customer
     segment, age band...), granularity (daily, weekly, monthly) and period it covers, so a reader can tell whether it
     answers a question or only part of it;
   - `## Business logic`: how each figure is calculated, as the page states it (titles, footnotes, column headers,
     legends, notes) and, where it does not, what you can establish by comparing one of its figures with the database
     (wizard_query_postgresql, with the dataset notes): what it includes and excludes, filters, adjustments,
     currencies. Mark what you concluded `(inferred)`; what you cannot see is `UNKNOWN (ask: <role>)`. Write the logic,
     never the figures;
   - `## Where the data comes from` (dataset note ids, also in `related`), `## Refresh and as-of` (how often, and where
     the page shows its date), `## Who maintains it` (a role), `## File` (its file name and subfolder inside the
     dashboards folder, never a drive letter, share path or full path), `## Questions this note answers`,
     `## Open questions`;
   - `related`: the dataset notes it reads and the metric notes for its measures; `aliases`: its file name without
     `.html` and the names people use for it.
5. No performance figures anywhere in a note, not even as an example (rule 7): the dashboard itself is the live source.
   A dashboard read live has no source id: keep a moved note's `sources`, and say in `## Refresh and as-of` the date
   you read it.
6. A SIGNED note is not changed or moved: put your proposal in the summary.
7. Save one or two dashboards per save: wizard_kb_save_notes, message "Describe the HTML dashboards".

When the tool budget runs low, save what you have and stop: the next run continues with the dashboards that have no
note yet.

End with: the dashboard notes written or updated, the notes moved or renamed, the dashboards that could not be read and
why (data loaded from elsewhere, an unreadable page), the business logic you could not establish (open questions for
the maintaining team), and the SIGNED notes with the changes you propose.
