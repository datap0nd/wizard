import {useCallback, useEffect, useState} from 'react';
import {ArrowDown, ArrowUp, ListChecks, ListOrdered, ListPlus, Loader2, Play, Square, X} from 'lucide-react';
import {api, ApiError} from '@/api';
import {formatDate} from '@/format';
import {Button} from './ui/button';
import type {QueueItem, TaskItem, TaskQueue, TasksView} from '@/types';

const POLL_MS = 15_000;
const INPUT = 'h-8 w-full rounded-lg border border-line bg-canvas px-2.5 text-[13px] outline-none focus:border-accent';
const PLACEHOLDER = {folder: 'C:\\Users\\you\\Documents\\Presentations', file: 'C:\\Users\\you\\Documents\\Template.potx',
  either: 'A folder, or one file: C:\\Users\\you\\Documents\\Presentations'};
const ICON = 'rounded p-1 text-ink-3 hover:bg-surface-2 hover:text-ink disabled:pointer-events-none disabled:opacity-30 [&_svg]:size-3.5';
/** A queued task still to run: Start or Continue runs the first one; it can move and leave the queue. */
const PENDING: QueueItem['state'][] = ['waiting', 'failed', 'stopped', 'interrupted'];
const ITEM_WORDS: Record<QueueItem['state'], [string, string]> = {
  waiting: ['Waiting', 'text-ink-3'], running: ['Running', 'text-accent'], done: ['Succeeded', 'text-ok'],
  failed: ['Failed', 'text-danger'], stopped: ['Stopped', 'text-ink-2'], interrupted: ['Interrupted', 'text-warn'],
};
const ITEM_LINKS: Record<QueueItem['state'], string> = {
  waiting: '', running: 'Watch it', done: 'See what it did', failed: 'See why', stopped: 'See how far it got',
  interrupted: 'See how far it got',
};

/** Where the list comes from: the installed version (owner, 13 Nov 2026: "package the tasks in the app"). */
function where(view: TasksView): string {
  return `The tasks that came with ${view.version ? `Wizard ${view.version}` : 'this version'}. New tasks arrive with Wizard's updates (Version and updates, in Settings).`;
}

