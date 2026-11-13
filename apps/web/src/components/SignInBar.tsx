import {useCallback, useEffect, useRef, useState} from 'react';
import {CheckCircle2, Loader2, LogIn} from 'lucide-react';
import {api, ApiError} from '@/api';
import {toHost} from '@/host';
import {cn} from '@/lib/utils';
import {names, setSignIn, signedOut, useSignIn} from '@/portalSignIn';
import {Button} from './ui/button';
import {WizardSprite} from './WizardSprite';

const POLL_MS = 3000;
const BACK_MS = 6000;

/** Read how every portal stands (no check: what Wizard last found). */
export async function readSignIn(): Promise<void> {
  try { setSignIn((await api.portals()).sign_in, true); } catch { /* no portals here, or the service is restarting */ }
}

/** Open Wizard's browser window for the person to sign in again (one tab per portal). The error in words, or null. */
export async function openSignIn(): Promise<string | null> {
  try { setSignIn((await api.portalSignIn()).sign_in, true); return null; } catch (e) {
    return e instanceof ApiError && e.status === 404 ? 'No portals are set up on this Wizard.' : e instanceof Error ? e.message : 'The sign-in window did not open.';
  }
}

/** Keeps the portals' sign-in known on the page (owner, 13 Nov 2026): read when Wizard opens and each time `again`
 * changes (an answer ended, the panel opened), and every few seconds while the sign-in window is open or a check runs.
 * Tells WizardBar which portals ended the sign-in, so the button at the top of the screen turns yellow until the person
 * signs in again. `enabled`: this person has portals. */
export function useSignInWatch(enabled: boolean, again: number): void {
  const state = useSignIn();
  useEffect(() => { if (enabled) void readSignIn(); }, [enabled, again]);
  const waiting = !!(state?.checking || state?.signing_in);
  useEffect(() => {
    if (!enabled || !waiting) return;
    const timer = setInterval(() => void readSignIn(), POLL_MS);
    return () => clearInterval(timer);
  }, [enabled, waiting]);
  const out = signedOut(state).map(p => p.name).join('\n');
  useEffect(() => { if (enabled) toHost({type: 'sign-in', portals: out ? out.split('\n') : []}); }, [enabled, out]);
}

/** The yellow bar at the top of Wizard while a portal has ended the person's sign-in: which ones, why that happens
 * every now and then, and Sign in, which opens Wizard's browser window on this PC. When the sign-in worked (the check
 * after the window closed found them signed in) it says so for a moment and goes. */
export function SignInBar({compact = false}: {compact?: boolean}) {
  const state = useSignIn();
  const out = signedOut(state);
  const [busy, setBusy] = useState<'open' | 'done' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [back, setBack] = useState<string | null>(null);
  const were = useRef('');
  const now = names(out);
  useEffect(() => {
    if (now) { were.current = now; setBack(null); return; }
    if (!were.current || state?.checking) return;  // until the check after the window has finished
    setBack(were.current);
    were.current = '';
    const timer = setTimeout(() => setBack(null), BACK_MS);
    return () => clearTimeout(timer);
  }, [now, state?.checking]);

  const open = useCallback(async () => {
    setBusy('open'); setError(null);
    setError(await openSignIn());
    setBusy(null);
  }, []);
  const done = useCallback(async () => {
    setBusy('done'); setError(null);
    try { setSignIn((await api.portalSignedIn()).sign_in, true); } catch (e) { setError(e instanceof Error ? e.message : 'That did not work.'); }
    setBusy(null);
  }, []);

  if (!out.length) {
    if (!back) return null;
    return (
      <div className={cn('stage-enter flex items-center gap-2 border-b border-ok-line bg-ok-soft text-[13px] text-ok', compact ? 'px-3 py-1.5' : 'px-4 py-2 md:px-6')}
        role="status" data-testid="sign-in-bar-back">
        <CheckCircle2 className="size-4 shrink-0" /><span><strong>Signed in again to {back}.</strong> Ask again and Wizard reads it.</span>
      </div>
    );
  }
  // The ones signed out are being checked again (the window just closed): another portal's check is not theirs.
  const checking = out.some(p => p.checking) && !state?.signing_in;
  return (
    <div className={cn('stage-enter flex items-center gap-2.5 border-b border-warn-line bg-[linear-gradient(to_bottom,#fff7d1,#fff1b3)] text-ink',
      compact ? 'px-2 py-1' : 'px-3 py-1.5 md:px-5')} role="alert" data-testid="sign-in-bar">
      <WizardSprite animation={state?.signing_in ? 'wave' : checking ? 'think' : 'idle'} scale={1} className="-my-1 shrink-0" />
      <div className="min-w-0 flex-1 py-0.5">
        <p className="text-[13px] font-semibold text-warn">
          {state?.signing_in ? `Sign in to ${now} in the Wizard window` : checking ? 'Checking your sign-in…' : `Sign in again to ${now}`}
        </p>
        <p className={cn('text-[12px] leading-snug text-ink-2', compact && 'line-clamp-2')} data-testid="sign-in-why">
          {state?.signing_in
            ? 'A Wizard browser window is open on this PC. Sign in to each portal there, then close the window or press Done.'
            : state?.why}
        </p>
        {error && <p className="mt-0.5 text-[12px] text-danger" role="alert">{error}</p>}
      </div>
      {state?.signing_in ? (
        <Button size="xs" variant="accent" onClick={() => void done()} disabled={busy !== null} data-testid="sign-in-bar-done">
          {busy === 'done' ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}Done</Button>
      ) : (
        <Button size="xs" className="border border-amber-500 bg-amber-400 text-amber-950 hover:bg-amber-300" onClick={() => void open()}
          disabled={busy !== null || checking} data-testid="sign-in-bar-open">
          {busy === 'open' || checking ? <Loader2 className="animate-spin" /> : <LogIn />}Sign in</Button>
      )}
    </div>
  );
}
