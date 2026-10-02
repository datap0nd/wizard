# Product requirements (Step 01 draft)

Status: DRAFT for owner review. Interviews with the CEO/CFO/director and planning representatives are still to be held;
items marked **OPEN** need their answers. Uncertain business definitions can also surface during live questions.

## Users and access

| Cohort | Typical question | Source rights (test identities in `fixtures/identities.json`) |
|---|---|---|
| CEO / CFO | Cross-market performance, marketing efficiency, budget calls | All systems, all markets, finance reports |
| Director (Gulf) | Their markets' performance and conquest | SA, AE only; no finance reports |
| Planner | Channel health by model | GSCM and ASAP consumer reports; no NERP |
| New joiner | — | No sources (sees an honest empty state) |

**OPEN:** the first pilot cohort, who may share/reopen reports, and the expected report lifetime (default 30 days).

## Demonstration questions (not the full list of permitted questions)

1. **Executive**: "Which market gave us the best return on marketing investment last quarter — tie NERP spend to
   sell-through, share gain, and competitive switching, and rank them." Without incrementality, margin and a
   counterfactual, the output is an **investment-efficiency proxy** (spend-normalised sell-through improvement) with
   share gain and observed switching shown separately. Never titled "ROI".
2. **Planner**: "Flag any model where sell-in is outpacing sell-out and installed-base growth is stalling — then check
   Smart Switch and app usage to tell me if it's a demand problem or a channel-stuffing problem." Output: a screening
   result with conflicting indicators, not a definitive cause.
3. **Conquest**: "Where are we winning switchers from Apple and Xiaomi according to Smart Switch, and does our investment
   and sell-out data support doubling down there?" Output: observed counts with coverage, and a recommendation that is a
   decision to investigate unless incremental economics exist.

Unscripted follow-ups and the 30 draft evaluation prompts are in `tests/evals/cases.json`.

## What an answer must give the reader

- The direct answer first, then the comparison, assumptions, gaps and caveats, then useful follow-ups.
- Every number from a source carries its evidence id; derived numbers state how they were derived.
- A chart or table when it helps (Gemini decides), with a Data view showing exact values.
- Data mode (SYNTHETIC / DATED_APPROVED_SNAPSHOT / LIVE_VERIFIED), check status, freshness per source, and which
  sources were consulted, visible without opening anything.
- **Show sources** (rows, filters, as-of) and **Check my data** (recompute and qualify) on every answer.
- A dated report with a stable link that reopens only for its owner while their source rights still allow it.

## Decisions answers support

Budget reallocation between markets (executive), stock and sell-in correction by model (planner), conquest
investment test design (conquest). **OPEN:** which decisions the owner wants explicitly framed, and the acceptable
freshness per decision (e.g. weekly panel share vs daily sell-out).

## Context Gemini can retrieve (knowledge/)

Fiscal calendar and "last quarter" (synthetic assumption: calendar quarters), MENAT market codes and currencies, model
line terminology, metric notes (proxy vs ROI, sell-in/out, share, observed switching, installed base and engagement),
reporting conventions. All DRAFT_UNSIGNED until owners sign (Step 04). **OPEN:** real fiscal calendar, language (Arabic
UI?), number formats, accessible chart conventions.

## Interaction flow (implemented)

Sign in → empty state with the three stories → ask → live "What Wizard did" timeline (tool calls with evidence ids,
Gemini's interim notes, warnings) → streamed answer with chips and visuals → Check my data / Show sources / Report /
Feedback → conversation history in the sidebar → Sources tab to browse what the user may see (system → folder → report
→ prompts, navigation-only reports marked).

**OPEN:** walk the flow with the owner against the real B2B page and the earlier clickable wireframe; record adjustments.
