import {createContext, useContext, useState, type FormEvent} from 'react';
import {Lock, LockOpen, ShieldCheck} from 'lucide-react';
import mark from '@/assets/wizard-mark.svg';
import {pinMatches, type Edits, type FeedbackConfig, type Quiz} from '@/feedback';
import {cn} from '@/lib/utils';
import {Dialog, DialogContent} from '../ui/dialog';

/** What the Cases site's pages share: the feedback set-up Wizard published (null: feedback is off), the admin pane's
 *  edits, the quiz, and whether this tab opened the admin pane with the PIN. */
export interface CasesSite {
  config: FeedbackConfig | null; edits: Edits; setEdits: (edits: Edits) => void; quiz: Quiz | null;
  admin: boolean; setAdmin: (on: boolean) => void;
}

export const CasesSiteContext = createContext<CasesSite | null>(null);
export const useCasesSite = () => useContext(CasesSiteContext);

/** The PIN that opens the admin pane (owner, 12 Nov 2026). It only hides the pane on this site. */
export function PinDialog({open, onClose, config, onOpen}: {open: boolean; onClose: () => void; config: FeedbackConfig; onOpen: () => void}) {
  const [pin, setPin] = useState('');
  const [wrong, setWrong] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (await pinMatches(pin, config)) { setPin(''); setWrong(false); onOpen(); return; }
    setWrong(true);
  };
  return (
    <Dialog open={open} onOpenChange={o => { if (!o) { onClose(); setPin(''); setWrong(false); } }}>
      {open && <DialogContent title="Admin" description="Enter the PIN to see everyone's feedback and quiz answers, and to edit the cases." className="w-[min(380px,94vw)]">
        <form onSubmit={e => void submit(e)} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1.5 text-[13px] text-ink-2">PIN
            <input type="password" inputMode="numeric" autoComplete="off" autoFocus value={pin} maxLength={12} data-testid="admin-pin"
              onChange={e => { setPin(e.target.value.replace(/\D/g, '')); setWrong(false); }}
              className="min-h-11 rounded-[10px] border border-line-2 bg-canvas px-3.5 text-[18px] tracking-[0.3em] text-ink outline-none focus:border-accent" />
          </label>
          {wrong && <p role="alert" className="text-[13px] text-danger" data-testid="admin-pin-wrong">That PIN is not right.</p>}
          <button type="submit" disabled={pin.length < 4} data-testid="admin-pin-open"
            className="min-h-11 rounded-[10px] bg-[#1428a0] px-4 text-[14px] font-semibold text-white disabled:opacity-50">Open the admin pane</button>
        </form>
      </DialogContent>}
    </Dialog>
  );
}

/** The top of every Cases page: the mark, Cases and the Quiz, and the admin pane's door on the right. Brain is a site of
 *  its own, so nothing here leads to it. */
export function SiteTop({home, page}: {home: string; page?: 'cases' | 'quiz' | 'admin'}) {
  const site = useCasesSite();
  const [asking, setAsking] = useState(false);
  const link = (active: boolean) => cn('rounded-full px-3 py-1.5 text-[15px] no-underline', active ? 'bg-surface font-semibold text-ink' : 'font-medium text-ink-2 hover:text-ink');
  const go = (search: string) => { location.search = search; };
  return (
    <header className="flex items-center gap-2 border-b border-line bg-canvas px-4 py-3 md:gap-3 md:px-8">
      <a href={home} className="mr-1 flex items-center gap-2.5 text-[17px] font-bold text-ink no-underline"><img src={mark} alt="" className="size-7" /><span className="max-sm:sr-only">Wizard</span></a>
      {site ? (
        <nav aria-label="Cases site" className="flex items-center gap-1">
          <a href={home} className={link(page === 'cases')} aria-current={page === 'cases' ? 'page' : undefined}>Cases</a>
          {(site.quiz || site.config) && <a href={`${home}?quiz`} className={link(page === 'quiz')} aria-current={page === 'quiz' ? 'page' : undefined} data-testid="site-quiz-link">Quiz</a>}
        </nav>
      ) : <span className="text-[15px] font-medium text-ink-2">Cases</span>}
      {site?.config && (
        <div className="ml-auto flex items-center gap-2">
          {site.admin ? <>
            {page !== 'admin' && <a href={`${home}?admin`} className="inline-flex min-h-10 items-center gap-1.5 rounded-[10px] border border-line-2 px-3 text-[14px] font-medium text-ink no-underline hover:bg-surface" data-testid="admin-pane-link"><ShieldCheck className="size-4" />Admin pane</a>}
            <button type="button" onClick={() => { site.setAdmin(false); if (page === 'admin') go(''); }} title="Close the admin pane on this tab"
              className="inline-flex min-h-10 items-center gap-1.5 rounded-[10px] px-3 text-[14px] text-ink-2 hover:bg-surface" data-testid="admin-lock"><Lock className="size-4" />Lock</button>
          </> : (
            <button type="button" onClick={() => setAsking(true)} data-testid="admin-open"
              className="inline-flex min-h-10 items-center gap-1.5 rounded-[10px] px-3 text-[14px] text-ink-2 hover:bg-surface"><LockOpen className="size-4" />Admin</button>
          )}
          <PinDialog open={asking} onClose={() => setAsking(false)} config={site.config}
            onOpen={() => { setAsking(false); site.setAdmin(true); go('?admin'); }} />
        </div>
      )}
    </header>
  );
}
