---
id: kb-review-2-sources-not-rules
title: Knowledge review 2 of 7: describe each source instead of ordering them
summary: Some notes set a "mandatory" order or tiers for checking sources, tell Wizard which tool to use first, or send it to places it cannot read. That contradicts how Wizard works (it decides which sources to use, and looks in the portal maps first). This rewrites them as descriptions of what each source holds and is good for.
added: 2026-11-02
---
Wizard decides for itself which sources to consult; its instructions say to look in the portal maps first, and the
knowledge standard says a note describes what the data can answer and how to reach it, never how an answer must be
built (end of section 11). A review found notes that work against this: a "retrieval order" or tier list that must be
followed, instructions addressed to Wizard ("always check X first", "use tool Y"), platform notes that say to find a
portal's reports with the report-catalog search tools, which only search Wizard's catalog and not the portal, and
sources named as the first place to look that no Wizard tool can open (files on a shared drive or in a PC's folder,
HTML dashboards, desktop applications). Rewrite them as descriptions.

1. Read wizard_kb_standard (sections 4, 6 and 11).
2. Find the notes. wizard_lookup_definitions with words such as mandatory, hierarchy, tier, priority, order, first,
   fallback, retrieval, escalate, always, never; then wizard_browse_knowledge and read every platform note and every
   top-level note. Read each candidate's file with wizard_kb_note_source.
3. Learn what Wizard can really read before you describe it: portal_guide and portal_map for each configured portal,
   wizard_list_sources, and the dataset notes for the database. A source is reachable by Wizard only when one of these
   shows it.
4. Rewrite each passage as a description, one short block per source: what it holds (measures, grain, markets,
   periods), how fresh it is and how it is refreshed, what it is good for and what not, what a reader must know to use
   it correctly (filters, versions, units), and how it is reached: by Wizard (the database, with the dataset note ids;
   a portal, with the portal and report ids from its map) or only by a person. Say the second plainly: "Wizard cannot
   open these dashboards; a person can, from the team's shared drive." Where sources overlap, say which answers which
   variant of a question (weekly or monthly, actual or plan, company figures or an estimate), as section 11 does.
5. Remove the rule words: mandatory, tier 1/2/3, must check first, fallback, and every instruction addressed to Wizard,
   the agent, the assistant or Gemini. Name a source by its system and its dataset or report id, never by a drive
   letter, a network share path, a server address or a folder on a PC.
6. A note that existed only to set the order keeps its id (other notes link to it): rewrite it in place as "<topic>:
   what each source holds and when it fits", with a new title, summary, tags and "Questions this note answers".
7. In a platform note, replace navigation with the report-catalog tools by what portal_guide and the portal map say
   about how Wizard reads that portal; keep the platform's facts.
8. Do not touch metric notes' `## Where to get it` (task "Knowledge review 3 of 7" checks them). Change nothing else;
   set `updated` to today. A SIGNED note is not changed: put your proposal in the summary for its owner.
9. Save with wizard_kb_save_notes, a few notes per save, message "Describe sources instead of ordering them".

End with: the notes changed and what each now says in one line; the sources only a person can open (for the owner: Wizard
cannot see them, so if they matter, Wizard needs a tool or the data in a source it reads); the SIGNED notes with the
changes you propose.
