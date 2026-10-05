# Task 30 — Expert quizzes

**Goal:** one quiz per area and stakeholder: 10 to 15 questions that take about ten minutes, sent by email as a single
HTML page the stakeholder opens in their browser, answers, saves and sends back.
**Output:** `documents\quiz-questions\<area>\<quiz id>.html` and `<quiz id>.email.txt`; a row per quiz in
`content\register\quiz-log.md` (internal) · **Shareable:** counts only.
**Model:** the strongest your plan lists under `/model`.

## Steps

1. Read `content\register\stakeholders.md` and `content\register\topic-map.md`. Ask the user which areas and
   stakeholders to quiz now (suggest priority 1 areas first), the reply-by date, and the name to sign with.
2. For each (area, stakeholder), collect candidate questions from that area's notes, in this order:
   1. "Open questions" and `UNKNOWN` items;
   2. statements marked `(inferred)`;
   3. "Conflicting information";
   4. entries of `glossary\ambiguous-terms.md` that belong to the area (which meaning is right here?);
   5. key facts Wizard relies on (definitions, owners, calendars, how a figure is computed), to confirm.
   Keep the 10 to 15 with the most impact on executives' answers. Never repeat a question this person already received
   (see the quiz log).
3. Write each question:
   - one fact per question, neutral wording, no leading;
   - `confirm` to check a statement: quote the note's statement, shortened if needed;
   - `choice` (one answer) or `multi` (several) when the sources suggest the possible answers; options come from the
     sources or are plain alternatives, never invented facts ("Other" and "Don't know" are added automatically);
   - `text` only when the answer cannot be listed, such as what an acronym stands for;
   - `"comment": true` where nuance is likely; a short `why` saying how Wizard uses the answer;
   - `topic` is the note id, `topic_title` the note title. No figures from data sources, no third parties' names, no
     email addresses.
4. Copy `templates\quiz-template.html` to `documents\quiz-questions\<area>\<quiz id>.html`, where the quiz id is
   `<area>__<stakeholder name in lowercase with dashes>` (for example `finance__ana-silva`). In the copy, replace only
   the JSON inside `<script type="application/json" id="quiz-data">`; the format is in the comment at the top of the
   template. Change nothing else.
5. `.\docs.ps1 quiz-check documents\quiz-questions\<area>\<quiz id>.html` and fix every error.
6. Write `<quiz id>.email.txt` next to it: a subject and a short email the user sends themselves. Say what it is for
   (Wizard, the internal assistant, should answer executives correctly about their area), that it takes about N
   minutes, and how: open the attached file in Edge or Chrome, answer ("Don't know" is fine), click "Save my answers",
   and reply with the saved file attached. Add the reply-by date and a thank-you. Never send email yourself.
7. Add a row to `content\register\quiz-log.md`: quiz id, stakeholder, area, number of questions, notes covered,
   created, sent, answered, applied.
8. Tell the user to send the first quiz to themselves before sending it out. If the mail system blocks .html
   attachments, put the file on OneDrive or SharePoint and send the link instead. A stakeholder who cannot attach
   files can click "Copy my answers" and paste them into the reply.

**Done when:** every chosen (area, stakeholder) has a quiz page that passes `quiz-check`, an email text and a quiz-log
row. Record in `STATUS.md` the number of quizzes and questions.
