# 2026-11-04 — A prompt queue: the person's questions one after another, overnight

**Owner:** project owner. **Status:** decided (4 November 2026).

**Context.** The owner: "Create a new feature in settings: a prompt queuer. I will put in 20 prompts, delimited with ';'
(allow the delimitation to be custom in a dropdown with the most freqeunt ones). And I want it to once it finishes a
prompt, goes to the next one, so I can run overnight. If there's an error, a retry, up to 2 retries per prompt." The task
queue (2026-11-02) runs the Wizard team's tasks; nothing ran the person's own questions in a row.

**Decision.**
- **Settings → Prompt queue.** A box for the prompts and a drop-down of separators, the most used first: semicolon
  (the default), new line, blank line, pipe, three dashes, and Custom (any text up to 40 characters; `\n` is a line
  break). The panel shows how many prompts it found and lists them; the choice is remembered in the browser. **Add to
  queue** appends them (also while the queue runs), **Add and start** starts it. Wizard cuts the text itself
  (`prompt_queue.split`), the same way the panel counts. At most 200 prompts in a queue.
- **Each prompt is a question in a chat of its own**, asked as if the person had typed it (Auto systems, their
  remembered notes), named by Gemini like any new chat, so the answers are in the chat list in the morning. The next
  starts when it ends. A queued question runs in a lane of its own (`runs.PROMPTS_LANE`): the person's own question, a
  task and a mapping round still run beside it.
- **Nobody is waiting.** The request tells Gemini the person is away and to choose where the request leaves something
  open and say so; `wizard_ask_person` is not offered and refuses if called.
- **Retries.** A run that fails is tried again in the same chat (a failed run is not part of the conversation Gemini
  reads), after 1 minute and then 5, at most twice; then the prompt is marked failed with its last reason and the queue
  goes on. A failure no retry mends (`runs.CANNOT_RUN`: Gemini not signed in, the quota used up, no permission) stops the
  queue at that prompt without spending its tries; Continue runs it again. A prompt the person stops in its own chat is
  "stopped by you" and the queue goes on; Stop stops the queue and the question it runs, at no cost to that prompt's
  tries. **Try the failed ones again** puts the failed prompts back with their tries.
- **Overnight.** The queue is kept per person in the data folder (`prompt_queues.json`); while it runs the PC is kept
  awake and the desktop app does not restart its service (`RunManager.busy`). A restart leaves it "interrupted", and
  Continue goes on from that prompt.

**Consequences.**
- Every queued question costs the person's own Gemini quota, like asking it.
- A queued question and the person's own both drive the same Wizard browser when both read a portal at once, as a task
  and a question already may.

**Evidence.** `tests/unit/test_prompt_queue.py` (the separators; three prompts in order, each in its own chat, nobody
asked; two failures then an answer, three failures then the next; a sign-in failure stops it; stop; the person's own
question beside it; limits; a restart); `apps/web/src/components/PromptQueuePanel.test.tsx` (the count per separator,
Add and start, the tries and the failed ones put back); checked in Chromium against the replay runtime.
