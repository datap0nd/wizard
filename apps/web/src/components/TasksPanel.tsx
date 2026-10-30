import {useCallback, useEffect, useState} from 'react';
import {Loader2, Play, RefreshCw} from 'lucide-react';
import {api, ApiError} from '@/api';
import {formatDate} from '@/format';
import {Button} from './ui/button';
import type {TaskItem, TasksView} from '@/types';

const POLL_MS = 15_000;

function where(view: TasksView): string {
  const failed = view.message ? ` GitHub did not answer (${view.message}), so this is the last list Wizard read.` : '';
  if (view.source === 'bundled') return `The tasks that came with this version.${view.message ? ` GitHub did not answer (${view.message}).` : ''}`;
  return `From GitHub${view.checked ? `, checked ${formatDate(new Date(view.checked * 1000).toISOString(), true)}` : ''}.${failed}`;
}

function Status({task}: {task: TaskItem}) {
  const watch = task.conversation_id ? `?c=${encodeURIComponent(task.conversation_id)}` : null;
  const link = (label: string) => watch ? <> · <a className="underline" href={watch}>{label}</a></> : null;
  if (task.state === 'running') return <p className="flex items-center gap-1.5 text-xs text-ink-2"><Loader2 className="size-3 animate-spin" />Running{link('Watch it')}</p>;
  if (task.state === 'done') return <p className="text-xs text-emerald-700">Done{task.at ? ` ${formatDate(task.at, true)}` : ''}{link('See what it did')}</p>;
  if (task.state === 'failed') return <p className="text-xs text-danger">Failed{task.message ? `: ${task.message}` : ''}{link('See why')}</p>;
  if (task.state === 'stopped') return <p className="text-xs text-ink-3">Stopped{link('See how far it got')}</p>;
  return null;
}

/** Settings → Tasks: work the Wizard team wrote for Gemini, read from GitHub so a new task appears without an update.
 * Run one and it works in a conversation of its own, saving what it produces to the company knowledge base. */
export function TasksPanel({active}: {active: boolean}) {
  const [view, setView] = useState<TasksView | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  async function run(task: TaskItem) {
    setBusy(task.id);
    try {
      setView(await api.runTask(task.id));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not start the task.');
    } finally {
      setBusy(null);
    }
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
      {view.tasks.map(task => (
        <div key={task.id} className="flex items-start gap-3 rounded-lg border border-line p-3" data-testid={`task-${task.id}`}>
          <div className="min-w-0 flex-1 space-y-1">
            <p className="text-[13px] font-medium">{task.title}</p>
            {task.summary && <p className="text-xs text-ink-3">{task.summary}</p>}
            <Status task={task} />
          </div>
          <Button size="xs" variant="outline" onClick={() => void run(task)} disabled={busy !== null || task.state === 'running'}
            data-testid={`run-${task.id}`}>
            {busy === task.id ? <Loader2 className="animate-spin" /> : <Play />}{task.state === 'todo' ? 'Run' : 'Run again'}</Button>
        </div>
      ))}
    </div>
  );
}
