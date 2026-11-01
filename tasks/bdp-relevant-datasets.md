---
id: bdp-relevant-datasets
title: Find the most relevant datasets in the Big Data Portal's information catalog (DIS)
summary: Mapping keeps reaching Big Data Portal dashboards whose tables this person cannot read. This ranks the information catalog's datasets by what Wizard's questions, metric notes and blocked dashboards need, records which ones the person lacks, and keeps the list in the Big Data Portal's map for the access request task.
added: 2026-11-01
---
The Big Data Portal (bdp) is two applications: the information catalog (DIS), where tables are found and access is
requested, and Superset, where they are queried. Mapping its dashboards keeps failing on tables this person has no
access to (permission errors such as 403 Access Denied). Find the datasets that matter most, so access can be requested
for them in the task "Prepare access requests for the 50 most relevant Big Data Portal datasets".

Read first:

1. portal_guide(system=bdp): the catalog's and Superset's addresses and how to read them.
2. portal_map(system=bdp), then portal_map(system=bdp, todo=true): the dashboards already mapped and the ones that
   failed or are partial. Their notes name the tables and datasets that were denied: each is a candidate, and the number
   of dashboards it blocks is evidence of its value.
3. The knowledge base: wizard_browse_knowledge for the metric notes and the business areas, wizard_read_knowledge for
   the measures, markets and periods people ask about, and their "Where to get it" sections. A dataset that holds a
   defined measure for the person's markets is a candidate.
4. portal_map for the other configured portals (gscm, asap): a measure people read there may also live in a catalog
   dataset with more detail.

Then explore the information catalog in the background:

- Open its address, look, search for a business word, and read the search request the page sent (`requests`). Send
  that request yourself with other words (`W.replay` with `replace`, or `fetch`) instead of typing into the page. Keep a
  search that works with portal_save_script (name: catalog-search) and describe it in a map topic `catalog-search`
  (portal_map_save): the request, its parameters, paging, and what a result holds.
- Search with the measures and terms from the notes, the names of the denied tables and datasets, and the business
  areas of the blocked dashboards. Open the promising results and read what helps rank them: full name (project,
  dataset, table as the catalog shows it), its page address in the catalog, description, owner, refresh and partitions,
  the markets or regions it covers, its row grain, and how the catalog requests access (per table, per dataset, or
  several at once in a cart or one form).
- Whether this person already has access: what the catalog says, otherwise one Superset query that reads no data
  (`SELECT 1 FROM <table> WHERE FALSE`, in that database's dialect, with a one-day partition filter if the table needs
  one). A permission error means no access. Do not read rows.

Rank the candidates, most relevant first:

1. Needed by dashboards in the map that failed for lack of access (more dashboards rank higher).
2. Holds a measure a metric note defines, or one people ask about, for the person's markets or region.
3. A maintained, documented source (recent refresh, an owner, a description) over a raw log or a personal copy; an
   aggregated mart over its raw source when both hold the measure.
4. Used widely, when the catalog shows it.

One entry per thing the catalog requests access for. Keep at least the 70 best, so 50 remain once those the person
already has are set aside.

Save the list with portal_map_save(system=bdp) as the topic `catalog-relevant-datasets`, titled "The most relevant
datasets in the information catalog". One line per dataset, in rank order, under about 250 characters:
`rank. full name | catalog page address | what it holds | why it ranks here (dashboards, notes) | access: has / lacks / unknown`.
Start the topic with one paragraph: the date, how the ranking was made, and how access is requested in the catalog.
If it does not fit in one topic, continue in `catalog-relevant-datasets-2`. For each failed dashboard whose tables you
found, also update its report in the map (portal_map_save, only its notes) with the catalog names it needs.

Rules: metadata only, never data rows. Never request access: your steps cannot, and the next task only prepares
requests for the person to send. Change no knowledge note. End with how many datasets you ranked, how many the person
lacks, the ten most relevant with one line each, and anything about the catalog the next task needs to know.
