---
id: where-to-get-it-portal-reports
title: Add mapped portal reports to the metric notes' "Where to get it"
summary: Business definitions say where their data is, but until now named only database tables. This adds the mapped portal reports that hold the same measure.
added: 2026-10-31
---
Every metric note (`type: metric`, mostly in the metrics area) ends with a `## Where to get it` section. Until now that
section could name only database objects, so Wizard went to the database first even when a mapped portal report answers
the question better. Section 11 of the knowledge standard (wizard_kb_standard) now treats database objects and mapped portal
reports as equal sources. Bring every metric note up to it.

For each metric note (wizard_browse_knowledge shows them):

1. Read its file with wizard_kb_note_source.
2. Find the mapped portal reports that hold its measure. Search each configured portal's map with the measure's name
   and aliases (portal_map with find), and look at the note's portal_reports (wizard_read_knowledge): those reports
   already name this note. Read each candidate in full (portal_map with report) and keep only the ones whose data really
   holds the measure.
3. In `## Where to get it`, keep every database block exactly as it is and add one short block per kept report: the
   portal and report id (for example `gscm:as470`), its name and menu path, what it answers (its use_for), and the
   filters that select the right rows with their values. No query: Wizard reads a mapped report through the map.
4. When a database object and a portal report answer different variants of the question (company sell-in or an
   analyst's shipment estimate, weekly or monthly, actual or plan), say which answers which, and order the blocks by
   that, not by kind of source.
5. Change nothing else in the note except its `updated` date (today). A note whose status is SIGNED is not changed:
   put the blocks you would add in your summary for its owner instead.
6. Save the changed notes with wizard_kb_save_notes, a few per save, with the message "Where to get it names mapped portal
   reports".

If this PC has no portal map, or no mapped report holds a note's measure, leave that note as it is. End with the notes
you changed, the notes left as they are and why, and the SIGNED notes with the blocks you propose.
