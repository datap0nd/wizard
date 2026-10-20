import {useEffect, useRef, useState} from 'react';
import {ChevronDown, ExternalLink, Lock, MousePointer2, Radio} from 'lucide-react';
import {cn} from '@/lib/utils';
import {SystemLogo} from './SystemLogo';
import type {BrowserFrame, RunView, SystemInfo} from '@/types';

export function frameUrl(runId: string, frame: BrowserFrame): string {
  return `/api/v1/runs/${encodeURIComponent(runId)}/frames/${encodeURIComponent(frame.frame)}`;
}

/** A frame's target as percentages of the picture, so the outline sits on the element at any display size. */
export function targetBox(frame: BrowserFrame): {left: string; top: string; width: string; height: string} | null {
  const t = frame.target, v = frame.viewport;
  if (!t || !v.width || !v.height) return null;
  const pct = (n: number, of: number) => `${Math.max(0, Math.min(100, (n / of) * 100)).toFixed(2)}%`;
  return {left: pct(t.x, v.width), top: pct(t.y, v.height), width: pct(t.width, v.width), height: pct(t.height, v.height)};
}

function address(url: string): {host: string; path: string} {
  try {
    const u = new URL(url);
    return {host: u.host, path: u.pathname + u.search};
  } catch {
    return {host: '', path: url};
  }
}

/** The click preview: the portal page Wizard is exploring, as it saw it. Before each click, typing or table read the
 *  target is outlined and the pointer moves onto it; after it, the page that came back. Live while the run works (it
 *  follows the newest picture unless the person picks one in the strip), and a replayable strip afterwards. The
 *  pictures are the screenshots the run took, served only to the person who asked. */
