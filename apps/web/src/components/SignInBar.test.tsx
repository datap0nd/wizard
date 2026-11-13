import {afterEach, describe, expect, it, vi} from 'vitest';
import {act, cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {api} from '@/api';
import {merge, names, resetSignIn, setSignIn, signedOut, standing} from '@/portalSignIn';
import {applyEvent, emptyRun} from '@/runState';
import type {PortalSignInState, PortalStatus, RunEvent} from '@/types';
import {RunCard} from './RunCard';
import {SignInBar, useSignInWatch} from './SignInBar';
import {SystemsContext} from './SystemsStage';
import {TooltipProvider} from './ui/menu';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); act(() => resetSignIn()); delete (window as {chrome?: unknown}).chrome; });

const WHY = "Most portals end your sign-in after a while (each portal sets its own time), so you sign in again in Wizard's browser every now and then.";
type Result = PortalSignInState['portals'][number];
const result = (id: string, name: string, state: Result['state'], extra: Partial<Result> = {}): Result =>
  ({id, portal: id.split('-')[0], name, state, signed_in: state === 'signed_in', ...extra});
const reading = (portals: Result[], extra: Partial<PortalSignInState> = {}): PortalSignInState =>
  ({portals, checking: portals.some(p => p.checking), signing_in: false, checked_at: '2026-11-13T09:00:00', why: WHY, ...extra});
const status = (sign_in: PortalSignInState): PortalStatus =>
  ({browser: 'Google Chrome', signing_in: sign_in.signing_in, running: false, last_sign_in: null, portals: [], sign_in});

describe('what Wizard knows of the sign-in', () => {
  it('names the portals that ended it and how each stands on the stage', () => {
    const state = reading([result('gscm', 'GSCM', 'signed_out'), result('asap', 'ASAP', 'signed_in'),
      result('bdp-superset', 'Big Data Portal: Superset', 'signed_in'), result('bdp-catalog', 'Big Data Portal: information catalog', 'signed_out')]);
    expect(names(signedOut(state))).toBe('GSCM and Big Data Portal: information catalog');
    expect(standing(state, 'gscm')).toBe('signed_out');
    expect(standing(state, 'bdp')).toBe('signed_out');  // one of its applications ended it
    expect(standing(state, 'asap')).toBe('signed_in');
    expect(standing(state, 'postgresql')).toBeNull();
    expect(standing(reading([result('asap', 'ASAP', 'signed_in', {checking: true})]), 'asap')).toBe('checking');
    expect(standing(reading([result('asap', 'ASAP', 'unreachable')]), 'asap')).toBe('unreachable');
  });

  it("folds a question's own check into what is known about the others", () => {
    const known = reading([result('gscm', 'GSCM', 'signed_in'), result('asap', 'ASAP', 'signed_out')]);
    const merged = merge(known, reading([result('gscm', 'GSCM', 'signed_out', {checked_at: '2026-11-13T10:00:00'})]));
    expect(merged.portals.map(p => [p.id, p.state])).toEqual([['gscm', 'signed_out'], ['asap', 'signed_out']]);
    expect(merged.checked_at).toBe('2026-11-13T10:00:00');
  });

  it("applies the check that ran beside an answer to the run's view", () => {
    const event: RunEvent = {seq: 2, type: 'portal_sign_in', ts: 't', payload: reading([result('gscm', 'GSCM', 'signed_out')])};
    expect(applyEvent(emptyRun('run_1', 'cnv_1', 'q'), event).signIn?.portals[0].state).toBe('signed_out');
  });
});

