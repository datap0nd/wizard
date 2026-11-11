import {describe, expect, it} from 'vitest';
import {koreanTable} from './koreanTable';
import type {Visual} from './types';

const base = {id: 'V1', kind: 'table' as const, subtitle: null, x: null, series: [], evidence_ids: [], note: null, derived_by: 'model'};

describe('a table laid out as a Korean report', () => {
  it('merges a repeated label only inside the label to its left, and never across a total', () => {
    const t = koreanTable({...base, title: 'Units', columns: [{key: 'a', label: 'Region', type: 'string', unit: null},
      {key: 'b', label: 'Channel', type: 'string', unit: null}, {key: 'u', label: 'Units', type: 'integer', unit: 'units'}],
      rows: [['Gulf', 'Online', 5], ['Gulf', 'Online', 6], ['Africa', 'Online', 7], ['Total', 'Online', 18]]} as Visual);
    expect(t.body.map(r => r[0].rowSpan)).toEqual([2, 1, 1, 1]);
    expect(t.body.map(r => r[1].rowSpan)).toEqual([2, 1, 1, 1]);   // Africa's Online is its own cell
    expect(t.body[1][0].covered).toBe(true);
    expect(t.body[3][0]).toMatchObject({bold: true, fill: '#D6E4F0'});
    expect(t.unit).toBeNull();                                      // counted units are not printed
    expect(t.header).toHaveLength(1);
    expect(t.labels).toBe(2);
  });

  it('names each unit in its header when the amount columns differ, and keeps a missing value blank', () => {
    const t = koreanTable({...base, title: '매출', columns: [{key: 'm', label: '국가', type: 'string', unit: null},
      {key: 's', label: 'Sales', type: 'currency', unit: 'USD'}, {key: 'w', label: 'Weight', type: 'number', unit: 'kg'}],
      rows: [['한국', 1234.5, null], ['일본', 0, 2.5]]} as Visual);
    expect(t.header[0].map(c => c.text)).toEqual(['국가', 'Sales (USD)', 'Weight (kg)']);
    expect(t.body[0].map(c => c.text)).toEqual(['한국', '1,234.50', '']);
    expect(t.body[1].map(c => c.text)).toEqual(['일본', '-', '2.50']);
    expect(t.body[0][2].value).toBeNull();
  });

  it('writes the unit line in Korean for a Korean table', () => {
    const t = koreanTable({...base, title: '매출', columns: [{key: 'm', label: '국가', type: 'string', unit: null},
      {key: 's', label: '매출', type: 'currency', unit: 'KRW'}], rows: [['한국', 10], ['소계', 10]]} as Visual);
    expect(t.unit).toBe('(단위: KRW)');
    const total = koreanTable({...base, title: 'Units', columns: [{key: 'a', label: 'Region', type: 'string', unit: null},
      {key: 'b', label: 'Market', type: 'string', unit: null}, {key: 'u', label: 'Units', type: 'integer', unit: null}],
      rows: [['Gulf', 'UAE', 5], ['합계', null, 5]]} as Visual);
    expect(total.body[1][0]).toMatchObject({colSpan: 2, text: '합계'});
    expect(total.body[1][1].covered).toBe(true);
    expect(t.body[1][0]).toMatchObject({bold: true});
  });

  it('keeps a heatmap cell its shading and a readable number', () => {
    const t = koreanTable({...base, kind: 'heatmap', title: 'Growth', x: 'm', series: ['j'], columns: [{key: 'm', label: 'Market', type: 'string', unit: null},
      {key: 'j', label: 'Jul', type: 'percent', unit: '%'}], rows: [['Egypt', -30], ['UAE', 30]]} as Visual);
    expect(t.body[0][1]).toMatchObject({text: '-30.0%', color: '#ffffff', format: '0.0%;-0.0%;"-"'});
    expect(t.body[0][1].fill).toBe('#7c1e1e');
  });
});
