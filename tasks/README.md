# Tasks

Instructions the Wizard team writes for Gemini, run by the person at their PC from **Settings → Tasks**. Wizard reads
this folder from GitHub (`main`) when the Tasks section opens, so a task pushed here appears without an update; with
no network it shows the copy that came with the installed version. What a task produces goes to the company's
knowledge-base repository (`wizard_kb_save_notes`), never here.

One Markdown file per task, named after its id:

```
---
id: where-to-get-it-portal-reports
title: Add mapped portal reports to the metric notes' "Where to get it"
summary: One line shown in Settings: what it changes and why.
added: 2026-10-31
---
The instructions for Gemini: what to read, what to change, what to leave alone, what to say at the end.
```

Rules:

- This repository is public: a task holds instructions only, never company content (names of reports, people,
  figures). Gemini finds those with its tools on the person's PC.
- A task runs with Wizard's tools: the knowledge tools, `wizard_kb_note_source`, `wizard_kb_standard`, `wizard_kb_save_notes`, the portal
  map and portal tools, the database and catalog tools. A task that needs a tool Wizard does not have needs an update
  first.
- Say what must not change, and what to do with a SIGNED note (usually: leave it and propose the change in the
  summary).
- Delete a task's file when it is no longer needed; Wizard drops it from the list.
