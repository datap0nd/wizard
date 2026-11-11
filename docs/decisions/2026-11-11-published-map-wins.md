# The published portal map always wins

**Date:** 11 November 2026 · **Owner:** the Wizard owner

**Context.** The owner asked whether Wizard reads anything from a PC instead of the knowledge-base repository. One
answer was the portal maps: a PC that had a map file of its own (`data/portal-maps/<portal>.json`) read that file and
never looked at the map published to the repository, so an old local file hid a newer published map, and decided
whether the portal's report catalog was retired.

**Options.** (1) Leave it: this PC's map first. (2) The newer of the two wins. (3) The published map always wins.

**Decision.** Option 3 (owner: "make the published one always win").

- The repository's `portal-maps/<portal>.json` is the master copy. Where the synced knowledge base holds one, it is the
  map Wizard reads.
- A PC's own file is read only while it **continues** that published map: it was saved on top of it (the file records
  the digest of the published file it started from, `based_on`), or the published file is the one this PC itself last
  committed (`sent`). That keeps a mapping run's rounds, and what a PC published and then added, across a restart.
- Once the repository's copy is another one, it replaces the PC's file, including whatever that PC had not published.
  The next save builds on the published map and overwrites the file.
- A map file from before this rule records neither digest, so it loses to a published map.
- Where no map is published (or no knowledge base is set up), the PC's own file is the map, as before.
- `based_on` and `sent` stay on the PC; they are never published.

**Consequences.** A PC without the write token keeps its own mapping work only until someone publishes a map of that
portal. Settings → Portals shows "from the knowledge base" whenever the published map is the one in use, and offers
**Publish now** and **Start over** only for a map of this PC's own. Catalog retirement
([decision](2026-11-02-retire-portal-catalogs.md)) counts the map in use by the same rule.

**Evidence.** `tests/unit/test_portal_map.py`: the published map replaces an older file and a file with unpublished
work; work saved on top of it is kept while it is unchanged; what this PC published and saved since survives the sync
that brings its own commit back, also after a later publish failed; the two digests are not in the published file.
