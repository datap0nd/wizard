# 2026-11-13 — Wizard checks the portals' sign-in before each answer, and turns yellow until the person signs in

**Owner:** project owner. **Status:** decided (13 November 2026).

**Context.** The owner: "Wizard needs to explain [that] in order for you to have access to most portals, you need to
login every now and then. Before any response, it does a check for sign ins in the portals. It flags portals not signed
in in the image where it's deciding the next step (currently it says ready on all of them, can have a button with sign
in instead). What I want is for wizard to be yellow at the top if any portal is not signed in anymore, to do a check
(without AI, a code check for sign in) so after a prompt you get prompted to sign in and re-enable credentials."

Until now Wizard found out that a portal had ended the person's sign-in only when Gemini's own steps met its sign-in
page (`sign_in_required`), part-way through an answer. The stage said "ready" on every portal, and nothing said that a
sign-in does not last.

**Options.** (1) Check the sign-in before Gemini starts, holding the answer until it is known: every answer would wait
for each portal's start page (seconds each, up to 45 s for one that does not answer). (2) Tell Gemini which portals are
signed out: that is a check whose only reader is the person, and it would steer Gemini's route from code. (3) Check
beside the answer, in code, and show the person (chosen).

**Decision.**
- **A check in code, never the model.** When a question starts (a question, its Check my data, a recurring brief; not
  a mapping round or a task), Wizard checks the portals the question may read: those the person may use, and, when
  they chose systems, only the chosen ones. The check opens each portal's start page (each application of the Big Data
  Portal) **in a tab of its own** in the person's background Wizard browser and reads it as before: a sign-in page (a
  password field, sign-in text, or an identity provider's host the person's sign-in went through) is *signed out*; a
  page that does not load is *unreachable*, which signing in does not fix. The tab closes; the page Gemini works on is
  left as it is, so a running GSCM client is not restarted.
- **Beside the answer.** The check does not hold Gemini, which is not told the result; its portal calls wait only for
  the browser, which runs one job at a time. An answer ready while the check still runs waits at most 1.5 s for it;
  a check that ends later is kept by the browser and read by the page from there.
- **Kept, not repeated.** A portal found signed in, or read by Gemini a moment ago (a read that ended on the portal,
  not on a sign-in page), is not opened again for three minutes. One found signed out stays signed out until the
  person signs in again: Wizard's browser is its own, so nothing else signs it in. Gemini's own read that meets a
  sign-in page marks the portal signed out at once.
- **The stage.** Where it said "ready", a portal says *checking sign-in…*, *signed in*, *can't be reached* or, when it
  ended the sign-in, shows a yellow key and a **Sign in** button that opens Wizard's browser window, one tab per portal.
- **Yellow at the top.** While any portal has ended the person's sign-in, a yellow bar with the wizard sits at the top
  of Wizard (the panel and the full window): which portals, why ("Most portals end your sign-in after a while (each
  portal sets its own time), so you sign in again in Wizard's browser every now and then. Wizard reads a portal only
  while you are signed in to it there, and it never stores your password."), and **Sign in**. **WizardBar's button at
  the top of the screen turns yellow** too ("Sign in again", "Click to sign in to GSCM"), with a notification once when
  the panel is not in front. When the person closes the sign-in window (or presses Done), Wizard checks every portal
  again at once; when they are signed in, the bar says "Signed in again to GSCM" for a moment and goes, and the button
  is blue again.
- **Settings → Portals** says the same, and its **Check sign-in** feeds the same bar. Gemini's `sign_in_required` error
  and its portal guide point to the yellow bar. Wizard still stores no password and Gemini still never types one.

**Consequences.** Each question opens the portals' start pages in the background at most every three minutes, beside
the answer. A portal that cannot be reached is shown as such, never as a sign-in to fix. No AGENTS.md rule changes: the
check reads only the portals' own start pages, under the portal browser's host and read-only rules.

**Evidence.** `tests/integration/test_portal_browser.py::test_the_sign_in_check_before_a_question_is_code_in_a_tab_of_its_own`
(a real Chromium: the check's own tab, the page Gemini works on left where it was, a portal read a moment ago not
opened again, signed out kept until the person signs in, a read that meets a sign-in page, nothing checked while the
window is open, everything checked again when it closes); `tests/integration/test_portal_sign_in_api.py` (each question
checks the portals its person may use and its card carries the result; none for a question that may not read a portal;
a check that ends after the answer adds nothing to the finished run); `apps/web/src/components/SignInBar.test.tsx` (the
bar, its Sign in and Done, "Signed in again", WizardBar told, the stage's Sign in instead of "ready"). WizardBar's yellow
button: built by the `desktop` workflow with warnings as errors, drawn by `WizardBar --snapshot` (`sign-in`,
`sign-in-hover`, `sign-in-working`).
