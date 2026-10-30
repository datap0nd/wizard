import {Fragment, useState} from 'react';
import {ChevronDown, ListChecks, User} from 'lucide-react';
import mark from '@/assets/wizard-mark.svg';
import {flowRows, type CaseSource, type CaseTurn} from '@/cases';
import {formatDate} from '@/format';
import {cn} from '@/lib/utils';
import {AnswerMarkdown} from '../AnswerMarkdown';
import {CheckBadge, DataModeBadge} from '../Badges';

const PROMPT = '#1428a0';  // Samsung Blue: the person's words; Wizard's answers are white windows
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
      <p className="whitespace-pre-wrap text-[17px] font-medium leading-[1.45]">{check ? 'Check my data: recompute the figures in the answer above from its sources.' : turn.prompt}</p>
      <p className="text-[12px] text-[#c9d3f5]">{formatDate(turn.asked_at, true)}</p>
    </section>
  );
}

function sourceName(source: CaseSource): string {
  return [source.system_name, source.report_name].filter(Boolean).join(' · ') || source.id;
}

function AnswerWindow({turn, className}: {turn: CaseTurn; className?: string}) {
  const [lit, setLit] = useState<string | null>(null);
  const show = (id: string) => {
    setLit(id);
    document.getElementById(`case-${turn.n}-${id}`)?.scrollIntoView({block: 'nearest', behavior: 'smooth'});
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
      <div className="px-5 py-4 lg:px-6">
        <AnswerMarkdown text={turn.answer} visuals={turn.visuals} onEvidence={show} />
      </div>
      {(turn.sources.length > 0 || turn.steps.length > 0) && (
        <div className="space-y-2 border-t border-line px-5 py-3 text-[13px] text-ink-3 lg:px-6">
          {turn.sources.length > 0 && (
            <ul className="flex flex-wrap gap-1.5" aria-label="Sources" data-testid="case-sources">
              {turn.sources.map(source => (
                <li key={source.id} id={`case-${turn.n}-${source.id}`}
                  className={cn('inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[12px]', lit === source.id ? 'border-accent bg-accent-soft text-ink' : 'border-line bg-canvas')}>
                  <span className="font-semibold text-accent">{source.id}</span>
                  <span className="text-ink-2">{sourceName(source)}</span>
                  {source.as_of && <span>as of {formatDate(source.as_of)}</span>}
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
                    {!step.ok && <span className="text-danger"> (failed)</span>}{step.evidence ? ` [${step.evidence}]` : ''}</li>
                ))}
              </ol>
            </details>
          )}
        </div>
      )}
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
