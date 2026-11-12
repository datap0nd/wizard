import {useMemo, useState} from 'react';
import {Check, Loader2, Send} from 'lucide-react';
import {FeedbackClient, MAX_ANSWER, memory, quizIssue, type QuizAnswer, type QuizQuestion, type QuizSection} from '@/feedback';
import {formatDate} from '@/format';
import {cn} from '@/lib/utils';
import {SiteTop, useCasesSite} from './SiteChrome';

type Draft = {choice: string | null; answer: string; unsure: boolean};
const EMPTY: Draft = {choice: null, answer: '', unsure: false};
const answered = (d: Draft | undefined) => !!d && (d.unsure || !!d.choice || !!d.answer.trim());

const ABOUT: Record<string, string> = {
  bi: 'Technical questions: data sources, reports, tables and columns, how a measure is calculated.',
  business: 'Concepts, terms and acronyms, processes, organisation and strategy.',
};

function QuestionCard({q, n, draft, sent, onChange}: {q: QuizQuestion; n: number; draft: Draft; sent: boolean; onChange: (d: Draft) => void}) {
  const other = draft.choice === null && !!q.choices.length;
  return (
    <article aria-labelledby={`q-${q.id}`} data-testid="quiz-question" data-sent={sent ? 'true' : 'false'}
      className={cn('space-y-3.5 rounded-2xl border bg-canvas p-5 md:p-6', answered(draft) ? 'border-accent-line' : 'border-line', sent && 'opacity-70')}>
      <p className="flex flex-wrap items-center gap-2 text-[12.5px] text-ink-3">
        <span className="font-semibold text-ink-2">{n}.</span>
        <span className="rounded-full bg-surface px-2.5 py-0.5 font-medium text-ink-2">{q.topic}</span>
        {sent && <span className="inline-flex items-center gap-1 font-medium text-ok"><Check className="size-3.5" />You answered this</span>}
      </p>
      <h3 id={`q-${q.id}`} className="text-[17px] font-semibold leading-snug">{q.question}</h3>
      <p className="rounded-[10px] bg-surface px-3.5 py-2.5 text-[14px] leading-normal text-ink-2"><span className="font-semibold text-ink">What Wizard has now: </span>{q.now}</p>
      {!sent && <>
        {q.choices.length > 0 && (
          <div role="radiogroup" aria-labelledby={`q-${q.id}`} className="flex flex-col gap-2">
            {q.choices.map(choice => (
              <label key={choice} className={cn('flex min-h-11 cursor-pointer items-center gap-3 rounded-[10px] border px-3.5 py-2 text-[14.5px]',
                draft.choice === choice ? 'border-[#1428a0] bg-accent-soft' : 'border-line-2 hover:bg-surface')}>
                <input type="radio" name={q.id} checked={draft.choice === choice} onChange={() => onChange({choice, answer: draft.answer, unsure: false})} className="size-4 accent-[#1428a0]" />
                {choice}
              </label>
            ))}
          </div>
        )}
        <label className="flex flex-col gap-1.5 text-[13px] text-ink-2">
          {q.choices.length ? (other ? 'Your answer' : 'Anything to add? (optional)') : 'Your answer'}
          <textarea value={draft.answer} rows={q.choices.length ? 2 : 3} maxLength={MAX_ANSWER} data-testid="quiz-answer"
            placeholder={q.choices.length ? 'None of these? Say what it is.' : 'What it is, and where it is written down if you know.'}
            onChange={e => onChange({...draft, answer: e.target.value, unsure: false})}
            className="resize-y rounded-[10px] border border-line-2 bg-canvas px-3 py-2 text-[14.5px] text-ink outline-none focus:border-accent" />
        </label>
        <label className="inline-flex cursor-pointer items-center gap-2 text-[13.5px] text-ink-2">
          <input type="checkbox" checked={draft.unsure} onChange={e => onChange(e.target.checked ? {...EMPTY, unsure: true} : EMPTY)} className="size-4 accent-[#1428a0]" />
          I don't know: someone else should answer this
        </label>
      </>}
    </article>
  );
}

