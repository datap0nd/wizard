---
id: kb-review-5-example-queries
title: Knowledge review 5: add an example query to every dataset note
summary: Gemini writes its SQL from the dataset notes, and most of them have no example query, which the knowledge standard requires. This writes one or two short queries per note with the exact column names and filters, proves each parses against the database (no rows read), and adds any missing filter to the note's pitfalls. It takes two or three runs.
added: 2026-11-02
repeat: until_done
---
Gemini queries the database with SQL it writes from the dataset notes, so section 10 of the knowledge standard requires
`## Example query` in every dataset note: one or two short SELECTs for the questions the object answers most often,
with the column names exactly as the database spells them and the filters a correct query needs. A review found most
dataset notes without one. Add them.

1. Read wizard_kb_standard, section 10.
2. wizard_browse_knowledge(area=datasets). Take the notes without `## Example query`, starting with the ones metric
   notes name in `## Where to get it` (their `related` lists those metrics once review 4 has run).
3. For each note, read its file (wizard_kb_note_source), its `## Columns`, `## Pitfalls` and `## Questions this note
   answers`, and the metric notes that name it.
4. Check the object in the database with wizard_query_postgresql, metadata only: its columns and types from the
   catalog tables (`pg_attribute` joined to `pg_class` for a materialized view), and the values of the category
   columns your filters use (`SELECT DISTINCT <column> FROM <object> ORDER BY 1 LIMIT 100`). Never read measure
   values, sums or counts, and never write a result into a note.
5. Write one or two queries for the questions the note answers most often: grouped by period and market where the
   object has them, with the filters a correct query needs (version or plan, actual or plan, units or value, currency),
   column names double-quoted when they have capitals, spaces or symbols, and every filter value exactly as the
   database holds it. Run each once with `LIMIT 0` (it parses, every name exists, no rows come back) and fix it until
   it does. The note shows the query without `LIMIT 0`.
6. When the query needs a filter that `## Pitfalls` does not mention (several plan versions, a mix of actual and plan,
   duplicated rows across snapshots), add one line to `## Pitfalls` saying so. When a column in `## Columns` does not
   exist in the database, or the database has a column the note lacks, do not rewrite the table: list it in your
   summary.
7. Put `## Example query` before `## Questions this note answers`. Change nothing else; set `updated` to today. Skip a
   note in `datasets/` that describes a dashboard or a report, not a database object. A SIGNED note is not changed: put
   the query in your summary for its owner.
8. Save as you go, a few notes per save: wizard_kb_save_notes, message "Example queries for dataset notes".

When the tool budget runs low, save what you have and stop: the next run continues with the notes still without an
example query.

End with: the notes given a query, the pitfalls added, the column differences between a note and the database, the
notes skipped and why, the notes still to do, and the SIGNED notes with the queries you propose.
