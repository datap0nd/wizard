# 2026-11-03 — Wizard asks the person before a long route

**Owner:** project owner. **Status:** decided (3 November 2026).

**Context.** On the work PC a question asked for "Samsung sell-out by operator, compared with the previous day, with the
highest and lowest growth". The run took 29 minutes 35 seconds and 59 steps: 14 minutes looking through knowledge
notes, 16 database queries (three refused for a schema Wizard may not query) and an unreachable dashboards folder,
eight minutes opening the daily sell-out report in GSCM, then an unrelated detour. With four minutes left it answered a
different question (September against October, from a monthly view) and named the wrong operator as the lowest grower.
Daily sell-out by operator was in one GSCM report; weekly by operator was in the database. Nobody had asked the person
which they wanted. The owner: "if you believe that perhaps ASKING the user for more info before proceeding, feel free.
like a prompt helper. its up to you."

**Options.** (1) A prompt helper before sending: Wizard rewrites or questions every request before it runs. It slows
every question, including clear ones, and choosing the questions in code is the intent classifier the agent-first
decision ruled out. (2) A tool Gemini may call: one short question with two to four options, shown as buttons; Gemini
decides when, after a few quick reads of what the sources cover, and the run stops gathering data once it asks.
(3) Leave it to the prompt's old line ("ask one short clarifying question") with no buttons: the person has to type the
answer, and nothing stops the run from going on.

**Decision.** Option 2.
- **The tool.** `wizard_ask_person(question, options, why)`: two to four options, the one Gemini would choose first,
  saying what each costs when that differs a lot (a live portal read takes minutes, a database query seconds). The
  answer card shows the question and the options as buttons; a click asks the option as the next question in the
  conversation, so Gemini reads its own question and the choice together. Only the latest answer takes a click.
- **When.** The prompt asks Gemini to ask before a long route, not after it, when the request leaves open something
  that changes where the data comes from or what the answer is (the period or granularity, the markets, units or value,
  what a breakdown means) and nothing the person said settles it; at most once per request; never about something
  every option answers nearly the same way. Otherwise it states its assumption and goes on, as before.
- **Inside the tool.** Offered only in a question (not in a task, a mapping round or Check my data, where nobody is
  waiting); a second ask in the same run is refused; once it has asked, the run's research and map writes are refused
  so it ends its turn with the question. Working out and presenting stay open.

**Consequences.**
- A run event `person_asked` (question, options, why) is stored with the run, so a reopened conversation shows it.
- Whether Gemini asks well is measured on the work PC; the eval log records the run that led to this.

**Evidence.** `tests/unit/test_ask_person.py` (asked once, options deduplicated, research refused after asking, the
click's follow-up carries the question; not offered in Check my data; the prompt's rule);
`apps/web/src/components/Steering.test.tsx` (the card, a click asks the option, no click while running or on an
earlier answer).
