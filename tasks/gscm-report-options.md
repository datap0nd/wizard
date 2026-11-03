---
id: gscm-report-options
title: "GSCM: map the columns and groupings behind each sales report's Configuration"
summary: Wizard could not answer daily sell-out by operator because the map knew only the default columns of GSCM's sales reports. This first corrects what an earlier run got wrong about the daily sell-out report, then opens each sales, sell-out, sell-in and stock report's Configuration, maps every category and choice in it (account, customer, channel...) with what each needs first, proves the request and a script that read it, and says what each report answers.
added: 2026-11-03
repeat: until_done
max_runs: 10
---
A person asked for sell-out by operator, compared with the day before. GSCM's daily sell-out report has the account
(operator, retailer, customer), but only through its own Configuration button, three levels deep, and only after the
subsidiaries are chosen. The GSCM guide's section "A report's Configuration" gives the proven path. Map what each sales
report's Configuration offers, so the next question reads the right report in one or two calls.

Never change anything in GSCM: never press Save or "Apply and save", and untick a choice that stays saved for the
person. Do not goto the start page while GSCM's client is running (Wizard keeps the page; the result says `kept`).
Metadata only in the map: names of columns, options and filters, their labels and values, counts and row structure;
never rows of data or figures. A choice you have not found is unknown, never absent: never write in the map or a note
that a report lacks a breakdown.

1. Read portal_guide(system=gscm), above all "Opening a report directly" and "A report's Configuration". Then
   portal_map(system=gscm), its topics, and the topic `options-review` if it exists.
2. First, correct an earlier run. On 3 November a run looked at the daily sell-out report's search conditions instead
   of its Configuration, and wrote that it has no account or operator breakdown and that operator questions must use a
   weekly database view: into the map (the report's views, notes, use_for, not_for) and into the GSCM platform note.
   That is wrong.
   a. Open the daily sell-out report (the topic `open-report-directly`). Choose the subsidiaries one by one in its
      search conditions (all of them; not a region). Find its Configuration button with `W.nexacro.find(/config/i)`,
      click it, and follow Configuration → Sales → Sales → ORG Sales: read the dialog with `W.nexacro.options()` after
      each click. Tick ORG Sales, Apply, search. Read the datasets (`W.nexacro.datasets(form)`): the account columns and
      the rows (a sub-total per account, then one row per country).
   b. Save the report again (portal_map_save) with the truth: its views (below), its notes without the wrong claim, and
      route it (portal_map_route) so questions about operators, accounts or customers, daily, come to it.
   c. Read the GSCM platform note (wizard_kb_note_source) and every other note whose text says this report has no
      account or operator breakdown (wizard_lookup_definitions with "operator", "account", "daily sell-out"). Rewrite
      those passages as what you proved: the report holds daily sell-out by account through its Configuration, after
      choosing subsidiaries; the database view holds it weekly. Save with wizard_kb_save_notes. A SIGNED note is not
      changed: put your proposal in the summary.
   d. In `options-review`, set this report back to `left` if it says `done`, and to `done` only when step 4 is done.
3. The list to work through, on the first run only (later runs read `options-review` and continue with the reports
   still `left`): the reports that hold sales, sell-out, sell-in, stock, shipment or channel measures (portal_map with
   those words and with daily, weekly, account, customer, operator, channel), the daily sell-out report first, then the
   other sell-out reports, then the rest. Save the list as the map topic `options-review`, one line per report:
   `<report id> | <name> | left` (or `done`, or `failed: <why>`).
4. For each report, in that order:
   a. Open it with the proven call (one evaluate step, no goto). Search with its defaults (never Save).
   b. Find its Configuration: `W.nexacro.find(/config/i)` (also try the words the report uses: setting, column, display,
      personal, layout). It may be in the report or in the report toolbar. The top bar's Setting gear is not it.
   c. Open it and read it with `W.nexacro.options()`. Open every category, and every group inside each category, reading
      the dialog again after each click, until you have seen every choice. For each choice record what it is (an
      account, a country, a model, a channel, a measure, a unit...) and whether it is ticked by default.
   d. Turn on the choices that are off, above all the account or customer, the channel and the country, and press
      Apply. If the portal refuses (a popup or alert: read its text, e.g. too much granularity), narrow the filter it
      names (choose subsidiaries one by one rather than a region) and try again. Record what it needed.
   e. Search, and record: the columns the datasets gained and what each holds on screen; how the rows change (totals,
      sub-totals per account, one row per country) and how to tell a total or sub-total row from a detail row; and
      whether the search request gained a parameter or only the reply gained columns (compare the request bodies in
      `requests` before and after).
   f. Prove the fast route with that choice on: send the search request again (a request step, or W.replay) with one
      filter changed, such as the date one day earlier, and check the reply still has the new columns. Save the request
      with its filters as `{{param}}` placeholders, and the parameter that turns the choice on when there is one;
      `verified` only when proven.
   g. If a choice is still ticked after you reopen the report (saved for the person), untick it, unless the request
      alone turns it on.
   h. Save the report (portal_map_save): `views`, one per Configuration category, each with `path` (the clicks, with the
      screen's labels: "Configuration > Sales > Sales > ORG Sales, then Apply"), `requires` (what must be set first and
      what the portal says otherwise), `options` (every choice, the default ones marked, what each is), `columns`,
      `effect` and `how`; `data` with the new columns and their labels; `requests`; `open`; `notes` with the row
      structure and the pitfalls; and a script that reads the report with the account breakdown for a date range and
      the subsidiaries (portal_save_script: it is kept in the map), named in `script`.
   i. Route it (portal_map_route): `use_for` in the words people use (operator, account, customer, retailer, channel,
      country) with its granularity (daily, weekly, monthly), and `not_for` the near misses with the report to use
      instead.
   j. Mark it `done` in `options-review` (or `failed: <why>` after two failed tries, with where you looked) and go on.
5. When a report's Configuration cannot be found or opened, mark it `failed: <where you looked>`, never `done`, and say
   in its notes that its options are not mapped yet.

When the tool budget or time runs low, save the report you are on and the `options-review` topic first, then stop: the
next run continues from there.

End with: what you corrected from the earlier run; the reports done in this run and what their Configuration offers;
which reports give sell-out by account, at which granularity, and what must be chosen first; the scripts saved; the
notes changed; the reports that failed and where you looked. Then the last line: `Left: <number of reports still left
in options-review>`.
