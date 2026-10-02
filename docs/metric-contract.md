# Metric contract (Step 04)

Definitions are **retrievable context** (`knowledge/`), not a mandatory calculation pipeline. Gemini looks them up when a
term matters and must say when it relies on an unsigned draft. Typed source contracts (`contracts/sources/*.json`)
limit what fields an adapter can expose and declare each measure's aggregation rule.

| Concept | Note | Status | Owner (to confirm) |
|---|---|---|---|
| Investment-efficiency proxy (not ROI) | `knowledge/metrics/investment-efficiency-proxy.md` | DRAFT_UNSIGNED | CFO / marketing |
| Sell-in, sell-out, sell-through rate, channel stock | `knowledge/metrics/sell-in-sell-out.md` | DRAFT_UNSIGNED | GSCM / planning |
| Market share, share gain (pp) | `knowledge/metrics/market-share.md` | DRAFT_UNSIGNED | Market intelligence |
| Observed switchers and coverage | `knowledge/metrics/observed-switchers.md` | DRAFT_UNSIGNED | Consumer data |
| Installed base, activations, app engagement | `knowledge/metrics/installed-base-and-engagement.md` | DRAFT_UNSIGNED | Consumer data |
| Fiscal calendar, "last quarter" | `knowledge/calendar.md` | DRAFT_UNSIGNED | Finance |
| Markets, currencies, model lines | `knowledge/markets-and-models.md` | DRAFT_UNSIGNED | Business owner |
| Reporting conventions (evidence, modes, checks) | `knowledge/reporting-conventions.md` | DRAFT_UNSIGNED | Project owner |

## Aggregation rules enforced by tools

| Rule | Meaning | Example |
|---|---|---|
| `sum` | additive across any dimension | units, USD spend, transfers |
| `sum_same_currency` | additive only within one currency; mixed groups return null with a warning | local-currency spend |
| `last` | period-end balance: latest period in the group, summed across other dimensions | channel stock, active devices |
| `none` | rate or share: never aggregated; null with a warning when a group has several rows | share %, sell-through rate, coverage % |

Missing rows are reported as missing, never as zero. A filter on a market or period with no rows produces an explicit
warning. Market rows outside a user's rights are dropped with an access note.

## Reference answers

Synthetic goldens (in Git): `fixtures/goldens/*.json`, independently re-derived by `scripts/verify_spec.py`.
Corporate reference answers (≥3 CEO, 1 planner, 1 conquest, including incomplete and contradictory cases) are owner
supplied and stored only in the approved private location; CI sees safe IDs and hashes only.

## Signing a definition

The business owner reviews the note, edits it if needed, sets `status: SIGNED` and `owner:` to their name, and records a
decision in `docs/decisions/`. An evaluation rubric signed with it decides what "correct" means for that metric.
