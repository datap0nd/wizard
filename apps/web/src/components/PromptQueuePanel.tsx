import {useCallback, useEffect, useMemo, useState} from 'react';
import {ArrowDown, ArrowUp, ListPlus, Loader2, Play, RotateCcw, Square, X} from 'lucide-react';
import {api, ApiError} from '@/api';
import {formatDate} from '@/format';
import {Button} from './ui/button';
import type {PromptItem, PromptQueue, PromptSeparator} from '@/types';

const POLL_MS = 10_000;
const KEPT = 'wizard.promptSeparator';
const ICON = 'rounded p-1 text-ink-3 hover:bg-surface-2 hover:text-ink disabled:pointer-events-none disabled:opacity-30 [&_svg]:size-3.5';
const BOX = 'rounded-lg border border-line bg-canvas px-2.5 text-[13px] outline-none focus:border-accent disabled:bg-surface';
/** The separators people use most, first; Custom takes their own. */
export const SEPARATORS: {id: PromptSeparator; label: string; example: string}[] = [
  {id: 'semicolon', label: 'Semicolon ( ; )', example: 'First question; second question; third question'},
  {id: 'newline', label: 'New line (one per line)', example: 'First question\nSecond question\nThird question'},
  {id: 'blank_line', label: 'Blank line between prompts', example: 'First question, which may\ntake several lines\n\nSecond question'},
  {id: 'pipe', label: 'Pipe ( | )', example: 'First question | second question | third question'},
  {id: 'dashes', label: 'Three dashes ( --- )', example: 'First question\n---\nSecond question'},
  {id: 'custom', label: 'Custom…', example: 'Type the separator to the right'},
];
const MARKS: Partial<Record<PromptSeparator, string>> = {semicolon: ';', pipe: '|', dashes: '---'};
const PENDING: PromptItem['state'][] = ['waiting', 'stopped', 'interrupted'];
const WORDS: Record<PromptItem['state'], [string, string]> = {
  waiting: ['Waiting', 'text-ink-3'], running: ['Running', 'text-accent'], retry_wait: ['Waiting to try again', 'text-warn'],
  done: ['Answered', 'text-ok'], failed: ['Failed', 'text-danger'], skipped: ['Stopped by you', 'text-ink-2'],
  stopped: ['Stopped', 'text-ink-2'], interrupted: ['Interrupted', 'text-warn'],
};

/** The prompts in the text, as Wizard cuts them (prompt_queue.split): at the separator, trimmed, empty ones dropped. */
export function splitPrompts(text: string, separator: PromptSeparator, custom = ''): string[] {
  const clean = text.replace(/\r\n?/g, '\n');
  let parts: string[];
  if (separator === 'custom') {
    const mark = custom.replace(/\\n/g, '\n');
    if (!mark.replace(/ /g, '')) return [];
    parts = clean.split(mark);
  } else if (separator === 'newline') parts = clean.split('\n');
  else if (separator === 'blank_line') parts = clean.split(/\n[ \t]*\n/);
  else parts = clean.split(MARKS[separator] ?? ';');
  return parts.map(p => p.trim()).filter(Boolean);
}

function kept(): PromptSeparator {
  try {
    const value = window.localStorage.getItem(KEPT);
    if (value && SEPARATORS.some(s => s.id === value)) return value as PromptSeparator;
  } catch { /* storage off: the default */ }
  return 'semicolon';
}

