import {Fragment, useState} from 'react';
import {Check, ChevronDown, Copy, Database, ListChecks, User} from 'lucide-react';
import mark from '@/assets/wizard-mark.svg';
import {flowRows, type CaseQuery, type CaseSource, type CaseTurn} from '@/cases';
import {formatDate} from '@/format';
import {cn} from '@/lib/utils';
import {AnswerMarkdown} from '../AnswerMarkdown';
import {CheckBadge, DataModeBadge} from '../Badges';
import {Dialog, DialogContent} from '../ui/dialog';

const PROMPT = '#1428a0';  // Samsung Blue: the person's words; Wizard's answers are white windows
// A long prompt or answer scrolls inside its box instead of stretching the case (owner, 3 Nov 2026). Focusable, so the
// box also scrolls with the keyboard.
const SCROLL = 'overflow-y-auto overscroll-contain [scrollbar-width:thin]';
const ARROW = '#6b7891';

function Right({className}: {className?: string}) {
  return <svg aria-hidden="true" width="76" height="24" viewBox="0 0 76 24" fill="none" stroke={ARROW} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M4 12h66" /><path d="M62 5l8 7-8 7" /></svg>;
}
function Left({className}: {className?: string}) {
  return <svg aria-hidden="true" width="76" height="24" viewBox="0 0 76 24" fill="none" stroke={ARROW} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M72 12H6" /><path d="M14 5l-8 7 8 7" /></svg>;
}
function Down({className, tall = false}: {className?: string; tall?: boolean}) {
  const h = tall ? 60 : 44;
  return <svg aria-hidden="true" width="24" height={h} viewBox={`0 0 24 ${h}`} fill="none" stroke={ARROW} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d={`M12 4v${h - 10}`} /><path d={`M5 ${h - 14}l7 8 7-8`} /></svg>;
}

function PromptCard({turn, className}: {turn: CaseTurn; className?: string}) {
  const check = turn.kind === 'check';
  return (
    <section aria-label={`Prompt ${turn.n}`} className={cn('flex flex-col gap-3 rounded-2xl p-5 text-white lg:p-6', className)} style={{background: PROMPT}} data-testid="case-prompt">
      <p className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.08em] text-[#d3dbf7]">
        {check ? <ListChecks className="size-4" /> : <User className="size-4" />}Prompt {turn.n}</p>
      <p tabIndex={0} aria-label={`Prompt ${turn.n} text`} data-testid="case-prompt-text"
        className={cn('max-h-[16rem] whitespace-pre-wrap pr-1 text-[17px] font-medium leading-[1.45] [scrollbar-color:#8fa3e6_transparent] focus-visible:outline focus-visible:outline-2 focus-visible:outline-white', SCROLL)}>{check ? 'Check my data: recompute the figures in the answer above from its sources.' : turn.prompt}</p>
      <p className="text-[12px] text-[#c9d3f5]">{formatDate(turn.asked_at, true)}</p>
    </section>
  );
}

function sourceName(source: CaseSource): string {
  return [source.system_name, source.report_name].filter(Boolean).join(' · ') || source.id;
}

function queryText(query: CaseQuery): string {
  if (query.kind !== 'portal') return query.text ?? '';
  return (query.steps ?? []).map((step, i) => {
    const head = [step.action, step.method, step.url, step.selector, step.text, step.name, step.value].filter(Boolean).join(' ');
    return [`${i + 1}. ${head}`, step.body ? `   body: ${step.body}` : '', step.script ? step.script.replace(/^/gm, '   ') : '']
      .filter(Boolean).join('\n');
  }).join('\n\n');
}

/** The query behind one source, opened from its evidence chip, its source chip or a step (owner, 4 Nov 2026: the
 *  queries looked clickable but did not open). Its rows are never on the site; the query says how they were read. */
function QueryDialog({source, onClose}: {source: CaseSource | null; onClose: () => void}) {
  const [copied, setCopied] = useState(false);
  const query = source?.query ?? null;
  const text = query ? queryText(query) : '';
  const what = query?.kind === 'sql' ? `SQL${query.database ? ` on ${query.database}` : ''}`
    : query?.kind === 'portal' ? `Steps in the portal${query.script ? ` (saved script ${query.script})` : ''}` : 'Request';
  return (
    <Dialog open={source !== null} onOpenChange={open => { if (!open) { onClose(); setCopied(false); } }}>
      {source && <DialogContent title={`${source.id} · ${sourceName(source)}`} className="w-[min(860px,96vw)]"
        description={[source.as_of ? `as of ${formatDate(source.as_of)}` : '', typeof source.total_rows === 'number'
          ? `${source.total_rows.toLocaleString()} row${source.total_rows === 1 ? '' : 's'} read (not published)` : ''].filter(Boolean).join(' · ')}>
        {query ? (
          <div className="space-y-2" data-testid="case-query">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-ink-2"><Database className="size-3.5" />{what}</span>
              <button type="button" onClick={() => void navigator.clipboard?.writeText(text).then(() => setCopied(true))}
                className="ml-auto inline-flex items-center gap-1 rounded-md border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface">
                {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}{copied ? 'Copied' : 'Copy'}</button>
            </div>
            <pre tabIndex={0} data-testid="case-query-text"
              className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-surface p-3 font-mono text-[12.5px] leading-relaxed text-ink [overflow-wrap:anywhere]">{text}</pre>
          </div>
        ) : (
          <p className="text-[13px] text-ink-2" data-testid="case-query-missing">
            {source.data_mode === 'USER_PROVIDED' ? 'A file the person attached: its name and folder stay on their PC.'
              : 'This case was published before Wizard kept its queries. Publish it again from Wizard (Share as case) to show them.'}</p>
        )}
      </DialogContent>}
    </Dialog>
  );
}

