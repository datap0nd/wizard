---
id: nerp-map-views
title: "Map NERP's views: what a row is, every column, and the filters a huge view needs"
summary: NERP is a few very large views on their own server. A question that does not know what a row is, what a column means or which filter keeps a query fast reads the wrong column or runs out of time. This writes one dataset note per view (grain, every column with its meaning and values, date range, the filters every query needs, example queries). Runs until every view has a note.
added: 2026-11-03
repeat: until_done
max_runs: 10
---
NERP is a few SQL views on a server of their own: one database, one schema, views only. You read them with
nerp_list_views (the views, and `unmapped`: the ones no note documents yet), nerp_view_columns (a view's columns) and
nerp_query (one SELECT that names only NERP's views). Some views are very large: a query with no filter on a date or
period column can run for a minute and be stopped. Write one dataset note per view, to section 10 of the knowledge
standard, so a later question goes straight to the right columns and filters in one query.

1. Read wizard_kb_standard: sections 1, 3, 4 and 10. Then nerp_list_views. If it says NERP is not connected, stop and
   say: set it in Settings → NERP, then run this task again.
2. Work through `unmapped` one view at a time, in the order nerp_list_views gives. Earlier runs' notes are in the
   knowledge base; a view with a note is done.
3. For each view:
   a. nerp_view_columns: every column and its type.
   b. Its size and its time column, carefully. Find the date or period columns (date and timestamp types; names such
      as day, date, posting, period, month, week, year). Query one recent slice first, with LIMIT: one day, or one week
      if days are sparse. Then the range it covers (min and max of that column), only if that query finishes within the
      time limit; if it is stopped, say so. Record roughly how many rows one day and one month hold (count(*) over one
      recent day), and how long each query took (elapsed_ms): that is the basis for the filter every query needs.
   c. What one row is: test candidate keys on one recent day, e.g.
      `SELECT count(*), count(DISTINCT (company_code, document, line)) FROM <view> WHERE <time column> = <a recent day>`.
   d. Every column's meaning. For text columns with few values (codes, companies, markets, cost centres, channels,
      currencies, statuses), their values over one recent month (`SELECT <column> FROM <view> WHERE <time filter>
      GROUP BY 1 ORDER BY count(*) DESC LIMIT 100`), listed in the note without counts. For numbers: the unit and
      currency (look for a currency column), whether credits are negative, and whether rows are amounts to sum or
      balances (summing a balance counts it many times). A column whose meaning neither its name, its values nor a note
      shows is `UNKNOWN (ask: <role>)`.
   e. What the knowledge base already says: wizard_lookup_definitions with the view's business words. Put the metric
      notes it holds in `related`.
   f. One or two example queries for the questions the view answers most often, with the time filter, spelled exactly
      as the database spells the names, proved with `LIMIT 0` (nerp_query), never run for their figures.
   g. The note: `knowledge/datasets/nerp-<schema>-<view>.md` (the id in kebab-case), `type: dataset`,
      `status: DRAFT_UNSIGNED`, `owner: TBD - <the team that owns NERP> (ask the user)`, title
      `<schema>.<view>: <what it holds, in words>`, `aliases`: `<schema>.<view>`, the bare view name and the business
      words for what it holds. Lead with NERP, the database and the exact name, what one row is, what it covers and how
      fresh it is. The sections of section 10, with `## Pitfalls` saying first the filter every query needs and why
      (rows per day, how long a query without it takes). Mark what you read in NERP `(checked in NERP on <date>)`.
   h. Save it with wizard_kb_save_notes, one or two views per save, message "Map NERP's views".
4. No sums, totals or business figures in a note, not even as an example: value lists, date ranges, row counts per day
   and timings are fine (they describe coverage and cost).
5. A view that no query can read within the time limit, even for one day: write its note from its columns, and say so
   under `## Pitfalls`.
6. A SIGNED note is not changed: put your proposal in the summary.

When the tool budget runs low, save what you have and stop: the next run continues with the views left.

End with: the notes written, the views that could not be read and why, the columns marked UNKNOWN (questions for
NERP's owners), and then the last line: `Left: <number of NERP views without a note>`.
