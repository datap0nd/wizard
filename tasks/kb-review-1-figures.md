---
id: kb-review-1-figures
title: Knowledge review 1 of 7: take performance figures out of the notes
summary: Some notes quote business figures copied from dashboards and decks (rates, unit counts, shares, multipliers), against rule 7 of the knowledge standard. Wizard repeats them as facts long after they go stale. This rewrites those passages to say what the source shows, without the numbers. Run it again until it finds none.
added: 2026-11-02
---
Rule 7 of the knowledge standard (section 4) says notes hold no performance figures: sales, units, revenue, spend,
share, attach and conversion rates, growth, margins, prices, multipliers, targets and forecasts come from the data
sources, where Wizard can cite and check them. A number copied into a note goes stale, contradicts the data, and Wizard
quotes it as a fact. A review found notes that break this rule, above all notes that describe dashboards and trackers
("key metrics", "snapshot", "highlights", "grounding" sections). Find every such figure and take it out.

1. Read wizard_kb_standard: section 4 (rules 4 and 7) and section 6.
2. wizard_browse_knowledge: every area. Go through every note, in this order: notes that describe a dashboard, tracker
   or report; metric notes; dataset notes; then the rest. Notes you cleaned in an earlier run have today's or a recent
   `updated` and no figures: check them last.
3. For each note, read its file with wizard_kb_note_source and find every performance figure: the value of a business
   measure for a period, market, product, partner or brand. That includes counts of units, devices, users or hosts;
   percentages and rates; shares and share changes; growth; multipliers and factors; amounts of money; ranks; targets;
   forecasts. Look in "Questions this note answers" too: a question that carries a figure or asks for one specific past
   period is a figure in disguise.
4. Rewrite the passage; do not just delete it. Say what the source shows instead of what it showed: the measure, its
   unit, how it is broken down (market, product, channel, period), its granularity and how often it is refreshed. For
   example "The dashboard shows the attach rate by market and month, as a percentage of units sold, next to the unit
   counts." A section that held only figures becomes "What <the dashboard's name> shows", listing measures and
   breakdowns. Rewrite a question in general words with placeholders ("What is our share in <market> by quarter?").
5. Keep what the standard allows: structural facts with their date (how many markets a source covers, the model
   line-up, when the fiscal year starts), value lists and date ranges that describe a dataset's coverage, units and
   currencies, and constants inside a definition's formula (x 100, per thousand). When you cannot tell whether a number
   is structural, keep it and list it in your summary.
6. Change nothing else in the note: every other section, its sources and its links stay. Set `updated` to today.
7. A note whose status is SIGNED is not changed: put the passages you would rewrite in your summary for its owner.
8. Save as you go, a few notes per save: wizard_kb_save_notes, message "Remove performance figures (standard rule 7)".
   A refused save says why: fix the note and save again.

When the tool budget runs low, save what you have and stop: the next run continues with the notes left.

End with: the notes changed; the numbers you kept and why (note id and the number's role); the notes in `datasets/`
that describe a dashboard or a report rather than a database object (they belong in another area, which needs a person
or a tool that can move a note); the SIGNED notes with the changes you propose; and the notes still to check, if any.
