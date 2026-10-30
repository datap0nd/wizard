import {useState} from 'react';
import {Check, Link2} from 'lucide-react';
import mark from '@/assets/wizard-mark.svg';
import {filterCases, systemsOf, type Case, type CaseEntry} from '@/cases';
import {formatDate} from '@/format';
import {cn} from '@/lib/utils';
import {DataModeBadge} from '../Badges';
import {CaseFlow} from './CaseFlow';

/** The top of a Cases page: the mark and the word Cases. Brain is a site of its own, so nothing here leads to it. */
function Top({home}: {home: string}) {
  return (
    <header className="flex items-center gap-3 border-b border-line bg-canvas px-4 py-3 md:px-8">
      <a href={home} className="flex items-center gap-2.5 text-[17px] font-bold text-ink no-underline"><img src={mark} alt="" className="size-7" />Wizard</a>
      <span className="text-[15px] font-medium text-ink-2">Cases</span>
    </header>
  );
}

function Meta({items}: {items: (string | null | false | undefined)[]}) {
  const shown = items.filter(Boolean) as string[];
  return <>{shown.map((item, i) => <span key={item} className="contents">{i > 0 && <span aria-hidden="true">·</span>}<span>{item}</span></span>)}</>;
}

/** One case: its title, who shared it and what it read, then the prompts and answers as a snake. `preview`: shown in
 *  Wizard before it is published, so nothing on it is on the site yet. */
export function CasePage({item, home, preview = false}: {item: Case; home: string; preview?: boolean}) {
  const [copied, setCopied] = useState(false);
  const copy = () => { void navigator.clipboard?.writeText(location.href).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000); }); };
  return (
    <div className="min-h-dvh bg-page text-ink" data-testid="case-page">
      <Top home={home} />
      {preview && <p className="border-b border-warn-line bg-warn-soft px-4 py-2 text-center text-[13px] font-medium text-warn md:px-8" data-testid="case-preview">
        Preview in Wizard: not on the site until you publish it.</p>}
      <main className="mx-auto max-w-[1240px] px-4 pb-20 pt-8 md:px-8">
        <p className="mb-3 text-[14px] text-ink-3"><a href={home}>Cases</a> <span aria-hidden="true">/</span> {item.title}</p>
        <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0 space-y-3">
            <h1 className="text-[28px] font-bold leading-tight tracking-[-0.01em] md:text-[34px]" data-testid="case-title">{item.title}</h1>
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[14px] text-ink-2">
              <Meta items={[`${item.turns.length} ${item.turns.length === 1 ? 'prompt' : 'prompts'}`, item.systems.join(', '),
                item.author ? `Shared by ${item.author}` : null, `published ${formatDate(item.published_at)}`]} />
              {item.data_modes.map(mode => <DataModeBadge key={mode} mode={mode} />)}
            </p>
            {item.takeaway && <p className="max-w-[760px] text-[16px] leading-relaxed text-ink" data-testid="case-takeaway">{item.takeaway}</p>}
          </div>
          {!preview && <button type="button" onClick={copy} className="inline-flex min-h-11 shrink-0 items-center gap-2 self-start rounded-[10px] border border-line-2 bg-canvas px-4 text-[14px] font-medium hover:bg-surface lg:self-auto">
            {copied ? <Check className="size-4" /> : <Link2 className="size-4" />}{copied ? 'Copied' : 'Copy link'}</button>}
        </div>
        <div className="my-7 flex flex-wrap items-center gap-x-6 gap-y-2 text-[13px] text-ink-2">
          <span className="inline-flex items-center gap-2"><i aria-hidden="true" className="size-[18px] rounded-[5px] bg-[#1428a0]" />Prompt</span>
          <span className="inline-flex items-center gap-2"><i aria-hidden="true" className="size-[18px] rounded-[5px] border border-[#c4cad6] bg-canvas" />Wizard's answer</span>
          <span>Follow the arrows: each follow-up continues from the answer above it.</span>
        </div>
        <CaseFlow turns={item.turns} />
        <p className="mt-12 border-t border-line pt-5 text-[13px] text-ink-3">
          Shared from Wizard by the person who asked. Each answer keeps its own data label; the sources are named, their rows are not published.</p>
      </main>
    </div>
  );
}

