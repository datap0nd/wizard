import {useEffect, useMemo, useState} from 'react';
import {CheckCircle2, Download, KeyRound, Loader2, PlugZap, RefreshCw, RotateCcw, XCircle} from 'lucide-react';
import {api, ApiError} from '@/api';
import {formatDate} from '@/format';
import {inHost, toHost} from '@/host';
import {cn} from '@/lib/utils';
import {Button} from './ui/button';
import {Dialog, DialogContent} from './ui/dialog';
import {PortalSignIn} from './PortalSignIn';
import type {SettingField, SettingsView, UpdateInfo} from '@/types';

const SOURCES: Record<string, string> = {
  environment: 'Set by an environment variable (locked)', env_file: 'From the .env file', this_pc: 'Set on this PC',
  company: 'From the company settings file', default: 'Default',
};
const TESTS: Record<string, 'postgres' | 'knowledge' | 'metronome'> = {knowledge: 'knowledge', postgres: 'postgres', metronome: 'metronome'};

type Draft = Record<string, string | null>;
type Result = {ok: boolean; message: string} | null;

/** Wait for the local service to stop and come back (it restarts itself about a second after the save). */
async function waitForRestart(): Promise<void> {
  const started = Date.now();
  let wentDown = false;
  while (Date.now() - started < 90_000) {
    await new Promise(r => setTimeout(r, 1000));
    try {
      await api.health();
      if (wentDown || Date.now() - started > 15_000) return;
    } catch { wentDown = true; }
  }
}

/** Company settings the person may change on their own PC: Gemini, the knowledge base, the read-only database, the
 * portals and the browser Wizard reads them in, the proxy. Secrets are write-only: the page learns only whether one is set. Also shows the version and installs updates. */
