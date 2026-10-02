# Knowledge notes

Business definitions and conventions Gemini can retrieve with `wizard_lookup_definitions`. They are context, not a
pipeline: Gemini decides when a definition is relevant. Each note has front matter:

```
id, title, status (DRAFT_UNSIGNED | SIGNED), owner, tags
```

`DRAFT_UNSIGNED` notes are working assumptions written for the synthetic Release A. A business owner signs a note
(Step 04) by changing `status` to `SIGNED`, naming themselves in `owner`, and recording the decision in
`docs/decisions/`. Gemini is told to say when it relies on an unsigned definition.
