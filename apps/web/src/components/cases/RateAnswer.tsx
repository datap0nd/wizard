import {useState} from 'react';
import {Check, Loader2, Star} from 'lucide-react';
import type {CaseTurn} from '@/cases';
import {FeedbackClient, feedbackIssue, MAX_COMMENT, memory, type FeedbackConfig} from '@/feedback';
import {cn} from '@/lib/utils';

const WORDS = ['', 'Not useful', 'Not quite', 'OK', 'Good', 'Excellent'];

/** Under each answer of a case on the site (owner, 12 Nov 2026): 1 to 5 stars and an optional comment, sent
 *  anonymously. This browser remembers that it rated the answer; nothing else about the person is kept or sent. */
export function RateAnswer({config, caseId, caseTitle, turn}: {config: FeedbackConfig; caseId: string; caseTitle: string; turn: CaseTurn}) {
  const [sent, setSent] = useState<number | null>(() => memory.rated(caseId, turn.n));
  const [value, setValue] = useState(0);
  const [hover, setHover] = useState(0);
  const [comment, setComment] = useState('');
  const [state, setState] = useState<'idle' | 'sending' | string>('idle');
  if (sent) {
    return (
      <p className="flex flex-wrap items-center gap-2 border-t border-line bg-ok-soft/50 px-5 py-3 text-[13px] text-ok lg:px-6" data-testid="case-rated">
        <Check className="size-4" />You rated this answer {sent} / 5. Thank you: it was sent anonymously.
        <button type="button" onClick={() => { setSent(null); setValue(sent); }} className="ml-auto text-[12.5px] font-medium text-accent hover:underline">Rate again</button>
      </p>
    );
  }
  const send = async () => {
    setState('sending');
    try {
      await new FeedbackClient(config).open(feedbackIssue({kind: 'feedback', case: caseId, case_title: caseTitle, turn: turn.n,
        prompt: turn.prompt.slice(0, 300), stars: value, comment: comment.trim().slice(0, MAX_COMMENT), at: new Date().toISOString()}));
      memory.rate(caseId, turn.n, value);
      setSent(value);
      setComment('');
      setState('idle');
    } catch (e) {
      setState(e instanceof Error ? e.message : 'It could not be sent. Try again.');
    }
  };
  const shown = hover || value;
  return (
    <div className="space-y-2.5 border-t border-line px-5 py-3.5 lg:px-6" data-testid="case-rate">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="text-[13px] font-medium text-ink-2" id={`rate-${caseId}-${turn.n}`}>Rate this answer</span>
        <div role="radiogroup" aria-labelledby={`rate-${caseId}-${turn.n}`} className="flex" onMouseLeave={() => setHover(0)}>
          {[1, 2, 3, 4, 5].map(n => (
            <button key={n} type="button" role="radio" aria-checked={value === n} aria-label={`${n} of 5 stars: ${WORDS[n]}`}
              onClick={() => setValue(n)} onMouseEnter={() => setHover(n)} data-testid="case-star"
              className="grid size-9 place-items-center rounded-md hover:bg-surface focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
              <Star className={cn('size-[22px] transition-colors', n <= shown ? 'fill-[#f5a524] text-[#f5a524]' : 'text-[#b4bccb]')} />
            </button>
          ))}
        </div>
        {shown > 0 && <span className="text-[13px] text-ink-3">{WORDS[shown]}</span>}
      </div>
      {value > 0 && (
        <div className="space-y-2">
          <label className="flex flex-col gap-1.5 text-[13px] text-ink-2">Anything to add? (optional)
            <textarea value={comment} onChange={e => setComment(e.target.value)} maxLength={MAX_COMMENT} rows={3} data-testid="case-comment"
              placeholder="What was right, what was wrong or missing…"
              className="resize-y rounded-[10px] border border-line-2 bg-canvas px-3 py-2 text-[14px] text-ink outline-none focus:border-accent" />
          </label>
          <div className="flex flex-wrap items-center gap-3">
            <button type="button" onClick={() => void send()} disabled={state === 'sending'} data-testid="case-rate-send"
              className="inline-flex min-h-10 items-center gap-2 rounded-[10px] bg-[#1428a0] px-4 text-[14px] font-semibold text-white disabled:opacity-60">
              {state === 'sending' && <Loader2 className="size-4 animate-spin" />}Send anonymously</button>
            <span className="text-[12.5px] text-ink-3">Your name is not sent or kept.</span>
          </div>
          {state !== 'idle' && state !== 'sending' && <p role="alert" className="text-[13px] text-danger">{state}</p>}
        </div>
      )}
    </div>
  );
}
