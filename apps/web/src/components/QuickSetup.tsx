import {useEffect, useRef, useState} from 'react';
import {ArrowLeft, ArrowRight, CheckCircle2, FileUp, Globe, Loader2, LogIn, MessageSquare, Minus, Paperclip, PlugZap, Search,
  ShieldCheck, XCircle} from 'lucide-react';
import {api, ApiError} from '@/api';
import {formatDate} from '@/format';
import {inHost} from '@/host';
import {cn} from '@/lib/utils';
import {Button} from './ui/button';
import {GeminiLink} from './GeminiLink';
import {WizardSprite} from './WizardSprite';
import type {Bootstrap, GeminiAccount, PortalCheck, PortalStatus, SettingsTest, SettingsTestResult, SettingsView} from '@/types';

/** The steps of Quick setup, in order (owner, 13 Nov 2026: "take them through Wizard, how it works, through the gemini
 *  sign in, through importing a settings file, etc."). The settings file comes before the sign-in: it can set the
 *  Gemini project and the company's Google domains the sign-in needs. */
export const STEPS = [
  {id: 'welcome', title: 'Welcome'},
  {id: 'how', title: 'How it works'},
  {id: 'file', title: 'Settings file'},
  {id: 'gemini', title: 'Gemini'},
  {id: 'portals', title: 'Portals'},
  {id: 'check', title: 'Check'},
  {id: 'done', title: 'Done'},
] as const;
type StepId = typeof STEPS[number]['id'];

/** The steps the person acts in, summed up on the last one. */
const SUMMARY = ['file', 'gemini', 'portals'] as const;
const skippable = (step: StepId) => (SUMMARY as readonly StepId[]).includes(step);
/** The connections the Check step tests, when this PC has them set. */
const CHECKS: SettingsTest[] = ['knowledge', 'postgres', 'nerp', 'dashboards', 'metronome'];
const MAX_FILE = 64 * 1024;

/** Whether a step is done, for the tick beside its name. */
function done(step: StepId, boot: Bootstrap, view: SettingsView, portals: PortalStatus | 'none' | null): boolean {
  if (step === 'file') return !!view.company_file;
  if (step === 'gemini') return !boot.gemini_account?.needs_link || !!boot.gemini_account.linked;
  if (step === 'portals') return !!(portals && portals !== 'none' && portals.last_sign_in);
  return false;
}

/** The sections this PC has a value for (not a default), so the Check step tests only what is set up. */
export function configured(view: SettingsView): SettingsTest[] {
  return CHECKS.filter(id => view.sections.some(s => s.id === id)
    && view.fields.some(f => f.section === id && f.set && f.source !== 'default'));
}

function Point({icon: Icon, title, children}: {icon: typeof Search; title: string; children: React.ReactNode}) {
  return (
    <li className="flex gap-3">
      <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent"><Icon className="size-4" /></span>
      <span><strong className="block text-[13.5px]">{title}</strong><span className="text-[13px] text-ink-2">{children}</span></span>
    </li>
  );
}

function Status({ok, children}: {ok: boolean; children: React.ReactNode}) {
  return <p className={cn('flex items-start gap-1.5 rounded-lg px-3 py-2 text-xs', ok ? 'bg-emerald-50 text-emerald-800' : 'bg-danger-soft text-danger')} role="status">
    {ok ? <CheckCircle2 className="mt-px size-3.5 shrink-0" /> : <XCircle className="mt-px size-3.5 shrink-0" />}<span>{children}</span></p>;
}

/** Quick setup, at the top of Settings: a new person's walk through Wizard on their own PC. Each step uses what Settings
 *  and Account already do (the settings file is checked and stored by the service, the Gemini sign-in is the person's
 *  own, the portals' sign-in is in Wizard's own browser); it skips nothing for them and sends nothing anywhere else. */
