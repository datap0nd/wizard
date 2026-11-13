import {useSyncExternalStore} from 'react';
import type {PortalSignInState} from './types';

/** Whether the person is still signed in to each portal, shared by the yellow bar at the top, the stage and Settings →
 * Portals (owner, 13 Nov 2026: docs/decisions/2026-11-13-portal-sign-in-check.md). Wizard checks in code, never with
 * Gemini: each question checks the portals it may read (its card's portal_sign_in event), and GET /api/v1/portals says
 * how all of them stand. */
export type SignInResult = PortalSignInState['portals'][number];
export type PortalStanding = SignInResult['state'] | 'checking';

/** The applications whose sign-in has ended: the person signs in to these again. */
export function signedOut(state: PortalSignInState | null | undefined): SignInResult[] {
  return state?.portals.filter(p => p.state === 'signed_out') ?? [];
}

/** How one portal (a system on the stage) stands: being checked, signed out when any of its applications is, can't be
 * reached, signed in when all are; null when Wizard has nothing on it (not a portal, or no check yet). */
export function standing(state: PortalSignInState | null | undefined, portal: string): PortalStanding | null {
  const parts = state?.portals.filter(p => p.portal === portal) ?? [];
  if (!parts.length) return null;
  if (parts.some(p => p.checking)) return 'checking';
  if (parts.some(p => p.state === 'signed_out')) return 'signed_out';
  if (parts.some(p => p.state === 'unreachable')) return 'unreachable';
  if (parts.every(p => p.state === 'signed_in')) return 'signed_in';
  return null;
}

/** Names joined for a sentence: "GSCM", "GSCM and ASAP", "GSCM, ASAP and Big Data Portal: Superset". */
export function names(results: SignInResult[]): string {
  const all = Array.from(new Set(results.map(r => r.name)));
  return all.length <= 1 ? all.join('') : `${all.slice(0, -1).join(', ')} and ${all[all.length - 1]}`;
}

/** A newer reading folded into what is known: a question's check names only its own portals, so the others keep what
 * Wizard found before. */
export function merge(known: PortalSignInState | null, next: PortalSignInState): PortalSignInState {
  if (!known) return next;
  const ids = new Set(next.portals.map(p => p.id));
  const portals = [...known.portals.filter(p => !ids.has(p.id)), ...next.portals];
  const order = known.portals.map(p => p.id);
  portals.sort((a, b) => (order.indexOf(a.id) + 1 || 1e6) - (order.indexOf(b.id) + 1 || 1e6));
  const times = portals.map(p => p.checked_at).filter((t): t is string => !!t).sort();
  return {...next, portals, checking: portals.some(p => p.checking),
    checked_at: times[times.length - 1] ?? null};
}

let current: PortalSignInState | null = null;
const listeners = new Set<() => void>();

/** A reading from the server: all portals (GET /api/v1/portals) replace what is known; a question's own merges in. */
export function setSignIn(state: PortalSignInState | null | undefined, whole = false): void {
  if (!state || !Array.isArray(state.portals)) return;
  current = whole ? state : merge(current, state);
  listeners.forEach(listener => listener());
}

export function getSignIn(): PortalSignInState | null {
  return current;
}

/** For tests: forget what is known. */
export function resetSignIn(): void {
  current = null;
  listeners.forEach(listener => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useSignIn(): PortalSignInState | null {
  return useSyncExternalStore(subscribe, getSignIn, getSignIn);
}
