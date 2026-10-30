import {useEffect, useMemo, useRef, useState} from 'react';
import {ChevronDown, Newspaper} from 'lucide-react';
import {ago, categoryColor, cumulative, itemKey, plural, type BrainNews, type NewsItem} from '@/brain';
import {formatDate} from '@/format';
import {cn} from '@/lib/utils';
import {CountUp} from './CountUp';

/** Articles per week as bars, and the running total as a line over them: the automation at work. */
function Growth({news}: {news: BrainNews}) {
  const weeks = useMemo(() => cumulative(news.weekly ?? []), [news.weekly]);
  if (weeks.length < 2) return null;
  const width = 440, height = 64, top = 6, bottom = 16;  // the panel's width, so the chart fills it at this height
  const most = Math.max(...weeks.map(w => w.count), 1), total = weeks.at(-1)!.total || 1;
  const step = width / weeks.length;
  const x = (i: number) => i * step + step / 2;
  const line = weeks.map((w, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${(top + (height - top - bottom) * (1 - w.total / total)).toFixed(1)}`).join(' ');
  const area = `${line} L${x(weeks.length - 1).toFixed(1)} ${height - bottom} L${x(0).toFixed(1)} ${height - bottom} Z`;
  return (
    <figure className="mt-3" data-testid="news-growth">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[64px] w-full" role="img"
        aria-label={`Articles collected per week, ${weeks.length} weeks, ${total.toLocaleString()} in all`}>
        <defs>
          <linearGradient id="news-area" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#fb7185" stopOpacity="0.35" /><stop offset="1" stopColor="#fb7185" stopOpacity="0" /></linearGradient>
        </defs>
        {weeks.map((w, i) => {
          const h = Math.max(1, (height - top - bottom) * 0.55 * (w.count / most));
          return <rect key={w.week} x={x(i) - Math.max(1, step * 0.32)} width={Math.max(1.2, step * 0.64)} y={height - bottom - h} height={h} rx="1" fill="#fda4af" opacity="0.45"><title>{`Week of ${formatDate(w.week)}: ${w.count}`}</title></rect>;
        })}
        <path d={area} fill="url(#news-area)" />
        <path d={line} fill="none" stroke="#fb7185" strokeWidth="2" className="brain-draw" pathLength={1} />
        <text x="0" y={height - 3} fontSize="10" fill="#94a3b8">{formatDate(weeks[0].week)}</text>
        <text x={width} y={height - 3} fontSize="10" fill="#94a3b8" textAnchor="end">{formatDate(weeks.at(-1)!.week)}</text>
      </svg>
      <figcaption className="text-[11.5px] text-slate-400">Articles per week (bars) and the running total (line)</figcaption>
    </figure>
  );
}

/** The news table an automation keeps filling, read live from the company database. `still`: the simple view, where
 *  nothing moves (no counting up, no scrolling headlines). */
export function NewsPanel({news, fresh, incoming, onCategory, category, name, still = false, snapshotAt}: {
  news: BrainNews; fresh: Set<string>; incoming: NewsItem[]; onCategory: (name: string | null) => void; category: string | null; name: string;
  still?: boolean; snapshotAt?: string;
}) {
  const order = (news.categories ?? []).map(c => c.name);
  // Demo arrivals sit on top, in place of the article each one re-shows.
  const moved = new Set(incoming.map(item => item.origin));
  const list = [...incoming, ...(news.latest ?? []).filter(item => !moved.has(itemKey(item)))]
    .filter(item => !category || (item.category ?? '').split(', ').includes(category));
  const scroller = useRef<HTMLDivElement>(null);
  const [paused, setPaused] = useState(false);
  const [arrived, setArrived] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 30_000); return () => clearInterval(t); }, []);
  // The headlines scroll slowly by themselves, for a screen in a meeting room; a pointer over them stops it.
  useEffect(() => {
    const el = scroller.current;
    if (!el || still || paused || arrived || (typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches)) return;
    const timer = setInterval(() => {
      if (el.scrollTop + el.clientHeight >= el.scrollHeight - 1) el.scrollTop = 0; else el.scrollTop += 1;
    }, 45);
    return () => clearInterval(timer);
  }, [still, paused, arrived, list.length]);
  // New articles: back to the top of the list, where they are, and hold the scrolling there for a while.
  useEffect(() => {
    if (!fresh.size) return;
    if (scroller.current) scroller.current.scrollTop = 0;
    setArrived(fresh.size);
    const timer = setTimeout(() => setArrived(0), 20_000);
    return () => clearTimeout(timer);
  }, [fresh]);
  const biggest = Math.max(1, ...(news.categories ?? []).map(c => c.count));
  // "Newest ... ago" only while it says something recent.
  const recent = !!news.last && now - new Date(news.last).getTime() < 7 * 86_400_000;
  return (
    <section className="flex min-h-0 flex-col rounded-2xl border border-white/10 bg-white/[0.04] p-4 backdrop-blur" aria-label="Market news" data-testid="news-panel">
      <header className="flex items-center gap-2">
        <span className="grid size-8 place-items-center rounded-lg bg-rose-500/20 text-rose-300"><Newspaper className="size-4" /></span>
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-semibold text-white">Market news</h2>
          <p className="truncate text-[11.5px] text-slate-400">Curated and categorized · {name}</p>
        </div>
        {snapshotAt
          ? <span className="inline-flex items-center rounded-full border border-slate-400/30 bg-slate-400/10 px-2 py-0.5 text-[11px] font-semibold text-slate-300"
            title={`Read from the company database on ${formatDate(snapshotAt, true)}, when this graph was published`} data-testid="news-snapshot">SNAPSHOT</span>
          : <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-300" title="Read from the company database a moment ago">
            <i className="brain-live size-1.5 rounded-full bg-emerald-400" />LIVE</span>}
      </header>
      <div className="mt-3 flex items-end gap-3">
        <p className="text-[40px] font-semibold leading-none tracking-tight text-white" data-testid="news-total"><CountUp value={news.total ?? 0} duration={1800} still={still} /></p>
        <p className="pb-1 text-[12.5px] leading-tight text-slate-300">articles<br />{news.first ? `since ${formatDate(news.first)}` : 'curated'}</p>
      </div>
      <p className="mt-1.5 text-[12.5px] text-slate-300">
        {news.last_7_days ? <><strong className="text-rose-300">+{news.last_7_days.toLocaleString()}</strong> published in the last 7 days · </> : null}
        {plural(news.categories?.length ?? 0, 'category', 'categories')}
        {recent ? <> · newest {ago(news.last, now)}</> : null}
      </p>
      <Growth news={news} />
      {(news.categories?.length ?? 0) > 0 && (
        <div className="mt-3" data-testid="news-categories">
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-400">{plural(news.categories!.length, 'category', 'categories')}</p>
          <ul className="grid grid-cols-2 gap-x-3 gap-y-1">
            {news.categories!.slice(0, 8).map(c => (
              <li key={c.name}>
                <button type="button" onClick={() => onCategory(category === c.name ? null : c.name)} aria-pressed={category === c.name}
                  className={cn('group block w-full rounded-md px-1 py-0.5 text-left text-[12.5px] hover:bg-white/5', category && category !== c.name && 'opacity-50')}>
                  <span className="flex items-baseline gap-2">
                    <span className="min-w-0 flex-1 truncate text-slate-200">{c.name}</span>
                    <span className="tabular-nums text-slate-300">{c.count.toLocaleString()}</span>
                  </span>
                  <span className="relative mt-0.5 block h-1.5 overflow-hidden rounded-full bg-white/5">
                    <span className="brain-grow absolute inset-y-0 left-0 rounded-full" style={{width: `${(c.count / biggest) * 100}%`, background: categoryColor(c.name, order)}} />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="mb-1.5 mt-3 flex items-center text-[12px] font-semibold uppercase tracking-wide text-rose-200">{category ? `Latest in ${category}` : 'Latest articles'}
        {arrived > 0 && <span className="brain-new ml-auto rounded-full bg-rose-500/20 px-2 py-px normal-case tracking-normal text-rose-200" data-testid="news-arrived">{plural(arrived, 'new article')} just arrived</span>}</p>
      <div ref={scroller} className="brain-fade min-h-[220px] flex-1 overflow-y-auto pr-1 scroll-thin" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)} data-testid="news-latest">
        <ul className="space-y-2">
          {list.map(item => {
            const isNew = fresh.has(itemKey(item));
            const color = categoryColor((item.category ?? '').split(', ')[0], order);
            const body = (
              <>
                <span className="flex items-center gap-1.5 text-[11px]">
                  {item.category && <span className="truncate rounded px-1.5 py-px font-medium" style={{color, background: `${color}22`}}>{item.category}</span>}
                  {isNew && <span className="brain-new rounded bg-rose-500 px-1.5 py-px font-bold text-white">NEW</span>}
                  <span className="ml-auto shrink-0 text-slate-400">{ago(item.date, now)}</span>
                </span>
                <span className="mt-1 line-clamp-2 block text-[13.5px] font-medium leading-snug text-slate-100">{item.title}</span>
                {(item.source || item.market) && <span className="mt-0.5 block truncate text-[11.5px] text-slate-400">{[item.source, item.market].filter(Boolean).join(' · ')}</span>}
              </>
            );
            return (
              <li key={itemKey(item)} className={cn('rounded-lg border border-white/5 bg-white/[0.03] p-2', isNew && 'brain-arrive border-rose-400/40')}>
                {item.url ? <a href={item.url} target="_blank" rel="noreferrer noopener" className="group block" title={item.summary ?? undefined}>{body}</a>
                  : <div title={item.summary ?? undefined}>{body}</div>}
              </li>
            );
          })}
          {list.length === 0 && <li className="text-[12.5px] text-slate-400">No articles to show.</li>}
        </ul>
      </div>
      <details className="group mt-2 text-[11.5px] text-slate-400">
        <summary className="flex cursor-pointer list-none items-center gap-1 hover:text-slate-200"><ChevronDown className="size-3.5 transition-transform group-open:rotate-180" />How this was read</summary>
        <p className="mt-1">Read {snapshotAt ? `on ${formatDate(snapshotAt, true)}` : 'live'} from <code className="text-slate-300">{news.table}</code> in database <code className="text-slate-300">{news.database}</code> with these read-only queries{news.read_at ? `, at ${new Date(news.read_at * 1000).toLocaleTimeString()}` : ''}:</p>
        <ul className="mt-1 space-y-1">{(news.queries ?? []).map(q => <li key={q}><code className="block whitespace-pre-wrap break-all rounded bg-black/30 p-1.5 font-mono text-[10.5px] text-slate-300">{q}</code></li>)}</ul>
      </details>
    </section>
  );
}

/** Where the news would be, when it cannot be shown: the reason, for whoever sets Wizard up. */
export function NewsMissing({news}: {news: BrainNews}) {
  return (
    <section className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 text-[12.5px] text-slate-300" data-testid="news-missing">
      <p className="flex items-center gap-2 font-semibold text-white"><Newspaper className="size-4 text-rose-300" />Market news</p>
      <p className="mt-1.5">{news.message ?? 'The news table could not be read.'}</p>
    </section>
  );
}
