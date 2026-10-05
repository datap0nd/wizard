# Task 31 — Apply the stakeholders' answers

**Goal:** turn the answers that came back into corrected, expert-checked notes.
**Output:** updated notes under `content\knowledge\`, `content\register\review-log.md`, `content\register\quiz-log.md`
(internal) · **Shareable:** counts only.
**Model:** the strongest your plan lists under `/model`.

## Steps

1. Ask the user to save each reply's attachment (`<quiz id>__answered.html`) into `documents\quiz-answers\`. When a
   stakeholder pasted their answers into the email instead, save the email text as a `.txt` file there.
2. `.\docs.ps1 quiz-answers` prints every answer with its question, the statement checked and its answer id
   (`A-<quiz id>-q3`). A file reported as `NO_ANSWERS` was answered in the email text: match the answers to the
   question numbers of that quiz yourself.
3. Apply each answer to its note (the topic is the note id):
   - **Correct:** keep the statement and add the answer id to the note's `sources` and after the statement.
   - **Partly correct / Wrong:** rewrite the statement with the stakeholder's version, cite the answer id, and remove
     `(inferred)`.
   - **Choice or text answers:** write the answer into the note where the open question was, cite the answer id, and
     remove the open question.
   - **Don't know:** keep the open question and add "(asked <name>: did not know)".
   - **Comments:** use them as context and cite the answer id.
   - **Two stakeholders disagree:** keep both under `## Conflicting information` with both answer ids, and add an open
     question for the note's owner.
   - **"Who else should we ask":** add those people to `content\register\stakeholders.md` for the area.
   - **"Anything missing or wrong":** add topics to the topic map or open questions to the notes.
4. When a stakeholder has confirmed or corrected the main statements of a note, set `reviewed:` to the answer date,
   `reviewed_by:` to "Name (role)" and `updated:` to today. Keep `status: DRAFT_UNSIGNED`: a note becomes `SIGNED` only
   when its owner explicitly approves it. Ask the user whether any owner wants to sign.
5. Add one row per changed note to `content\register\review-log.md`: date, note, quiz id, stakeholder, what changed.
   Update the quiz's row in `content\register\quiz-log.md` (answered, applied) and the topic map state (`quizzed`).
6. Run `.\docs.ps1 validate` (fix every error) and `.\docs.ps1 status`.

**Done when:** every answer file in `documents\quiz-answers\` is applied and logged, and the validator reports no
errors. Record in `STATUS.md` the notes updated and the open questions left.
