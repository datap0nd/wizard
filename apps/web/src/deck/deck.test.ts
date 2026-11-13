import JSZip from 'jszip';
import {describe, expect, it} from 'vitest';
import {deckFileName, drawnChart, fit, layoutDeck, lead, runs, sections, tableCells, textWidth, unitLabel, type Element, type Para} from './layout';
import {deckPptx, tidyParagraphs} from './pptx';
import type {Deck, DesignTokens, Visual} from '../types';

const TOKENS: DesignTokens = {
  name: 'Test', slide: {width: 13.333, height: 7.5},
  fonts: {title: 'Brand Sans', subtitle: 'Brand Sans', body: 'Calibri', labels: 'Arial', east_asian: 'Malgun Gothic'},
  colors: {brand: '#1428A0', title: '#000000', text: '#000000', secondary: '#404040', muted: '#7F7F7F', background: '#FFFFFF',
    card: '#E7ECF0', line: '#D9D9D9', good_fill: '#E2EFDA', good_text: '#375623', bad_fill: '#FFF2CC', bad_text: '#7F6000',
    positive: '#1F7A3A', negative: '#C00000', series: ['#1428A0', '#7F7F7F', '#A6A6A6']},
  sizes: {cover_title: 44, cover_subtitle: 20, cover_meta: 16, title: 32, subtitle: 14, section_title: 36, agenda: 22, heading: 12,
    body: 10, kpi: 28, table: 10, chart_label: 8, unit: 8, footnote: 6.5},
  cover: {background: 'brand'}, footer: {text: 'Confidential', page_numbers: true}, rules: {max_highlights: 4, max_points: 6},
};

const SEGMENTS: Visual = {id: 'V1', kind: 'bar', title: 'Sell-out by segment', subtitle: null, x: 'segment', series: ['q2', 'q3'],
  columns: [{key: 'segment', label: 'Segment', type: 'string', unit: null}, {key: 'q2', label: 'Q2', type: 'number', unit: 'units'},
    {key: 'q3', label: 'Q3', type: 'number', unit: 'units'}],
  rows: [['Flagship', 100, 118], ['Mass', 300, null]], evidence_ids: ['E1'], note: null, derived_by: 'model'};
const TABLE: Visual = {...SEGMENTS, id: 'V2', kind: 'table', title: 'Segments'};

function deck(over: Partial<Deck> = {}): Deck {
  return {id: 'D1', run_id: 'r', title: 'Q3 review: MENA', storyline: 'Flagship carried Q3.', audience: null, revises: null,
    family: null, version: 1, created_at: '2026-11-13T10:00:00', evidence_ids: ['E1'], data_mode: 'SYNTHETIC',
    visuals: {V1: SEGMENTS, V2: TABLE},
    sources: {E1: {name: 'AI Team Database · Sell-out by segment', as_of: '2026-11-10', data_mode: 'SYNTHETIC'}},
    design: {tokens: TOKENS, source: 'knowledge', note: 'presentation-look', status: 'DRAFT_UNSIGNED', problems: [], about: ''},
    slides: [
      {kind: 'cover', title: 'Q3 review', subtitle: 'Flagship carried the quarter', meta: 'MENA · November 2026'},
      {kind: 'agenda'},
      {kind: 'section', title: 'Where we stand'},
      {kind: 'summary', title: 'Flagship carried Q3 while Mass fell', kpis: [{value: '+18%', label: 'Flagship sell-out', change: '▲ vs plan', tone: 'good', evidence_ids: ['E1']}],
        points: ['**Flagship:** grew 18%', {text: 'Mass fell', sub: ['C-brands took share']}]},
      {kind: 'chart', title: 'Flagship grew while Mass fell', visual: 'V1', chart: 'stacked', points: ['So what']},
      {kind: 'section', title: 'What we do next'},
      {kind: 'table', title: 'Mass is the gap', visual: 'V2', highlights: [{row: 'Mass', column: 'Q3', tone: 'bad'}, {row: 'Flagship', column: 'q3', tone: 'good'}]},
      {kind: 'cards', title: 'Three moves for Q4', cards: [{heading: 'Win mid-tier', points: ['A-series push']}, {heading: 'Defend', value: '2 pp'}, {heading: 'Fund it'}]},
      {kind: 'kpis', title: 'Targets', kpis: [{value: '1', label: 'a'}, {value: '2', label: 'b'}, {value: '3', label: 'c'}, {value: '4', label: 'd'}, {value: '5', label: 'e'}]},
      {kind: 'split', title: 'Two views', left: {heading: 'Chart', visual: 'V1'}, right: {heading: 'Notes', points: ['x']}},
      {kind: 'text', title: '시장 점유율이 하락했습니다', points: ['한국어 텍스트']},
      {kind: 'closing', title: 'Thank you'},
    ], ...over};
}

