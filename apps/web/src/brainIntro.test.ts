import {describe, expect, it} from 'vitest';
import {GLOW_MS, introAt, introSeen, introWanted, wizardScale, ZOOM_MS} from './brainIntro';

// Owner, 6 Nov 2026: "when I open brain page for the first time, it should zoom in to the same wizard pixel character, in
// his brain".
describe('the Brain page intro', () => {
  it('plays on the first visit, again with ?intro, never with reduced motion', () => {
    localStorage.clear();
    expect(introWanted('', false)).toBe(true);
    expect(introWanted('', true)).toBe(false);
    introSeen();
    expect(introWanted('', false)).toBe(false);
    expect(introWanted('?intro', false)).toBe(true);
    expect(introWanted('?intro=0', false)).toBe(false);
    expect(introWanted('?intro', true)).toBe(false);
  });

  it('dives from the wizard into his brain, the graph growing out of his head into its place', () => {
    const start = introAt(0, 16);
    expect(start).toMatchObject({wizard: 1, graphOpacity: 0, wizardOpacity: 1, done: false});
    expect(start.graph).toBeCloseTo(1 / 16);
    expect(introAt(GLOW_MS, 16)).toMatchObject({wizard: 1, graphOpacity: 1, wizardOpacity: 1});  // his brain lit, in his head
    const middle = introAt(GLOW_MS + ZOOM_MS / 2, 16);
    expect(middle.wizard).toBeCloseTo(4);
    expect(middle.graph * 16).toBeCloseTo(middle.wizard);  // the graph stays inside his head as both grow
    expect(introAt(GLOW_MS + ZOOM_MS, 16)).toMatchObject({wizard: 16, graph: 1, wizardOpacity: 0, done: true});
  });

  it('draws the wizard in whole pixels, as big as the window allows', () => {
    expect(wizardScale(1440, 900)).toBe(7);
    expect(wizardScale(400, 300)).toBe(3);
    expect(wizardScale(4000, 3000)).toBe(8);
  });
});
