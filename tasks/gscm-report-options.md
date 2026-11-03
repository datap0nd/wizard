---
id: gscm-report-options
title: "GSCM: map the columns and groupings behind each sales report's configuration gear"
summary: Wizard could not answer daily sell-out by operator because the map knew only the default columns of GSCM's sales reports. This proves one way to open a report, then maps what each sales, sell-out, sell-in and stock report's configuration gear adds (account, customer, channel), the request and a script that read it, and what each report answers.
added: 2026-11-03
repeat: until_done
max_runs: 10
---
A person asked for sell-out by operator, compared with the day before. The GSCM map knew a daily sell-out report but
only its default view, which groups by region and has no account column. In GSCM, the account (the operator, retailer
or customer) is a column added in the report grid's configuration gear and applied with Apply. Wizard never read the
report: opening it took eight minutes, and it answered from a monthly database view instead. Map what each sales
report's configuration adds, so the next question reads the right report in one or two calls.

Never change anything in GSCM: never press Save or "Apply and save", and put a choice that stays saved for the person
back the way it was. Do not goto the start page while GSCM's client is running: it restarts the client (Wizard keeps the
page; the goto's result says `kept`). Metadata only in the map: names of columns, options and filters, their labels and
values, counts and row structure; never rows of data or figures.

1. Read portal_guide(system=gscm): "Opening a report directly", "Columns behind a grid's gear" and "Popups and
   waiting". Then portal_map(system=gscm) and its topics.
2. The way to open a report, first. Find the topic that says how a report opens by its menu id. Prove it on a mapped
   report in one evaluate step with no goto: `return await W.nexacro.open('<the client's open function>', '<menu id>')`
   (it waits for the client, calls the function with its own form as `this`, then waits for the report). If the topic
   starts with a goto of the start page, calls the function bare, or has no wait, rewrite it (portal_map_save, topics)
   with the call that worked. Use that call, and write it in the `open` of every report you save.
3. The list to work through. On the first run, find the reports that hold sales, sell-out, sell-in, stock, shipment or
   channel measures: portal_map(system=gscm, find=...) with those words and with daily, weekly, account, customer,
   operator and channel. Put the daily sell-out report first (the one the GSCM guide uses as its example), then the
   other sell-out reports, then the rest. Save the list as a map topic `options-review` (portal_map_save, topics), one
   line per report: `<report id> | <name> | left` (or `done`, or `failed: <why>`). On a later run, read that topic and
   continue with the reports still `left`.
4. For each report, in that order:
   a. Open it with step 2's call. Search with its defaults (its request in the map, or its search button; never Save).
   b. Find its grid's configuration: a gear, or a Configuration, Setting, Column, Display or Personalize control on or
      above the grid (`W.nexacro.inputs()`, `look`). Open it and list every choice with its default state: columns,
      groupings and dimensions (region, country, account or customer, channel, product, model), measures, units.
   c. Turn on each choice that is off, above all the account or customer, the channel and the country. Press Apply,
      search again, and record: the columns the datasets gained (`W.nexacro.datasets(form)`) and what each holds on
      screen; how the rows change (a total row, a sub-total per account, then one row per country...) and how to tell
      a total or sub-total row from a detail row; and whether the search request gained a parameter or only the reply
      gained columns (compare the request bodies in `requests` before and after).
   d. Prove the fast route with that choice on: send the search request again (a request step, or W.replay) with one
      filter changed, such as the date one day earlier, and check the reply still has the new columns. Save the request
      with its filters as `{{param}}` placeholders, and the parameter that turns the choice on when there is one;
      `verified` only when proven.
   e. If the choice is still on after you reopen the report (it is saved for the person), turn it off again, unless the
      request alone turns it on.
   f. Save the report (portal_map_save): `views` with every option, its choices, the default and what each adds;
      `data` with the new columns and their screen labels; `requests`; `open`; `notes` with the row structure and the
      pitfalls; and a script that reads the report with the account breakdown for a date range (portal_save_script: it
      is kept in the map, so every PC can run it), named in `script`. If the map names a script that portal_map shows as
      `script_missing`, save the proven one under that name.
   g. Route it (portal_map_route): `use_for` in the words people use (operator, account, customer, retailer, channel,
      country) with its granularity (daily, weekly, monthly), and `not_for` the near misses with the report to use
      instead (a weekly report for a question about one day, a region-only view for a question by account).
   h. Mark it `done` in `options-review` (or `failed: <why>` after two failed tries) and go on.
5. Two knowledge notes were changed by hand outside Wizard on 3 November 2026: the GSCM platform note and the dataset
   note on sell-out by operator in the database. Read both (wizard_kb_note_source) and wizard_kb_standard. Where they
   disagree with what you proved (which report holds the account breakdown, at which granularity, how it is turned
   on) or break the standard, correct them with wizard_kb_save_notes: a description of what each source holds and
   covers, not an order to follow. A SIGNED note is not changed: put your proposal in the summary.

When the tool budget runs low, save the report you are on and the `options-review` topic, then stop: the next run
continues from there.

End with: the reports done in this run and what their configuration adds; which reports give sell-out by account, at
which granularity, and how the account is turned on (a request parameter, or the gear only); the open call you proved;
the scripts saved; the notes changed; the reports that failed and why. Then the last line: `Left: <number of reports
still left in options-review>`.
