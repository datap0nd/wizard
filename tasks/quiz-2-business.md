---
id: quiz-2-business
title: Prepare the Business quiz on the Cases site
summary: Gemini reads the knowledge base, finds 25 points about concepts, terms and acronyms, processes, organisation and strategy that it is unsure of, and publishes them as the quiz's Business section on the Cases site, where people answer anonymously. It changes no note.
added: 2026-11-12
---
The Cases site has a quiz where the people who know the business answer what the knowledge base is still unsure of,
without signing in. Prepare its **Business** section: 25 questions about concepts, terms and strategy. A first task
prepares the Business intelligence section (the technical questions); together they are the quiz's 50 questions. This
task changes no note: it only publishes the questions, with `wizard_quiz_save`.

What counts as Business here: what people mean and how the company works. Terms, acronyms and internal names
(programmes, products, channels, partner types); terms that mean different things to different teams; concepts such
as what counts as a switcher, a launch or an active partner; processes and rhythms (planning cycles, approval gates,
launch steps, the reporting calendar) and who decides what, by role; organisation (functions and what each owns);
products, markets, regions and channels as described; strategy themes and standing decisions. Data sources, reports,
columns and calculations belong to the Business intelligence section: leave them out.

1. Read wizard_kb_standard, then go through the knowledge base with wizard_browse_knowledge (glossary, concepts,
   processes, org, products, markets, company, decisions) and wizard_read_knowledge for the notes that matter. Start
   with `glossary/ambiguous-terms` when it exists. Use wizard_lookup_definitions for a term several notes use.
2. Collect what the notes are unsure of, in this order of value:
   - entries in `glossary/ambiguous-terms` and terms whose meaning is `UNKNOWN` (an acronym without its expansion);
   - `UNKNOWN: ... (ask: <role>)` lines and `## Open questions` in concept, process, organisation and strategy notes;
   - `## Conflicting information`, and two notes that describe the same term, step or responsibility differently;
   - what is marked `(inferred)`, and drafts nobody checked (`DRAFT_UNSIGNED` with no `reviewed`) on the topics people
     ask about most.
   A SIGNED note is settled: do not ask about it.
3. Write 25 questions, the most useful first: those that settle a term or concept many notes and questions use. One
   thing per question, in plain words anyone in the business understands, ending with a question mark. For each:
   - `topic`: a short label (the term, process or theme), e.g. "Switchers" or "Launch gates";
   - `question`;
   - `now`: what the knowledge base says today and why it is unsure, in one or two sentences ("Two decks use 'active
     partner' for partners with a sale in 4 weeks and in 13 weeks.");
   - `choices`: when the plausible answers are known (the meanings two notes give, the options a process has), give
     them, 2 to 6, short. Leave it empty for an open question. People can always write their own answer;
   - `notes`: the ids of the notes the answer would settle.
4. Never put in a question what the standard keeps out of notes: performance figures (sales, share, spend, margins,
   prices, targets, forecasts), people's names or contact details, anything marked confidential, restricted, HR or
   legal, passwords or tokens. Ask who decides by role, never by name. Do not ask what the notes already settle, and do
   not ask the same thing twice in other words.
5. Publish them: wizard_quiz_save with `section: "business"`, a one-sentence `intro` (what the questions are about),
   and the 25 questions. A refused save says why: fix it and save again. When the knowledge base holds fewer than 25
   real doubts, publish the ones it has (at least 5) and say so; never invent a doubt to reach 25.

End with: how many questions you published, the notes they are about (ids), and the doubts you left out and why.
