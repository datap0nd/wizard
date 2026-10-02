# wizard-content (template)

The real platform documentation and report catalogs Wizard's Gemini reads. **This folder becomes its own internal
repository on the corporate Git server** (or an approved share). It must not be pushed to a personal GitHub account:
report names, column names and platform notes are internal company metadata.

```
wizard-content/
  GEMINI.md                         authoring rules for Gemini CLI sessions in this repo
  .gemini/commands/wizard/          /wizard:platform-guide and /wizard:report-catalog prompts
  schema/source-contract.schema.json  copy of Wizard's catalog schema (keep in sync with the Wizard repo)
  inbox/                            raw source documents (PDF, DOCX, exports) — never committed (.gitignore)
  knowledge/platforms/<platform>.md platform guides (Markdown + front matter)
  knowledge/metrics/<topic>.md      business definitions (Markdown + front matter)
  contracts/sources/<platform>.json report catalog per platform (JSON, one entry per report)
  register/source-register.csv      tracking: one row per candidate report, owner and approval status
```

## Workflow per platform

1. Put the platform's documentation in `inbox/<platform>/` (Mosaic Q&As, help pages, owner notes, a report list
   exported from the platform, or the ASAP importer draft from `scripts/import_asap_catalog.py`).
2. On the work PC, in this folder, start Gemini CLI signed in with your work account and pick the strongest model your
   enterprise plan lists under `/model`.
3. `/wizard:platform-guide asap inbox/asap/` → writes `knowledge/platforms/asap.md`.
4. `/wizard:report-catalog asap inbox/asap/` → writes or extends `contracts/sources/asap.json` and the register, and
   replies with a table of uncertain choices and open questions for the owner.
5. Validate: from the Wizard repo, `uv run python scripts/validate_content.py <path to wizard-content>`. Wizard runs the
   same checks at start-up and refuses to start on errors.
6. Open a pull request. The **source owner** reviews every report entry (description, grain, units, aggregation rule,
   caveats, sensitivity). Approved notes get `status: SIGNED` and the owner's name.

To use it, set `WIZARD_CONTENT_DIR=<path to wizard-content>` in Wizard's `.env` (with the `gemini-cli` or `code-assist`
runtime). Wizard then shows these platforms and reports instead of its synthetic examples.

Everything Gemini writes starts as `DRAFT_UNSIGNED` / `NAVIGATION_ONLY`. A report becomes readable only after a live
adapter and a signed parity check exist (Wizard docs: `docs/asap-implementation.md`, `docs/source-onboarding.md`).
