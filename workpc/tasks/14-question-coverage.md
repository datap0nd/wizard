# Task 14 — Can the catalog answer the three first questions?

**Goal:** show which data each demonstration question needs and whether a catalogued report provides it.
**Outputs:** `content\register\coverage.md` (internal, with report ids) and `outbox\14-coverage-summary.md`
(**shareable**: no report names).

## The questions

1. Executive: "Which market gave us the best return on marketing investment last quarter — tie NERP spend to
   sell-through, share gain, and competitive switching, and rank them."
2. Planner: "Flag any model where sell-in is outpacing sell-out and installed-base growth is stalling — then check
   Smart Switch and app usage to tell me if it's a demand problem or a channel-stuffing problem."
3. Conquest: "Where are we winning switchers from Apple and Xiaomi according to Smart Switch, and does our investment
   and sell-out data support doubling down there?"

## Fields to check

Marketing spend by market and quarter · campaign spend by objective · sell-out by market and quarter · sell-in,
sell-out and channel stock by model and month · market share by brand, market and quarter · Smart Switch transfers by
origin brand and market · Smart Switch observation coverage · installed base by model and month · new activations ·
app usage by model · channel stock age or returns · incremental margin or any measure of incremental sales.

## Steps

For each field, search `content\contracts\sources\*.json`. Mark it `CANDIDATE` (a report provides it; numbers are not
readable yet), `MISSING` (no report found) or `UNCLEAR` (a report might provide it; say what is unclear). Note
mismatches that would make comparisons unsafe: different market codes, fiscal vs calendar periods, currencies.

**Shareable file:** the field list with statuses and mismatch types only, no report or column names.

**Done when:** every field of the three questions has a status in `content\register\coverage.md`, and the summary
lists, per question, how many fields are CANDIDATE / MISSING / UNCLEAR.
