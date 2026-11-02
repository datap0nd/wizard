---
id: kb-review-4-link-datasets
title: Knowledge review 4: link the dataset notes to the metrics they hold
summary: Almost no dataset note links to anything, so Wizard finds a table only when a question happens to use its own words. This does the backlink step of the knowledge standard - each dataset note names the metrics it holds, their business names and the questions it answers. Run it after review 3.
added: 2026-11-02
repeat: until_done
---
Section 11 of the knowledge standard ends with a step that was never done: point the data back at the metric. A
dataset note should list in `related` the metric notes whose `## Where to get it` names it, and carry the measure's
business names, so a search for "sell-in" or an acronym finds the table and not only its technical name. A review found
almost every dataset note with an empty `related`. Link them. Run this after "Knowledge review 3", which corrects
the metric notes this task reads.

1. Read wizard_kb_standard, sections 3, 10 and 11.
2. wizard_browse_knowledge(area=metrics): for each metric note, read its `## Where to get it` (wizard_read_knowledge)
   and note which dataset notes it names. That gives, per dataset note, the metrics it holds.
3. For each dataset note (wizard_browse_knowledge(area=datasets)), read its file (wizard_kb_note_source) and add:
   - to `related`: the ids of the metric notes that name it, and the dataset notes it is built from or feeds, when its
     `## Where the data comes from` names them;
   - to `aliases`: the business names and acronyms of the measures it holds that it does not have yet (the metric
     notes' titles and aliases); keep `tags` at 8 to 15 words, adding a measure's name there only when there is room;
   - to `## Questions this note answers`: one question per metric it holds, in the words an executive uses ("sell-in
     by market last week"), keeping 3 to 6 questions in all.
4. A dataset note that no metric note names: read its columns. When it clearly holds a measure a metric note defines,
   link it the same way and list the pair in your summary (that metric's "Where to get it" should name it: run review
   3 again). When it holds a measure no metric note defines, list it for "Knowledge review 7".
5. Skip a note in `datasets/` that still describes a dashboard, not a database object, and list it (review 0 moves it).
6. Change nothing else; set `updated` to today. Every id you add to `related` must exist. A SIGNED note is not changed:
   put the links you would add in your summary for its owner.
7. Save as you go, five or so notes per save: wizard_kb_save_notes, message "Link dataset notes to the metrics they
   hold".

When the tool budget runs low, save what you have and stop: the next run continues with the dataset notes whose
`related` is still empty.

End with: how many dataset notes you linked, the pairs to add to a metric's "Where to get it", the measures with no
metric note, the notes skipped and why, and the SIGNED notes with the links you propose.
