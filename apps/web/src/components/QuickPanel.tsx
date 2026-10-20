import {ArrowRight, Maximize2, Plus, UserRound} from 'lucide-react';
import {cn} from '@/lib/utils';
import {Button} from './ui/button';
import {Hint} from './ui/menu';
import type {Bootstrap} from '@/types';

/** Top row of the compact view WizardBar shows under its button: title, new question, full window, account. */
export function QuickHeader({boot, title, conversationId, synthetic, onNew, onAccount}: {
  boot: Bootstrap; title: string; conversationId: string | null; synthetic: boolean; onNew: () => void; onAccount: () => void;
}) {
  const account = boot.gemini_account;
  const needsLink = !!account?.needs_link && !account.linked;
  return (
    <header className="flex items-center gap-1.5 border-b border-line bg-canvas px-3 py-2" data-testid="quick-header">
      <span className="grid size-6 shrink-0 place-items-center rounded-md bg-accent text-[12px] font-bold text-white" aria-hidden="true">W</span>
      <h2 className="mr-1 min-w-0 flex-1 truncate text-[13.5px] font-semibold" data-testid="conversation-title">{title}</h2>
      {synthetic && <span className="rounded-full border border-warn-line bg-warn-soft px-2 py-0.5 text-[11px] font-semibold text-warn" data-testid="synthetic-banner">SYNTHETIC</span>}
      <Hint text="New question"><Button variant="ghost" size="icon-sm" onClick={onNew} aria-label="New question" data-testid="new-chat"><Plus /></Button></Hint>
      <Hint text="Open in a full window">
        <a href={conversationId ? `/?c=${encodeURIComponent(conversationId)}` : '/'} target="_blank" rel="noopener noreferrer"
          aria-label="Open in a full window" data-testid="open-full"
          className="grid size-8 place-items-center rounded-md text-ink-2 hover:bg-surface hover:text-ink [&_svg]:size-4"><Maximize2 /></a>
      </Hint>
      <Hint text={needsLink ? 'Link your Gemini account' : 'Your account'}>
        <button type="button" onClick={onAccount} aria-label="Your account" data-testid="account-button"
          className="relative grid size-8 place-items-center rounded-md text-ink-2 hover:bg-surface hover:text-ink">
          <UserRound className="size-4" />
          <i className={cn('absolute right-1 top-1 size-2 rounded-full ring-2 ring-canvas', !account?.needs_link ? 'bg-slate-400' : account.linked ? 'bg-emerald-600' : 'bg-amber-500')} aria-hidden="true" />
        </button>
      </Hint>
    </header>
  );
}

/** What the compact view shows before the first question. */
export function QuickEmpty({boot, onPick, onAccount}: {boot: Bootstrap; onPick: (q: string) => void; onAccount: () => void}) {
  const account = boot.gemini_account;
  return (
    <div className="mx-auto mt-6 w-full max-w-[640px] px-1" data-testid="empty-state">
      <h1 className="text-[22px] font-semibold tracking-tight">What do you want to know?</h1>
      <p className="mt-1.5 text-[13.5px] text-ink-2">Wizard answers from the company knowledge base and the approved data, and shows where every number comes from.</p>
      {account?.needs_link && !account.linked && (
        <button type="button" onClick={onAccount} data-testid="link-prompt"
          className="mt-4 flex w-full items-center gap-2 rounded-xl border border-warn-line bg-warn-soft px-3 py-2.5 text-left text-[13px] text-ink">
          <span className="flex-1"><strong>First, link your Gemini account.</strong> Wizard answers under your own company Google sign-in.</span>
          <ArrowRight className="size-4 shrink-0 text-warn" />
        </button>
      )}
      {boot.suggestions.length > 0 && (
        <ul className="mt-4 space-y-1.5">
          {boot.suggestions.map(s => (
            <li key={s.story}>
              <button type="button" onClick={() => onPick(s.question)} data-testid="suggestion"
                className="w-full rounded-lg border border-line bg-canvas px-3 py-2 text-left text-[13px] leading-snug hover:border-accent-line hover:bg-accent-soft/40">{s.question}</button>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-5 text-[12px] text-ink-3">Ctrl+Alt+W shows or hides Wizard from anywhere. Esc hides it; a question keeps running in the background.</p>
    </div>
  );
}
