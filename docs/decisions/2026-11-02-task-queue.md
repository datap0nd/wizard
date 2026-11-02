# 2026-11-02 — A task queue: tasks run one after another, and a task may repeat until done

**Owner:** project owner. **Status:** decided (2 November 2026).

**Context.** Settings → Tasks ran one task at a time from its **Run** button ([decision](2026-10-31-tasks.md)). The
knowledge-base review is seven numbered tasks (`kb-review-1-…` to `kb-review-7-…`) meant to run in order, several of
which say "run it again until it finds none", so the person had to come back after each run to start the next. The
owner: "I need something new, a task queuer. It should allow me to run tasks in a sequence. A 'run all tasks' button,
where I can run and it goes from one to another (only when all of them succeeded)." And later the same day: "Also,
allow me to choose which ones I can run on a batch sequence, if I can tick like 5 of them and click run selected tasks,
that would be helpful, so I can go to lunch and leave them running." Earlier the owner had decided against running two
tasks at the same time: one task at a time per person stays.

**Options.** (1) Start every task at once: against the owner's one-task-at-a-time decision, and a later review step
would read notes an earlier one is still changing. (2) A queue per person that starts the next task when the one
before ended **succeeded**, kept on the PC so it outlives a restart. (3) One long run that does every task's
instructions in turn: a single run's tool calls and time limit would not cover seven reviews, and one failure would
lose the lot.

**Decision.** Option 2.
- **Filling the queue.** Settings → Tasks has **Run all** (every task), **Run selected** (the tasks ticked in the
  list) and, on each task, **Add to queue**. Run all and Run selected put the tasks in run order: oldest `added` first,
  then id ascending, so the numbered reviews run 1 → 7. The queue panel shows them in order with up, down and remove;
  nothing runs until **Start**, so the order can be checked first (the same for Run all and Run selected). A task
  added while the queue runs goes at the end. Ticks are kept for the person on this PC until the queue starts.
- **Tasks that ask for a path** (`input:`) are queued only with one: the path box's value, checked as a single Run
  checks it. Run all and Run selected leave out a path task with no path, or one whose path does not pass, and say
  which and why; a task that goes through every file of a folder already done is left out too.
- **Running.** Start runs the first task as **Run** would (its own conversation, **Watch it**). When it ends
  succeeded, the next starts; a task that goes through every file advances only after its last round ends done. When
  one fails, is stopped, or is cancelled in its conversation, the queue stops there and says which task and why;
  **Continue** runs that task again and goes on, **Clear** empties the queue, **Stop** stops the running task and the
  queue. While the queue runs, a single Run is refused (one task at a time); the queue shows "Running n of m" with the
  task, its round or run, and Watch it.
- **Coming back.** The panel keeps the result until Clear or a new queue: each task with Succeeded, Failed, Stopped,
  Waiting or Interrupted, when it ended, a link to its conversation (See what it did, See why), and a line saying how
  the queue ended ("All 7 tasks succeeded.", or "Stopped at “…”, which failed: …").
- **Repeat until done.** A task may declare `repeat: until_done` (optional `max_runs`, default 5, at most 10). Its
  frame asks Gemini to end the summary with `Left: <number>` (what remains, 0 when done). After a run succeeds, Wizard
  runs it again, a fresh run in the same conversation, while Left is above 0, the run saved at least one note or map
  change, and `max_runs` is not reached; then the task is done and the queue moves on. A summary without a Left line
  counts as done; a repeat that fails fails the task. A single Run repeats the same way. The task shows "Run 2 of up
  to 5". A task that goes through every file already runs until each file is done, so `repeat` does not apply to it.
- **Unattended.** The queue holds the PC's keep-awake request (`awake.py`, as each run does) from Start until it ends,
  so the PC does not sleep between two tasks. A running queue counts as busy: the desktop app does not restart its
  service for a new knowledge-base snapshot (nor to apply saved settings) until the queue ends.
- **Restarts.** The queue is kept per person in the data folder (`data\tasks\queues.json`). When the service restarts
  anyway (a crash, an update, Restart Wizard), the queue shows "Interrupted at “…”" with Continue, which runs that task
  again and goes on.

**Consequences.**
- The queue adds no tool and no new write: each task runs exactly as its Run button runs it, under the person's own
  identity and write token.
- A queue of reviews can take hours; it keeps the PC awake and delays a knowledge-base restart for that long. Stop ends
  both.
- Settings saved while a queue runs apply when it ends, not after the running task.
- The Left line is Gemini's own count. A missing or wrong count ends the repeats early (counted as done) rather than
  looping; `max_runs` and the progress check bound a count that never reaches 0.

**Evidence.** `tests/unit/test_task_queue.py`: run order (default and reordered), success advances, a failure, Stop
and a run cancelled in its conversation stop the queue and Continue resumes from that task, ticks kept until Start, a
task added while it runs, the PC kept awake from Start to the end, path tasks queued only with a checked path and left
out with the reason, a path gone when its turn comes, a folder task that hands on only after its last round, the
`repeat` front matter and the Left line, repeats while work is left and progress is made, no progress, `max_runs`, a
missing Left line, a failed repeat stopping the queue, a restart and a crash leaving the queue interrupted with
Continue, a running queue keeping the desktop service from restarting, the queue only for the person at their own PC.
`apps/web/src/components/TasksPanel.test.tsx`: Run all with what it left out, Start and progress, ticks kept and Run
selected with paths, reorder, remove and Add to queue, a failed queue with Continue, an interrupted one with Clear,
Stop.
