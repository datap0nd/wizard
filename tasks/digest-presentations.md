---
id: digest-presentations
title: Digest a folder of presentations into the knowledge base
summary: You choose a folder of presentations (subfolders too). Wizard reads every one and adds what it teaches to the knowledge base - terms and acronyms, how measures are defined, processes, organisation, products, markets and standing decisions. It works in rounds until every file is done; Continue picks up where it stopped.
added: 2026-11-01
input: folder
input_label: The folder with the presentations
every_file: true
---
The company's presentations hold much of what people mean when they ask Wizard a question: the terms and acronyms
they use, how a measure is defined and calculated, how planning, approvals and launches work, who decides what, and
the standing rules behind the numbers. Read every file in the folder the person chose and add that knowledge to the
knowledge base, so Wizard answers with it.

At the start of each round:

1. Read wizard_kb_standard: every note you write follows it (front matter, areas, lead, sections, sources, status).
2. wizard_browse_knowledge: the areas and notes that exist, including the notes saved in earlier rounds.
3. wizard_task_files: the files left. Work through them in that order, one file at a time.

For each file:

1. Read it with wizard_task_read_file, all of it: a long deck part by part (`parts`, `next_offset`), speaker notes
   included. A slide that is only a picture says nothing you can use; do not guess what it shows.
2. Take what is lasting knowledge about how the business works, and where it belongs:
   - Terms: acronyms, jargon, the internal names of programmes, products, systems, reports and KPIs, each with its
     meaning as the deck uses it. Glossary notes in `glossary/`, one per domain (sales, supply chain, marketing,
     finance, products...), at most 60 entries each, sorted A to Z. A term that means different things in different
     decks goes in `glossary/ambiguous-terms` with the question to ask.
   - How a measure is defined or calculated: what counts and what does not, the formula, units, period and the source
     it comes from. Metric notes in `metrics/` (`type: metric`). Their `## Where to get it` names only the sources the
     deck or a dataset note names; the rest is UNKNOWN.
   - Processes and rhythms: planning and budgeting cycles, approval gates, launch steps, the reporting calendar, who
     decides what (by role). `processes/`.
   - Organisation: functions and teams and what each is responsible for, by role, never by person. `org/`.
   - Products (line-ups, families, naming, life cycle) in `products/`; markets, regions, channels and partners
     (described, not their figures) in `markets/`; strategy themes and priorities (dated, without targets) in
     `company/`; standing decisions and rules ("since 2026 share is measured from ...") in `decisions/`.
3. Leave out what the standard forbids: performance figures (sales, share, spend, margins, prices, targets, forecasts),
   people's names except as a note's owner, contact details, and anything marked confidential, restricted, HR or
   legal. Leave out what does not last: agendas, meeting logistics, action items with dates, one-off project status.
4. Before you write, find the note it belongs in: wizard_lookup_definitions with the term or topic and its other
   names, and wizard_browse_knowledge for the area. When a note exists, read its file (wizard_kb_note_source) and add
   to it: new glossary entries, a new section, a missing alias, the source id in `sources`, today's `updated`. Keep
   what it says. When the deck disagrees with it, give both under `## Conflicting information` with their source ids
   and add an open question. Write a new note only for a topic no note covers, with a lead, self-contained `##`
   sections, `## Questions this note answers` and `## Open questions`.
5. Cite every fact with the file's source id ([S-xxxxxxxx], from wizard_task_read_file) and add the id to the note's
   `sources`. Date what changes ("As of the March 2026 planning deck, ..."). Mark what you concluded rather than read
   `(inferred)`. Notes are in English; a term in another language keeps its original in `aliases`.
6. A note whose status is SIGNED is never changed: put what you would add in your summary for its owner.

Save as you go, every two or three files: wizard_kb_save_notes with the notes you added or changed, message "Digest
presentations: <topics>". A refused save says why: fix the note and save again. Then mark those files done with
wizard_task_files_done and a short note of what was taken (for example "glossary/sales-terms +4; processes/launch-gates").
Mark a file with nothing to keep done too, with why: only pictures, an agenda, unreadable, or a copy of another file.
When several files are versions of one deck (v1, v2, final, the same title and outline), read the newest and mark
the older ones done with "older version of <id>".

End each round with: the files done this round, the notes added or changed (ids), questions worth asking an expert,
the SIGNED notes with the changes you propose, and the files that could not be read.
