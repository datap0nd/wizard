---
id: gscm-db4009-daily-sellout
title: "GSCM daily sell-out by account (DB4009): map it precisely and prove it"
summary: Wizard could not read daily sell-out by operator. This maps the daily sell-out report completely (its code's data requests, every Configuration category and choice), finds the request that returns the account (ORG Sales) breakdown, has Wizard prove it, and checks the direct read row by row against what the report's own screen shows for the same filters. It also corrects an earlier run that wrote the report had no account breakdown. No file needed.
added: 2026-11-04
repeat: until_done
max_runs: 5
---
The daily sell-out report (menu id DB4009) holds sell-out by account (operator, retailer, customer), but only through
its own Configuration: **Configuration → Sales → Sales → ORG Sales**, then **Apply**, after choosing the subsidiaries one
by one in the search conditions (all of them is fine; a region such as Middle East is refused as too much granularity).
The grid then shows a sub-total per account and one row per country under it. Map this one report so precisely that a
question about operators reads it in one direct request, and prove that request gives exactly what the screen shows.

Never change anything in GSCM: never press Save or "Apply and save"; untick a choice that stays saved for the person.
Do not goto the start page while GSCM's client is running. A choice you have not found is unknown, never absent.
Metadata only in the map and the notes: names, labels, parameters, row structure, counts; never figures.

1. Read portal_guide(system=gscm), above all "Opening a report directly" and "A report's Configuration", then
   portal_map(system=gscm, report=db4009) and the topic `open-report-directly`. Earlier runs' work is there; continue
   from it.
2. Choose the reference filters: a recent day that has data (yesterday, or the last working day) and the day before,
   and two or three subsidiaries chosen one by one. Use the same filters on the screen and in the direct request.
3. Open DB4009 with the proven call (one evaluate step). Read its code before touching the screen:
   `return W.nexacro.transactions()`: every data request its functions can send (the address, the input datasets,
   the arguments) and the application's wrappers that complete an address. Read the search function and whatever
   Configuration's Apply calls with `W.nexacro.source('<name>')`. Read the input datasets each request sends
   (`W.nexacro.read('<dataset>')`): which column carries the subsidiaries, the dates, and the dimensions or levels.
4. The person's path, once, exactly, with the reference filters: choose the subsidiaries one by one in the search
   conditions, find Configuration (`W.nexacro.find(/config/i)`), open it, and read it with `W.nexacro.options()` after
   every click: Sales → Sales → ORG Sales. Tick it, Apply, then search for the two days. If the portal answers with a
   message (too much granularity...), read it, narrow as it says, and record it.
5. The reference: read the grid's rows as the screen shows them, in one evaluate step that returns the table
   (`W.nexacro.readGrid('<the grid's path>')`, every row). Its evidence id is the reference for step 9. Note how a total,
   a sub-total and a country row are told apart, and which columns are the account, the country and each day.
6. What Apply changed: compare the search request before and after (the result's `requests`, `W.requests('.do')`,
   bodies in full) and the input datasets. Record the parameter or dataset column that carries ORG Sales, and its values
   for each level (region, subsidiary, account...).
7. Every other choice of the Configuration: open each of its six categories and every group inside each, reading
   `W.nexacro.options()` after each click, and record every choice with what it is and whether it is on by default.
   Untick what you ticked when you are done, unless the request alone turns it on.
8. Save the report (portal_map_save): its `views` (one per category, each with `path`, `requires`, `options`,
   `columns`, `effect`, `how`), `filters` with the parameter each sets, `data` with every column and its label, the
   request with `{{param}}` placeholders for the dates, the subsidiaries and the ORG Sales level, `open`, `notes` (row
   structure, totals, pitfalls). Then prove the request: portal_prove_request with `first` the reference filters and
   `second` the same a day earlier. If it is not proven, read its problems, fix the request (steps 3 and 6 say what it
   must carry) and prove it again.
9. Check the direct read against the screen: wizard_compare_evidence(reference = step 5's evidence, checked = the
   proof's first reply, keys = the account and country columns of each, values = each day's sell-out column of each,
   system=gscm, report=db4009). MATCH is the goal. When it is DIFFERENT, read the differences and find the cause (a
   subsidiary or date not the same, the account level, sub-total rows, the wrong columns paired), fix it and check
   again. Only a MATCH makes the report precise.
10. With a MATCH: save a script that reads DB4009 by account for a date range and subsidiaries with the proven request
    (portal_save_script, kept in the map), name it in `script`, and save the report as mapped. Route it
    (portal_map_route): use_for daily sell-out by operator, account, customer, retailer, by country, day against day;
    not_for weekly or monthly totals (name the report to use instead if the map has one).
11. Correct the earlier run. On 3 November a run wrote that this report has no account or operator breakdown and that
    operator questions must use a weekly database view: into the map and into the GSCM platform note. Remove that claim
    wherever it is: the map's notes, use_for and not_for (steps 8 and 10 replace them), and the notes:
    wizard_lookup_definitions with "operator", "account" and "daily sell-out", wizard_kb_note_source for each, and
    rewrite the passage as what you proved (daily sell-out by account through Configuration, after choosing subsidiaries;
    the database view holds it weekly). Save with wizard_kb_save_notes. A SIGNED note is not changed: put your proposal
    in the summary.
12. In the topic `options-review` (if it exists), set db4009 to `done` only with a MATCH.

When the tool budget or time runs low, save what you have proven so far (the map and the request) and stop: the next run
continues from there.

End with: the request that returns the account breakdown and the parameter that carries ORG Sales; every Configuration
category and its choices; the outcome of the check against the screen (rows and numbers matched, and the differences
left, if any, with their cause); the script saved; the notes corrected. Then the last line: `Left: 0` with a MATCH and
the corrections saved, else `Left: 1`.
