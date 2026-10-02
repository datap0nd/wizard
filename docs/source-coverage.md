# Source coverage matrix (Step 03)

Cells: **VERIFIED** (owner-approved sample and parity), **CANDIDATE** (believed to exist; not yet confirmed), **MISSING**
(no known source), **SYNTHETIC** (Release A fixture only). Every live cell is CANDIDATE or MISSING today. The metadata
inventory lives in [source-register.csv](source-register.csv).

## Executive (CEO) question

| Required field | Synthetic report (Release A) | Live status | Likely system | Notes |
|---|---|---|---|---|
| Marketing spend by market and quarter (USD and local) | `nerp-mkt-spend-quarterly` | CANDIDATE | NERP | FX basis and regional cost-centre exclusions to confirm |
| Sell-out / sell-through units by market and quarter | `gscm-sell-through-quarterly`, `gscm-sell-in-sell-out-monthly` | CANDIDATE | GSCM | ~100 candidate reports to inventory by metadata |
| Market share (volume/value) by brand | `asap-share-quarterly` | CANDIDATE | ASAP (panel) or share provider | Panel denominator and lag to confirm |
| Competitive switching (Apple, Xiaomi) | `asap-smartswitch-transfers` + `-coverage` | CANDIDATE | Smart Switch data (via ASAP?) | Aggregated only; coverage definition needed |
| Incrementality / counterfactual | — | MISSING | — | Without it the result stays a proxy |
| Incremental margin | `asap-gross-margin` (not incremental) | MISSING | Finance | Gross margin is not incremental margin |

Field matching to resolve: market codes (SA/AE/EG/MA vs system codes), fiscal vs calendar quarters, model line codes,
USD conversion basis.

## Planner question

| Required field | Synthetic report | Live status | Notes |
|---|---|---|---|
| Sell-in, sell-out, channel stock by model and month | `gscm-sell-in-sell-out-monthly` | CANDIDATE | Stock age and returns: MISSING (limits any stuffing conclusion) |
| Installed base by model | `asap-installed-base` | CANDIDATE | Model-line vs model mapping |
| Activations and app engagement | `asap-app-engagement` | CANDIDATE | Denominator: activated devices; feed gaps by market |
| Smart Switch by target family | `asap-smartswitch-transfers` | CANDIDATE | Family, not model granularity |

## Conquest question

| Required field | Synthetic report | Live status | Notes |
|---|---|---|---|
| Observed switchers by origin brand | `asap-smartswitch-transfers` | CANDIDATE | Observed events only |
| Eligible / observed population | `asap-smartswitch-coverage` | CANDIDATE | Opt-in coverage % per market |
| Conquest spend | `nerp-campaigns` (objective = Conquest) | CANDIDATE | Campaign objective taxonomy to confirm |
| Sell-out, share | as above | CANDIDATE | |
| Incremental economics, capacity | — | MISSING | Recommendation stays "decision to investigate" |

## Three MCP connections ≠ three reports

Release A models three systems (NERP, GSCM, ASAP) as three MCP connections. Live coverage may need a fourth
authorised connection (e.g. Smart Switch or a share provider outside ASAP). If three cannot cover spend, sell-through,
share and switching, the owner chooses a documented scope change, a fourth connection, or a partial first report.
Coverage is never manufactured.
