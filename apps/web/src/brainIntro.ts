// The Brain page's intro (owner, 6 Nov 2026: "when I open brain page for the first time, it should zoom in to the same
// wizard pixel character, in his brain"): the wizard thinks, his brain lights up in his head, and the view dives into it
// until the knowledge graph fills the page. Decoration only: it reads nothing and says nothing about the knowledge base.
// Pure timing and placement, so the page's component only applies them.

/** Where his brain sits in a 48 px frame of the sprite (behind his forehead, under the hat band), and how wide it is
 *  there: small, so the view dives through his head (which ends many times the page's size) into it. */
export const HEAD = {x: 24.5, y: 24.5, width: 5};
export const HOLD_MS = 1300;   // the wizard on his own, thinking, before his brain lights up
export const GLOW_MS = 700;    // his brain lights up in his head
export const ZOOM_MS = 2600;   // the dive into it
export const WAIT_MS = 4500;   // a knowledge base still settling by then is shown as it is
export const GIVE_UP_MS = 9000; // nothing read by then: the intro ends without the dive
const KEY = 'wizard.brain.intro';

/** Played once per browser, on the first visit; `?intro` in the address plays it again (for presenting). */
export function introWanted(search: string, reduced: boolean): boolean {
  if (reduced) return false;
  const asked = new URLSearchParams(search).get('intro');
  if (asked !== null) return asked !== '0';
  try { return localStorage.getItem(KEY) === null; } catch { return false; }
}

export function introSeen(): void {
  try { localStorage.setItem(KEY, 'seen'); } catch { /* a browser that keeps nothing plays it each time */ }
}

const clamp = (v: number) => Math.min(1, Math.max(0, v));
const ease = (p: number) => (p < 0.5 ? 4 * p * p * p : 1 - (-2 * p + 2) ** 3 / 2);

/**
 * The intro `t` ms after his brain starts to light up, for a dive of `depth` (how much bigger the graph is on the page
 * than in his head). `wizard`: how much the wizard has grown about his brain; `graph`: the page's scale about the same
 * point (1 / depth to start, 1 at the end), so the graph grows out of his head into its place.
 */
export function introAt(t: number, depth: number): {wizard: number; graph: number; graphOpacity: number; wizardOpacity: number; done: boolean} {
  const p = clamp((t - GLOW_MS) / ZOOM_MS), e = ease(p);
  const wizard = depth ** e;
  return {wizard, graph: wizard / depth, graphOpacity: clamp(t / GLOW_MS), wizardOpacity: 1 - clamp((e - 0.5) / 0.4), done: p >= 1};
}

/** The sprite's scale (whole pixels, so it stays crisp) for a window this size. */
export function wizardScale(width: number, height: number, frame = 48): number {
  return Math.max(3, Math.min(8, Math.floor((Math.min(width, height) * 0.42) / frame)));
}
