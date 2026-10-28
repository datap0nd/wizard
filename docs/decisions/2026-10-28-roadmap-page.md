# 2026-10-28 — The roadmap page: what Wizard does today and what comes next

**Owner:** project owner. **Status:** decided (28 October 2026).

**Context.** The owner asked for "a /roadmap in wizard, that has a future road map of stuff to come", with "what
wizard can already do on the left, the roadmap comes on the right. make it visual", a deadline "on each friday,
starting from this next one and you keep going one week at a time" (PowerPoint creation then two weeks),
controlled "with left and right arrows", with
logos ("for example for slides, powerpoint").

**Decision.**
- **A page of its own,** like `/brain`: `/roadmap`. The app is unchanged and nothing in it links there; the page links
  to `/brain` and back to the app. It reads no data and needs no sign-in: its content is
  [`apps/web/src/roadmap.ts`](../../apps/web/src/roadmap.ts), so changing the roadmap is an edit to that file.
- **Left: what Wizard does today**, from the README's "What runs today", and the systems it reads.
- **Right: the roadmap, one Friday at a time**, from Friday 30 October 2026. Each step is due on the Friday its last
  week ends ("PowerPoint creation timeline for 2 weeks instead of 1"), so a longer step moves the ones after it:
  1. Week 1, Friday 30 October: more portals read live, SC+ Global Dashboard and the NERP BI Portal.
  2. Weeks 2–3, Friday 13 November: PowerPoint slides from an answer.
  3. Week 4, Friday 20 November: a richer knowledge base (metrics, business presentations digested, strategy), compiled
     in meetings with the heads of business and the main PIC of each business area.
- **For presenting:** the roadmap starts empty; → (or Space, Page Down) shows the next Friday, ← takes it back, End
  shows all, Home none, F is full screen. Each step shows its countdown on the viewer's calendar. A step past its date
  and not marked `done` says "Due date passed", never quietly moves.
