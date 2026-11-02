---
id: kb-review-6-notes-to-standard
title: Knowledge review 6 of 7: bring old notes up to the standard and remove PC-specific details
summary: The first notes were written before the knowledge standard - bold paragraphs instead of sections, no lead, no aliases, no questions - so search cannot return one part of them. Some notes carry one PC's details (server addresses, drive letters, share and folder paths, local scripts), mix owner formats or run past 600 words. This restructures and cleans them without adding or losing a fact.
added: 2026-11-02
---
Search returns a note's lead and its matching `##` sections, so a note written as bold paragraphs comes back whole or
not at all. A review found the first notes (top-level notes, platform notes and the first metric notes) still in that
older format, with no lead, no aliases, no "Questions this note answers", no `updated` date and no inline citations. It
also found details that only make sense on one PC, owner fields in two formats or naming several owners (only one
owner signs), and notes over the 600-word guideline. Fix the format and the hygiene; keep every fact.

1. Read wizard_kb_standard, sections 2 to 7.
2. wizard_browse_knowledge: every area. Read the files (wizard_kb_note_source) of the top-level notes, the platform
   notes and the metric notes first, then the rest, and take each note with one of these problems:
   - Format: no lead; bold paragraphs or a single block instead of `##` sections; no `## Questions this note
     answers`; no `## Open questions`; no `aliases`; no `updated`; fewer than 8 tags; no summary.
   - PC-specific details: server addresses (IP addresses, host names with ports), drive letters, network share paths,
     paths into a PC's folders (user folders, an `inbox` folder and its `manifest.csv`), and the names of local
     scripts and batch files.
   - Owner: more than one owner, or not in the standard's form.
   - Length: over about 600 words (a dataset note may be longer because of its column table; a glossary note is
     limited to 60 entries instead).
3. Restructure to section 4: a lead of 2 to 4 sentences that makes sense alone; `##` sections whose headings name
   their subject and whose first sentence names it again; `## Questions this note answers` (3 to 6, in executives'
   words); `## Open questions` with the `UNKNOWN` items; `aliases` with every acronym and other name the note uses;
   8 to 15 tags; a summary of at most 200 characters. Move every fact into its section with the source ids it already
   has. Do not add a fact; what the note does not settle becomes an open question. Leave a metric note's `## Where to
   get it` and a note's source order as they are (reviews 2 and 3 handle those).
4. PC-specific details: replace each with what a reader on any PC can use: the system's name and what it is, the
   team's shared drive, how to get access (by role). Wizard's own settings hold the addresses it needs, never a note.
5. Owner: exactly one, written `<Name>, <role>` when the note names a person as its owner, otherwise `TBD - <role or
   team> (ask the user)`. When a note names several, keep the one whose role fits the note's topic best and list the
   others in your summary for the owner to settle.
6. Too long: split it into notes of one topic each, at most about 600 words. The original keeps its id (other notes
   link to it), its lead and the part asked about most, and lists the new notes in `related`; each new note gets a new
   kebab-case id, the same owner, `status: DRAFT_UNSIGNED`, the source ids that support its content, and the full
   front matter.
7. A sentence followed by a long run of source ids (more than about five): leave it, and list the note in your summary.
   Which source supports which claim can be decided only with the sources themselves, on the owner's PC.
8. Set `updated` to today on every note you change. A SIGNED note is not changed: put your proposal in the summary for
   its owner.
9. Save as you go, a few notes per save: wizard_kb_save_notes, message "Bring notes up to the knowledge standard".

When the tool budget runs low, save what you have and stop: the next run continues with the notes that still have one
of these problems.

End with: the notes restructured, the notes split (old id and new ids), the PC-specific details removed (note id and
kind, not the value), the owners to settle, the notes with long citation runs, and the SIGNED notes with the changes
you propose.
