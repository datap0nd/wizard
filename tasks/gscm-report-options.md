---
id: gscm-report-options
title: "GSCM: map the columns and groupings behind each sales report's Configuration"
summary: Run it after the daily sell-out (DB4009) task. Goes through GSCM's other sales, sell-out, sell-in and stock reports: reads each report's code for every data request it can send, maps every Configuration category and choice (account, customer, channel...) with what each needs first, has Wizard prove the request that reads it, saves a script, and says what each report answers.
added: 2026-11-04
repeat: until_done
max_runs: 30
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
2. The daily sell-out report (DB4009) has its own task, "GSCM daily sell-out by account (DB4009)", which proves it
   against the person's own export. Leave it to that task: skip it here, whatever `options-review` says.
3. The list to work through, on the first run only (later runs read `options-review` and continue with the reports
   still `left`): the reports that hold sales, sell-out, sell-in, stock, shipment or channel measures (portal_map with
   those words and with daily, weekly, account, customer, operator, channel), the daily sell-out report first, then the
   other sell-out reports, then the rest. Save the list as the map topic `options-review`, one line per report:
   `<report id> | <name> | left` (or `done`, or `failed: <why>`).
4. For each report, in that order:
   a. Open it with the proven call (one evaluate step, no goto). Read its code first: `W.nexacro.transactions()`
      lists every data request its functions can send (address, input datasets, arguments), and
      `W.nexacro.source('<name>')` gives a function's whole code. Then search with its defaults (never Save).
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
   f. Save the request with its filters as `{{param}}` placeholders, and the parameter that turns the choice on when
      there is one. Then prove it: portal_prove_request with the values the screen used as `first` and one changed
      (the date one day earlier) as `second`. Only that marks it verified, and a report is mapped only once one of its
      requests is proven; when it is not proven, read its problems and fix the request.
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
