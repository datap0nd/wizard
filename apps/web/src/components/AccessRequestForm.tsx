import {useCallback, useEffect, useState} from 'react';
import {CheckCircle2, ExternalLink, ListChecks, Loader2, Plus, RefreshCw, Save, Send, Square, Trash2, X} from 'lucide-react';
import {api, ApiError} from '@/api';
import {formatDate} from '@/format';
import {Button} from './ui/button';
import type {AccessField, AccessForm, AccessSending, Answer, QueuedRequest, Submission} from '@/types';

const input = 'h-8 w-full rounded-lg border border-line bg-canvas px-2.5 text-[13px] outline-none focus:border-accent';
const blank: Answer = {label: '', value: ''};

/** How a field is named: "DPA / DSA › Purpose", or its label alone. */
const fieldName = (f: Answer) => (f.section ? `${f.section} › ${f.label}` : f.label);
const saved = (f: Answer): Answer => ({label: f.label, value: f.value, ...(f.section ? {section: f.section} : {}), ...(f.kind ? {kind: f.kind} : {})});

function where(item: QueuedRequest): string {
  if (item.tables.length) return item.tables.join(', ');
  try {
    const url = new URL(item.address);
    return url.host + url.pathname;
  } catch {
    return item.address;
  }
}

function state(item: QueuedRequest): string {
  if (item.sent) return `sent by ${item.sent.by === 'you' ? 'you' : 'Wizard'} ${formatDate(item.sent.at, true)}`;
  if (item.failed) return 'not sent';
  return item.opened ? `opened ${formatDate(item.opened, true)}` : 'not opened';
}

/** What the window saw when a request went out: the control, the request and the catalog's answer. */
function described(s: Submission): string {
  const expect = Object.entries(s.expect ?? {}).map(([k, v]) => `${k}: ${String(v)}`).join(', ');
  return `you pressed ${s.button || 'a button'}${s.dialog ? ` and answered OK to "${s.dialog}"` : ''}; it sent ${s.method} ${s.path}, `
    + `and the catalog answered ${s.status}${expect ? ` (${expect})` : ''}`;
}

/** Sending: Wizard watches the person submit one request; once they say it worked, it sends the ones they approve. */
function SendingPanel({sending, busy, onToggle}: {sending: AccessSending; busy: boolean; onToggle: (on: boolean) => void}) {
  const last = sending.last_submission;
  const went = !!last && last.status >= 200 && last.status < 300;
  if (sending.enabled && sending.proof) {
    return (
      <div className="rounded-md bg-emerald-50 px-2.5 py-2 text-xs text-emerald-900" data-testid="access-sending" data-enabled="true">
        <p>Wizard sends the requests you approve, the way your own request{sending.proof.tables?.length ? ` for ${sending.proof.tables.join(', ')}` : ''} went
          ({described(sending.proof)}), and stops at the first that does not go through the same way.</p>
        <Button size="xs" variant="ghost" className="mt-1" onClick={() => onToggle(false)} disabled={busy} data-testid="access-sending-off">Turn off</Button>
      </div>
    );
  }
  return (
    <div className="rounded-md bg-surface px-2.5 py-2 text-xs text-ink-2" data-testid="access-sending" data-enabled="false">
      {went && last ? (<>
        <p>Wizard saw your request{last.tables?.length ? ` for ${last.tables.join(', ')}` : ''} go out: {described(last)}. If the catalog
          accepted it, Wizard can send the next ones the same way, each only when you approve it.</p>
        <Button size="xs" variant="accent" className="mt-1.5" onClick={() => onToggle(true)} disabled={busy} data-testid="access-sending-on">
          <CheckCircle2 />It worked: let Wizard send the requests I approve</Button>
      </>) : last ? (
        <p>Wizard saw your last request answered {last.status}: submit one that goes through, and Wizard can send the next ones the same way.</p>
      ) : (
        <p>Wizard fills each request and you press Submit. Submit one yourself in Wizard's window, and Wizard can send the next ones the same
          way, each when you approve it.</p>
      )}
    </div>
  );
}

/** The portal's predefined fields, the ones sharing a section in one box (DPA / DSA). */
function groups(presets: AccessField[]): {section: string; fields: {field: AccessField; index: number}[]}[] {
  const out: {section: string; fields: {field: AccessField; index: number}[]}[] = [];
  presets.forEach((field, index) => {
    const section = field.section ?? '';
    const last = out[out.length - 1];
    if (last && last.section === section) last.fields.push({field, index});
    else out.push({section, fields: [{field, index}]});
  });
  return out;
}

