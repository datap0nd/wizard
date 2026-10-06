# Task 19 — Make the PostgreSQL views queryable

**Goal:** let Wizard answer with numbers from the documented materialized views (SIBP and sell-in first). Each view gets
a reviewed report entry. A signed check per view (one figure compared with a report the user trusts) then turns its
figures from "Live · not yet checked" into "Live · verified".
**Output:** `content\contracts\sources\postgresql.json`, rows in `content\register\review-log.md` (internal)
· **Shareable:** counts only.
**Model:** the strongest your plan lists under `/model`.

Never edit `.env` or anything under `releases\`: ask the user. Wizard's code changes come through `.\update_app.ps1`.

## Steps

1. **Before you start.** Task 18 must be done: the export exists in `content\inbox\postgres\`, and the dataset notes
   exist in `content\knowledge\datasets\`. Then:
   - `.\docs.ps1 postgres-check` must show the session is read-only.
   - If the export is more than a week old, run `.\docs.ps1 postgres-catalog` again (add `--schema <name>` to keep it
     short).
2. **Choose the views.** Ask the user which views Wizard should read first. Suggest the SIBP and sell-in views, for
   example `bi_reporting.sell_in_amt_mv` and `bi_reporting.psi_combined`; the exact names are in `00-overview.md`.
3. **Draft.** For example: `.\docs.ps1 postgres-contract --view bi_reporting.sell_in_amt_mv --view bi_reporting.psi_combined`.
   It adds one entry per view to `content\contracts\sources\postgresql.json`, with every guess marked `UNCERTAIN:`.
   An entry that already exists is kept; `--replace` regenerates it.
4. **Review each new entry** against its dataset note (`content\knowledge\datasets\<schema>-<view>.md`) and its export
   file:
   - `description`: 1 to 3 sentences on what one row is, what the view covers, and important exclusions.
   - `dimensions`: snake_case keys; keep `column` when the database name differs. Roles: exactly one `period` (the
     column people filter by, such as week or month), plus `market` and `model` where they apply.
   - `measures`: the `aggregation` decides what Wizard may add up:
     - `sum`: units, or amounts in one currency;
     - `sum_same_currency`: amounts in several currencies (the report needs a currency dimension);
     - `last`: period-end balances such as stock (needs the period role);
     - `none`: rates, shares, prices and averages.
     Name units: `USD`, `units`, `%`.
   - Delete each `UNCERTAIN:` caveat you settled from the note or the user's answer. Ask the user closed questions about
     the rest.
   - Never change `relation`, `row_access` or the system's `connector` block. Never add `parity` in this step.
   - Run `.\docs.ps1 validate` until it reports no errors.
5. **Switch Wizard to the real content** if task 17 has not done it yet (`WIZARD_CONTENT_DIR=content`, which the user
   adds to `.env`). Ask the user to restart Wizard: close its window, then `.\start.ps1`. Its start-up check must show
   "PostgreSQL reachable ... session read-only: on".
6. **First question.** Ask the user to put a question to Wizard in the browser that one of the views answers, for
   example "What was SIBP sell-in by market last week?". The answer shows "Live · not yet checked".
7. **Check each view (parity), with the user.**
   - The user picks one figure they trust, from the SIBP report or portal they normally use, and its filters.
   - Run the same query, for example
     `.\docs.ps1 postgres-sample --report <report id> --filter market=EG --filter week=202640 --group-by market`.
     Compare the two figures.
   - **Same figure:** add to that report entry
     `"parity": {"checked": "<today, YYYY-MM-DD>", "by": "<user name (role)>", "reference": "<which report, which filters, which figure>"}`.
     Add a row to `content\register\review-log.md`, then run `.\docs.ps1 validate`. After a restart, that view shows
     "Live · verified".
   - **Different figure:** do not sign. Find out why using the dataset note and the view's SQL: a filter, a currency, a
     column's meaning, or refresh timing. Fix the entry, or record the difference as an open question, and tell the
     user.

**Done when:**
- the chosen views are in the catalog and the validator reports no errors;
- Wizard has answered from at least one of them;
- each checked view has its `parity` recorded, or the mismatch is explained.

Record the counts in `STATUS.md`.
