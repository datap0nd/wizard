import {useEffect, useRef} from 'react';
import {ArrowDown, ArrowUp, X} from 'lucide-react';
import {cn} from '@/lib/utils';
import {canMove, cleanUse, levelNumbers, move, parseOrder, remove, serialise, sourceName, update, withSources,
  type OrderEntry, type OrderSource} from '@/sourceOrder';
import {Button} from './ui/button';
import {SystemLogo} from './SystemLogo';

/** Settings → Source order: the data sources in the company's order. Move one up or down (the buttons keep focus, so
 * the keyboard can keep moving it), put it on the same level as the one above, say in a line what it is for, or keep
 * it for when someone asks. A source the order names that this PC does not have stays in the list, kept for the PCs
 * that have it. Every change is the stored line (`onChange`), saved with the other settings. */
export function SourceOrder({value, defaults, sources, maxUse = 200, disabled, onChange}: {
  value: string; defaults: OrderEntry[]; sources: OrderSource[]; maxUse?: number; disabled?: boolean;
  onChange: (next: string) => void;
}) {
  const entries = withSources(parseOrder(value, defaults), sources);
  const numbers = levelNumbers(entries);
  const here = new Set(sources.map(s => s.id));
  const list = useRef<HTMLOListElement>(null);
  const refocus = useRef<{id: string; direction: 'up' | 'down'} | null>(null);

  useEffect(() => {  // after a move, the same button of the same source (or its other one, at an end) keeps focus
    const wanted = refocus.current;
    if (!wanted || !list.current) return;
    refocus.current = null;
    const buttons = ['up', 'down'].map(d => list.current?.querySelector<HTMLButtonElement>(`[data-move="${wanted.id}:${d}"]`));
    const same = buttons[wanted.direction === 'up' ? 0 : 1];
    (same && !same.disabled ? same : buttons.find(b => b && !b.disabled))?.focus();
  });

  const change = (next: OrderEntry[]) => onChange(serialise(next));
  const shift = (index: number, direction: -1 | 1) => {
    refocus.current = {id: entries[index].id, direction: direction < 0 ? 'up' : 'down'};
    change(move(entries, index, direction));
  };

  return (
    <ol ref={list} className="space-y-1.5" data-testid="source-order" aria-label="Source order, first to last">
      {entries.map((entry, i) => {
        const name = sourceName(entry.id, sources);
        const joined = i > 0 && numbers[i] === numbers[i - 1];
        const present = here.has(entry.id);
        return (
          <li key={entry.id} data-testid="source-order-row" data-source={entry.id} data-level={numbers[i]}
            className={cn('rounded-lg border border-line bg-canvas px-2.5 py-2', joined && 'ml-4 border-l-2 border-l-accent-line',
              !present && 'bg-surface/60')}>
            <div className="flex items-center gap-2">
              <span className="w-5 shrink-0 text-center text-xs font-semibold tabular-nums text-ink-3" aria-hidden="true"
                title={joined ? 'Same level as the one above' : `Level ${numbers[i]}`}>{joined ? '=' : numbers[i]}</span>
              <span className="sr-only">Level {numbers[i]}:</span>
              <SystemLogo id={entry.id} name={name} size={20} />
              <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{name}
                {!present && <span className="ml-1.5 text-[11px] font-normal text-ink-3">not on this PC, kept for the others</span>}
              </span>
              <Button size="icon-sm" variant="ghost" aria-label={`Move ${name} up`} data-move={`${entry.id}:up`}
                disabled={disabled || !canMove(entries, i, -1)} onClick={() => shift(i, -1)}><ArrowUp /></Button>
              <Button size="icon-sm" variant="ghost" aria-label={`Move ${name} down`} data-move={`${entry.id}:down`}
                disabled={disabled || !canMove(entries, i, 1)} onClick={() => shift(i, 1)}><ArrowDown /></Button>
              {!present && (
                <Button size="icon-sm" variant="ghost" aria-label={`Remove ${name} from the order`} disabled={disabled}
                  onClick={() => change(remove(entries, i))}><X /></Button>
              )}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 pl-7 text-[12px] text-ink-2">
              <label className="inline-flex items-center gap-1.5">
                <input type="checkbox" checked={joined} disabled={disabled || i === 0} data-testid="source-same"
                  onChange={e => change(update(entries, i, {same: e.target.checked}))} />
                Same level as the one above
              </label>
              <label className="inline-flex items-center gap-1.5">
                <input type="checkbox" checked={!!entry.when_asked} disabled={disabled} data-testid="source-when-asked"
                  onChange={e => change(update(entries, i, {when_asked: e.target.checked}))} />
                Only when asked
              </label>
            </div>
            <input type="text" value={entry.use ?? ''} maxLength={maxUse} disabled={disabled} spellCheck={false}
              aria-label={`What ${name} is for`} placeholder="Use it for… e.g. monthly figures by market and channel"
              data-testid="source-use" onChange={e => change(update(entries, i, {use: cleanUse(e.target.value, maxUse)}))}
              className="mt-1.5 h-8 w-full rounded-md border border-line bg-canvas px-2.5 text-[12.5px] outline-none focus:border-line-2 disabled:bg-surface disabled:text-ink-3" />
          </li>
        );
      })}
    </ol>
  );
}