function keep(separator: PromptSeparator) {
  try { window.localStorage.setItem(KEPT, separator); } catch { /* storage off: not remembered */ }
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;
const chat = (conversation: string | null) => conversation ? `?c=${encodeURIComponent(conversation)}` : null;
const LINKS: Partial<Record<PromptItem['state'], string>> = {
  running: 'Watch it', retry_wait: 'See why', done: 'Read the answer', failed: 'See why', skipped: 'Open the chat',
  stopped: 'Open the chat', interrupted: 'Open the chat',
};

function QueueStatus({queue}: {queue: PromptQueue}) {
  const current = queue.items.find(i => i.key === queue.current) ?? null;
  const times = queue.started_at ? ` Started ${formatDate(queue.started_at, true)}${queue.finished_at ? `, ended ${formatDate(queue.finished_at, true)}` : ''}.` : '';
  if (queue.state === 'ready') return <p className="text-xs text-ink-2">{plural(queue.total, 'prompt')}, not started yet. Press
    Start: each is asked in a chat of its own, the next when it ends, and one that fails is tried again up to {queue.max_retries} times.</p>;
  if (queue.state === 'running') return <p className="flex flex-wrap items-center gap-x-1.5 text-xs text-ink-2">
    <Loader2 className="size-3 animate-spin" />{current?.state === 'retry_wait' ? 'Waiting to try again' : 'Running'} {queue.position} of {queue.total}
    {queue.done ? <span>· {queue.done} answered</span> : null}{queue.failed ? <span className="text-danger">· {queue.failed} failed</span> : null}</p>;
  if (queue.state === 'done') return <p className="text-xs text-ok">{queue.message}{times}</p>;
  if (queue.state === 'empty') return <p className="text-xs text-ink-3">No prompts yet.</p>;
  const tone = queue.state === 'failed' ? 'text-danger' : queue.state === 'interrupted' ? 'text-warn' : 'text-ink-2';
  return <p className={`text-xs ${tone}`}>{queue.message} {queue.done} of {queue.total} answered.{times}</p>;
}

/** Settings → Prompt queue (owner, 4 Nov 2026: "I will put in 20 prompts ... so I can run overnight"). Paste the prompts,
 * cut by the separator chosen; Start asks each in a chat of its own, the next when it ends; a prompt that fails is tried
 * again up to twice (after a minute, then five), then the queue goes on. The chats are in the list in the morning. */
export function PromptQueuePanel({active}: {active: boolean}) {
  const [queue, setQueue] = useState<PromptQueue | null>(null);
  const [text, setText] = useState('');
  const [separator, setSeparator] = useState<PromptSeparator>(kept);
  const [custom, setCustom] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setQueue(await api.promptQueue()); setError(null); }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Could not read the prompt queue.'); }
  }, []);

  useEffect(() => { if (active) void load(); }, [active, load]);
  const running = queue?.state === 'running';
  useEffect(() => {
    if (!active || !running) return undefined;
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [active, running, load]);

  const prompts = useMemo(() => splitPrompts(text, separator, custom), [text, separator, custom]);
  const room = queue ? queue.max_prompts - (queue.state === 'done' ? 0 : queue.items.length) : 200;

  async function act(key: string, call: () => Promise<PromptQueue>, failed = 'That did not work.'): Promise<PromptQueue | null> {
    setBusy(key);
    try {
      const next = await call();
      setQueue(next); setError(null);
      return next;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : failed);
      return null;
    } finally { setBusy(null); }
  }

  async function add(start: boolean) {
    const next = await act(start ? 'add-start' : 'add', () => api.addPrompts(text, separator, custom), 'Could not add the prompts.');
    if (!next) return;
    setText('');
    if (start && next.state !== 'running') await act('add-start', api.startPrompts, 'Could not start the queue.');
  }

  function choose(value: PromptSeparator) { setSeparator(value); keep(value); }

  const resumable = queue && ['failed', 'stopped', 'interrupted'].includes(queue.state)
    && queue.items.some(i => PENDING.includes(i.state));
  const example = SEPARATORS.find(s => s.id === separator)?.example ?? '';
  return (
    <div className="space-y-3" data-testid="prompt-queue">
      {error && <p className="text-xs text-danger" role="alert">{error}</p>}
      <div className="space-y-2">
        <label className="block text-[12px] font-medium" htmlFor="prompt-text">Your prompts</label>
        <textarea id="prompt-text" className={`${BOX} min-h-32 w-full py-2 leading-5`} value={text} onChange={e => setText(e.target.value)}
          placeholder={example} spellCheck data-testid="prompt-text" />
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-[12px] text-ink-2" htmlFor="prompt-separator">Separated by</label>
          <select id="prompt-separator" className={`${BOX} h-8`} value={separator}
            onChange={e => choose(e.target.value as PromptSeparator)} data-testid="prompt-separator">
            {SEPARATORS.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
          {separator === 'custom' && <input className={`${BOX} h-8 w-28 font-mono`} value={custom} maxLength={40}
            onChange={e => setCustom(e.target.value)} placeholder="e.g. ##" aria-label="Custom separator" spellCheck={false}
            data-testid="prompt-custom" />}
          <p className="min-w-40 flex-1 text-[11.5px] text-ink-3" data-testid="prompt-count" role="status">
            {text.trim() ? (prompts.length ? `${plural(prompts.length, 'prompt')}${prompts.length > room ? ` · the queue has room for ${room}` : ''}`
              : separator === 'custom' && !custom.trim() ? 'Type the separator.' : 'No prompt found with this separator.') : ''}</p>
        </div>
        {prompts.length > 1 && (
          <ol className="max-h-28 list-inside list-decimal space-y-0.5 overflow-y-auto rounded-md bg-surface px-3 py-1.5 text-[11.5px] text-ink-2" aria-label="Prompts found">
            {prompts.slice(0, 50).map((p, n) => <li key={n} className="truncate" title={p}>{p}</li>)}
            {prompts.length > 50 && <li className="list-none text-ink-3">and {prompts.length - 50} more</li>}
          </ol>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button size="xs" variant="outline" onClick={() => void add(false)} disabled={busy !== null || !prompts.length || prompts.length > room}
            data-testid="prompt-add">{busy === 'add' ? <Loader2 className="animate-spin" /> : <ListPlus />}Add to queue</Button>
          {!running && <Button size="xs" variant="accent" onClick={() => void add(true)} disabled={busy !== null || !prompts.length || prompts.length > room}
            data-testid="prompt-add-start">{busy === 'add-start' ? <Loader2 className="animate-spin" /> : <Play />}Add and start</Button>}
          <p className="min-w-48 flex-1 text-[11px] text-ink-3">Each prompt is asked in a chat of its own, as if you asked it; nobody
            is asked a question back. Keep Wizard open and the PC on: it stays awake while the queue runs.</p>
        </div>
      </div>
      {queue && queue.state !== 'empty' && (
        <section className="space-y-2 rounded-lg border border-line bg-surface/50 p-3" aria-label="Prompt queue" data-testid="prompt-queue-list">
          <div className="flex flex-wrap items-center gap-2">
            <p className="min-w-0 flex-1 text-[13px] font-medium">Queue</p>
            {queue.state === 'ready' && <Button size="xs" variant="accent" onClick={() => void act('start', api.startPrompts)} disabled={busy !== null}
              data-testid="prompts-start">{busy === 'start' ? <Loader2 className="animate-spin" /> : <Play />}Start</Button>}
            {resumable && <Button size="xs" variant="accent" onClick={() => void act('start', api.startPrompts)} disabled={busy !== null}
              data-testid="prompts-continue">{busy === 'start' ? <Loader2 className="animate-spin" /> : <Play />}Continue</Button>}
            {running && <Button size="xs" variant="outline" onClick={() => void act('stop', api.stopPrompts)} disabled={busy !== null}
              data-testid="prompts-stop">{busy === 'stop' ? <Loader2 className="animate-spin" /> : <Square />}Stop</Button>}
            {queue.failed > 0 && <Button size="xs" variant="outline" onClick={() => void act('retry', api.retryFailedPrompts)} disabled={busy !== null}
              data-testid="prompts-retry-failed">{busy === 'retry' ? <Loader2 className="animate-spin" /> : <RotateCcw />}Try the failed ones again ({queue.failed})</Button>}
            {!running && <Button size="xs" variant="ghost" onClick={() => void act('clear', api.clearPrompts)} disabled={busy !== null}
              data-testid="prompts-clear"><X />Clear</Button>}
          </div>
          <div data-testid="prompts-status"><QueueStatus queue={queue} /></div>
          <ol className="space-y-1.5">
            {queue.items.map((item, n) => {
              const [word, tone] = WORDS[item.state];
              const href = chat(item.conversation_id);
              const pending = PENDING.includes(item.state);
              const movable = (other: PromptItem | undefined) => Boolean(other && PENDING.includes(other.state));
              const tries = item.attempts > 1 || item.state === 'retry_wait' ? ` · try ${item.attempts} of ${queue.max_retries + 1}` : '';
              return (
                <li key={item.key} className="flex items-start gap-2 text-xs" data-testid={`prompt-${item.key}`}>
                  <span className="w-6 shrink-0 pt-0.5 text-right tabular-nums text-ink-3">{n + 1}.</span>
                  <div className="min-w-0 flex-1 pt-0.5">
                    <p className="line-clamp-2 break-words text-ink" title={item.prompt}>{item.prompt}</p>
                    <p><span className={tone}>{item.state === 'running' ? <Loader2 className="mr-1 inline size-3 animate-spin" /> : null}{word}</span>
                      <span className="text-ink-3">{tries}</span>
                      {item.finished_at && ['done', 'failed', 'skipped'].includes(item.state) ? <span className="text-ink-3"> · {formatDate(item.finished_at, true)}</span> : null}
                      {href && LINKS[item.state] ? <> · <a className="underline" href={href}>{LINKS[item.state]}</a></> : null}</p>
                    {item.message && <p className="text-ink-3">{item.message}</p>}
                  </div>
                  {(pending || ['done', 'failed', 'skipped'].includes(item.state)) && (
                    <div className="flex shrink-0 items-center">
                      {pending && <>
                        <button type="button" className={ICON} aria-label={`Move prompt ${n + 1} up`} disabled={busy !== null || !movable(queue.items[n - 1])}
                          onClick={() => void act('move', () => api.movePrompt(item.key, -1))}><ArrowUp /></button>
                        <button type="button" className={ICON} aria-label={`Move prompt ${n + 1} down`} disabled={busy !== null || !movable(queue.items[n + 1])}
                          onClick={() => void act('move', () => api.movePrompt(item.key, 1))}><ArrowDown /></button>
                      </>}
                      <button type="button" className={ICON} aria-label={`Remove prompt ${n + 1} from the queue`} disabled={busy !== null}
                        onClick={() => void act('remove', () => api.removePrompt(item.key))}><X /></button>
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        </section>
      )}
    </div>
  );
}