async function zipOf(blob: Blob) {
  return JSZip.loadAsync(await blob.arrayBuffer());
}

describe('deck layout', () => {
  it('lays out every slide inside the slide, with sources, page numbers and the data label', () => {
    const pages = layoutDeck(deck());
    expect(pages).toHaveLength(12);
    for (const page of pages) {
      for (const el of page.elements) {
        expect(el.x).toBeGreaterThanOrEqual(0);
        expect(el.y).toBeGreaterThanOrEqual(0);
        expect(el.x + el.w).toBeLessThanOrEqual(13.333 + 1e-6);
        expect(el.y + el.h).toBeLessThanOrEqual(7.5 + 1e-6);
      }
    }
    expect(pages[0].background).toBe('#1428A0');
    const texts = (n: number) => pages[n].elements.flatMap(e => e.type === 'text' ? [e.paras.map(p => p.runs.map(r => r.text).join('')).join('\n')] : []);
    expect(texts(4).some(t => t.includes('Source: AI Team Database · Sell-out by segment (as of') && t.includes('SYNTHETIC test data'))).toBe(true);
    expect(texts(4)).toContain('5');
    expect(texts(4)).toContain('Confidential');
    expect(texts(4)).toContain('(units)');
    expect(texts(0).some(t => t.includes('Source'))).toBe(false);
    // The agenda lists the sections with their pages.
    expect(texts(1).join('\n')).toContain('Where we stand\n(3–5)');
    expect(texts(1).join('\n')).toContain('What we do next\n(6–12)');
    expect(pages[4].notes).toContain('Source: AI Team Database');
  });

  it('fills the slide: led points become a grid of rows down to the footer, a chart has its takeaways column beside it', () => {
    const t = deck({slides: [
      {kind: 'text', title: 'Four points', points: ['**Flagship:** +18%', '**Mass:** -15%', '**Eco:** +9%', '**Q4:** three moves']},
      {kind: 'chart', title: 'A chart', visual: 'V1', points: ['One', 'Two', 'Three']},
      {kind: 'grid', title: 'Three panels', panels: [{heading: 'A', visual: 'V1'}, {heading: 'B', visual: 'V1'}, {heading: 'C', points: ['x', 'y', 'z']}]},
      {kind: 'cards', title: 'Cards', cards: [{heading: 'One', points: ['a', 'b', 'c']}, {heading: 'Two', points: ['d', 'e', 'f']}]},
    ]});
    const [text, chart, grid, cards] = layoutDeck(t);
    const bottom = (els: Element[]) => Math.max(...els.filter(e => e.type === 'rect' && e.h < 0.05 && e.w > 1).map(e => e.y));
    expect(bottom(text.elements)).toBeGreaterThan(6.4);  // the last row's rule sits just above the footer
    const labels = text.elements.filter(e => e.type === 'text' && e.paras[0]?.runs[0]?.text === 'Flagship');
    expect(labels).toHaveLength(1);
    expect(text.elements.some(e => e.type === 'rect' && e.fill === TOKENS.colors.card && e.w > 1.5 && e.w < 3)).toBe(true);
    const column = chart.elements.find(e => e.type === 'text' && e.paras[0]?.runs[0]?.text === 'Key takeaways');
    expect(column).toBeDefined();
    const panel = chart.elements.find(e => e.type === 'rect' && e.fill === TOKENS.colors.card)!;
    expect(panel.y + panel.h).toBeGreaterThan(6.5);
    expect(grid.elements.filter(e => e.type === 'chart')).toHaveLength(2);
    expect(Math.max(...cards.elements.filter(e => e.type === 'rect' && e.fill === TOKENS.colors.card).map(e => e.y + e.h))).toBeGreaterThan(6.5);
    expect(lead('**Flagship:** +18% vs plan')).toEqual(['Flagship', '+18% vs plan']);
    expect(lead('No lead here')).toBeNull();
  });

  it('shades the highlighted cells and keeps a heatmap or table as a native table', () => {
    const {cells} = tableCells(TABLE, [{row: 'mass', column: 'Q3', tone: 'bad'}, {row: 'Flagship', column: 'q3', tone: 'good'}, {row: 'Eco', column: 'Q3', tone: 'good'}], TOKENS);
    expect(cells[0].map(c => c.text)).toEqual(['Segment', 'Q2 (units)', 'Q3 (units)']);
    expect(cells[2][2]).toMatchObject({fill: '#FFF2CC', color: '#7F6000', bold: true});
    expect(cells[1][2]).toMatchObject({fill: '#E2EFDA', color: '#375623'});
    expect(cells[1][1].fill).toBeUndefined();
    const table = layoutDeck(deck()).find(p => p.kind === 'table')!.elements.find(e => e.type === 'table');
    expect(table).toBeDefined();
  });

  it('chooses how a chart is drawn and states its unit', () => {
    expect(drawnChart(SEGMENTS, 'auto')).toBe('column');
    expect(drawnChart({...SEGMENTS, rows: Array.from({length: 12}, (_, i) => [`M${i}`, i, i])}, 'auto')).toBe('bar');
    expect(drawnChart({...SEGMENTS, kind: 'line'}, undefined)).toBe('line');
    expect(drawnChart({...SEGMENTS, kind: 'scatter'}, 'stacked')).toBe('scatter');
    expect(drawnChart(SEGMENTS, 'percent')).toBe('percent');
    expect(unitLabel(SEGMENTS)).toBe('(units)');
    expect(unitLabel({...SEGMENTS, columns: [SEGMENTS.columns[0], {...SEGMENTS.columns[1], type: 'percent', unit: null}, {...SEGMENTS.columns[2], unit: 'USD'}]})).toBe('');
  });

  it('draws a long title smaller rather than cutting it, and measures Korean wider', () => {
    const para: Para = {runs: [{text: 'A very long takeaway title that keeps going and going well past two lines on a slide'}], size: 40, color: '#000', font: 'x', bold: true};
    const [fitted] = fit([para], {w: 6, h: 0.9});
    expect(fitted.size).toBeLessThan(40);
    expect(fitted.size).toBeGreaterThanOrEqual(24);
    expect(textWidth('가나다', 10)).toBeGreaterThan(textWidth('abc', 10));
    expect(runs('**Lead:** rest')).toEqual([{text: 'Lead:', bold: true, color: undefined}, {text: ' rest', color: undefined}]);
    expect(sections(deck().slides).map(s => [s.from, s.to])).toEqual([[3, 5], [6, 12]]);
    expect(deckFileName(deck({title: 'Q3: review?', version: 2}))).toBe('Q3 review (v2).pptx');
  });
});

