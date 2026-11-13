# 2026-11-01 — Wizard sends the access requests the person approves, the way their own one went

> **Superseded** on 13 November 2026 by [Wizard names the Big Data Portal tables the person needs; the person requests access](2026-11-13-bdp-access-self-service.md): Wizard no longer prepares, opens, fills or sends access requests. Kept as the record of what was built.

**Owner:** project owner. **Status:** decided (1 November 2026). Changes the submit rule of
[2026-10-28](2026-10-28-bdp-access-requests.md) and [2026-11-01](2026-11-01-bdp-dataset-access.md) (until now the
person always pressed Submit).

**Context.** With fifty requests prepared, pressing Submit on each is the person's work Wizard was meant to take. The
owner: "I'll test this again. And if one works, I want to tell Gemini that this worked and to reproduce the requests so
whenever we need a request, I just need to give permission, but Gemini should be filling in the requests. Not the
person."

**Options.**
1. Keep the person's Submit on every request. Safe, and fifty presses.
2. Gemini sends requests with a tool. A write in a corporate system in the person's name that Gemini (or text it read)
   could start: not acceptable.
3. The person's click is the permission; Wizard sends with a recipe it saw work: the person submits one request
   themselves, says it worked, and from then on Wizard sends the requests they approve the same way, checking each.

**Decision.** Option 3.
- **Seeing the person's request go through.** The request window notes which control the person presses
  (`portal_clicks.js`) and the requests the page then sends. After they press a control in the filled form, the first
  request it sends (after a submit-like control; otherwise the first whose address names a change) is their
  submission: the control's text, its method, host and path (ids as `*`), the catalog's answer (status and its success
  fields such as `success` or `code`) and the question the page asked, if any. A prepared request is then marked sent by
  them. Their window answers OK to a submit question ("Do you want to submit the request?") right after their own press;
  any other question is Cancel (until now every question was Cancel, which would have stopped their own Submit).
- **Saying it worked.** Settings → Portals shows what Wizard saw ("you pressed Submit; it sent POST /…; the catalog
  answered 200 (success: true)") and **It worked: let Wizard send the requests I approve**. Only a submission answered
  2xx can be used. **Turn off** goes back to filling only. Kept on this PC for this person; audited.
- **Permission.** Nothing is sent without the person's click: **Send request** on a card Gemini put under an answer,
  or **Send the N not sent** in the prepared requests, which asks them to confirm the list. Gemini has no tool that
  sends, and its own steps still refuse every access request.
- **Sending.** In the visible request window, one request after another: reach the table, open its form, fill it
  (every saved answer filled or already there, within a minute), press the control with the proven text in that form
  (exactly one), let through only a request with the proven method, host and path (any other change the write rules
  name is stopped), and require a 2xx answer with the same success fields. The first that does not go through is
  marked with why, and the rest are not sent. Closing the window or **Stop sending** stops. Each send is audited
  (`portals:access_submitted`, `portals:access_send`).

**Consequences.** AGENTS.md's exception allows this submit and lists what must stay. New `portal_clicks.js`;
`access_requests.py` keeps the last submission, the proof and each request's sent or failed state; the window observes,
answers submit questions and sends; API `POST /api/v1/portals/{system}/access-sending`, `.../access-send`,
`.../access-send/stop`; the settings form and the card.

**Residual risk.** If the request the person's Submit sends first is not the submission itself (a check before it),
Wizard copies that instead; the person sees the request Wizard saw before turning sending on. A catalog that answers
2xx with no success fields to compare is checked by status only. A form that changes (a new required field without a
saved answer) stops sending at its first request.

**Evidence.** `tests/unit/test_access_requests.py`: request patterns and success fields, sending refused until a 2xx
submission of the person's own, Send refused while off and for a request already sent, approved requests in order, the
audit, and Gemini offered Send only when sending is on, with no tool that sends. `tests/integration/test_portal_browser.py`,
in a real Chromium: the person submits one request (the page's question answered OK, the Submit's own request told from
a draft cleared after it); Wizard sends the next approved one with the person's answers, stops the draft change while it
submits, and stops at a request the catalog answers with `success: false`, leaving the one after it unsent.
`AccessRequestForm.test.tsx`, `AccessRequestCard.test.tsx`.
