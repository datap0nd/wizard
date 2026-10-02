---
id: platform-gscm
title: GSCM platform guide (supply chain and channel)
status: DRAFT_UNSIGNED
owner: TBD - GSCM / IT VOC (Step 03)
tags: [gscm, platform, supply chain, channel, sell-in, sell-out, sell-through, stock, inventory, distributor, reports]
---
**What it is.** GSCM holds supply-chain and channel data: what the company ships into the channel (sell-in), what the
channel sells to consumers (sell-out, also called sell-through units) and what the channel holds at month end (channel
stock). Data arrives from channel partners and can be restated for up to two months.

**How to navigate.** `gscm_search_reports` (e.g. "sell-in sell-out model month", "sell-through quarter"), then
`gscm_get_report_schema`, then `gscm_run_report`. Monthly reports accept `fiscal_quarter` filters and grouping;
Wizard expands a quarter to its months.

**What lives here (synthetic Release A).** Sell-in, sell-out and channel stock by market, model and month; quarterly
sell-through by market.

**Pitfalls.** Channel stock is a balance: compare month ends, never add months. Sell-in above sell-out is a screening
signal, not proof of channel stuffing (no stock age or returns yet). The real GSCM catalog (~100 candidate reports) is
still to be inventoried by metadata with IT VOC; partner-level and stock-age reports may exist there.