/** The thumbnail of a case in the gallery: its first prompts and answers as a small snake. */
function Thumb({prompts}: {prompts: number}) {
  const block = 'h-[22px] w-16 shrink-0 rounded-md bg-[#1428a0]';
  const pane = 'h-[30px] flex-1 rounded-md border border-line-2 bg-canvas';
  const line = 'h-0.5 w-3.5 shrink-0 bg-[#9aa3b5]';
  return (
    <div aria-hidden="true" className="flex h-[120px] flex-col justify-center gap-1.5 border-b border-line bg-[#f7f8fa] px-[18px]">
      <div className="flex items-center gap-1.5"><span className={block} /><span className={line} /><span className={pane} /></div>
      {prompts > 1 && <>
        <div className="flex justify-end pr-[31px]"><span className="h-2.5 w-0.5 bg-[#9aa3b5]" /></div>
        <div className="flex items-center gap-1.5"><span className={pane} /><span className={line} /><span className={block} /></div>
      </>}
    </div>
  );
}

/** Every case on the site, newest first, with a search and a filter by system. */
export function CasesGallery({cases, home}: {cases: CaseEntry[]; home: string}) {
  const [query, setQuery] = useState('');
  const [system, setSystem] = useState<string | null>(null);
  const systems = systemsOf(cases);
  const shown = filterCases(cases, query, system);
  const chip = (active: boolean) => cn('min-h-11 rounded-full border px-4 text-[14px]', active ? 'border-[#1428a0] bg-[#1428a0] font-semibold text-white' : 'border-line-2 bg-canvas font-medium text-ink hover:bg-surface');
  return (
    <div className="min-h-dvh bg-page text-ink" data-testid="cases-gallery">
      <Top home={home} />
      <main className="mx-auto flex max-w-[1240px] flex-col gap-7 px-4 pb-20 pt-10 md:px-8">
        <div className="space-y-2">
          <h1 className="text-[34px] font-bold leading-tight tracking-[-0.01em]">Cases</h1>
          <p className="max-w-[680px] text-[16px] leading-normal text-ink-2">Analyses people ran with Wizard and chose to share: every prompt, every answer, and the data each answer was built from.</p>
        </div>
        {cases.length > 0 && (
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex max-w-[460px] flex-[1_1_320px] flex-col gap-1.5 text-[13px] text-ink-2">Search cases
              <input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Market, report, question…" data-testid="cases-search"
                className="min-h-11 rounded-[10px] border border-line-2 bg-canvas px-3.5 text-[15px] text-ink outline-none focus:border-accent" />
            </label>
            {systems.length > 1 && (
              <div role="group" aria-label="Filter by system" className="flex flex-wrap gap-2">
                <button type="button" aria-pressed={system === null} onClick={() => setSystem(null)} className={chip(system === null)}>All</button>
                {systems.map(s => <button key={s} type="button" aria-pressed={system === s} onClick={() => setSystem(system === s ? null : s)} className={chip(system === s)}>{s}</button>)}
              </div>
            )}
          </div>
        )}
        <div className="grid grid-cols-[repeat(auto-fill,minmax(min(330px,100%),1fr))] gap-5">
          {shown.map(item => (
            <a key={item.id} href={`?case=${encodeURIComponent(item.id)}`} data-testid="case-card"
              className="flex flex-col overflow-hidden rounded-2xl border border-line bg-canvas text-ink no-underline transition-shadow hover:border-accent-line hover:shadow-card">
              <Thumb prompts={item.prompts} />
              <div className="flex flex-1 flex-col gap-2.5 px-5 pb-5 pt-4">
                <h2 className="text-[18px] font-semibold leading-snug">{item.title}</h2>
                <p className="line-clamp-3 text-[14px] leading-normal text-ink-2">{item.takeaway || item.first_prompt}</p>
                <p className="mt-auto flex flex-wrap items-center gap-x-2.5 gap-y-1 pt-2 text-[12.5px] text-ink-3">
                  <Meta items={[`${item.prompts} ${item.prompts === 1 ? 'prompt' : 'prompts'}`, item.systems.join(', '), formatDate(item.published_at)]} />
                  {item.data_modes.map(mode => <DataModeBadge key={mode} mode={mode} />)}
                </p>
              </div>
            </a>
          ))}
        </div>
        {cases.length === 0 && <p className="text-[15px] text-ink-2" data-testid="cases-empty">No cases yet. In Wizard, open a chat and choose Share as case.</p>}
        {cases.length > 0 && shown.length === 0 && <p className="text-[15px] text-ink-2">No case matches.</p>}
      </main>
    </div>
  );
}
