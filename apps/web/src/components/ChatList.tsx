import {useMemo, useState} from 'react';
import {MoreHorizontal, Pencil, Search, Trash2} from 'lucide-react';
import {cn} from '@/lib/utils';
import {DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger} from './ui/menu';
import type {ConversationSummary} from '@/types';

function group(iso: string): string {
  const date = new Date(iso); if (Number.isNaN(date.getTime())) return 'Earlier';
  const day = 86_400_000; const today = new Date(); today.setHours(0, 0, 0, 0);
  const diff = today.getTime() - new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  return diff < day ? 'Today' : diff < 2 * day ? 'Yesterday' : diff < 7 * day ? 'Previous 7 days' : 'Earlier';
}

/** The person's analyses, newest first, grouped by day, with a search and rename / delete on each: the full window's
 *  sidebar and the desktop panel's history show the same list. */
export function ChatList({conversations, currentId, onSelect, onRename, onDelete}: {conversations: ConversationSummary[]; currentId: string | null;
  onSelect: (id: string) => void; onRename: (id: string, title: string) => void; onDelete: (id: string) => void}) {
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
  return <>
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
  </>;
}
