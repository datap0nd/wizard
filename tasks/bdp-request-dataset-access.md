---
id: bdp-request-dataset-access
title: Prepare access requests for the 50 most relevant Big Data Portal datasets
summary: Takes the ranked list from "Find the most relevant datasets" and prepares an access request for each of the 50 most relevant datasets this person cannot read yet. Wizard fills the form from the person's saved answers; they check it and press Submit for each one.
added: 2026-11-01
---
Prepare access requests in the Big Data Portal's information catalog (DIS) for the 50 most relevant datasets this
person cannot read yet. You only prepare them: each goes into the person's prepared requests (Settings → Portals),
where Wizard opens the dataset's page in a visible window, fills the request form from their saved answers (the
purpose, the DPA / DSA box's purpose and subsidiary, the subsidiary's address) and they check it and press Submit.

1. Read the ranked list: portal_map(system=bdp, topic=catalog-relevant-datasets), and
   `catalog-relevant-datasets-2` if the first says it continues. If there is no list, stop and say that the task
   "Find the most relevant datasets in the Big Data Portal's information catalog (DIS)" must run first.
2. Read portal_guide(system=bdp). Its `access_request_form` says which answers the person saved (`saved_labels`) and
   which requests are already prepared (`prepared_requests.tables`). If no answers are saved, still prepare the
   requests, and say at the end that Settings → Portals → Access request form needs their answers first.
3. Go down the list in rank order. Skip a dataset that is already in the prepared requests, and one the person already
   has access to: check the ones marked `lacks` or `unknown` again the same way the list was made (what the catalog
   says, or one Superset query that reads no data; a permission error means no access).
4. For each of the first 50 that the person lacks, call portal_request_access with:
   - `system`: bdp
   - `address`: the dataset's own page in the catalog, from the list (where the person presses Request access), or
     the page that opens its request form if the list says so. Open it first (portal_run, look) if you are not sure
     it is the right page, and correct the list's address when it changed.
   - `tables`: the dataset's full name as the catalog shows it.
   - `answers`: none, unless the form asks for something about this dataset that the saved answers do not cover. Never
     send an answer for a field the person saved: theirs is used.
   When the list says the catalog takes several datasets in one request (a cart, or one form with several tables),
   prepare one request per group of up to 20 instead, at the page where that request starts, and say so at the end.
5. Update the list's topic (portal_map_save, the same topic id and title, every line kept): mark each dataset you
   prepared `access: request prepared <today's date>`, and correct `access` for the ones you found the person has.

Rules: never request access yourself (Wizard refuses it), never read data rows, change no knowledge note. End with the
number of requests prepared, the datasets skipped because the person has them or they were already prepared, any that
could not be prepared and why, and this for the person: "Open Settings → Portals → Prepared requests and press Open
the next request. For each dataset: press Request access on its page if the form is not open, check every field Wizard
filled, press Submit, then press Next request in Wizard's note at the bottom of the page."