/** The answers this person gives on every access request in a portal's information catalog: the form's predefined
 *  fields (the Big Data Portal's purpose and its DPA / DSA box) and any other field they add, kept on this PC. Wizard
 *  fills them into the request form's empty fields, choosing their option in a drop-down, when it opens the form; the
 *  person checks every field and submits the request themselves. Below them, the requests Gemini prepared. */
export function AccessRequestForm({system, name}: {system: string; name: string}) {
  const [form, setForm] = useState<AccessForm | null>(null);
  const [page, setPage] = useState('');
  const [presets, setPresets] = useState<AccessField[]>([]);
  const [fields, setFields] = useState<Answer[]>([]);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const show = useCallback((next: AccessForm) => {
    setForm(next); setPage(next.page);
    setPresets(next.fields.filter(f => f.preset));
    const own = next.fields.filter(f => !f.preset).map(saved);
    setFields(own.length ? own : [blank]); setDirty(false);
  }, []);
  const reload = useCallback(() => {
    api.accessForm(system).then(show).catch(e => setError(e instanceof Error ? e.message : 'The form could not be read.'));
  }, [system, show]);
  useEffect(reload, [reload]);

  const change = (next: Answer[]) => { setFields(next); setDirty(true); setNotice(null); };
  const answer = (index: number, value: string) => {
    setPresets(presets.map((f, i) => (i === index ? {...f, value} : f))); setDirty(true); setNotice(null);
  };
  const unused = (form?.seen ?? []).filter(label => ![...presets, ...fields].some(f => f.label.trim().toLowerCase() === label.toLowerCase()));
  const queue = form?.queue ?? [];
  const waiting = queue.filter(item => !item.opened).length;
  const unsent = queue.filter(item => !item.sent);
  const canSend = !!form?.sending?.enabled;
  const [confirming, setConfirming] = useState(false);
  const [sendingNow, setSendingNow] = useState(false);

  const payload = () => ({page: page.trim(), fields: [...presets.map(saved), ...fields.filter(f => f.label.trim()).map(saved)]});
  async function save() {
    setBusy('save'); setError(null); setNotice(null);
    try {
      show(await api.saveAccessForm(system, payload()));
      setNotice('Saved on this PC.');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The form could not be saved.');
    } finally { setBusy(null); }
  }

  /** Open the request page (no argument), a prepared request (its id), or the next prepared one not opened yet. */
  async function open(queued?: string) {
    setBusy(queued ?? 'open'); setError(null); setNotice(null);
    try {
      if (dirty) show(await api.saveAccessForm(system, payload()));
      const status = await api.openAccessRequest(system, queued ? {queued} : {});
      const place = status.access_request?.queued;
      setNotice(place
        ? `Prepared request ${place.position} of ${place.total} is open in Wizard's browser window on this PC. Press Request access there if the form is behind it, check every field Wizard filled, submit it, then press Next request in Wizard's note on the page.`
        : "The request page is open in Wizard's browser window on this PC. Check every field Wizard filled, submit it there, then close the window.");
      if (queued) reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The request page could not be opened.');
    } finally { setBusy(null); }
  }

  async function toggle(on: boolean) {
    setBusy('sending'); setError(null); setNotice(null);
    try {
      setForm(await api.setAccessSending(system, on));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not work.');
    } finally { setBusy(null); }
  }

  /** The person's permission: Wizard sends these (or every request not sent yet) in its window. */
  async function send(ids?: string[]) {
    setBusy('send'); setError(null); setNotice(null); setConfirming(false);
    try {
      await api.sendAccessRequests(system, ids ? {ids} : {waiting: true});
      setSendingNow(true);
      setNotice(`Wizard is sending ${ids ? ids.length : unsent.length} request(s) in its browser window on this PC, one after another, and stops at the first that does not go through. Press Refresh to see each one marked sent.`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Sending did not start.');
    } finally { setBusy(null); }
  }

  async function stop() {
    setBusy('stop');
    try {
      await api.stopSendingAccessRequests(system);
      setSendingNow(false); setNotice('Sending stopped.'); reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not work.');
    } finally { setBusy(null); }
  }

  async function remove(body: {ids?: string[]; opened?: boolean}) {
    setBusy('remove'); setError(null); setNotice(null);
    try {
      const next = await api.removeQueuedRequests(system, body);
      setForm(next);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not work.');
    } finally { setBusy(null); }
  }

  if (!form) return error ? <p className="mt-3 text-xs text-danger" role="alert">{error}</p> : null;
  return (
    <div className="mt-3 space-y-2.5 rounded-lg border border-line px-3 py-3" data-testid="access-form">
      <div>
        <p className="text-[13px] font-medium">Access request form · {name}</p>
        <p className="text-xs text-ink-3">The answers you give on every request in the information catalog. When Wizard opens the
          request form, it fills these into the empty fields and chooses your option in a drop-down; you check every field
          and submit the request yourself. The form fills in your name and email itself.</p>
      </div>
      {groups(presets).map(group => (
        <div key={group.section || 'form'} className={group.section ? 'space-y-2 rounded-lg border border-line px-2.5 py-2.5' : 'space-y-2'}
          role="group" aria-label={group.section || 'The form'} data-testid="access-form-section">
          {group.section && <p className="text-xs font-semibold text-ink-2">{group.section}</p>}
          {group.fields.map(({field, index}) => (
            <label key={fieldName(field)} className="block" data-testid="access-form-preset">
              <span className="mb-1 flex items-center gap-1.5 text-xs font-medium text-ink-2">{field.label}
                <span className="rounded bg-surface px-1.5 text-[10.5px] font-normal text-ink-3">{field.kind === 'choice' ? 'drop-down' : 'free text'}</span>
              </span>
              <input className={input} value={field.value} aria-label={fieldName(field)}
                placeholder={field.example ? `e.g. ${field.example}` : ''} onChange={e => answer(index, e.target.value)} />
              {field.hint && <span className="mt-1 block text-[11.5px] text-ink-3">{field.hint}</span>}
            </label>
          ))}
        </div>
      ))}
      <div className="space-y-1.5" role="group" aria-label="Your other answers">
        <p className="text-xs font-medium text-ink-2">{presets.length ? 'Other fields (optional)' : 'Your usual answers'}</p>
        <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)_auto] gap-1.5 text-[11.5px] text-ink-3">
          <span>Field, as the form names it</span><span>Your usual answer</span><span className="w-7" />
        </div>
        {fields.map((field, index) => (
          <div key={index} className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)_auto] gap-1.5" data-testid="access-form-row">
            <input className={input} value={field.label} placeholder="e.g. Duration" aria-label={`Field ${index + 1}`}
              onChange={e => change(fields.map((f, i) => (i === index ? {...f, label: e.target.value} : f)))} />
            <input className={input} value={field.value} placeholder="e.g. 6 months" aria-label={`Answer ${index + 1}`}
              onChange={e => change(fields.map((f, i) => (i === index ? {...f, value: e.target.value} : f)))} />
            <Button size="xs" variant="ghost" aria-label={`Remove field ${index + 1}`}
              onClick={() => change(fields.length > 1 ? fields.filter((_, i) => i !== index) : [blank])}><X /></Button>
          </div>
        ))}
        <Button size="xs" variant="ghost" onClick={() => change([...fields, blank])} data-testid="access-form-add"><Plus />Add a field</Button>
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
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-ink-2">Request page (optional)</span>
        <input className={input} value={page} placeholder={form.default_page} data-testid="access-form-page"
          onChange={e => { setPage(e.target.value); setDirty(true); setNotice(null); }} />
        <span className="mt-1 block text-[11.5px] text-ink-3">Only if the catalog has one page for every request. Otherwise Wizard opens the
          catalog, or the table's own page when it prepares a request for you.</span>
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="xs" variant={dirty ? 'accent' : 'outline'} onClick={() => void save()} disabled={!dirty || busy !== null} data-testid="access-form-save">
          {busy === 'save' ? <Loader2 className="animate-spin" /> : <Save />}Save answers</Button>
        <Button size="xs" variant="ghost" onClick={() => void open()} disabled={busy !== null} data-testid="access-form-open">
          {busy === 'open' ? <Loader2 className="animate-spin" /> : <ExternalLink />}Open the request page</Button>
      </div>

      <div className="space-y-2 border-t border-line pt-2.5" data-testid="access-queue">
        <div className="flex items-center gap-2">
          <p className="flex flex-1 items-center gap-1.5 text-[13px] font-medium"><ListChecks className="size-3.5" />Prepared requests
            <span className="font-normal text-ink-3">{queue.length ? `· ${waiting} not opened of ${queue.length}` : ''}</span></p>
          <Button size="xs" variant="ghost" aria-label="Refresh the prepared requests" onClick={reload} disabled={busy !== null}><RefreshCw /></Button>
        </div>
        {form.sending && <SendingPanel sending={form.sending} busy={busy !== null} onToggle={on => void toggle(on)} />}
        {queue.length === 0 ? (
          <p className="text-xs text-ink-3">None yet. When Gemini finds a table you lack, in an answer or a task, it prepares the request here.</p>
        ) : (<>
          <p className="text-xs text-ink-3">Each opens the table's page in Wizard's browser window with your answers ready. Press Request access there
            if the form is behind it, check the form and submit it; Next request in Wizard's note on the page opens the following one.</p>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="xs" variant="accent" onClick={() => void open('next')} disabled={busy !== null || waiting === 0} data-testid="access-queue-next">
              {busy === 'next' ? <Loader2 className="animate-spin" /> : <ExternalLink />}Open the next request</Button>
            {canSend && unsent.length > 0 && !confirming && (
              <Button size="xs" variant="accent" onClick={() => setConfirming(true)} disabled={busy !== null} data-testid="access-queue-send">
                <Send />Send the {unsent.length} not sent</Button>
            )}
            {sendingNow && (
              <Button size="xs" variant="ghost" onClick={() => void stop()} disabled={busy !== null} data-testid="access-queue-stop"><Square />Stop sending</Button>
            )}
            {queue.some(item => item.opened) && (
              <Button size="xs" variant="ghost" onClick={() => void remove({opened: true})} disabled={busy !== null} data-testid="access-queue-clear">
                <Trash2 />Remove the opened ones</Button>
            )}
          </div>
          {confirming && (
            <div className="rounded-md border border-accent/40 bg-canvas px-2.5 py-2 text-xs" data-testid="access-queue-confirm">
              <p>Send {unsent.length} request{unsent.length === 1 ? '' : 's'} ({unsent.slice(0, 3).map(where).join(', ')}{unsent.length > 3 ? ', …' : ''})?
                Wizard opens each in its browser window, fills the form with your answers, presses {form.sending.proof?.button || 'Submit'} and checks the
                catalog's answer.</p>
              <div className="mt-1.5 flex gap-2">
                <Button size="xs" variant="accent" onClick={() => void send()} disabled={busy !== null} data-testid="access-queue-send-yes">
                  {busy === 'send' ? <Loader2 className="animate-spin" /> : <Send />}Yes, send them</Button>
                <Button size="xs" variant="ghost" onClick={() => setConfirming(false)}>Cancel</Button>
              </div>
            </div>
          )}
          <ol className="max-h-72 space-y-1 overflow-y-auto pr-1">
            {queue.map((item, index) => (
              <li key={item.id} className="flex flex-wrap items-center gap-2 rounded-md bg-surface px-2 py-1.5 text-xs" data-testid="access-queue-item"
                data-opened={item.opened ? 'true' : 'false'} data-sent={item.sent ? item.sent.by : item.failed ? 'failed' : 'no'}>
                <span className="w-6 shrink-0 text-right text-ink-3">{index + 1}.</span>
                <span className="min-w-0 flex-1 truncate" title={item.address}>{where(item)}</span>
                <span className={item.sent ? 'shrink-0 text-emerald-800' : item.failed ? 'shrink-0 text-danger' : 'shrink-0 text-ink-3'}
                  title={item.failed?.reason}>{state(item)}</span>
                {canSend && !item.sent && (
                  <Button size="xs" variant="ghost" onClick={() => void send([item.id])} disabled={busy !== null} aria-label={`Send the request for ${where(item)}`}><Send /></Button>
                )}
                <Button size="xs" variant="ghost" onClick={() => void open(item.id)} disabled={busy !== null} aria-label={`Open the request for ${where(item)}`}>
                  {busy === item.id ? <Loader2 className="animate-spin" /> : <ExternalLink />}</Button>
                <Button size="xs" variant="ghost" onClick={() => void remove({ids: [item.id]})} disabled={busy !== null} aria-label={`Remove the request for ${where(item)}`}><X /></Button>
                {item.failed && !item.sent && <span className="w-full pl-8 text-danger">{item.failed.reason}</span>}
              </li>
            ))}
          </ol>
        </>)}
      </div>
      {notice && <p className="flex items-start gap-1.5 text-xs text-emerald-800" role="status"><CheckCircle2 className="mt-px size-3.5 shrink-0" />{notice}</p>}
      {error && <p className="text-xs text-danger" role="alert">{error}</p>}
    </div>
  );
}