function SectionQuiz({section}: {section: QuizSection}) {
  const site = useCasesSite();
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [sent, setSent] = useState<string[]>(() => memory.answered());
  const [state, setState] = useState<'idle' | 'sending' | 'done' | string>('idle');
  const ready = section.questions.filter(q => !sent.includes(q.id) && answered(drafts[q.id]));
  const left = section.questions.filter(q => !sent.includes(q.id)).length;
  const send = async () => {
    if (!site?.config || !ready.length) return;
    setState('sending');
    const answers: QuizAnswer[] = ready.map(q => {
      const d = drafts[q.id];
      return {question_id: q.id, question: q.question, topic: q.topic, choice: d.unsure ? null : d.choice,
        answer: d.unsure ? '' : d.answer.trim().slice(0, MAX_ANSWER), unsure: d.unsure};
    });
    try {
      await new FeedbackClient(site.config).open(quizIssue({kind: 'quiz', section: section.id, section_title: section.title, answers,
        at: new Date().toISOString()}));
      const ids = answers.map(a => a.question_id);
      memory.answer(ids);
      setSent(s => [...s, ...ids]);
      setDrafts(d => Object.fromEntries(Object.entries(d).filter(([k]) => !ids.includes(k))));
      setState('done');
    } catch (e) {
      setState(e instanceof Error ? e.message : 'The answers could not be sent. Try again.');
    }
  };
  return (
    <section aria-label={section.title} className="space-y-5" data-testid="quiz-section">
      <div className="space-y-1.5">
        <p className="text-[14px] text-ink-2">{section.intro || ABOUT[section.id]}</p>
        <p className="text-[13px] text-ink-3">{section.questions.length} questions · prepared {formatDate(section.prepared_at)} · {left === 0 ? 'you answered them all' : `${left} left for you`}</p>
      </div>
      <div className="flex flex-col gap-4">
        {section.questions.map((q, i) => (
          <QuestionCard key={q.id} q={q} n={i + 1} draft={drafts[q.id] ?? EMPTY} sent={sent.includes(q.id)}
            onChange={d => { setDrafts(all => ({...all, [q.id]: d})); if (state !== 'sending') setState('idle'); }} />
        ))}
      </div>
      {site?.config ? (
        <div className="sticky bottom-0 -mx-4 flex flex-wrap items-center gap-3 border-t border-line bg-page/95 px-4 py-3 backdrop-blur md:mx-0 md:rounded-2xl md:border">
          <button type="button" onClick={() => void send()} disabled={!ready.length || state === 'sending'} data-testid="quiz-send"
            className="inline-flex min-h-11 items-center gap-2 rounded-[10px] bg-[#1428a0] px-5 text-[14.5px] font-semibold text-white disabled:opacity-50">
            {state === 'sending' ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
            {ready.length ? `Send ${ready.length} ${ready.length === 1 ? 'answer' : 'answers'} anonymously` : 'Answer a question to send it'}</button>
          {state === 'done' && <span className="inline-flex items-center gap-1.5 text-[13.5px] font-medium text-ok" data-testid="quiz-sent"><Check className="size-4" />Sent. Thank you.</span>}
          {state !== 'idle' && state !== 'sending' && state !== 'done' && <span role="alert" className="text-[13.5px] text-danger">{state}</span>}
          <span className="text-[12.5px] text-ink-3 sm:ml-auto">Answer only what you know. Your name is not sent or kept.</span>
        </div>
      ) : <p className="text-[13.5px] text-ink-3">Answers cannot be sent from this site yet.</p>}
    </section>
  );
}

/** The quiz (owner, 12 Nov 2026): what Wizard's knowledge base is unsure of, prepared by Gemini in two quiz tasks, for
 *  the people who know to answer anonymously. Business intelligence holds the technical questions; Business the
 *  concepts, terms and strategy. */
export function QuizPage({home, section: wanted}: {home: string; section: string | null}) {
  const site = useCasesSite();
  const sections = site?.quiz?.sections.filter(s => s.questions.length) ?? [];
  const first = useMemo(() => sections.find(s => s.id === wanted)?.id ?? sections[0]?.id ?? null, [sections, wanted]);
  const [open, setOpen] = useState<string | null>(first);
  const shown = sections.find(s => s.id === (open ?? first)) ?? null;
  const tab = (active: boolean) => cn('min-h-11 rounded-full border px-4 text-[14px]', active ? 'border-[#1428a0] bg-[#1428a0] font-semibold text-white' : 'border-line-2 bg-canvas font-medium text-ink hover:bg-surface');
  return (
    <div className="min-h-dvh bg-page text-ink" data-testid="quiz-page">
      <SiteTop home={home} page="quiz" />
      <main className="mx-auto flex max-w-[860px] flex-col gap-6 px-4 pb-24 pt-10 md:px-8">
        <div className="space-y-2">
          <h1 className="text-[34px] font-bold leading-tight tracking-[-0.01em]">Quiz</h1>
          <p className="text-[16px] leading-normal text-ink-2">These are points Wizard's knowledge base is unsure of. Each question says what Wizard has now: confirm it, correct it, or skip what you don't know. Answers are anonymous and go to Wizard's team, who update the knowledge base.</p>
        </div>
        {sections.length > 1 && (
          <div role="tablist" aria-label="Quiz sections" className="flex flex-wrap gap-2">
            {sections.map(s => (
              <button key={s.id} type="button" role="tab" aria-selected={shown?.id === s.id} onClick={() => { setOpen(s.id); history.replaceState(null, '', `?quiz=${s.id}`); }}
                className={tab(shown?.id === s.id)} data-testid="quiz-tab">{s.title} · {s.questions.length}</button>
            ))}
          </div>
        )}
        {shown ? <SectionQuiz key={shown.id} section={shown} /> :
          <p className="text-[15px] text-ink-2" data-testid="quiz-empty">No questions yet. Wizard's team prepares them with a quiz task in Wizard (Settings → Tasks).</p>}
      </main>
    </div>
  );
}
