import {useEffect, useState} from 'react';
import {ArrowRight, Maximize2, PanelLeftClose, PanelLeftOpen, Plus, Settings, UserRound} from 'lucide-react';
import mark from '@/assets/wizard-mark.svg';
import {cn} from '@/lib/utils';
import {ChatList} from './ChatList';
import {Button} from './ui/button';
import {Hint} from './ui/menu';
import {WizardSprite} from './WizardSprite';
import type {Bootstrap, ConversationSummary} from '@/types';

/** Top row of the compact view WizardBar shows under its button: the history, title, new question, full window,
 *  account. */
export function QuickHeader({boot, title, conversationId, synthetic, history, onHistory, onNew, onAccount, onSettings}: {
  boot: Bootstrap; title: string; conversationId: string | null; synthetic: boolean; history: boolean; onHistory: () => void; onNew: () => void;
  onAccount: () => void; onSettings?: () => void;
}) {
  const account = boot.gemini_account;
  const needsLink = !!account?.needs_link && !account.linked;
  return (
    <header className="relative flex items-center gap-1.5 overflow-hidden border-b border-line bg-canvas px-3 py-2" data-testid="quick-header">
      <Hint text={history ? 'Hide your analyses' : 'Your analyses'}>
        <Button variant="ghost" size="icon-sm" onClick={onHistory} aria-label={history ? 'Hide your analyses' : 'Show your analyses'} aria-pressed={history}
          data-testid="history-toggle">{history ? <PanelLeftClose /> : <PanelLeftOpen />}</Button>
      </Hint>
      <img src={mark} alt="" className="size-6 shrink-0" />
      <h2 className="mr-1 min-w-0 flex-1 truncate text-[13.5px] font-semibold" data-testid="conversation-title">{title}</h2>
      {synthetic && <span className="rounded-full border border-warn-line bg-warn-soft px-2 py-0.5 text-[11px] font-semibold text-warn" data-testid="synthetic-banner">SYNTHETIC</span>}
      <Hint text="New question"><Button variant="ghost" size="icon-sm" onClick={onNew} aria-label="New question" data-testid="new-chat"><Plus /></Button></Hint>
      <Hint text="Open in a full window">
        <a href={conversationId ? `/?c=${encodeURIComponent(conversationId)}` : '/'} target="_blank" rel="noopener noreferrer"
          aria-label="Open in a full window" data-testid="open-full"
          className="grid size-8 place-items-center rounded-md text-ink-2 hover:bg-surface hover:text-ink [&_svg]:size-4"><Maximize2 /></a>
      </Hint>
      {onSettings && <Hint text="Settings and updates"><Button variant="ghost" size="icon-sm" onClick={onSettings} aria-label="Settings" data-testid="settings-button"><Settings /></Button></Hint>}
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

/** What the compact view shows before the first question. The wizard waves each time the panel opens (`greeting`). */
export function QuickEmpty({boot, greeting = 0, onPick, onAccount}: {boot: Bootstrap; greeting?: number; onPick: (q: string) => void; onAccount: () => void}) {
  const account = boot.gemini_account;
  const [hello, setHello] = useState(true);
  useEffect(() => {
    setHello(true);
    const timer = setTimeout(() => setHello(false), 2600);
    return () => clearTimeout(timer);
  }, [greeting]);
  return (
    <div className="mx-auto mt-4 w-full max-w-[640px] px-1" data-testid="empty-state">
      <div className="flex items-center gap-3">
        <WizardSprite animation={hello ? 'wave' : 'idle'} scale={2} label="Wizard" className="-my-2 -ml-2" />
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight">What do you want to know?</h1>
          <p className="mt-1 text-[13.5px] text-ink-2">Wizard answers from the company knowledge base and the approved data, and shows where every number comes from.</p>
        </div>
      </div>
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
      <p className="mt-5 text-[12px] text-ink-3">Ctrl+Alt+W shows or hides Wizard from anywhere. Esc hides it; a question keeps running in the background.
        Drop a file on the Ask Wizard button, or here, to attach it.</p>
    </div>
  );
}

/** The desktop panel's history (owner, 6 Nov 2026: "should have sidebar on left with chat history"): the person's
 *  analyses as the full window's sidebar lists them. Beside the chat when the panel is wide enough; over it, with a
 *  shade to click away, when it is not. */
export function QuickHistory({conversations, currentId, overlay, onSelect, onRename, onDelete, onClose}: {conversations: ConversationSummary[];
  currentId: string | null; overlay: boolean; onSelect: (id: string) => void; onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void; onClose: () => void}) {
  const list = (
    <aside aria-label="Your analyses" data-testid="quick-history" data-overlay={overlay}
      className={cn('flex h-full w-[236px] shrink-0 flex-col border-r border-line bg-surface', overlay && 'absolute inset-y-0 left-0 z-50 shadow-2xl')}>
      <p className="px-4 pb-1.5 pt-3 text-[11px] font-semibold uppercase tracking-wide text-ink-3">Your analyses</p>
      <div className="min-h-0 flex-1 overflow-y-auto scroll-thin">
        <ChatList conversations={conversations} currentId={currentId} onSelect={onSelect} onRename={onRename} onDelete={onDelete} />
      </div>
    </aside>
  );
  if (!overlay) return list;
  return <>
    <button type="button" aria-label="Hide your analyses" onClick={onClose} className="absolute inset-0 z-40 cursor-default bg-black/20" data-testid="history-shade" />
    {list}
  </>;
}
