import {useCallback, useEffect, useState} from 'react';
import {Loader2, Play, RefreshCw} from 'lucide-react';
import {api, ApiError} from '@/api';
import {formatDate} from '@/format';
import {Button} from './ui/button';
import type {TaskItem, TasksView} from '@/types';

const POLL_MS = 15_000;
const INPUT = 'h-8 w-full rounded-lg border border-line bg-canvas px-2.5 text-[13px] outline-none focus:border-accent';
const PLACEHOLDER = {folder: 'C:\\Users\\you\\Documents\\Presentations', file: 'C:\\Users\\you\\Documents\\Template.potx',
  either: 'A folder, or one file: C:\\Users\\you\\Documents\\Presentations'};

function where(view: TasksView): string {
  const failed = view.message ? ` GitHub did not answer (${view.message}), so this is the last list Wizard read.` : '';
  if (view.source === 'bundled') return `The tasks that came with this version.${view.message ? ` GitHub did not answer (${view.message}).` : ''}`;
  return `From GitHub${view.checked ? `, checked ${formatDate(new Date(view.checked * 1000).toISOString(), true)}` : ''}.${failed}`;
}

function files(task: TaskItem): string {
  const p = task.progress;
  return p ? `${p.done} of ${p.total} file${p.total === 1 ? '' : 's'} done` : '';
}

function Status({task}: {task: TaskItem}) {
  const watch = task.conversation_id ? `?c=${encodeURIComponent(task.conversation_id)}` : null;
  const link = (label: string) => watch ? <> · <a className="underline" href={watch}>{label}</a></> : null;
  const count = files(task);
  if (task.state === 'running') {
    const round = task.every_file && task.round ? `Round ${task.round}` : 'Running';
    return <p className="flex items-center gap-1.5 text-xs text-ink-2"><Loader2 className="size-3 animate-spin" />
      {round}{count ? ` · ${count}` : ''}{link('Watch it')}</p>;
  }
  if (task.state === 'done') return <p className="text-xs text-emerald-700">{task.message ?? `Done${task.at ? ` ${formatDate(task.at, true)}` : ''}`}
    {link('See what it did')}</p>;
  if (task.state === 'failed') return <p className="text-xs text-danger">{task.every_file && task.message ? task.message : `Failed${task.message ? `: ${task.message}` : ''}`}
    {link('See why')}</p>;
  if (task.state === 'stopped') return <p className="text-xs text-ink-3">{task.message ?? 'Stopped'}{link('See how far it got')}</p>;
  return null;
}

/** Settings → Tasks: work the Wizard team wrote for Gemini, read from GitHub so a new task appears without an update.
 * Run one and it works in a conversation of its own, saving what it produces to the company knowledge base. A task
 * may ask for a folder or file on this PC first; one that goes through every file of a folder runs in rounds until
 * each is done, and Continue picks up where it stopped. */
export function TasksPanel({active}: {active: boolean}) {
  const [view, setView] = useState<TasksView | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paths, setPaths] = useState<Record<string, string>>({});

  const load = useCallback(async (refresh: boolean) => {
    try {
      setView(await api.tasks(refresh));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not read the tasks.');
    }
  }, []);

  useEffect(() => {
    if (active) void load(true);
  }, [active, load]);

  const running = view?.tasks.some(t => t.state === 'running') ?? false;
  useEffect(() => {
    if (!active || !running) return undefined;
    const timer = window.setInterval(() => void load(false), POLL_MS);
    return () => window.clearInterval(timer);
  }, [active, running, load]);

  const pathOf = (task: TaskItem) => paths[task.id] ?? task.path ?? '';
  /** The progress shown belongs to the folder chosen last time; another path starts that folder from its own count. */
  const samePath = (task: TaskItem) => pathOf(task).trim().replace(/^"|"$/g, '') === (task.path ?? '');

  async function run(task: TaskItem, fresh = false) {
    setBusy(task.id);
    try {
      setView(await api.runTask(task.id, task.input ? {path: pathOf(task), fresh} : {}));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not start the task.');
    } finally {
      setBusy(null);
    }
  }

  function label(task: TaskItem): string {
    const progress = samePath(task) ? task.progress : null;
    if (progress && progress.done > 0 && progress.left > 0) return 'Continue';
    return task.state === 'todo' ? 'Run' : 'Run again';
  }

  if (!view) return error ? <p className="text-xs text-danger" role="alert">{error}</p> : <p className="text-xs text-ink-3">Loading…</p>;
  return (
    <div className="space-y-3" data-testid="tasks-panel">
      <div className="flex items-center gap-2">
        <p className="min-w-0 flex-1 text-[11.5px] text-ink-3">{where(view)}</p>
        <Button size="xs" variant="ghost" onClick={() => { setBusy('refresh'); void load(true).finally(() => setBusy(null)); }} disabled={busy !== null}>
          {busy === 'refresh' ? <Loader2 className="animate-spin" /> : <RefreshCw />}Check for new tasks</Button>
      </div>
      {!view.can_save && <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">Add the knowledge base's write token
        (Knowledge base, above) so a task can save what it produces.</p>}
      {error && <p className="text-xs text-danger" role="alert">{error}</p>}
      {view.tasks.length === 0 && <p className="text-xs text-ink-3">No tasks right now.</p>}
      {view.tasks.map(task => {
        const isRunning = task.state === 'running';
        const progress = samePath(task) ? task.progress : null;
        const needsPath = Boolean(task.input) && !pathOf(task).trim();
        const action = label(task);
        return (
          <div key={task.id} className="space-y-2 rounded-lg border border-line p-3" data-testid={`task-${task.id}`}>
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1 space-y-1">
                <p className="text-[13px] font-medium">{task.title}</p>
                {task.summary && <p className="text-xs text-ink-3">{task.summary}</p>}
                <Status task={task} />
              </div>
              <Button size="xs" variant="outline" onClick={() => void run(task, Boolean(task.every_file && progress && progress.left === 0))}
                disabled={busy !== null || isRunning || needsPath} data-testid={`run-${task.id}`}>
                {busy === task.id ? <Loader2 className="animate-spin" /> : <Play />}{action}</Button>
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
