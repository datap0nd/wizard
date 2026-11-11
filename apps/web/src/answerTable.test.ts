import {describe, expect, it} from 'vitest';
import {tableVisual, type HastNode} from './answerTable';

const text = (value: string): HastNode => ({type: 'text', value});
const el = (tagName: string, children: HastNode[], properties: Record<string, unknown> = {}): HastNode => ({type: 'element', tagName, children, properties});
const row = (tag: string, cells: (string | HastNode[])[]) => el('tr', cells.map(c => el(tag, typeof c === 'string' ? [text(c)] : c)));
const table = (head: string[], body: (string | HastNode[])[][]) => el('table', [el('thead', [row('th', head)]), text('\n'), el('tbody', body.map(r => row('td', r)))]);

describe("a table in Gemini's answer", () => {
  it('becomes a table visual: numbers typed for Excel, each cell keeping its wording, its citations as evidence', () => {
    const v = tableVisual(table(['Market', 'Year', 'Units', 'Share', 'Spend', 'Note'], [
      ['Egypt', '2025', '1,200', '12.5%', '$3,400', [text('up '), el('strong', [text('fast')])]],
      ['UAE', '2026', [text('(800) '), el('a', [text('E2')], {href: '#evidence-E2'})], '—', '$90', ''],
    ]))!;
    expect(v.columns.map(c => c.type)).toEqual(['string', 'string', 'integer', 'percent', 'currency', 'string']);
    expect(v.rows).toEqual([['Egypt', '2025', 1200, 12.5, 3400, 'up fast'], ['UAE', '2026', -800, null, 90, null]]);
    expect(v.texts![1]).toEqual(['UAE', '2026', '(800)', '—', '$90', '']);
    expect(v.evidence_ids).toEqual(['E2']);
    expect(v).toMatchObject({kind: 'table', title: '', id: 'Table'});
  });

  it('keeps a column as text when one cell is not a number, and codes with a leading zero as names', () => {
    const v = tableVisual(table(['Model', 'Sales', 'Code'], [['A', '1.2M', '00123'], ['B', '900', '00456']]))!;
    expect(v.columns.map(c => c.type)).toEqual(['string', 'string', 'string']);
    expect(v.rows[1]).toEqual(['B', '900', '00456']);
  });

  it('is nothing to copy without rows', () => {
    expect(tableVisual(el('table', [el('thead', [row('th', ['A'])])]))).toBeNull();
  });
});
