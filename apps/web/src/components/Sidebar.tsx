import {useMemo, useState} from 'react';
import {Database, LogOut, MessagesSquare, MoreHorizontal, Pencil, Plus, Search, Trash2, UserRound} from 'lucide-react';
import {cn} from '@/lib/utils';
import {Button} from './ui/button';
import {DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, Hint} from './ui/menu';
import {SourceExplorer} from './SourceExplorer';
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
  onLogout: () => void;
  onAsk: (text: string) => void;
}

function group(iso: string): string {
  const date = new Date(iso); if (Number.isNaN(date.getTime())) return 'Earlier';
  const day = 86_400_000; const today = new Date(); today.setHours(0, 0, 0, 0);
  const diff = today.getTime() - new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  return diff < day ? 'Today' : diff < 2 * day ? 'Yesterday' : diff < 7 * day ? 'Previous 7 days' : 'Earlier';
}

export function Sidebar({boot, conversations, currentId, onNew, onSelect, onRename, onDelete, onAccount, onLogout, onAsk}: Props) {
  const [tab, setTab] = useState<'chats' | 'sources'>('chats');
  const [query, setQuery] = useState('');
  const [renaming, setRenaming] = useState<{id: string; title: string} | null>(null);
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const out: {label: string; items: ConversationSummary[]}[] = [];
    for (const c of conversations.filter(c => !q || c.title.toLowerCase().includes(q))) {
      const label = group(c.updated_at);
      const existing = out.find(g => g.label === label);
      if (existing) existing.items.push(c); else out.push({label, items: [c]});
    }
    return out;
  }, [conversations, query]);
  const account = boot.gemini_account;
  const needsLink = !!account?.needs_link && !account.linked;
  return (
    <aside aria-label="Navigation" className="flex h-full w-[272px] shrink-0 flex-col border-r border-line bg-surface">
      <div className="flex items-center gap-2 px-3 py-3">
        <span className="flex items-center gap-2 pl-1 text-[15px] font-semibold tracking-tight"><span className="grid size-6 place-items-center rounded-md bg-accent text-[12px] font-bold text-white">W</span>Wizard</span>
        <Hint text="New analysis"><Button variant="ghost" size="icon-sm" className="ml-auto" onClick={onNew} aria-label="New analysis" data-testid="new-chat"><Plus /></Button></Hint>
      </div>
      <div role="tablist" aria-label="Sidebar" className="mx-3 mb-2 grid grid-cols-2 rounded-lg bg-surface-2 p-1">
        {([['chats', 'Analyses', <MessagesSquare key="c" />], ['sources', 'Sources', <Database key="s" />]] as const).map(([key, label, icon]) => (
          <button key={key} role="tab" type="button" aria-selected={tab === key} onClick={() => setTab(key)} data-testid={`tab-${key}`}
            className={cn('inline-flex items-center justify-center gap-1.5 rounded-md py-1 text-[13px] font-medium [&_svg]:size-3.5', tab === key ? 'bg-canvas text-accent shadow-sm' : 'text-ink-2 hover:text-ink')}>{icon}{label}</button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto scroll-thin">
        {tab === 'sources' ? <SourceExplorer onAsk={onAsk} /> : <>
          <div className="px-3 pb-2">
            <label className="relative block">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-ink-3" aria-hidden="true" />
              <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search analyses" aria-label="Search analyses"
                className="h-8 w-full rounded-md border border-line bg-canvas pl-8 pr-2 text-[13px] outline-none placeholder:text-ink-3 focus:border-line-2" />
            </label>
          </div>
          <nav className="px-2 pb-3" aria-label="Analyses">
            {groups.length === 0 && <p className="px-2 py-3 text-[13px] text-ink-3">{query ? 'No analyses match.' : 'No analyses yet.'}</p>}
            {groups.map(g => (
              <div key={g.label} className="mb-2">
                <p className="px-2 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-ink-3">{g.label}</p>
                <ul className="flex flex-col gap-px">
                  {g.items.map(c => (
                    <li key={c.id} className={cn('group flex items-center rounded-md', c.id === currentId ? 'bg-canvas shadow-card' : 'hover:bg-canvas/70')}>
                      {renaming?.id === c.id ? (
                        <form className="flex flex-1" onSubmit={e => { e.preventDefault(); if (renaming.title.trim()) onRename(c.id, renaming.title.trim()); setRenaming(null); }}>
                          <input autoFocus value={renaming.title} onChange={e => setRenaming({id: c.id, title: e.target.value})} onBlur={() => setRenaming(null)}
                            onKeyDown={e => { if (e.key === 'Escape') setRenaming(null); }} aria-label="Analysis title" className="h-8 w-full rounded-md border border-line-2 bg-canvas px-2 text-[13px] outline-none" />
                        </form>
                      ) : <>
                        <button type="button" onClick={() => onSelect(c.id)} aria-current={c.id === currentId ? 'page' : undefined} data-testid="conversation-item"
                          className={cn('min-w-0 flex-1 truncate px-2 py-1.5 text-left text-[13px]', c.id === currentId ? 'font-medium text-ink' : 'text-ink-2')}>{c.title}</button>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild><button type="button" aria-label={`Actions for ${c.title}`} className="mr-1 rounded p-1 text-ink-3 opacity-0 hover:bg-surface-2 focus-visible:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100"><MoreHorizontal className="size-4" /></button></DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onSelect={() => setRenaming({id: c.id, title: c.title})}><Pencil className="size-3.5" />Rename</DropdownMenuItem>
                            <DropdownMenuItem danger onSelect={() => onDelete(c.id)}><Trash2 className="size-3.5" />Delete</DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        </>}
      </div>
      <div className="border-t border-line p-2">
        <button type="button" onClick={onAccount} data-testid="account-button" className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left hover:bg-canvas">
          <span className="grid size-8 shrink-0 place-items-center rounded-full bg-canvas text-ink-2 shadow-sm"><UserRound className="size-4" /></span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-medium">{boot.identity?.name}</span>
            <span className="flex items-center gap-1.5 text-[11.5px] text-ink-3">
              <i className={cn('size-1.5 rounded-full', !account?.needs_link ? 'bg-slate-400' : account.linked ? 'bg-emerald-600' : 'bg-amber-500')} aria-hidden="true" />
              {!account?.needs_link ? `${boot.identity?.role} · replay mode` : account.linked ? `Gemini linked${account.google_email ? ` · ${account.google_email}` : ''}` : 'Link your Gemini account'}
            </span>
          </span>
        </button>
        {needsLink && <p className="px-2 pb-1 text-[11.5px] text-warn">Questions run under your own Gemini account.</p>}
        <Button variant="ghost" size="xs" className="w-full justify-start text-ink-3" onClick={onLogout}><LogOut />Sign out</Button>
      </div>
    </aside>
  );
}
