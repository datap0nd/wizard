import {useEffect, useState} from 'react';
import {Pencil, Plus, Trash2} from 'lucide-react';
import {api, ApiError} from '@/api';
import {Button} from './ui/button';
import type {Memory} from '@/types';

/** What Wizard remembers for this person: their own notes (usually corrections), sent with every question they ask. Only
 * they see them; they add, edit and delete them here, or with Remember under a note or a question. */
export function RememberedNotes({open}: {open: boolean}) {
  const [notes, setNotes] = useState<Memory[] | null>(null);
  const [adding, setAdding] = useState('');
  const [editing, setEditing] = useState<{id: string; text: string} | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!open) return;
    api.memories().then(r => setNotes(r.memories)).catch(() => setNotes([]));
  }, [open]);
  const fail = (e: unknown, fallback: string) => setError(e instanceof ApiError ? e.message : fallback);
  async function add() {
    setError(null);
    try { const {memory} = await api.remember(adding.trim()); setNotes(n => [...(n ?? []), memory]); setAdding(''); }
    catch (e) { fail(e, 'The note could not be kept.'); }
  }
  async function save() {
    if (!editing) return;
    setError(null);
    try { await api.editMemory(editing.id, editing.text.trim()); setNotes(n => (n ?? []).map(m => (m.id === editing.id ? {...m, text: editing.text.trim()} : m))); setEditing(null); }
    catch (e) { fail(e, 'The note could not be changed.'); }
  }
  async function remove(id: string) {
    setError(null);
    try { await api.forget(id); setNotes(n => (n ?? []).filter(m => m.id !== id)); }
    catch (e) { fail(e, 'The note could not be deleted.'); }
  }
  return (
    <section className="rounded-xl border border-line p-4" data-testid="remembered-notes">
      <h3 className="font-semibold">What Wizard remembers</h3>
      <p className="mt-1 text-[13px] text-ink-2">Your own notes, sent with every question you ask, such as which table to use for a figure. Only you see them.</p>
      {notes === null ? <p className="mt-3 text-[13px] text-ink-3">Loading…</p> : <>
        {notes.length === 0 && <p className="mt-3 text-[13px] text-ink-3">Nothing yet. Press Remember under a note you sent Wizard, or under a question.</p>}
        <ul className="mt-3 space-y-1.5">
          {notes.map(note => (
            <li key={note.id} className="flex items-start gap-2 rounded-lg bg-surface px-3 py-2 text-[13px]" data-testid="remembered-note">
              {editing?.id === note.id ? (
                <form className="flex flex-1 gap-1.5" onSubmit={e => { e.preventDefault(); void save(); }}>
                  <input autoFocus value={editing.text} maxLength={500} onChange={e => setEditing({id: note.id, text: e.target.value})} aria-label="Edit the note"
                    className="h-8 min-w-0 flex-1 rounded-md border border-line bg-canvas px-2 outline-none focus:border-line-2" />
                  <Button type="submit" size="xs" disabled={!editing.text.trim()}>Save</Button>
                  <Button size="xs" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
                </form>
              ) : <>
                <span className="min-w-0 flex-1 break-words">{note.text}</span>
                <Button size="icon-sm" variant="ghost" aria-label="Edit the note" onClick={() => setEditing({id: note.id, text: note.text})}><Pencil /></Button>
                <Button size="icon-sm" variant="ghost" aria-label="Delete the note" onClick={() => void remove(note.id)}><Trash2 /></Button>
              </>}
            </li>
          ))}
        </ul>
        <form className="mt-2 flex gap-1.5" onSubmit={e => { e.preventDefault(); if (adding.trim()) void add(); }}>
          <input value={adding} maxLength={500} onChange={e => setAdding(e.target.value)} placeholder="e.g. For sell-out, use the weekly sell-out view"
            aria-label="A note for Wizard to remember" className="h-9 min-w-0 flex-1 rounded-lg border border-line px-3 text-sm outline-none focus:border-line-2" />
          <Button type="submit" size="sm" variant="outline" disabled={!adding.trim()}><Plus />Add</Button>
        </form>
      </>}
      {error && <p className="mt-2 rounded-lg bg-danger-soft px-3 py-2 text-[13px] text-danger" role="alert">{error}</p>}
    </section>
  );
}
