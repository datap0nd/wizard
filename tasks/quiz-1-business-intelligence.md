---
id: quiz-1-business-intelligence
title: Prepare the Business intelligence quiz on the Cases site
summary: Gemini reads the knowledge base, finds 25 technical points it is unsure of (data sources, reports, tables and columns, how a measure is calculated, filters, refresh times, which source to use) and publishes them as the quiz's Business intelligence section on the Cases site, where people answer anonymously. It changes no note.
added: 2026-11-12
---
The Cases site has a quiz where the people who know the company's data answer what the knowledge base is still unsure
of, without signing in. Prepare its **Business intelligence** section: 25 technical questions. A second task prepares
the Business section; together they are the quiz's 50 questions. This task changes no note: it only publishes the
questions, with `wizard_quiz_save`.

What counts as Business intelligence here: where a figure comes from and how it is read. Data sources, systems,
portal reports and dashboards; tables, views and columns, and what one row is; how a measure is calculated (what it
counts and leaves out, the formula, units, currency, rounding); filters and their defaults; time grain, fiscal weeks
and period labels (YTD, L4W...); refresh times and lags; which source to use when two give the same figure; how two
sources join. Concepts, terms, processes, organisation and strategy belong to the Business section: leave them out.

1. Read wizard_kb_standard, then go through the knowledge base with wizard_browse_knowledge (every area: metrics,
   datasets, dashboards, reporting conventions, glossary) and wizard_read_knowledge for the notes that matter. Use
   wizard_lookup_definitions for a measure or term that several notes name.
2. Collect what the notes are unsure of, in this order of value:
   - `UNKNOWN: ... (ask: <role>)` lines and `## Open questions` in metric, dataset and dashboard notes;
   - `## Conflicting information`, and two notes (or a note and a mapped portal report) that define or source the same
     measure differently;
   - a metric note whose `## Where to get it` is empty or UNKNOWN, a dataset or view whose columns are UNKNOWN, a
     calculation marked `(inferred)`;
   - drafts nobody checked (`DRAFT_UNSIGNED` with no `reviewed`) on the measures people ask about most.
   A SIGNED note is settled: do not ask about it.
3. Write 25 questions, the most useful first: those that unblock the most answers (a measure many notes use, a source
   Wizard reads often). One thing per question, in plain words that a data analyst at the company understands,
   ending with a question mark. For each:
   - `topic`: a short label (the measure, report or system), e.g. "Sell-out" or "Weekly sell-in dashboard";
   - `question`;
   - `now`: what the knowledge base says today and why it is unsure, in one or two sentences ("The note gives net and
     gross units and does not say which the weekly report uses.");
   - `choices`: when the plausible answers are known (two notes that disagree, the options a report shows), give
     them, 2 to 6, short. Leave it empty for an open question. People can always write their own answer;
   - `notes`: the ids of the notes the answer would settle.
4. Never put in a question what the standard keeps out of notes: performance figures (sales, share, spend, margins,
   prices, targets), people's names or contact details, passwords, tokens or addresses with credentials. Ask about a
   definition or a source, never about a figure's value. Do not ask what the notes already settle, and do not ask the
   same thing twice in other words.
5. Publish them: wizard_quiz_save with `section: "bi"`, a one-sentence `intro` (what the questions are about), and the
   25 questions. A refused save says why: fix it and save again. When the knowledge base holds fewer than 25 real
   doubts, publish the ones it has (at least 5) and say so; never invent a doubt to reach 25.

End with: how many questions you published, the notes they are about (ids), and the doubts you left out and why.
