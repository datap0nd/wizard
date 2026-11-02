---
id: kb-review-7-missing-metrics
title: Knowledge review 7: write metric notes for the measures the data holds
summary: The data holds many more measures than the knowledge base defines - whole families of dataset notes and mapped portal reports have no metric note, so Wizard has no definition to check them against. This writes a draft metric note for each measure people ask about, from the database definitions and the maps only, with UNKNOWN where they do not settle it.
added: 2026-11-02
repeat: until_done
---
When a question names a measure, Wizard looks up its definition (wizard_lookup_definitions) to name it correctly, avoid
summing what must not be summed and find where to read it. A review found far more dataset notes and mapped portal
reports than metric notes: many measures the data holds have no definition. Write a draft metric note for each measure
that people ask about and the data holds.

1. Read wizard_kb_standard: sections 3, 4, 10 and 11.
2. List the measures the data holds: wizard_browse_knowledge(area=datasets) and the dataset notes' columns, and each
   configured portal's map (portal_map: the mapped reports' use_for and definitions; a mapped report with no
   definition often holds an undefined measure), and the dashboard notes (wizard_browse_knowledge(area=dashboards)).
   Group the columns, reports and dashboards by the measure they hold.
3. Keep the measures no metric note defines: search for each with its names and acronyms (wizard_lookup_definitions,
   wizard_browse_knowledge(area=metrics)). A measure a glossary entry explains still needs a metric note. Rank them by
   how many dataset notes and mapped reports hold them, and take the first six or so this run.
4. For each, write `knowledge/metrics/<id>.md`, `type: metric`, `status: DRAFT_UNSIGNED`, `owner: TBD - <the role
   that owns this measure> (ask the user)`, following section 4:
   - Lead: what the measure is, its unit, and the one thing not to get wrong (for a rate: never sum it, recompute it
     from its parts).
   - `## How <measure> is calculated`: from the column definitions and SQL the dataset notes give, or the report's own
     definition in the map, or a dashboard note's `## Business logic` (the team's own definition, which wins over a
     column's when they differ: say so under `## Variants`): what is counted and what is not, the numerator and
     denominator of a rate, the unit and currency, the period. Cite the dataset notes' sources; mark what you concluded `(inferred)`.
   - `## Variants` when the sources compute it differently, saying which source computes which.
   - `## Where to get it`, built and checked as section 11 and "Knowledge review 3" say: database blocks checked
     with metadata and value lists only, each example query run once with `LIMIT 0`; portal blocks only for mapped or
     partial reports.
   - `## Questions this note answers` and `## Open questions`. Aliases with every name and acronym the dataset notes
     and maps use; 8 to 15 tags; `related` with the dataset notes; `sources` with their source ids.
5. Never invent a definition: what the database definitions, notes and maps do not settle is `UNKNOWN (ask: <role>)`.
   No performance figures, not even as an example.
6. Link back as section 11 says: add the new metric's id to each dataset note's `related` and its names to their
   `aliases` or `tags` (read each file with wizard_kb_note_source and save it whole). A SIGNED dataset note is not
   changed: list it.
7. Save each metric note with the dataset notes it changes: wizard_kb_save_notes, message "Metric notes for measures the
   data holds".

When the tool budget runs low, save what you have and stop: the next run continues with the measures left.

End with: the metric notes written, the measures still without one (ranked), the open questions for each owner, and the
SIGNED notes you would link.
