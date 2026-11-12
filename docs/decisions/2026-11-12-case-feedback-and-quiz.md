# 2026-11-12 — Feedback, a quiz and an admin pane on the Cases site

**Owner:** project owner. **Status:** decided (12 November 2026).

**Context.** The owner: "allow users to submit feedback in each case for the answer and to rate the answer from 1 to 5
stars", "comments are anonymous. If users put in a pin on the top right they get access to an 'admin' pane that allows
them to edit cases, see comments other people made, etc.", "There should be a quiz/definitions part, where gemini is
going to prepare 50 questions about the knowledge base that are currently a bit uncertain. Users will be able to go to
that section and answer those questions, anonymous. it will have business intelligence section and a business section,
one will be more to answer technical questions, the other more concepts/terms/strategy questions", "gemini will
prepare these questions via tasks. Create those tasks", and "The pin will be 2323".

The Cases site is static (GitHub Pages on the company GitHub): it can show files but cannot keep what a visitor types.
Asked where submissions should go (a Cloudflare service, each person's Wizard, or GitHub issues under the visitor's
own name), the owner asked: "cant a 'submit' button be a little script that pushes the contents they just wrote to the
repo somehow? using my PAT or something like that?" Told that every visitor could read a token the page uses: "they
dont know how to use tis token, assume users are non-tech", and "i will create wizard-feedback".

**Options.** (1) A small service elsewhere (Cloudflare): truly anonymous, but company comments leave the company GitHub
and the office network must reach it. (2) Submissions through each person's Wizard with a token in the provisioning
file: only people with Wizard could send. (3) Issues opened under each visitor's own GitHub account: not anonymous.
(4) The site's pages open issues with a token published beside them, limited to a repository of its own.

**Decision.** Option 4, with the token limited so that a copy of it can do little.
- **The feedback repository** is a repository of its own on the company GitHub (`WIZARD_FEEDBACK_REPO`; empty:
  `wizard-feedback` beside the site's repository), never the knowledge base's or the site's, and not public. Every
  rating, comment and set of quiz answers is one issue there, opened by the page; its body ends with the data as JSON.
- **The feedback token** (`WIZARD_FEEDBACK_TOKEN`, Settings → Pages site) is entered on the publishing PC only (never in
  a provisioning file or Export settings, like the write token) and published in `cases/feedback.json` beside the
  pages. Before it is published, every time, Wizard checks that it is a fine-grained token (a classic token is
  refused: it reaches every repository its account can), that it cannot change files in the feedback repository, the
  knowledge base's or the site's (GitHub refuses it before it looks at the request), and that it can open issues
  there. A token that fails a check is never published, and one already on the site is taken off at the next publish.
  Settings → Pages site → **Turn feedback on** runs the checks and puts feedback on the site without waiting for a
  case. Owner-accepted risk: anyone who can open the site can read the token and open, edit or close issues in the
  feedback repository; they cannot delete issues or reach any other repository.
- **Anonymous.** Every issue is opened with that token, so GitHub shows its account as the author, never the visitor.
  The pages send nothing about the person; the browser remembers only what it already sent, to show it as sent.
- **Rating.** Under each answer of a case: 1 to 5 stars and an optional comment, sent with **Send anonymously**.
- **The quiz** (`?quiz`): two sections, **Business intelligence** (technical: sources, reports, columns, how a measure
  is calculated) and **Business** (concepts, terms, processes, organisation, strategy). Each question says what the
  knowledge base holds now; people pick a choice, write their answer, or say they do not know, and send a section's
  answers as one issue. The gallery leads to it.
- **Gemini prepares the quiz in tasks.** `tasks/quiz-1-business-intelligence.md` and `tasks/quiz-2-business.md` (25
  questions each, 50 in all) read the knowledge base for what it is unsure of (UNKNOWN, open questions, conflicting
  information, ambiguous terms, unchecked drafts) and publish a section with `wizard_quiz_save`: only in a task run,
  5 to 50 questions that replace that section on the site (`cases/quiz.json`), checked for credentials, published with
  the write token like a case. A question asked again keeps its id, so its answers stay with it. This changes the Pages
  decision's "Gemini has no tool for any of this" for the quiz alone: the task is the person's click.
- **The admin pane** (`?admin`): **Admin** at the top right asks for the PIN (`WIZARD_FEEDBACK_PIN`, 2323; the site
  holds its SHA-256, not the PIN) and opens, in that browser tab, every case's ratings (average, per answer) with the
  comments (Mark done closes the issue), every quiz answer by question, and **Edit cases**: a case's title and takeaway,
  a note from the editors above an answer, and hiding a case from the gallery. Edits are kept in one issue Wizard opens
  in the feedback repository and are shown over what Wizard published, which is not changed; removing a case stays in
  Wizard (Share as case). Both lists download as CSV. The PIN only hides the pane: the token reads the same issues.

**What this does not do.** No visitor's name, email or account is sent or kept. Wizard never writes to the feedback
repository except the edits issue it opens with the feedback token. Answers reach the admin pane, not the knowledge
base: a person (or a later task) folds them into notes.

**Evidence.** `tests/unit/test_feedback.py` (17: an issues-only token published with the Cases page and the edits issue
opened once; a classic token, one that can change files in the feedback or knowledge-base repository, a public
repository and issues turned off each refused before anything is opened; an unsafe token already on the site taken off;
no feedback file without a token; Turn feedback on with the values typed, an empty gallery when no case is published;
the settings stay on this PC; a quiz section published and the other kept, ids stable; a quiz that breaks a rule
publishes nothing; no write token, no quiz; only a task publishes the quiz), `apps/web/src/feedback.test.ts` and
`components/cases/CaseFeedback.test.tsx` (issues read back, a comment with backticks included; averages; answers by
question; edits merged on top of GitHub's; the PIN against the digest Python publishes; a rating sent once and
remembered; the quiz sent as one issue; the admin pane's ratings, Mark done and an edit saved). The built site was
served with a fake GitHub issues API and driven in Chromium at 1280×800 and 390×844: rate and comment, the quiz sent,
the PIN, the admin pane's three tabs, an editor's note saved and shown on the case, no console errors, no sideways
scroll. Not run: the company GitHub itself (its CORS answers to the Pages origin, fine-grained tokens and secret
scanning), first used when the owner turns feedback on.
