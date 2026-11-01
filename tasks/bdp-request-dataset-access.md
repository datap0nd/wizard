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
2. Read portal_guide(system=bdp). Its `access_request_form` says which answers the person saved (`saved_labels`),
   which requests are already prepared (`prepared_requests.tables`), and which of those open only the catalog's start
   page (`prepared_requests.to_prepare_again`, from an earlier run). If no answers are saved, still prepare the
   requests, and say at the end that Settings → Portals → Access request form needs their answers first.
3. Go down the list in rank order. Skip a dataset that is already prepared (unless it is in `to_prepare_again`), and
   one the person already has access to: check the ones marked `lacks` or `unknown` again the same way the list was made (what the catalog
   says, or one Superset query that reads no data; a permission error means no access).
4. Find out once how a dataset's page is reached, with portal_run: open one dataset from the list, look, and see
   whether the address changes when it opens (`page.url`), and what the control that opens the request form says (for
   example Request access). `access_request_form.form_pages_seen` shows where request forms appeared before. Never
   press that control yourself: Wizard refuses it.
5. For each of the first 50 that the person lacks, call portal_request_access with:
   - `system`: bdp
   - `address`: the dataset's own page in the catalog (where the control that opens the request form is), never the
     catalog's start page: Wizard refuses that for a table, because the person would have to find it themselves.
   - only if the catalog keeps one address whatever dataset is open: `open_steps`, the steps from that address to the
     dataset's page (fill the catalog's search with its name, press Enter, click the result), run exactly as given
     with portal_run first for this dataset and seen to end on its page.
   - `form_button`: the text of the control on that page that opens the request form.
   - `tables`: the dataset's full name as the catalog shows it.
   - `answers`: none, unless the form asks for something about this dataset that the saved answers do not cover. Never
     send an answer for a field the person saved: theirs is used.
   When the list says the catalog takes several datasets in one request (a cart, or one form with several tables),
   prepare one request per group of up to 20 instead, at the page where that request starts, and say so at the end.
   A request prepared before for the same dataset and not opened yet is replaced by the new one in its place, so
   requests from an earlier run that opened only the catalog's start page are fixed by preparing them again.
6. Update the list's topic (portal_map_save, the same topic id and title, every line kept): mark each dataset you
   prepared `access: request prepared <today's date>`, and correct `access` for the ones you found the person has.

Rules: never request access yourself (Wizard refuses it), never read data rows, change no knowledge note. End with the
number of requests prepared, the datasets skipped because the person has them or they were already prepared, any that
could not be prepared and why, and this for the person: "Open Settings → Portals → Prepared requests and press Open
the next request. Wizard opens each dataset's page and its request form and fills it; check every field, press Submit,
then press Next request in Wizard's note at the bottom of the page."
