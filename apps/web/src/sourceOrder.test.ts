import {describe, expect, it} from 'vitest';
import {canMove, cleanUse, levelNumbers, move, parseOrder, remove, serialise, sourceName, update, withSources,
  type OrderEntry} from './sourceOrder';
import {autoSystems, whenAsked} from './systems';
import type {SystemInfo} from './types';

const DEFAULT: OrderEntry[] = [{id: 'dashboards'}, {id: 'postgresql'}, {id: 'asap'}, {id: 'gscm', same: true}, {id: 'nerp'}, {id: 'bdp'}];
const ids = (entries: OrderEntry[]) => entries.map(e => e.id);

describe('the source order', () => {
  it('reads the stored line, falls back to the default, and writes it back compact', () => {
    expect(parseOrder('', DEFAULT)).toBe(DEFAULT);
    expect(parseOrder('not json', DEFAULT)).toBe(DEFAULT);
    const read = parseOrder('[{"id":"gscm","same":true,"use":"Stock"},{"id":"asap","same":true},{"id":"nerp","when_asked":true}]', DEFAULT);
    expect(levelNumbers(read)).toEqual([1, 1, 2]);  // the first source has no level above
    expect(serialise(read)).toBe('[{"id":"gscm","use":"Stock"},{"id":"asap","same":true},{"id":"nerp","when_asked":true}]');
    expect(serialise([{id: 'asap', use: '   '}])).toBe('[{"id":"asap"}]');
  });

  it('shows the sources it names, then this PC\'s others at the end', () => {
    const shown = withSources(DEFAULT, [{id: 'asap', name: 'ASAP'}, {id: 'crm', name: 'CRM portal'}]);
    expect(ids(shown)).toEqual(['dashboards', 'postgresql', 'asap', 'gscm', 'nerp', 'bdp', 'crm']);
    expect(levelNumbers(shown)).toEqual([1, 2, 3, 3, 4, 5, 6]);
    expect(sourceName('crm', [{id: 'crm', name: 'CRM portal'}])).toBe('CRM portal');
    expect(sourceName('bdp', [])).toBe('Big Data Portal');
    expect(sourceName('sap', [])).toBe('SAP');
  });

  it('moves a source past a whole level, and out of a shared level onto its own', () => {
    // NERP up: past the ASAP/GSCM level as a whole.
    const nerpUp = move(DEFAULT, 4, -1);
    expect(ids(nerpUp)).toEqual(['dashboards', 'postgresql', 'nerp', 'asap', 'gscm', 'bdp']);
    expect(levelNumbers(nerpUp)).toEqual([1, 2, 3, 4, 4, 5]);
    // GSCM up: out of ASAP's level, onto a level of its own just above it.
    const gscmUp = move(DEFAULT, 3, -1);
    expect(ids(gscmUp)).toEqual(['dashboards', 'postgresql', 'gscm', 'asap', 'nerp', 'bdp']);
    expect(levelNumbers(gscmUp)).toEqual([1, 2, 3, 4, 5, 6]);
    // ASAP down: onto its own level just below GSCM's.
    expect(levelNumbers(move(DEFAULT, 2, 1))).toEqual([1, 2, 3, 4, 5, 6]);
    expect(ids(move(DEFAULT, 2, 1))).toEqual(['dashboards', 'postgresql', 'gscm', 'asap', 'nerp', 'bdp']);
    // The ends.
    expect(canMove(DEFAULT, 0, -1)).toBe(false);
    expect(canMove(DEFAULT, 5, 1)).toBe(false);
    expect(canMove(DEFAULT, 0, 1)).toBe(true);
  });

  it('puts a source on the level above and takes it off again; lines and only-when-asked are kept', () => {
    const joined = update(DEFAULT, 1, {same: true});
    expect(levelNumbers(joined)).toEqual([1, 1, 2, 2, 3, 4]);
    expect(levelNumbers(update(joined, 1, {same: false}))).toEqual([1, 2, 3, 3, 4, 5]);
    expect(update(DEFAULT, 0, {same: true})[0].same).toBe(false);
    const lined = update(update(DEFAULT, 2, {use: 'Customer segmentation'}), 4, {when_asked: true});
    expect(serialise(move(lined, 4, -1))).toContain('{"id":"nerp","when_asked":true},{"id":"asap","use":"Customer segmentation"}');
    expect(cleanUse('Segments\n<by age>', 200)).toBe('Segments  by age ');
    expect(cleanUse('x'.repeat(250), 200)).toHaveLength(200);
  });

  it('removes a source this PC does not have, keeping the levels sound', () => {
    expect(serialise(remove(DEFAULT, 2))).toBe('[{"id":"dashboards"},{"id":"postgresql"},{"id":"gscm"},{"id":"nerp"},{"id":"bdp"}]');
    expect(serialise(remove(DEFAULT, 0))).toBe('[{"id":"postgresql"},{"id":"asap"},{"id":"gscm","same":true},{"id":"nerp"},{"id":"bdp"}]');
  });

  it('in Auto, leaves out the sources used only when asked', () => {
    const systems: SystemInfo[] = [{id: 'asap', name: 'ASAP', kind: 'portal'}, {id: 'nerp', name: 'NERP', kind: 'reports', only_when_asked: true},
      {id: 'knowledge', name: 'Knowledge base', kind: 'knowledge'}];
    expect(autoSystems(systems)).toEqual(['asap', 'knowledge']);
    expect(whenAsked(systems).map(s => s.id)).toEqual(['nerp']);
  });
});