describe('the yellow bar at the top', () => {
  it('says which portals ended the sign-in and why, opens the sign-in window, then says it worked', async () => {
    act(() => setSignIn(reading([result('gscm', 'GSCM', 'signed_out'), result('asap', 'ASAP', 'signed_in')]), true));
    const open = vi.spyOn(api, 'portalSignIn').mockResolvedValue(status(reading([result('gscm', 'GSCM', 'signed_out')], {signing_in: true})));
    const done = vi.spyOn(api, 'portalSignedIn').mockResolvedValue(status(reading([result('gscm', 'GSCM', 'signed_out', {checking: true})])));
    render(<SignInBar />);
    expect(screen.getByTestId('sign-in-bar').textContent).toContain('Sign in again to GSCM');
    expect(screen.getByTestId('sign-in-why').textContent).toBe(WHY);
    fireEvent.click(screen.getByTestId('sign-in-bar-open'));
    await waitFor(() => expect(screen.getByTestId('sign-in-bar').textContent).toContain('Sign in to GSCM in the Wizard window'));
    expect(open).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByTestId('sign-in-bar-done'));
    await waitFor(() => expect(screen.getByTestId('sign-in-bar').textContent).toContain('Checking your sign-in'));
    expect(done).toHaveBeenCalledOnce();
    act(() => setSignIn(reading([result('gscm', 'GSCM', 'signed_in'), result('asap', 'ASAP', 'signed_in')]), true));
    expect(screen.queryByTestId('sign-in-bar')).toBeNull();
    expect(screen.getByTestId('sign-in-bar-back').textContent).toContain('Signed in again to GSCM');
  });

  it('stays away while every portal is signed in, or only cannot be reached', () => {
    act(() => setSignIn(reading([result('gscm', 'GSCM', 'signed_in'), result('asap', 'ASAP', 'unreachable')]), true));
    render(<SignInBar />);
    expect(screen.queryByTestId('sign-in-bar')).toBeNull();
  });

  it('reads the sign-in when Wizard opens, while a check runs, and tells WizardBar to turn its button yellow', async () => {
    vi.useFakeTimers();
    const posted: unknown[] = [];
    (window as {chrome?: unknown}).chrome = {webview: {postMessage: (m: unknown) => posted.push(m), addEventListener: () => undefined, removeEventListener: () => undefined}};
    const portals = vi.spyOn(api, 'portals')
      .mockResolvedValueOnce(status(reading([result('gscm', 'GSCM', 'signed_in', {checking: true})])))
      .mockResolvedValue(status(reading([result('gscm', 'GSCM', 'signed_out')])));
    function Watch() { useSignInWatch(true, 0); return null; }
    render(<Watch />);
    await act(async () => { await Promise.resolve(); });
    expect(portals).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(3100); await Promise.resolve(); });
    expect(portals).toHaveBeenCalledTimes(2);
    expect(posted).toContainEqual({type: 'sign-in', portals: []});
    expect(posted[posted.length - 1]).toEqual({type: 'sign-in', portals: ['GSCM']});
    await act(async () => { vi.advanceTimersByTime(10_000); await Promise.resolve(); });
    expect(portals).toHaveBeenCalledTimes(2);  // nothing is being checked: no more reads
  });
});

describe('the stage while Gemini decides the next step', () => {
  it('shows Sign in instead of "ready" on a portal that ended the sign-in', async () => {
    let seq = 0;
    const ev = (type: string, payload: Record<string, unknown>): RunEvent => ({seq: ++seq, type, ts: '2026-11-13T09:00:00Z', payload});
    let run = applyEvent(emptyRun('run_1', 'cnv_1', 'Weekly sell-out'), ev('run_started', {runtime: 'code-assist', runtime_label: 'x', model: 'm'}));
    run = applyEvent(run, ev('portal_sign_in', {...reading([result('gscm', 'GSCM', 'signed_out'), result('asap', 'ASAP', 'signed_in')])}));
    const open = vi.spyOn(api, 'portalSignIn').mockResolvedValue(status(reading([result('gscm', 'GSCM', 'signed_out')], {signing_in: true})));
    render(
      <SystemsContext.Provider value={[{id: 'gscm', name: 'GSCM', kind: 'portal'}, {id: 'asap', name: 'ASAP', kind: 'portal'},
        {id: 'postgresql', name: 'AI Team Database', kind: 'database'}]}>
        <TooltipProvider><RunCard run={run} onEvidence={() => {}} onCheck={() => {}} onCancel={() => {}} onRetry={() => {}} onFeedback={() => {}} onEmail={() => {}} busy={false} /></TooltipProvider>
      </SystemsContext.Provider>,
    );
    const nodes = Object.fromEntries(screen.getAllByTestId('stage-node').map(n => [n.dataset.system, n]));
    expect(nodes.gscm.dataset.state).toBe('sign-in');
    expect(nodes.gscm.textContent).not.toContain('ready');
    expect(nodes.asap.textContent).toContain('signed in');
    expect(nodes.postgresql.textContent).toContain('ready');
    expect(screen.getAllByTestId('stage-sign-in')).toHaveLength(1);
    fireEvent.click(screen.getByTestId('stage-sign-in'));
    await waitFor(() => expect(open).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.getByTestId('stage-sign-in').textContent).toContain('Signing in'));
  });
});