describe('deck PowerPoint file', () => {
  it('writes every slide with native charts, tables, notes and the company fonts', async () => {
    const zip = await zipOf(await deckPptx(deck()));
    const slides = Object.keys(zip.files).filter(n => /^ppt\/slides\/slide\d+\.xml$/.test(n));
    expect(slides).toHaveLength(12);
    const charts = Object.keys(zip.files).filter(n => /^ppt\/charts\/chart\d+\.xml$/.test(n));
    expect(charts.length).toBe(2);
    const chart = await zip.file(charts[0])!.async('string');
    expect(chart).toContain('<c:grouping val="stacked"/>');
    expect(chart).toContain('<c:barDir val="col"/>');
    expect(chart).toContain('1428A0');
    const summary = await zip.file('ppt/slides/slide4.xml')!.async('string');
    expect(summary).toContain('Flagship carried Q3 while Mass fell');
    expect(summary).toContain('typeface="Brand Sans"');
    expect(summary).toContain('<a:ea typeface="Malgun Gothic"');
    expect(summary).not.toMatch(/<a:ea typeface="Calibri"/);
    // A bullet with a bold lead-in is one paragraph with one set of settings.
    for (const name of slides) {
      const xml = await zip.file(name)!.async('string');
      for (const p of xml.match(/<a:p>[\s\S]*?<\/a:p>/g) ?? []) expect((p.match(/<a:pPr\b/g) ?? []).length).toBeLessThanOrEqual(1);
    }
    const table = await zip.file('ppt/slides/slide7.xml')!.async('string');
    expect(table).toContain('<a:tbl>');
    expect(table).toContain('FFF2CC');
    const theme = await zip.file('ppt/theme/theme1.xml')!.async('string');
    expect(theme).toContain('<a:ea typeface="Malgun Gothic"/>');
    const notes = Object.keys(zip.files).filter(n => /^ppt\/notesSlides\/notesSlide\d+\.xml$/.test(n));
    expect(notes.length).toBeGreaterThan(0);
    const presentation = await zip.file('ppt/presentation.xml')!.async('string');
    expect(presentation).toContain('cx="12192000"');
    expect(chart).not.toContain('<c:pt idx="1"><c:v></c:v></c:pt>');
  });

  it('keeps a 4:3 company slide size', async () => {
    const zip = await zipOf(await deckPptx(deck({design: {...deck().design, tokens: {...TOKENS, slide: {width: 10, height: 7.5}}}})));
    expect(await zip.file('ppt/presentation.xml')!.async('string')).toContain('cx="9144000"');
  });

  it('tidies repeated paragraph settings', () => {
    expect(tidyParagraphs('<a:p><a:pPr algn="l"><a:buChar char="x"/></a:pPr><a:r/><a:pPr algn="l" indent="0"/><a:r/></a:p><a:p><a:pPr/><a:r/></a:p>'))
      .toBe('<a:p><a:pPr algn="l"><a:buChar char="x"/></a:pPr><a:r/><a:r/></a:p><a:p><a:pPr/><a:r/></a:p>');
  });
});
