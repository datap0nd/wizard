# Documentation guide: what Gemini reads, how it is written, where it lives

## Structure

| Layer | Format | File | Read by Gemini through |
|---|---|---|---|
| Platform guide (one per platform) | Markdown with front matter, ≤600 words | `knowledge/platforms/<platform>.md` | `wizard_list_sources` names it; `wizard_lookup_definitions` returns it |
| Report catalog (one per platform, one entry per report) | JSON validated by `contracts/source-contract.schema.json` | `contracts/sources/<platform>.json` | `<platform>_search_reports`, `<platform>_get_report_schema`, `wizard_search_catalog` |
| Business definitions (cross-platform) | Markdown with front matter | `knowledge/metrics/<topic>.md`, `knowledge/calendar.md`, … | `wizard_lookup_definitions` |
| Inventory register (people only) | CSV | `register/source-register.csv` | not read by Gemini; tracks owner and approval per report |

Front matter for every Markdown note: `id`, `title`, `status` (`DRAFT_UNSIGNED` or `SIGNED`), `owner`, `tags`. Report
entries carry the fields listed in [platforms.md](platforms.md); the aggregation rule per measure (`sum`,
`sum_same_currency`, `last`, `none`) matters most, because Wizard's tools enforce it.

## Where

- **This repository (personal GitHub):** application code plus SYNTHETIC examples only. No real report names or
  platform notes.
- **Real documentation:** a separate internal repository on the corporate Git server, created from
  [`templates/content/`](../templates/content/README.md). Same folder layout, so Wizard can load it unchanged.
- **Raw source documents** (Mosaic Q&As, help PDFs, exports) stay in `inbox/` on the work PC and are never committed;
  only the distilled metadata is.
- Wizard reads that folder when `WIZARD_CONTENT_DIR` points at it (with the `gemini-cli` or `code-assist` runtime). The
  synthetic examples are then not loaded. Validate first with `uv run python scripts/validate_content.py <folder>`;
  Wizard applies the same checks at start-up and will not start on errors.
- Real content can only *describe* reports: every report is `NAVIGATION_ONLY` with no data file until a live adapter
  and a signed parity check exist. Gemini can find a report, explain what it holds and tell the user to open it, but it
  cannot read its numbers yet.

## Which model and prompt

- **Model:** Gemini, through Gemini CLI on the work PC, signed in with your own work account. Company documentation
  and report metadata should only go to the AI covered by the enterprise agreement. Pick the strongest model your plan
  lists under `/model` for drafting (quality matters more than speed for a one-off per report). `gemini-3.8-flash`
  with high thinking is fine for large batches.
- **Prompts:** two Gemini CLI slash commands shipped in the content template:
  - `/wizard:platform-guide <platform> inbox/<platform>/` writes the platform guide.
  - `/wizard:report-catalog <platform> inbox/<platform>/` writes catalog entries and register rows, and lists every
    uncertain choice for the owner.
  - Shared rules for both live in the template's `GEMINI.md`: only use the given material, write UNKNOWN instead of
    guessing, metadata only, everything starts as a draft.
- **For ASAP**, run `scripts/import_asap_catalog.py` first. It reads ASAP's own metadata (no AI, no data rows), and its
  draft becomes the input for `/wizard:report-catalog`, which adds descriptions, units, aggregation rules and caveats.

## Review and sign-off

A pull request per platform or batch. The source owner checks each entry, fixes descriptions, confirms grain, units and
aggregation rules, and signs (`status: SIGNED`, owner name). Reports remain `NAVIGATION_ONLY` until a live adapter and a
signed parity check exist ([source-onboarding.md](source-onboarding.md)).