function files(task: TaskItem): string {
  const p = task.progress;
  return p ? `${p.done} of ${p.total} file${p.total === 1 ? '' : 's'} done` : '';
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;
const watch = (conversation: string | null) => conversation ? `?c=${encodeURIComponent(conversation)}` : null;

function Status({task}: {task: TaskItem}) {
  const href = watch(task.conversation_id);
  const link = (label: string) => href ? <> · <a className="underline" href={href}>{label}</a></> : null;
  const count = files(task);
  if (task.state === 'running') {
    const round = task.every_file && task.round ? `Round ${task.round}`
      : task.max_runs ? (task.message ?? `Run ${task.round ?? 1} of up to ${task.max_runs}`) : 'Running';
    return <p className="flex items-center gap-1.5 text-xs text-ink-2"><Loader2 className="size-3 animate-spin" />
      {round}{count ? ` · ${count}` : ''}{link('Watch it')}</p>;
  }
  if (task.state === 'done') return <p className="text-xs text-emerald-700">{task.message ?? `Done${task.at ? ` ${formatDate(task.at, true)}` : ''}`}
    {link('See what it did')}</p>;
  if (task.state === 'failed') return <p className="text-xs text-danger">{(task.every_file || task.max_runs) && task.message ? task.message : `Failed${task.message ? `: ${task.message}` : ''}`}
    {link('See why')}</p>;
  if (task.state === 'stopped') return <p className="text-xs text-ink-3">{task.message ?? 'Stopped'}{link('See how far it got')}</p>;
  return null;
}

/** Where the queue is, in a line: what runs now, or, when the person comes back, how it ended and where it stopped. */
function QueueStatus({queue}: {queue: TaskQueue}) {
  const current = queue.items.find(i => i.key === queue.current) ?? null;
  const href = current && watch(current.conversation_id);
  const times = queue.started_at ? ` Started ${formatDate(queue.started_at, true)}${queue.finished_at ? `, ended ${formatDate(queue.finished_at, true)}` : ''}.` : '';
  if (queue.state === 'ready') return <p className="text-xs text-ink-2">{plural(queue.total, 'task')} in this order, not started yet.
    Press Start: each runs only when the one before succeeded.</p>;
  if (queue.state === 'running') return <p className="flex flex-wrap items-center gap-x-1.5 text-xs text-ink-2">
    <Loader2 className="size-3 animate-spin" />Running {queue.position} of {queue.total}: <span className="font-medium text-ink">{current?.title}</span>
    {current?.message ? <span>· {current.message}</span> : null}
    {href ? <>· <a className="underline" href={href}>Watch it</a></> : null}</p>;
  if (queue.state === 'done') return <p className="text-xs text-ok">{queue.message}{times}</p>;
  if (queue.state === 'empty') return <p className="text-xs text-ink-3">Nothing to run.</p>;
  const tone = queue.state === 'failed' ? 'text-danger' : queue.state === 'interrupted' ? 'text-warn' : 'text-ink-2';
  return <p className={`text-xs ${tone}`}>{queue.message} {queue.done} of {queue.total} done.{times}</p>;
}

function QueuePanel({queue, busy, act}: {queue: TaskQueue; busy: string | null; act: (key: string, call: () => Promise<TasksView>) => void}) {
  const running = queue.state === 'running';
  const resumable = queue.state === 'failed' || queue.state === 'stopped' || queue.state === 'interrupted';
  const pending = (item: QueueItem | undefined) => Boolean(item && PENDING.includes(item.state));
  return (
    <section className="space-y-2 rounded-lg border border-line bg-surface/50 p-3" aria-label="Task queue" data-testid="task-queue">
      <div className="flex items-center gap-2">
        <p className="min-w-0 flex-1 text-[13px] font-medium">Queue</p>
        {queue.state === 'ready' && <Button size="xs" variant="accent" onClick={() => act('start', api.startQueue)} disabled={busy !== null}
          data-testid="queue-start">{busy === 'start' ? <Loader2 className="animate-spin" /> : <Play />}Start</Button>}
        {resumable && <Button size="xs" variant="accent" onClick={() => act('start', api.startQueue)} disabled={busy !== null}
          data-testid="queue-continue">{busy === 'start' ? <Loader2 className="animate-spin" /> : <Play />}Continue</Button>}
        {running && <Button size="xs" variant="outline" onClick={() => act('stop', api.stopQueue)} disabled={busy !== null}
          data-testid="queue-stop">{busy === 'stop' ? <Loader2 className="animate-spin" /> : <Square />}Stop</Button>}
        {!running && queue.items.length > 0 && <Button size="xs" variant="ghost" onClick={() => act('clear', api.clearQueue)}
          disabled={busy !== null} data-testid="queue-clear"><X />Clear</Button>}
      </div>
      <div data-testid="queue-status"><QueueStatus queue={queue} /></div>
      {queue.left_out.length > 0 && (
        <div className="rounded-md bg-warn-soft px-2.5 py-1.5 text-xs text-warn" data-testid="queue-left-out">
          Left out: {queue.left_out.map((o, n) => <span key={o.id}>{n ? '; ' : ''}<span className="font-medium">{o.title}</span> ({o.reason})</span>)}.
        </div>
      )}
      {queue.items.length > 0 && (
        <ol className="space-y-1.5">
          {queue.items.map((item, n) => {
            const [word, tone] = ITEM_WORDS[item.state];
            const href = watch(item.conversation_id);
            const movable = pending(item);
            return (
              <li key={item.key} className="flex items-start gap-2 text-xs" data-testid={`queued-${item.id}`}>
                <span className="w-5 shrink-0 pt-0.5 text-right tabular-nums text-ink-3">{n + 1}.</span>
                <div className="min-w-0 flex-1 pt-0.5">
                  <p><span className="font-medium text-ink">{item.title}</span> · <span className={tone}>{word}</span>
                    {item.finished_at && item.state !== 'waiting' ? <span className="text-ink-3"> {formatDate(item.finished_at, true)}</span> : null}
                    {href && ITEM_LINKS[item.state] ? <> · <a className="underline" href={href}>{ITEM_LINKS[item.state]}</a></> : null}</p>
                  {item.message && <p className="text-ink-3">{item.message}</p>}
                  {item.path && <p className="truncate text-[11px] text-ink-3" title={item.path}>{item.path}</p>}
                </div>
                {movable && (
                  <div className="flex shrink-0 items-center">
                    <button type="button" className={ICON} aria-label={`Move ${item.title} up`} disabled={busy !== null || !pending(queue.items[n - 1])}
                      onClick={() => act('move', () => api.moveQueued(item.key, -1))}><ArrowUp /></button>
                    <button type="button" className={ICON} aria-label={`Move ${item.title} down`} disabled={busy !== null || !pending(queue.items[n + 1])}
                      onClick={() => act('move', () => api.moveQueued(item.key, 1))}><ArrowDown /></button>
                    <button type="button" className={ICON} aria-label={`Remove ${item.title} from the queue`} disabled={busy !== null}
                      onClick={() => act('remove', () => api.removeQueued(item.key))}><X /></button>
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

/** Settings → Tasks: work the Wizard team wrote for Gemini, read from GitHub so a new task appears without an update.
 * Run one and it works in a conversation of its own, saving what it produces to the company knowledge base. A task
 * may ask for a folder or file on this PC first; one that goes through every file of a folder runs in rounds until
 * each is done, and Continue picks up where it stopped. Run all, Run selected (the ticked tasks) or Add to queue puts
 * tasks in the queue, oldest first; Start runs them one after another, each only when the one before succeeded. */
export function TasksPanel({active}: {active: boolean}) {
  const [view, setView] = useState<TasksView | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paths, setPaths] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      setView(await api.tasks());
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not read the tasks.');
    }
  }, []);

  useEffect(() => {
    if (active) void load();
  }, [active, load]);

  const queue = view?.queue ?? null;
  const queueRunning = queue?.state === 'running';
  const running = (view?.tasks.some(t => t.state === 'running') ?? false) || queueRunning;
  useEffect(() => {
    if (!active || !running) return undefined;
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [active, running, load]);

  const pathOf = (task: TaskItem) => paths[task.id] ?? task.path ?? '';
  /** The progress shown belongs to the folder chosen last time; another path starts that folder from its own count. */
  const samePath = (task: TaskItem) => pathOf(task).trim().replace(/^"|"$/g, '') === (task.path ?? '');

  async function act(key: string, call: () => Promise<TasksView>, failed = 'That did not work.') {
    setBusy(key);
    try {
      setView(await call());
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : failed);
    } finally {
      setBusy(null);
    }
  }

  const run = (task: TaskItem, fresh = false) =>
    act(task.id, () => api.runTask(task.id, task.input ? {path: pathOf(task), fresh} : {}), 'Could not start the task.');

  /** The path box of every task that asks for one: Run all and Run selected queue such a task only with its path. */
  function typedPaths(): Record<string, string> {
    return Object.fromEntries((view?.tasks ?? []).filter(t => t.input && pathOf(t).trim()).map(t => [t.id, pathOf(t)]));
  }

  const listed = new Set(view?.tasks.map(t => t.id) ?? []);
  const selected = (queue?.selected ?? []).filter(id => listed.has(id));
  function tick(task: TaskItem, on: boolean) {
    const next = on ? [...selected, task.id] : selected.filter(id => id !== task.id);
    setView(current => current && current.queue ? {...current, queue: {...current.queue, selected: next}} : current);
    void api.selectTasks(next).catch(e => setError(e instanceof ApiError ? e.message : 'Could not keep the ticks.'));
  }

  function label(task: TaskItem): string {
    const progress = samePath(task) ? task.progress : null;
    if (progress && progress.done > 0 && progress.left > 0) return 'Continue';
    return task.state === 'todo' ? 'Run' : 'Run again';
  }

  if (!view) return error ? <p className="text-xs text-danger" role="alert">{error}</p> : <p className="text-xs text-ink-3">Loading…</p>;
  const inQueue = new Map((queue?.items ?? []).filter(i => i.state === 'waiting' || i.state === 'running')
    .map(i => [i.id, queue!.items.indexOf(i) + 1]));
  return (
    <div className="space-y-3" data-testid="tasks-panel">
      <p className="text-[11.5px] text-ink-3" data-testid="tasks-source">{where(view)}</p>
      {!view.can_save && <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">Add the knowledge base's write token
        (Knowledge base, above) so a task can save what it produces.</p>}
      {error && <p className="text-xs text-danger" role="alert">{error}</p>}
      {view.tasks.length > 0 && queue && (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="xs" variant="outline" onClick={() => void act('all', () => api.fillQueue(null, typedPaths()))}
            disabled={busy !== null || queueRunning} data-testid="queue-all">
            {busy === 'all' ? <Loader2 className="animate-spin" /> : <ListOrdered />}Run all</Button>
          <Button size="xs" variant="outline" onClick={() => void act('selected', () => api.fillQueue(selected, typedPaths()))}
            disabled={busy !== null || queueRunning || selected.length === 0} data-testid="queue-selected">
            {busy === 'selected' ? <Loader2 className="animate-spin" /> : <ListChecks />}Run selected{selected.length ? ` (${selected.length})` : ''}</Button>
          <p className="min-w-56 flex-1 text-[11px] text-ink-3">
            {queueRunning ? 'The queue is running: add a task to it, or stop it to run another one.'
              : 'Queues them oldest first; reorder them, then press Start. Each runs only when the one before succeeded.'}</p>
        </div>
      )}
      {queue && (queue.state !== 'empty' || queue.left_out.length > 0) && <QueuePanel queue={queue} busy={busy} act={(k, c) => void act(k, c)} />}
      {view.tasks.length === 0 && <p className="text-xs text-ink-3">No tasks right now.</p>}
      {view.tasks.map(task => {
        const isRunning = task.state === 'running';
        const progress = samePath(task) ? task.progress : null;
        const needsPath = Boolean(task.input) && !pathOf(task).trim();
        const action = label(task);
        const place = inQueue.get(task.id);
        return (
          <div key={task.id} className="space-y-2 rounded-lg border border-line p-3" data-testid={`task-${task.id}`}>
            <div className="flex items-start gap-3">
              {queue && <input type="checkbox" className="mt-0.5 size-4 shrink-0 cursor-pointer accent-accent" checked={selected.includes(task.id)}
                onChange={e => tick(task, e.target.checked)} aria-label={`Select ${task.title}`} data-testid={`select-${task.id}`} />}
              <div className="min-w-0 flex-1 space-y-1">
                <p className="text-[13px] font-medium">{task.title}
                  {place ? <span className="ml-1.5 rounded bg-accent-soft px-1.5 py-0.5 text-[10.5px] font-normal text-accent">In the queue, {place}</span> : null}</p>
                {task.summary && <p className="text-xs text-ink-3">{task.summary}</p>}
                {task.max_runs ? <p className="text-[11px] text-ink-3">Runs again until it is done, up to {plural(task.max_runs, 'run')}.</p> : null}
                <Status task={task} />
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {queue && <Button size="xs" variant="ghost" onClick={() => void act(`queue-${task.id}`, () => api.queueTask(task.id, task.input ? pathOf(task) : undefined))}
                  disabled={busy !== null || needsPath || place !== undefined} title="Add to queue" aria-label={`Add ${task.title} to the queue`}
                  data-testid={`queue-${task.id}`}>{busy === `queue-${task.id}` ? <Loader2 className="animate-spin" /> : <ListPlus />}</Button>}
                <Button size="xs" variant="outline" onClick={() => void run(task, Boolean(task.every_file && progress && progress.left === 0))}
                  disabled={busy !== null || isRunning || needsPath || queueRunning} data-testid={`run-${task.id}`}>
                  {busy === task.id ? <Loader2 className="animate-spin" /> : <Play />}{action}</Button>
              </div>
            </div>
            {task.input && (
              <div className="space-y-1">
                <label className="block text-[11.5px] text-ink-2" htmlFor={`path-${task.id}`}>{task.input_label ?? 'The folder'}</label>
                <input id={`path-${task.id}`} className={INPUT} value={pathOf(task)} placeholder={PLACEHOLDER[task.input]}
                  onChange={e => setPaths(current => ({...current, [task.id]: e.target.value}))} disabled={isRunning}
                  spellCheck={false} data-testid={`path-${task.id}`} />
                <p className="text-[11px] text-ink-3">
                  In File Explorer, right-click the {task.input === 'file' ? 'file' : 'folder'} and choose Copy as path, then paste it here.
                  {task.every_file && progress && !isRunning && <> {files(task)}.{progress.done > 0 && progress.left > 0 && <> <button type="button"
                    className="underline" onClick={() => void run(task, true)} disabled={busy !== null} data-testid={`fresh-${task.id}`}>
                    Start over</button></>}</>}
                </p>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
