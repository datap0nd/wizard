---
id: kb-review-2-sources-not-rules
title: Knowledge review 2: describe each source instead of ordering them
summary: The order Wizard starts in now lives in Settings → Source order, with a test for when a source is enough. Notes that still set a "mandatory" order or tiers, tell Wizard which tool to use first, carry access rules or point at one PC's drive would contradict it. This rewrites them as descriptions of what each source holds, covers and is good for.
added: 2026-11-02
repeat: until_done
---
Where Wizard starts and when it goes further is now set by the owner in Settings → Source order (Dashboards, the
database, the portals, the Big Data Portal...), together with a test for when a source is enough: it covers the
measure, every breakdown asked for, the period, the markets and the granularity. Which schemas the database tool may
read is a setting too, enforced by the tool. A knowledge note that sets its own order no longer helps: it can disagree
with the setting, and Wizard only sees it when a search returns it. What Wizard needs from the notes is what each source
holds and covers, so it can judge whether a source is enough. A review found notes that work against this: a
"retrieval hierarchy" or tier list that must be followed, instructions addressed to Wizard ("always check X first",
"answer with no SQL"), rules about which schema may be read, platform notes that say to find a portal's reports with
the report-catalog search tools, and sources named by a drive letter or a folder on one PC. Rewrite them as
descriptions.

1. Read wizard_kb_standard (sections 4, 6, 11 and 13).
2. Find the notes. wizard_lookup_definitions with words such as mandatory, hierarchy, tier, priority, order, first,
   fallback, retrieval, escalate, always, never, forbidden, allowed; then wizard_browse_knowledge and read every
   platform note and every top-level note. Read each candidate's file with wizard_kb_note_source.
3. Learn what Wizard can really read before you describe it: wizard_list_sources (it lists the sources in the owner's
   order, with their status), wizard_dashboards and the notes in `dashboards/`, portal_guide and portal_map for each
   configured portal, and the dataset notes for the database.
4. Rewrite each passage as a description, one short block per source: what it holds (measures), what it covers
   (breakdowns, markets, periods, granularity: "monthly only", "by age band, not by gender"), how fresh it is and how
   it is refreshed, what it is good for and what not, what a reader must know to use it correctly (filters, versions,
   units), and how it is reached (Dashboards with the dashboard note ids; the database with the dataset note ids; a
   portal with the portal and report ids from its map). Where sources overlap, say which answers which variant of a
   question (weekly or monthly, actual or plan, a headline figure with the team's logic or a finer breakdown), as
   section 11 does.
5. Remove the rule words and the rules: mandatory, tier 1/2/3, must check first, fallback, "answer with no SQL", every
   instruction addressed to Wizard, the agent, the assistant or Gemini, and every rule about which schema or table may
   be read (the database tool enforces that from Settings; "the reporting schema holds the views people use" is fine
   as a description). Write one line where the order used to be: "The order Wizard starts in is set in Settings →
   Source order." Name a source by its system and its note or report id, never by a drive letter, a network share
   path, a server address or a folder on a PC.
6. A note that existed only to set the order keeps its id (other notes link to it): rewrite it in place as "<topic>:
   what each source holds and covers", with a new title, summary, tags and "Questions this note answers". List in your
   summary the order it used to set, so the owner can compare it with Settings → Source order.
7. In a platform note, replace navigation with the report-catalog tools by what portal_guide and the portal map say
   about how Wizard reads that portal; keep the platform's facts.
8. Do not touch metric notes' `## Where to get it` (review 3 checks them). Change nothing else; set `updated` to today.
   A SIGNED note is not changed: put your proposal in the summary for its owner.
9. Save with wizard_kb_save_notes, a few notes per save, message "Describe sources instead of ordering them".

End with: the notes changed and what each now says in one line; the orders and access rules the notes used to state,
for the owner to check against Settings → Source order and the schema setting; the SIGNED notes with the changes you
propose.
