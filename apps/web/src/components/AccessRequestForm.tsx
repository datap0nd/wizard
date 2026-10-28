import {useCallback, useEffect, useState} from 'react';
import {CheckCircle2, ExternalLink, Loader2, Plus, Save, X} from 'lucide-react';
import {api, ApiError} from '@/api';
import {Button} from './ui/button';
import type {AccessForm, Answer} from '@/types';

const input = 'h-8 w-full rounded-lg border border-line bg-canvas px-2.5 text-[13px] outline-none focus:border-accent';

/** The answers this person gives on every access request in a portal's information catalog (purpose, manager,
 *  duration...), kept on this PC. Wizard fills them into the request form's empty fields when it opens it; the person
 *  checks every field and submits the request themselves. */
export function AccessRequestForm({system, name}: {system: string; name: string}) {
  const [form, setForm] = useState<AccessForm | null>(null);
  const [page, setPage] = useState('');
  const [fields, setFields] = useState<Answer[]>([]);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<'save' | 'open' | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const show = useCallback((saved: AccessForm) => {
    setForm(saved); setPage(saved.page); setFields(saved.fields.length ? saved.fields : [{label: '', value: ''}]); setDirty(false);
  }, []);
  useEffect(() => {
    api.accessForm(system).then(show).catch(e => setError(e instanceof Error ? e.message : 'The form could not be read.'));
  }, [system, show]);

  const change = (next: Answer[]) => { setFields(next); setDirty(true); setNotice(null); };
  const unused = (form?.seen ?? []).filter(label => !fields.some(f => f.label.trim().toLowerCase() === label.toLowerCase()));

  async function save() {
    setBusy('save'); setError(null); setNotice(null);
    try {
      show(await api.saveAccessForm(system, {page: page.trim(), fields: fields.filter(f => f.label.trim())}));
      setNotice('Saved on this PC.');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The form could not be saved.');
    } finally { setBusy(null); }
  }

  async function open() {
    setBusy('open'); setError(null); setNotice(null);
    try {
      if (dirty) show(await api.saveAccessForm(system, {page: page.trim(), fields: fields.filter(f => f.label.trim())}));
      await api.openAccessRequest(system);
      setNotice("The request page is open in Wizard's browser window on this PC. Check every field Wizard filled, submit it there, then close the window.");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The request page could not be opened.');
    } finally { setBusy(null); }
  }

  if (!form) return error ? <p className="mt-3 text-xs text-danger" role="alert">{error}</p> : null;
  return (
    <div className="mt-3 space-y-2.5 rounded-lg border border-line px-3 py-3" data-testid="access-form">
      <div>
        <p className="text-[13px] font-medium">Access request form · {name}</p>
        <p className="text-xs text-ink-3">The answers you give on every request in the information catalog. When Wizard opens the
          request form, it fills these into the empty fields; you check every field and submit the request yourself.</p>
      </div>
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-ink-2">Request page (optional)</span>
        <input className={input} value={page} placeholder={form.default_page} data-testid="access-form-page"
          onChange={e => { setPage(e.target.value); setDirty(true); setNotice(null); }} />
        <span className="mt-1 block text-[11.5px] text-ink-3">Only if the catalog has one page for every request. Otherwise Wizard opens the
          catalog, or the table's own page when it prepares a request for you.</span>
      </label>
      <div className="space-y-1.5" role="group" aria-label="Your usual answers">
        <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)_auto] gap-1.5 text-[11.5px] text-ink-3">
          <span>Field, as the form names it</span><span>Your usual answer</span><span className="w-7" />
        </div>
        {fields.map((field, index) => (
          <div key={index} className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)_auto] gap-1.5" data-testid="access-form-row">
            <input className={input} value={field.label} placeholder="e.g. Purpose" aria-label={`Field ${index + 1}`}
              onChange={e => change(fields.map((f, i) => (i === index ? {...f, label: e.target.value} : f)))} />
            <input className={input} value={field.value} placeholder="e.g. Weekly sales reporting" aria-label={`Answer ${index + 1}`}
              onChange={e => change(fields.map((f, i) => (i === index ? {...f, value: e.target.value} : f)))} />
            <Button size="xs" variant="ghost" aria-label={`Remove field ${index + 1}`}
              onClick={() => change(fields.length > 1 ? fields.filter((_, i) => i !== index) : [{label: '', value: ''}])}><X /></Button>
          </div>
        ))}
        <Button size="xs" variant="ghost" onClick={() => change([...fields, {label: '', value: ''}])} data-testid="access-form-add"><Plus />Add a field</Button>
      </div>
      {unused.length > 0 && (
        <div className="text-xs text-ink-3" data-testid="access-form-seen">
          <p>Fields Wizard saw on the request form last time:</p>
          <div className="mt-1 flex flex-wrap gap-1">
            {unused.map(label => (
              <button key={label} type="button" className="rounded-full border border-line bg-canvas px-2 py-0.5 text-ink-2 hover:border-accent hover:text-accent"
                onClick={() => change([...fields.filter(f => f.label.trim() || f.value.trim()), {label, value: ''}])}>+ {label}</button>
            ))}
          </div>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="xs" variant={dirty ? 'accent' : 'outline'} onClick={() => void save()} disabled={!dirty || busy !== null} data-testid="access-form-save">
          {busy === 'save' ? <Loader2 className="animate-spin" /> : <Save />}Save answers</Button>
        <Button size="xs" variant="ghost" onClick={() => void open()} disabled={busy !== null} data-testid="access-form-open">
          {busy === 'open' ? <Loader2 className="animate-spin" /> : <ExternalLink />}Open the request page</Button>
      </div>
      {notice && <p className="flex items-start gap-1.5 text-xs text-emerald-800" role="status"><CheckCircle2 className="mt-px size-3.5 shrink-0" />{notice}</p>}
      {error && <p className="text-xs text-danger" role="alert">{error}</p>}
    </div>
  );
}
