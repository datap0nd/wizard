---
id: kb-review-8-route-reports
title: Knowledge review 8: link every mapped portal report to the right notes
summary: Mapped portal reports are linked to the knowledge base through the notes they name as their definition, and the Brain page now draws those links. Many reports name no note, or one broad note for very different measures. This links each mapped report to the metric and dashboard notes it really holds, now that those notes exist. Run it after reviews 0 to 7.
added: 2026-11-02
repeat: until_done
---
A mapped portal report says what it is for in its map: `use_for` (the questions it answers), `not_for` (near misses and
the report to use instead) and `definitions` (the knowledge notes that define its measures). Wizard finds the right
report through them, and the Brain page draws a report's `definitions` as its links to the knowledge base. Many mapped
reports name no note yet, or name one broad note for measures that now have notes of their own (reviews 0 and 7 wrote
metric and dashboard notes). Link every mapped report to the notes it really holds.

1. wizard_browse_knowledge(area=metrics) and (area=dashboards): the notes a report can name, with what each defines.
2. For each configured portal with a map (portal_guide lists them): portal_map(system=..., todo=true) shows the reports
   still to route; then go through the mapped and partial reports (portal_map with find, by business area) and take
   the ones whose `definitions` are empty, name a note that does not exist, or name one broad note where a narrower one
   now fits.
3. Read each candidate in full (portal_map with report): its name, menu path, filters and data. Name in `definitions`
   only the notes whose measure the report's data really holds (at most 8), the narrowest that fits. Keep the report's
   `use_for` and `not_for` as they are unless they are wrong or empty; when you change them, follow the mapping rules
   (2 to 5 short phrases in the words people use; a near miss names the report to use instead).
4. Save with portal_map_route, a batch at a time. It replaces a report's `use_for`, `not_for` and `definitions`
   together, so always send all three, carrying over what you keep. Never use portal_map_save for this: routing changes
   nothing else in the map.
5. A report whose measure no note defines: leave `definitions` empty, add a `routing_note` naming the measure, and list
   it in your summary (it needs a metric note: review 7).
6. Change no knowledge note in this task.

When the tool budget runs low, stop after a saved batch: the next run continues with the reports left.

End with: per portal, how many reports you linked and to which notes (counts per note), the reports whose measure has
no note yet (the measures, for review 7), and the reports you could not judge from the map.