export function SettingsDialog({open, onClose, onSaved}: {open: boolean; onClose: () => void; onSaved: () => void}) {
  const [view, setView] = useState<SettingsView | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [editingSecret, setEditingSecret] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [tests, setTests] = useState<Record<string, Result | 'running'>>({});
  const [update, setUpdate] = useState<UpdateInfo | 'checking' | null>(null);

  useEffect(() => {
    if (!open) return;
    setDraft({}); setEditingSecret({}); setError(null); setNotice(null); setTests({});
    api.settings().then(setView).catch(e => setError(e instanceof Error ? e.message : 'Settings could not be read.'));
    api.updates().then(setUpdate).catch(() => setUpdate(null));
  }, [open]);

  const changed = useMemo(() => Object.keys(draft), [draft]);
  const value = (f: SettingField) => (f.key in draft ? draft[f.key] ?? '' : f.value ?? '');
  const edit = (key: string, text: string | null) => setDraft(d => ({...d, [key]: text}));

  async function save() {
    if (!changed.length) return;
    setSaving(true); setError(null); setNotice(null);
    try {
      const saved = await api.saveSettings(draft);
      setView(saved); setDraft({}); setEditingSecret({});
      if (saved.apply === 'now') {
        setNotice('Saved. Wizard is restarting to apply the change…');
        await waitForRestart();
        setNotice('Saved and applied.');
      } else if (saved.apply === 'after_run') {
        setNotice('Saved. Wizard restarts to apply the change when the running question finishes.');
      } else if (saved.apply === 'manual') {
        setNotice('Saved. Restart Wizard to apply it: close its window and run start.ps1 again.');
      } else setNotice('Saved. It applies to your next question.');
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The settings could not be saved.');
    } finally { setSaving(false); }
  }

  async function runTest(section: 'postgres' | 'knowledge' | 'metronome') {
    setTests(t => ({...t, [section]: 'running'}));
    const values = Object.fromEntries(Object.entries(draft).filter(([k]) => view?.fields.find(f => f.key === k)?.section === section));
    try { const result = await api.testSettings(section, values); setTests(t => ({...t, [section]: result})); }
    catch (e) { setTests(t => ({...t, [section]: {ok: false, message: e instanceof Error ? e.message : 'The test failed.'}})); }
  }

  async function checkUpdate() {
    setUpdate('checking');
    try { setUpdate(await api.updates(true)); } catch (e) {
      setUpdate({installed: null, download: '', message: e instanceof Error ? e.message : 'Could not check for updates.'});
    }
  }

  function input(f: SettingField) {
    const disabled = !f.editable || saving;
    const common = 'h-9 w-full rounded-lg border border-line bg-canvas px-3 text-sm outline-none focus:border-line-2 disabled:bg-surface disabled:text-ink-3';
    if (f.secret && f.set && !editingSecret[f.key]) {
      return (
        <div className="flex items-center gap-2">
          <span className="flex h-9 flex-1 items-center gap-2 rounded-lg border border-line bg-surface px-3 text-sm text-ink-2"><KeyRound className="size-3.5" />Saved (hidden)</span>
          {f.editable && <Button size="sm" variant="outline" onClick={() => setEditingSecret(s => ({...s, [f.key]: true}))}>Change</Button>}
        </div>
      );
    }
    if (f.choices.length) {
      return (
        <select value={value(f) || f.placeholder} disabled={disabled} onChange={e => edit(f.key, e.target.value)} aria-label={f.label} className={common}>
          {f.choices.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      );
    }
    return <input type={f.secret ? 'password' : 'text'} value={value(f)} placeholder={f.placeholder} disabled={disabled} aria-label={f.label}
      autoComplete="off" spellCheck={false} onChange={e => edit(f.key, e.target.value)} className={common} data-testid={`setting-${f.key}`} />;
  }

  return (
    <Dialog open={open} onOpenChange={v => { if (!v) onClose(); }}>
      <DialogContent side="right" title="Settings" description="For Wizard on this PC. Secrets are stored encrypted and never shown again.">
        <div className="space-y-6 pb-20 text-sm" data-testid="settings-dialog">
          {error && <p className="rounded-lg bg-danger-soft px-3 py-2 text-danger" role="alert">{error}</p>}
          {!view && !error && <p className="text-ink-3">Loading…</p>}
          {view?.company_file && (
            <p className="rounded-lg bg-surface px-3 py-2 text-xs text-ink-2">Company settings file: <strong>{view.company_file.name || 'imported'}</strong>
              {view.company_file.imported_at ? `, imported ${formatDate(view.company_file.imported_at, true)}` : ''}. What you set here wins over it; clear a field to use the company value again.</p>
          )}
          {view?.sections.map(section => (
            <section key={section.id} className="rounded-xl border border-line p-4" data-testid={`settings-${section.id}`}>
              <div className="flex items-start gap-2">
                <div className="flex-1"><h3 className="font-semibold">{section.title}</h3><p className="text-xs text-ink-3">{section.about}</p></div>
                {TESTS[section.id] && (
                  <Button size="xs" variant="outline" onClick={() => void runTest(TESTS[section.id])} disabled={tests[section.id] === 'running'} data-testid={`test-${section.id}`}>
                    {tests[section.id] === 'running' ? <Loader2 className="animate-spin" /> : <PlugZap />}Test connection
                  </Button>
                )}
              </div>
              {tests[section.id] && tests[section.id] !== 'running' && (() => {
                const result = tests[section.id] as {ok: boolean; message: string};
                return <p className={cn('mt-2 flex items-start gap-1.5 rounded-lg px-3 py-2 text-xs', result.ok ? 'bg-emerald-50 text-emerald-800' : 'bg-danger-soft text-danger')} role="status">
                  {result.ok ? <CheckCircle2 className="mt-px size-3.5 shrink-0" /> : <XCircle className="mt-px size-3.5 shrink-0" />}{result.message}</p>;
              })()}
              <div className="mt-3 space-y-3">
                {view.fields.filter(f => f.section === section.id).map(f => (
                  <label key={f.key} className="block">
                    <span className="mb-1 flex items-center gap-2 text-[13px] font-medium">{f.label}
                      <span className="text-[11px] font-normal text-ink-3">{f.key in draft ? 'Changed' : SOURCES[f.source]}</span>
                      {f.editable && f.source === 'this_pc' && !(f.key in draft) && (
                        <button type="button" className="ml-auto inline-flex items-center gap-1 text-[11px] font-normal text-accent hover:underline"
                          onClick={e => { e.preventDefault(); edit(f.key, ''); }}><RotateCcw className="size-3" />{f.company_value ? 'Use company value' : 'Clear'}</button>
                      )}
                    </span>
                    {input(f)}
                    {f.help && <span className="mt-1 block text-[11.5px] text-ink-3">{f.help}</span>}
                  </label>
                ))}
              </div>
              {section.id === 'portals' && <PortalSignIn />}
            </section>
          ))}
          {view && (
            <section className="rounded-xl border border-line p-4" data-testid="settings-updates">
              <h3 className="font-semibold">Version and updates</h3>
              <p className="mt-1 text-xs text-ink-3">Wizard {view.build.version ?? `${view.version} (development copy)`}{view.build.commit ? ` · ${view.build.commit.slice(0, 12)}` : ''}</p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button size="sm" variant="outline" onClick={() => void checkUpdate()} disabled={update === 'checking'}>
                  {update === 'checking' ? <Loader2 className="animate-spin" /> : <RefreshCw />}Check for updates</Button>
                {update && update !== 'checking' && update.available && (inHost()
                  ? <Button size="sm" variant="accent" onClick={() => toHost({type: 'update'})} data-testid="update-now"><Download />Update to {update.latest}</Button>
                  : <a className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-accent px-3 text-[13px] font-medium text-white" href={update.download} target="_blank" rel="noopener noreferrer"><Download className="size-4" />Download {update.latest}</a>)}
                {/* WizardBar checks and downloads with Windows' own connection, which can work where the service's does not. */}
                {update && update !== 'checking' && update.ok === false && inHost() && (
                  <Button size="sm" variant="outline" onClick={() => toHost({type: 'update'})} data-testid="update-with-windows"><Download />Check with Windows</Button>)}
              </div>
              {update && update !== 'checking' && <p className="mt-2 text-xs text-ink-2" role="status" data-testid="update-message">{update.message}</p>}
            </section>
          )}
        </div>
        {view && (
          <div className="sticky bottom-0 -mx-5 flex items-center gap-3 border-t border-line bg-canvas px-5 py-3">
            <p className="min-w-0 flex-1 text-xs text-ink-2" role="status">{notice ?? (changed.length ? `${changed.length} unsaved change${changed.length === 1 ? '' : 's'}` : '')}</p>
            <Button variant="ghost" size="sm" onClick={() => { setDraft({}); setEditingSecret({}); }} disabled={!changed.length || saving}>Discard</Button>
            <Button variant="accent" size="sm" onClick={() => void save()} disabled={!changed.length || saving} data-testid="settings-save">
              {saving && <Loader2 className="animate-spin" />}Save</Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