export function PortalPreview({run, systems = []}: {run: RunView; systems?: SystemInfo[]}) {
  const frames = run.frames;
  const running = run.status === 'running' || run.status === 'queued';
  const [picked, setPicked] = useState<number | null>(null);
  const [open, setOpen] = useState<boolean | null>(null);
  const strip = useRef<HTMLOListElement>(null);
  const following = picked === null;
  const index = Math.min(picked ?? frames.length - 1, frames.length - 1);
  useEffect(() => {  // keep the newest picture in view in the strip while following
    if (following && strip.current) strip.current.scrollLeft = strip.current.scrollWidth;
  }, [frames.length, following]);
  if (!frames.length) return null;
  const expanded = open ?? running;
  const frame = frames[index];
  const portal = systems.find(s => s.id === frame.portal);
  const name = portal?.name ?? frame.portal.toUpperCase();
  const where = address(frame.url);
  const box = targetBox(frame);
  const pointer = box && !frame.action.startsWith('Reading');  // a click or typing; reading a table is only outlined
  const step = frames.slice(0, index + 1).filter(f => f.phase === 'after').length;

  if (!expanded) {
    return (
      <button type="button" onClick={() => setOpen(true)} data-testid="portal-preview-folded"
        className="flex w-full items-center gap-2 rounded-xl border border-line bg-surface/60 px-3 py-2 text-left text-[13px] font-medium text-ink-2 hover:text-ink">
        <SystemLogo id={frame.portal} name={name} size={20} />
        <span>What Wizard saw on {Array.from(new Set(frames.map(f => systems.find(s => s.id === f.portal)?.name ?? f.portal.toUpperCase()))).join(', ')}</span>
        <span className="font-normal text-ink-3">· {frames.length} picture{frames.length === 1 ? '' : 's'}</span>
        <ChevronDown className="ml-auto size-4" />
      </button>
    );
  }
  return (
    <div className="stage-enter overflow-hidden rounded-xl border border-line bg-canvas shadow-sm" data-testid="portal-preview">
      <div className="flex items-center gap-2 border-b border-line bg-surface/80 px-2.5 py-1.5">
        <span className="hidden gap-1 sm:flex" aria-hidden="true">
          <i className="size-2.5 rounded-full bg-[#ff5f57]" /><i className="size-2.5 rounded-full bg-[#febc2e]" /><i className="size-2.5 rounded-full bg-[#28c840]" />
        </span>
        <SystemLogo id={frame.portal} name={name} size={20} />
        <div className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md bg-canvas px-2 py-0.5 text-[12px] ring-1 ring-line" data-testid="portal-address" title={frame.url}>
          <Lock className="size-3 shrink-0 text-ink-3" />
          <span className="shrink-0 text-ink-3">{where.host}</span>
          <span className="truncate text-ink">{where.path}</span>
        </div>
        {running && following ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-danger-soft px-2 py-0.5 text-[11px] font-semibold text-danger" data-testid="portal-live">
            <Radio className="size-3 animate-pulse" />Live
          </span>
        ) : running ? (
          <button type="button" onClick={() => setPicked(null)} className="shrink-0 rounded-full border border-line px-2 py-0.5 text-[11px] font-medium text-accent hover:bg-accent-soft">
            Back to live
          </button>
        ) : null}
        {!running && <button type="button" onClick={() => setOpen(false)} className="shrink-0 text-[12px] font-medium text-accent hover:underline">Fold</button>}
      </div>
      <div className="relative w-full overflow-hidden bg-surface" style={{aspectRatio: `${frame.viewport.width} / ${frame.viewport.height}`}}>
        <img key={frame.frame} src={frameUrl(run.id, frame)} alt={`${name}: ${frame.title || where.path}`} draggable={false}
          className="portal-fade absolute inset-0 size-full object-contain" data-testid="portal-picture" />
        {box && (
          <>
            <span className="portal-target pointer-events-none absolute rounded-[4px]" style={box} data-testid="portal-target" />
            {pointer && <MousePointer2 className="portal-cursor pointer-events-none absolute size-6 fill-white text-ink drop-shadow"
              style={{left: `calc(${box.left} + ${box.width} / 2)`, top: `calc(${box.top} + ${box.height} / 2)`}} aria-hidden="true" data-testid="portal-pointer" />}
          </>
        )}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between gap-2 bg-gradient-to-t from-black/55 to-transparent px-3 pb-2 pt-8">
          <span className="rounded-full bg-black/70 px-2.5 py-1 text-[12.5px] font-medium text-white" data-testid="portal-action">
            {frame.action}{running && following && frame.phase === 'before' && <span className="stage-dots" aria-hidden="true" />}
          </span>
          <span className="shrink-0 text-[11.5px] font-medium text-white/90">Step {Math.max(step, 1)}</span>
        </div>
      </div>
      <ol ref={strip} className="flex gap-1.5 overflow-x-auto border-t border-line p-2" aria-label="Portal pictures" data-testid="portal-strip">
        {frames.map((f, i) => (
          <li key={f.frame} className="shrink-0">
            <button type="button" onClick={() => setPicked(i === frames.length - 1 && running ? null : i)} title={f.action}
              aria-label={`Picture ${i + 1}: ${f.action}`} aria-current={i === index}
              className={cn('relative block h-12 overflow-hidden rounded-md ring-1 ring-line transition hover:ring-accent', i === index && 'ring-2 ring-accent')}
              style={{aspectRatio: `${f.viewport.width} / ${f.viewport.height}`}}>
              <img src={frameUrl(run.id, f)} alt="" loading="lazy" className="size-full object-cover" />
              {f.phase === 'before' && !f.action.startsWith('Reading') && <MousePointer2 className="absolute bottom-0.5 right-0.5 size-3 fill-white text-ink" aria-hidden="true" />}
            </button>
          </li>
        ))}
      </ol>
      <p className="flex items-center gap-1.5 border-t border-line px-3 py-1.5 text-[11.5px] text-ink-3">
        Read-only, signed in as you: Wizard never saves, exports or sends anything on a portal.
        <a href={frame.url} target="_blank" rel="noopener noreferrer" className="ml-auto inline-flex shrink-0 items-center gap-1 font-medium text-accent hover:underline">
          <ExternalLink className="size-3" />Open this page
        </a>
      </p>
    </div>
  );
}
