import {useState} from 'react';
import {CalendarClock, Database, LogOut, MessagesSquare, Plus, ScrollText, Settings, UserRound} from 'lucide-react';
import {cn} from '@/lib/utils';
import {Button} from './ui/button';
import {ChatList} from './ChatList';
import {Hint} from './ui/menu';
import {QuotaRing} from './QuotaRing';
import mark from '@/assets/wizard-mark.svg';
import {SourceExplorer} from './SourceExplorer';
import {RecurringPanel} from './RecurringPanel';
import type {Bootstrap, ConversationSummary} from '@/types';

interface Props {
  boot: Bootstrap;
  conversations: ConversationSummary[];
  currentId: string | null;
  onNew: () => void;
  onSelect: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  onAccount: () => void;
  onLog: () => void;
  busy: boolean;
  onLogout: () => void;
  onAsk: (text: string) => void;
  /** Set on a person's own install: their settings, model and updates. */
  onSettings?: () => void;
}

export function Sidebar({boot, conversations, currentId, onNew, onSelect, onRename, onDelete, onAccount, onLog, onLogout, onAsk, onSettings, busy}: Props) {
  const [tab, setTab] = useState<'chats' | 'recurring' | 'sources'>('chats');
  const recurring = !!boot.metronome?.enabled;
  const account = boot.gemini_account;
  return (
    <aside aria-label="Navigation" className="flex h-full w-[272px] shrink-0 flex-col border-r border-line bg-surface">
      <div className="flex items-center gap-2 px-3 py-3">
        <span className="flex items-center gap-2 pl-1 text-[15px] font-semibold tracking-tight"><img src={mark} alt="" className="size-6" />Wizard</span>
        <Hint text="New analysis"><Button variant="ghost" size="icon-sm" className="ml-auto" onClick={onNew} aria-label="New analysis" data-testid="new-chat"><Plus /></Button></Hint>
      </div>
      <div role="tablist" aria-label="Sidebar" className={cn('mx-3 mb-2 grid rounded-lg bg-surface-2 p-1', recurring ? 'grid-cols-3' : 'grid-cols-2')}>
        {([['chats', 'Analyses', <MessagesSquare key="c" />], ...(recurring ? [['recurring', 'Recurring', <CalendarClock key="r" />] as const] : []),
          ['sources', 'Sources', <Database key="s" />]] as const).map(([key, label, icon]) => (
          <button key={key} role="tab" type="button" aria-selected={tab === key} onClick={() => setTab(key)} data-testid={`tab-${key}`}
            className={cn('inline-flex items-center justify-center rounded-md py-1 text-[13px] font-medium [&_svg]:size-3.5', recurring ? 'gap-1' : 'gap-1.5', tab === key ? 'bg-canvas text-accent shadow-sm' : 'text-ink-2 hover:text-ink')}>{icon}{label}</button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto scroll-thin">
        {tab === 'sources' ? <SourceExplorer onAsk={onAsk} /> : tab === 'recurring' ? <RecurringPanel /> : <>
          <ChatList conversations={conversations} currentId={currentId} onSelect={onSelect} onRename={onRename} onDelete={onDelete} />
        </>}
      </div>
      <div className="border-t border-line p-2">
        <div className="flex items-center gap-1">
        <button type="button" onClick={onAccount} data-testid="account-button" className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-2 text-left hover:bg-canvas">
          <span className="grid size-8 shrink-0 place-items-center rounded-full bg-canvas text-ink-2 shadow-sm"><UserRound className="size-4" /></span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-medium">{boot.identity?.name}</span>
            <span className="flex items-center gap-1.5 text-[11.5px] text-ink-3">
              <i className={cn('size-1.5 rounded-full', !account?.needs_link ? 'bg-slate-400' : account.linked ? 'bg-emerald-600' : 'bg-amber-500')} aria-hidden="true" />
              {!account?.needs_link ? `${boot.identity?.role} · replay mode` : account.linked ? `Gemini linked${account.google_email ? ` · ${account.google_email}` : ''}` : 'Link your Gemini account'}
            </span>
          </span>
        </button>
        <QuotaRing enabled={!!account?.needs_link && !!account.linked} busy={busy} />
        </div>
        <div className="flex">
          <Button variant="ghost" size="xs" className="flex-1 justify-start text-ink-3" onClick={onLogout}><LogOut />Sign out</Button>
          {onSettings && <Button variant="ghost" size="xs" className="text-ink-3" onClick={onSettings} data-testid="settings-button"><Settings />Settings</Button>}
          {boot.diagnostics && <Button variant="ghost" size="xs" className="text-ink-3" onClick={onLog} data-testid="log-button"><ScrollText />Log</Button>}
        </div>
      </div>
    </aside>
  );
}
