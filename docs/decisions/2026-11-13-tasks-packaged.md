# 2026-11-13 — The tasks come packaged with the app

**Owner:** project owner. **Status:** decided (13 November 2026). Supersedes, in
[2026-10-31-tasks.md](2026-10-31-tasks.md), that Wizard reads the `tasks/` folder from GitHub at runtime.

**Context.** The owner: "can you package the tasks in the app? I cant read the tasks, I believe there's an issue in
reading tasks. Checking for updates work, but checking for tasks doesnt." Settings → Tasks read the repository's
`tasks/` folder from api.github.com with Wizard's own connection, one route with no other way round. The update check
has three: api.github.com, the release's own download host, and Check with Windows, which WizardBar sends through
Windows' proxy settings with the person's proxy sign-in. On the work network the update gets through and the task list
does not. The bundled copy was only a fallback, and a list GitHub had given once was kept in its place.

**Decision.**
- Settings → Tasks lists the `tasks/` folder of the installed version, and nothing else. It reads nothing from the
  network, so it does not depend on GitHub, the proxy or a rate limit. The payload already carries the folder
  (`scripts/build_desktop_payload.py` ships every tracked file but tests, docs and sources).
- A new or changed task reaches a PC with an update: every push to `main` releases (CLAUDE.md), and Wizard's update
  works where the task list did not. The section says which version its tasks came with and points to Version and
  updates; its Check for new tasks button is gone.
- Nothing else changes: a task is still one Markdown file in `tasks/`, runs from Settings → Tasks, and saves only to
  the company knowledge base. A list kept from GitHub on a PC (`tasks/cache.json` in Wizard's data folder) is no longer
  read.

**Evidence.** `tests/unit/test_tasks.py` (the list is the installed folder, newest first, without the README or files
that are not tasks; a task added by an update appears at once; no network connection is made; the payload carries the
folder); the task, task-file and queue tests run on the installed list; `apps/web/src/components/TasksPanel.test.tsx`
(the section names the version its tasks came with, no Check for new tasks).
