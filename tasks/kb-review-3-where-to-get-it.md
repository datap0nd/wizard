---
id: kb-review-3-where-to-get-it
title: Knowledge review 3 of 7: check and correct every metric note's "Where to get it"
summary: Wizard follows a metric note's "Where to get it" to the table or portal report and its filters. A review found filter values that do not exist, no plan-version filter (a query adds up every version), drafts named instead of mapped reports, and notes with none. This checks every block against the database (no data rows read) and the portal maps, and corrects it. Replaces the earlier portal-reports task.
added: 2026-11-02
---
Every metric note (`type: metric`) ends with `## Where to get it` (knowledge standard, section 11): one block per
database object and one per mapped portal report that holds the measure, with the exact filters that select the right
rows. Wizard follows it on live questions, so a wrong value there gives a wrong answer. A review found filter values
that do not exist in the data, no filter on a plan or version column (a query then adds up every plan version and
double-counts), portal blocks that name an uncertain catalog draft instead of the mapped reports, mapped reports that
name the note as their definition but are missing from it, and metric notes with no such section at all. Check every
metric note and correct it.

1. Read wizard_kb_standard, sections 10 and 11.
2. wizard_browse_knowledge(area=metrics), and any note of `type: metric` elsewhere. Start with the notes most mapped
   reports name as their definition (wizard_read_knowledge shows a note's portal reports), then the rest.
3. For each note: read its file (wizard_kb_note_source) and the dataset notes it names, and find the other dataset
   notes that hold the measure (wizard_lookup_definitions with the measure's names and aliases).
4. Check each database block against the database with wizard_query_postgresql. Read metadata and value lists only,
   never measure values, sums or counts:
   - The object and every column exist with that exact spelling: the catalog tables (`pg_attribute` joined to
     `pg_class` for a materialized view, which `information_schema.columns` does not list).
   - Every filter value exists exactly: `SELECT DISTINCT <column> FROM <object> ORDER BY 1 LIMIT 100` on the category
     column (with a date or partition filter when the object is large). A value that does not exist is wrong: replace it
     with the value or values that select the rows the measure needs, as the dataset note explains them.
   - Versions: when the object holds several versions of the same number (plan or forecast versions, a current or
     previous plan flag, scenarios, snapshots, a data type such as actual, plan or annual), the block must name the
     filter that selects one version, and say why. The dataset note's columns and pitfalls, and the distinct values,
     show these columns. When no note says which value is the current one, write `UNKNOWN: which <column> value is the
     current version (ask: <role>)`; never pick one.
   - The unit and grain: the column for units and the one for value, and whether rows must be summed or already hold
     totals.
   - The example query: run it once with `LIMIT 0`, which proves that it parses and every name exists and returns no
     rows. Fix it until it does.
5. Check each portal block against the map (portal_map with report): keep a report only when its status is mapped or
   partial and its data really holds the measure, with the filters and values the map gives. Remove a block that names
   a report the map does not have, or has as failed, or that comes only from a catalog draft; say so in your summary.
   Add a block for every mapped report that holds the measure: search each portal's map with the measure's name and
   aliases (portal_map with find), and read the reports that name this note as their definition. Use the block format
   of section 11: portal and report id, name and menu path, what it answers (its use_for), filters with their values.
6. A metric note without the section gets one, built the same way. When no dataset note or mapped report holds the
   measure, write `UNKNOWN: no dataset note or mapped portal report holds <measure> yet (ask: <role>)`.
7. Order the blocks by the variant of the question each answers (weekly or monthly, units or value, actual or plan,
   company figures or an estimate), not by kind of source. After a value you checked in the database, write
   "(checked in the database on <date>)"; it has no source id.
8. Add the dataset note ids to the metric note's `related`. Change nothing else except `updated` (today). A SIGNED note
   is not changed: put the corrected section in your summary for its owner.
9. Save each note once it is checked, one or two per save: wizard_kb_save_notes, message "Where to get it checked
   against the database and the portal maps".

When the tool budget runs low, save what you have and stop: the next run continues with the notes not yet checked
(their `updated` is older).

End with, for each note: what was wrong and what you changed, the values left UNKNOWN with the question for the owner,
and the blocks removed and why. Then the notes left as they are and why, and the SIGNED notes with the section you
propose.