export function QuickSetup({boot, view, onExit, onFinish, onAccount, onImported, waitForRestart}: {
  /** onExit: back to every setting; onFinish: the last step's Finish, which closes Settings. */
  boot: Bootstrap; view: SettingsView; onExit: () => void; onFinish: () => void; onAccount: (a: GeminiAccount) => void;
  /** After an import applied: read the settings again (the company file's name, the new values) and the bootstrap. */
  onImported: () => Promise<void>; waitForRestart: () => Promise<void>;
}) {
  const [index, setIndex] = useState(0);
  const step = STEPS[index].id;
  const [portals, setPortals] = useState<PortalStatus | 'none' | null>(null);
  const [importing, setImporting] = useState<string | null>(null);
  const [imported, setImported] = useState<{ok: boolean; message: string} | null>(null);
  const [portalBusy, setPortalBusy] = useState<'sign-in' | 'done' | 'check' | null>(null);
  const [portalCheck, setPortalCheck] = useState<PortalCheck | null>(null);
  const [portalError, setPortalError] = useState<string | null>(null);
  const [checks, setChecks] = useState<Partial<Record<SettingsTest, SettingsTestResult | 'running'>>>({});
  const file = useRef<HTMLInputElement>(null);
  const top = useRef<HTMLDivElement>(null);

  const loadPortals = () => api.portals().then(setPortals).catch(e => setPortals(e instanceof ApiError && e.status === 404 ? 'none' : null));
  useEffect(() => { void loadPortals(); }, [view.company_file?.imported_at]);  // an imported file can add portals
  useEffect(() => { top.current?.scrollIntoView?.({block: 'nearest'}); }, [index]);

  async function importFile(chosen: File | undefined) {
    if (!chosen) return;
    setImported(null);
    if (chosen.size > MAX_FILE) { setImported({ok: false, message: `${chosen.name} is too large for a Wizard settings file.`}); return; }
    setImporting('Importing…');
    try {
      const result = await api.importSettings(await chosen.text());
      const what = `Imported ${result.name || chosen.name}: ${result.settings} setting${result.settings === 1 ? '' : 's'} and `
        + `${result.secrets} password${result.secrets === 1 ? '' : 's'} or token${result.secrets === 1 ? '' : 's'}, stored encrypted on this PC.`;
      if (result.apply === 'now') {
        setImporting('Wizard is restarting to apply the settings…');
        await waitForRestart();
        await onImported();
        setImported({ok: true, message: `${what} Delete ${chosen.name} now: it holds the passwords in plain text.`});
      } else if (result.apply === 'after_run') {
        setImported({ok: true, message: `${what} Wizard restarts to apply them when the running question or queue finishes. Delete ${chosen.name}: it holds the passwords in plain text.`});
      } else {
        setImported({ok: true, message: `${what} Restart Wizard to apply them. Delete ${chosen.name}: it holds the passwords in plain text.`});
      }
    } catch (e) {
      setImported({ok: false, message: e instanceof Error ? e.message : 'The settings file could not be imported.'});
    } finally {
      setImporting(null);
      if (file.current) file.current.value = '';
    }
  }

  async function portalAct(kind: 'sign-in' | 'done' | 'check') {
    setPortalBusy(kind); setPortalError(null);
    try {
      if (kind === 'check') setPortalCheck(await api.portalCheck());
      else setPortals(kind === 'sign-in' ? await api.portalSignIn() : await api.portalSignedIn());
    } catch (e) { setPortalError(e instanceof Error ? e.message : 'That did not work.'); }
    finally { setPortalBusy(null); }
  }

  async function runChecks() {
    const sections = configured(view);
    setChecks(Object.fromEntries(sections.map(s => [s, 'running'])));
    await Promise.all(sections.map(async section => {
      let result: SettingsTestResult;
      try { result = await api.testSettings(section, {}); }
      catch (e) { result = {ok: false, message: e instanceof Error ? e.message : 'The test failed.'}; }
      setChecks(c => ({...c, [section]: result}));
    }));
  }

  const runtime = boot.runtime;
  const toCheck = configured(view);
  const left = SUMMARY.filter(id => !done(id, boot, view, portals) && !(id === 'portals' && portals === 'none'));
  const title = (id: string) => view.sections.find(s => s.id === id)?.title ?? id;
  const body: Record<StepId, React.ReactNode> = {
    welcome: (
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <WizardSprite animation="wave" scale={2} label="Wizard" className="-my-2 -ml-2" />
          <div>
            <h3 className="text-[18px] font-semibold tracking-tight">Welcome to Wizard</h3>
            <p className="text-[13px] text-ink-2">A few minutes, once, on this PC.</p>
          </div>
        </div>
        <p className="text-[13.5px] text-ink-2">Wizard answers questions about the business from the company's own data: the knowledge base,
          the team's dashboards, the company database and the portals. Gemini does the analysis under your own company Google sign-in,
          and every figure shows where it came from.</p>
        <p className="text-[13.5px] text-ink-2">Quick setup walks you through how it works, the company settings file, your Gemini sign-in
          and the portals, then checks that Wizard reaches your data. You can leave at any step and come back: it is always at the top of Settings.</p>
      </div>
    ),
    how: (
      <ul className="space-y-3">
        <Point icon={MessageSquare} title="Ask in your own words">Click the Ask Wizard button at the top of the screen, or press Ctrl+Alt+W
          from anywhere. Esc hides Wizard; a question keeps running in the background and the button tells you when the answer is ready.</Point>
        <Point icon={Search} title="Gemini does the analysis">It picks the sources that hold what you asked, reads them, compares and
          explains. You see each step it takes and can send it a note while it works.</Point>
        <Point icon={ShieldCheck} title="Read-only, with evidence">Wizard only reads: it never changes a company system. Every source it read
          is in the evidence with its date. LIVE is read just now, USER_PROVIDED is a file you attached, SYNTHETIC is example data.
          Check my data reads the figures again.</Point>
        <Point icon={Paperclip} title="Bring your own files">Drop a PowerPoint, Excel, Word, email or CSV file on the button or in the chat to
          ask about it. Wizard never changes your file; an edited copy is a new file you download.</Point>
      </ul>
    ),
    file: (
      <div className="space-y-3">
        <p className="text-[13.5px] text-ink-2">Your company's settings file (<code className="text-[12.5px]">wizard.provision</code>) connects
          Wizard on this PC to the knowledge base, the company database, the portals and the Gemini project. Your administrator gives it to
          you, or a colleague makes one with Export settings… in Wizard's tray menu.</p>
        {view.company_file && (
          <Status ok>Imported: <strong>{view.company_file.name || 'company settings'}</strong>
            {view.company_file.imported_at ? `, ${formatDate(view.company_file.imported_at, true)}` : ''}. Import a newer file to replace it.</Status>
        )}
        <input ref={file} type="file" accept=".provision,application/json" className="hidden" data-testid="setup-file-input"
          onChange={e => void importFile(e.target.files?.[0])} />
        <Button variant={view.company_file ? 'outline' : 'accent'} size="sm" disabled={!!importing} onClick={() => file.current?.click()}
          data-testid="setup-file-choose">{importing ? <Loader2 className="animate-spin" /> : <FileUp />}
          {importing ?? (view.company_file ? 'Import another settings file…' : 'Choose the settings file…')}</Button>
        {imported && <Status ok={imported.ok}>{imported.message}</Status>}
        <p className="text-xs text-ink-3">Wizard checks the file first and stores its passwords and tokens encrypted for your Windows account.
          What you set yourself in Settings stays and wins over it. No file yet? Skip this step and import it later here or from the tray menu
          (Import a settings file…).</p>
      </div>
    ),
    gemini: (
      <div className="space-y-2 text-sm">
        <p className="text-[13.5px] text-ink-2">Wizard asks Gemini under your own enterprise Google account, so answers use your entitlement
          and nobody else's. Sign in once; Wizard keeps the sign-in encrypted on this PC and never sees your password.</p>
        <GeminiLink boot={boot} onChanged={onAccount} tone="setup" />
        {runtime && !runtime.ready && runtime.reason && done('gemini', boot, view, portals) && (
          <p className="rounded-lg bg-warn-soft px-3 py-2 text-xs text-ink">{runtime.reason}</p>)}
      </div>
    ),
    portals: (
      <div className="space-y-3">
        <p className="text-[13.5px] text-ink-2">Gemini reads the company portals (ASAP, GSCM, the Big Data Portal) in Wizard's own browser on
          this PC, signed in as you. Sign in once in the window Wizard opens; Wizard then reads them in the background. It never types
          your password and never saves, submits or changes anything there.</p>
        {portals === null && <p className="text-xs text-ink-3">Looking for the portals…</p>}
        {portals === 'none' && <p className="rounded-lg bg-surface px-3 py-2 text-xs text-ink-2" data-testid="setup-portals-none">No portals are
          set up on this PC. The settings file sets them; if yours has none, there is nothing to do here.</p>}
        {portals && portals !== 'none' && (
          <div className="space-y-2" data-testid="setup-portals">
            <p className="flex items-center gap-1.5 text-xs text-ink-2"><Globe className="size-3.5" />{portals.portals.map(p => p.name).join(', ')}
              {portals.last_sign_in ? ` · last signed in ${formatDate(portals.last_sign_in, true)}` : ' · not signed in yet'}</p>
            {portals.signing_in ? (
              <div className="flex flex-wrap items-center gap-2">
                <p className="flex-1 text-xs text-ink-2" role="status">A Wizard browser window is open on this PC. Sign in to each portal there,
                  then close the window or press Done.</p>
                <Button size="xs" variant="accent" onClick={() => void portalAct('done')} disabled={portalBusy !== null} data-testid="setup-portal-done">
                  {portalBusy === 'done' ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}Done</Button>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" variant="accent" onClick={() => void portalAct('sign-in')} disabled={portalBusy !== null} data-testid="setup-portal-sign-in">
                  {portalBusy === 'sign-in' ? <Loader2 className="animate-spin" /> : <LogIn />}Sign in to the portals</Button>
                <Button size="sm" variant="ghost" onClick={() => void portalAct('check')} disabled={portalBusy !== null} data-testid="setup-portal-check">
                  {portalBusy === 'check' ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}Check sign-in</Button>
              </div>
            )}
            {portalCheck && (
              <ul className="space-y-1 text-xs">
                {portalCheck.portals.map(p => (
                  <li key={p.id} className={cn('flex items-center gap-1.5', p.signed_in ? 'text-emerald-800' : 'text-danger')}>
                    {p.signed_in ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" />}
                    {p.name}: {p.signed_in ? 'signed in' : p.error ?? 'asks for a sign-in'}
                  </li>
                ))}
              </ul>
            )}
            {portalError && <p className="text-xs text-danger" role="alert">{portalError}</p>}
          </div>
        )}
      </div>
    ),
    check: (
      <div className="space-y-3">
        <p className="text-[13.5px] text-ink-2">Wizard tests each connection this PC has, with its saved settings. Nothing is changed.</p>
        <Status ok={!!runtime?.ready}>Gemini: {runtime?.ready ? `ready (${runtime.label})` : runtime?.reason ?? 'not available yet.'}</Status>
        {toCheck.length === 0
          ? <p className="rounded-lg bg-surface px-3 py-2 text-xs text-ink-2" data-testid="setup-nothing-to-check">No connections are set up on this
              PC yet. Import the settings file first (step 3), or set them in Settings.</p>
          : <>
              <Button size="sm" variant="accent" onClick={() => void runChecks()} disabled={Object.values(checks).includes('running')} data-testid="setup-check">
                {Object.values(checks).includes('running') ? <Loader2 className="animate-spin" /> : <PlugZap />}Test the connections</Button>
              <ul className="space-y-1.5" data-testid="setup-check-results">
                {toCheck.map(id => {
                  const result = checks[id];
                  return <li key={id}>{!result ? <p className="px-3 text-xs text-ink-3">{title(id)}: not tested yet</p>
                    : result === 'running' ? <p className="flex items-center gap-1.5 px-3 text-xs text-ink-2"><Loader2 className="size-3.5 animate-spin" />{title(id)}…</p>
                    : <Status ok={result.ok}><strong>{title(id)}:</strong> {result.message}</Status>}</li>;
                })}
              </ul>
            </>}
      </div>
    ),
    done: (
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <WizardSprite animation={left.length ? 'idle' : 'success'} scale={2} label="Wizard" className="-my-2 -ml-2" />
          <h3 className="text-[18px] font-semibold tracking-tight">{left.length ? 'Almost there' : 'You are ready'}</h3>
        </div>
        <ul className="space-y-1.5 text-[13px]" data-testid="setup-summary">
          {SUMMARY.map(id => {
            const ok = done(id, boot, view, portals);
            const none = id === 'portals' && portals === 'none';
            return <li key={id} className={cn('flex items-center gap-1.5', ok ? 'text-emerald-800' : 'text-ink-2')}>
              {ok ? <CheckCircle2 className="size-4" /> : none ? <Minus className="size-4 text-ink-3" /> : <XCircle className="size-4 text-ink-3" />}
              {id === 'file' ? (ok ? 'Settings file imported' : 'No settings file yet')
                : id === 'gemini' ? (ok ? 'Gemini signed in' : 'Gemini not signed in yet: Wizard cannot answer until you are')
                : none ? 'No portals on this PC' : ok ? 'Signed in to the portals' : 'Not signed in to the portals yet'}
              {!ok && !none && <button type="button" className="ml-1 text-accent hover:underline" onClick={() => setIndex(STEPS.findIndex(x => x.id === id))}>Go back</button>}
            </li>;
          })}
        </ul>
        <p className="text-[13.5px] text-ink-2">{left.length ? 'Finish now and come back to the rest later, or go back to it now. ' : 'Press Finish and ask your first question. '}
          {inHost() ? 'Ctrl+Alt+W shows Wizard from anywhere. ' : ''}Settings holds every other option, and Quick setup stays at its top.</p>
      </div>
    ),
  };

  return (
    <div className="space-y-5" data-testid="quick-setup">
      <div ref={top} className="flex items-center justify-between gap-2">
        <button type="button" onClick={onExit} className="inline-flex items-center gap-1 text-xs text-accent hover:underline" data-testid="setup-exit">
          <ArrowLeft className="size-3.5" />All settings</button>
        <span className="text-xs text-ink-3">Step {index + 1} of {STEPS.length}</span>
      </div>
      <ol className="flex flex-wrap gap-1" aria-label="Quick setup steps">
        {STEPS.map((s, i) => {
          const ok = done(s.id, boot, view, portals);
          return (
            <li key={s.id}>
              <button type="button" onClick={() => setIndex(i)} aria-current={i === index ? 'step' : undefined} data-testid={`setup-step-${s.id}`}
                className={cn('inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[12px]',
                  i === index ? 'border-accent bg-accent-soft font-medium text-accent' : 'border-line text-ink-2 hover:bg-surface')}>
                {ok ? <CheckCircle2 className="size-3.5 text-emerald-700" /> : <span className="tabular-nums">{i + 1}</span>}{s.title}
              </button>
            </li>
          );
        })}
      </ol>
      <section className="rounded-xl border border-line p-4 text-sm" data-testid={`setup-panel-${step}`}>{body[step]}</section>
      <div className="flex items-center gap-2">
        {index > 0 && <Button variant="ghost" size="sm" onClick={() => setIndex(i => i - 1)} data-testid="setup-back"><ArrowLeft />Back</Button>}
        <span className="flex-1" />
        {index < STEPS.length - 1
          ? <Button variant="accent" size="sm" onClick={() => setIndex(i => i + 1)} data-testid="setup-next">
              {skippable(step) && !done(step, boot, view, portals) && !(step === 'portals' && portals === 'none') ? 'Skip for now' : 'Next'}<ArrowRight /></Button>
          : <Button variant="accent" size="sm" onClick={onFinish} data-testid="setup-finish"><CheckCircle2 />Finish</Button>}
      </div>
    </div>
  );
}