function AnswerWindow({turn, className}: {turn: CaseTurn; className?: string}) {
  const [lit, setLit] = useState<string | null>(null);
  const [opened, setOpened] = useState<CaseSource | null>(null);
  const show = (id: string) => {
    setLit(id);
    const source = turn.sources.find(s => s.id === id);
    if (source) setOpened(source);
    else document.getElementById(`case-${turn.n}-${id}`)?.scrollIntoView({block: 'nearest', behavior: 'smooth'});
  };
  return (
    <article aria-label={`Answer ${turn.n}`} className={cn('min-w-0 overflow-hidden rounded-[14px] border border-line bg-canvas shadow-card', className)} data-testid="case-answer">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-2 border-b border-line bg-surface px-4 py-2.5">
        <span aria-hidden="true" className="mr-1 flex gap-1.5">{[0, 1, 2].map(i => <i key={i} className="size-2.5 rounded-full bg-[#c4cad6]" />)}</span>
        <img src={mark} alt="" className="size-[18px]" />
        <span className="text-[13px] font-semibold">Wizard · Answer {turn.n}</span>
        <span className="ml-auto flex flex-wrap gap-1.5">
          <DataModeBadge mode={turn.data_mode} />
          <CheckBadge status={turn.check.status} />
        </span>
      </div>
      <div tabIndex={0} aria-label={`Answer ${turn.n} text`} data-testid="case-answer-body"
        className={cn('max-h-[min(36rem,70vh)] px-5 py-4 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent lg:px-6', SCROLL)}>
        <AnswerMarkdown text={turn.answer} visuals={turn.visuals} onEvidence={show} />
      </div>
      {(turn.sources.length > 0 || turn.steps.length > 0) && (
        <div className="space-y-2 border-t border-line px-5 py-3 text-[13px] text-ink-3 lg:px-6">
          {turn.sources.length > 0 && (
            <ul className="flex flex-wrap gap-1.5" aria-label="Sources" data-testid="case-sources">
              {turn.sources.map(source => (
                <li key={source.id} id={`case-${turn.n}-${source.id}`}>
                  <button type="button" onClick={() => show(source.id)} data-testid="case-source" title="Show the query"
                    className={cn('inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-left text-[12px] hover:border-accent',
                      lit === source.id ? 'border-accent bg-accent-soft text-ink' : 'border-line bg-canvas')}>
                    <span className="font-semibold text-accent">{source.id}</span>
                    <span className="text-ink-2">{sourceName(source)}</span>
                    {source.as_of && <span>as of {formatDate(source.as_of)}</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {turn.steps.length > 0 && (
            <details className="group">
              <summary className="inline-flex cursor-pointer list-none items-center gap-1 font-medium text-accent hover:underline">
                <ChevronDown className="size-3.5 transition-transform group-open:rotate-180" />What Wizard did ({turn.steps.length} {turn.steps.length === 1 ? 'step' : 'steps'})</summary>
              <ol className="mt-2 list-decimal space-y-1 pl-5 text-[12.5px] text-ink-2">
                {turn.steps.map((step, i) => (
                  <li key={i}><span className="font-medium text-ink">{step.label}</span>{step.summary ? `: ${step.summary}` : ''}
                    {!step.ok && <span className="text-danger"> (failed)</span>}
                    {step.evidence && (turn.sources.some(s => s.id === step.evidence)
                      ? <> <button type="button" onClick={() => show(step.evidence!)} data-testid="case-step-query"
                          className="font-semibold text-accent hover:underline">[{step.evidence}]</button></>
                      : ` [${step.evidence}]`)}</li>
                ))}
              </ol>
            </details>
          )}
        </div>
      )}
      <QueryDialog source={opened} onClose={() => setOpened(null)} />
    </article>
  );
}

/** A case as the owner drew it: prompt → answer, a follow-up drops down and runs ← the other way, and so on. On a narrow
 *  screen every step stacks with arrows down. Prompts are Samsung Blue; answers are white windows. */
export function CaseFlow({turns}: {turns: CaseTurn[]}) {
  return (
    <div className="flex flex-col" data-testid="case-flow">
      {flowRows(turns).map(({turn, reversed, drop}) => (
        <Fragment key={turn.n}>
          <div className={cn('grid grid-cols-1 items-start', reversed ? 'lg:grid-cols-[minmax(0,1fr)_88px_minmax(0,340px)]' : 'lg:grid-cols-[minmax(0,340px)_88px_minmax(0,1fr)]')}
            data-testid="case-row" data-reversed={reversed ? 'true' : 'false'}>
            <PromptCard turn={turn} className={reversed ? 'lg:col-start-3 lg:row-start-1' : undefined} />
            <div className={cn('flex justify-center py-2 lg:pt-12', reversed && 'lg:col-start-2 lg:row-start-1')}>
              {reversed ? <Left className="hidden lg:block" /> : <Right className="hidden lg:block" />}
              <Down className="lg:hidden" />
            </div>
            <AnswerWindow turn={turn} className={reversed ? 'lg:col-start-1 lg:row-start-1' : undefined} />
          </div>
          {drop && (
            <div className={cn('flex justify-center py-2', drop === 'right' ? 'lg:justify-end' : 'lg:justify-start')} data-testid="case-drop" data-side={drop}>
              <div className="flex items-center justify-center gap-2 lg:w-[340px]"><Down tall /><span className="text-[12px] text-ink-3">follow-up</span></div>
            </div>
          )}
        </Fragment>
      ))}
    </div>
  );
}
