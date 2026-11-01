---
id: presentation-guide
title: Write the company's presentation guide from its decks
summary: You choose a folder of the company's presentations, or one deck or template. Wizard reads how they look and how they are built - template, colors, fonts, layouts, logo and labels, slide types, charts, wording - and writes the presentation guide in the knowledge base, so presentations Wizard makes follow the company's way.
added: 2026-11-01
input: folder or file
input_label: The folder with the presentations, or one deck or template (.potx)
---
Write the company's presentation guide: notes in the knowledge base that say how a presentation is made here, precisely
enough that someone who has never seen one, or Wizard, can build a deck that looks and reads like the company's own.
Wizard follows these notes when it makes or plans a presentation, so write them as instructions it can follow, with
exact values.

1. Read wizard_kb_standard, section 12 first: it names the notes and what each holds. Then look for an earlier guide
   (wizard_browse_knowledge, area `presentations`): when its notes exist, read their files (wizard_kb_note_source) and
   improve them with what these decks show, rather than starting over.
2. Choose the decks with wizard_task_files(left=false). When the person chose one file, it is the reference. With a
   folder, take every template (.potx, .pot, and files whose name says template, master or guideline), which define
   the standard, then up to 40 other presentations: the newest first, spread over the subfolders (teams, years, kinds
   of deck), never several versions of the same deck.
3. Read how they look with wizard_task_design, 4 decks a call, until every chosen deck is read. `all_read_so_far.shared`
   counts, once per deck, what the decks share. What most decks share is the standard; what one team or one template
   uses is a variant: name it as such. A one-off is not the standard. When the decks use more than one template, say
   which one is current (the newest decks, the templates folder) and when the others are used.
4. Read how they are built with wizard_task_read_file, 8 to 12 representative decks (a few of each kind: business
   review, strategy or plan, project update, proposal): the storyline from the cover to the appendix, how titles are
   phrased (a full-sentence message or a topic, how long), how much is on a slide, how charts and tables are labelled
   (units, periods, sources, footnotes), how numbers, dates and fiscal periods are written, the closing slides, the
   language and tone.
5. Write the notes in `knowledge/presentations/`, `type: guide`, `status: DRAFT_UNSIGNED`, `owner: TBD - the team that
   owns presentation standards (ask the user)`, each following the standard (lead, self-contained `##` sections,
   `## Questions this note answers`, `## Open questions`), each under about 600 words, tables welcome:
   - `presentation-standard`: the lead says which template to use and what makes a deck look like the company's; then
     the decisions a deck maker takes, in order (template and slide size, storyline, slide types, look, charts and
     tables, wording) and a final checklist. Its `related` lists the four notes below.
   - `presentation-look`: slide size and aspect; the template or theme name; the palette as a table (hex value, theme
     slot, what it is used for: titles, text, highlights, chart series in order, backgrounds), only colors the decks
     really use; the fonts (Latin and East Asian, for titles and body) with point sizes for the title, subtitle, each
     body level, footnotes and chart labels; the logo (where, how big), the confidentiality label (its exact text,
     where), page number, footer and date; margins; and what is never done (fonts, colors or effects no deck uses).
   - `presentation-slide-types`: each slide type the decks use (cover, agenda, executive summary, section divider,
     content with a chart, content with a table, comparison, timeline or roadmap, key message, closing, appendix): its
     layout name in the template, what goes on it in what order, and how much text (the decks' words per slide).
   - `presentation-charts-and-tables`: which chart types are used for which message (from the counts), series colors in
     order, labels and legends, where units and periods go, how the source line reads and where it sits, table style
     (header, font size, alignment of numbers, totals), number formats (separators, decimals, %, currencies, K/M/B).
   - `presentation-writing`: how titles and bullets are written, how numbers, dates, periods, currencies and units are
     written, abbreviations used without spelling them out, the storyline the decks follow, language and tone.
6. Name a value only when the decks show it, and cite the decks it comes from by source id (wizard_task_design and
   wizard_task_read_file return each file's `source_id`). What the decks do not settle is UNKNOWN with an open
   question. Examples use placeholders you write ("<market> sell-out grew <x>% in
   <period>"), never a deck's figures, names or plans: the guide describes the form, not the content.
7. A note whose status is SIGNED is never changed: put the change you propose in your summary for its owner.
8. Save the notes with wizard_kb_save_notes, message "Presentation guide from the company's decks". A refused save
   says why: fix it and save again.

End with: how many decks and which templates you read, the notes you wrote or changed, the standard in five lines
(template, colors, fonts, logo and label, title style), the variants you found, and the open questions for the guide's
owner.
