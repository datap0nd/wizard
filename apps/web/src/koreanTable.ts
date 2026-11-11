// A visual's table laid out the way Korean business reports are (the look of the owner's Composer project, its
// designer/generic_report.py and render/excel.py): Malgun Gothic 9 pt, a dark header band with grouped columns merged
// over a lighter second row, repeated row labels merged downwards, shaded bold total and subtotal rows, one
// "(Unit: ...)" line above the table in place of a unit in every cell, negatives in red brackets, zero as "-" and change
// columns with a blue ▲ or a red ▼. Pure: visualExport.ts writes it to the clipboard and to Excel.
import type {Visual} from './types';
import {excelValue, grid, gridColumns, type Cell} from './visuals';

export const KOREAN = {
  font: 'Malgun Gothic', ink: '#1F2937', header: '#1F4E78', subheader: '#D9EAF7', subtotal: '#EAF2F8', total: '#D6E4F0',
  thin: '#CCD6E0', medium: '#7A8FA6', title: '#17365D', subtitle: '#5B6573', unit: '#6B7280', up: '#0000FF', down: '#FF0000',
};

export interface KCell {
  text: string;
  /** What Excel keeps: a number (a percent as a fraction) or text. */
  value: string | number | null;
  format: string | null;
  fill?: string;
  color: string;
  bold: boolean;
  align: 'left' | 'right' | 'center';
  rowSpan: number;
  colSpan: number;
  /** Under a merged cell above or to the left: nothing is written here. */
  covered: boolean;
}

export interface KTable {
  /** "(Unit: USD)" when every amount column has the same unit; else each header names its own. */
  unit: string | null;
  header: KCell[][];
  body: KCell[][];
  /** How many leading columns are row labels (they stay in view when the sheet scrolls sideways). */
  labels: number;
  /** Column widths in Excel's character units. */
  widths: number[];
}

const COUNTED = ['units', 'devices', 'transfers'];
const TOTAL = /^(grand\s+total|totals?|합계|총계|총합계|전체\s*합계|계)$/i;
const SUBTOTAL = /(^|\s)(sub-?\s?totals?|totals?)$|(소계|합계)$/i;
const CHANGE = /growth|change|yoy|y\/y|mom|m\/m|qoq|q\/q|\bvs\.?\b|variance|delta|Δ|증감|성장|대비|신장/i;
const HANGUL = /[가-힣]/;
const SPLIT = /\s+[-–—|·/]\s+|:\s+/;

/** A label as its column group and its own name ("2025 · Units" → 2025, Units), or null when it names no group. */
function split(label: string): [string, string] | null {
  const at = label.match(SPLIT);
  if (!at || at.index === undefined) return null;
  const [group, leaf] = [label.slice(0, at.index).trim(), label.slice(at.index + at[0].length).trim()];
  return group && leaf ? [group, leaf] : null;
}

/** Text as wide as Excel shows it: a Korean, Chinese or Japanese character takes two columns. */
function span(text: string): number {
  let n = 0;
  for (const ch of text) n += ch.codePointAt(0)! >= 0x1100 ? 2 : 1;
  return n;
}

function shown(value: number, decimals: number, percent: boolean): string {
  return Math.abs(value).toLocaleString('en-US', {minimumFractionDigits: decimals, maximumFractionDigits: decimals}) + (percent ? '%' : '');
}

/** The Korean-report table of a visual (`all`: every column of a heatmap, not only the shaded ones). */
export function koreanTable(visual: Visual, all = false): KTable {
  const columns = gridColumns(visual, all);
  const g = grid(visual, all);
  const n = columns.length;
  const numeric = columns.map(c => c.type !== 'string');
  const values = (j: number): Cell[] => g.rows.map(r => r[j].value);

  // One unit line when every amount column shares a unit; percent columns say % themselves.
  const unitOf = (j: number) => columns[j].type === 'currency' ? columns[j].unit || 'USD' : columns[j].unit && !COUNTED.includes(columns[j].unit!) ? columns[j].unit : null;
  const amounts = columns.map((_, j) => j).filter(j => numeric[j] && columns[j].type !== 'percent');
  const units = new Set(amounts.map(unitOf));
  const shared = amounts.length > 0 && units.size === 1 ? [...units][0] : null;
  const korean = HANGUL.test([visual.title, ...columns.map(c => c.label), ...g.rows.slice(0, 100).map(r => r[0]?.text ?? '')].join(' '));
  const label = (j: number) => {
    const unit = numeric[j] && columns[j].type !== 'percent' && !shared ? unitOf(j) : null;
    return columns[j].label + (unit ? ` (${unit})` : '');
  };

  // Header: a run of two or more neighbouring columns naming the same group shares one merged cell above their names.
  const parts = columns.map((c, j) => numeric[j] ? split(c.label) : null);
  const grouped = parts.map((p, j) => !!p && ((parts[j - 1]?.[0] === p[0]) || (parts[j + 1]?.[0] === p[0])));
  const two = grouped.some(Boolean);
  const head = (text: string, second: boolean, over: Partial<KCell> = {}): KCell => ({text, value: text, format: null,
    fill: second ? KOREAN.subheader : KOREAN.header, color: second ? KOREAN.ink : '#FFFFFF', bold: true, align: 'center', rowSpan: 1, colSpan: 1, covered: false, ...over});
  const top: KCell[] = [], below: KCell[] = [];
  for (let j = 0; j < n; j++) {
    if (!grouped[j]) {
      top.push(head(label(j), false, {rowSpan: two ? 2 : 1}));
      below.push(head('', false, {covered: true}));
      continue;
    }
    const first = !grouped[j - 1] || parts[j - 1]![0] !== parts[j]![0];
    let run = 1;
    while (first && grouped[j + run] && parts[j + run]![0] === parts[j]![0]) run++;
    top.push(first ? head(parts[j]![0], false, {colSpan: run}) : head('', false, {covered: true}));
    const unit = columns[j].type !== 'percent' && !shared ? unitOf(j) : null;
    below.push(head(parts[j]![1] + (unit ? ` (${unit})` : ''), true));
  }

  // Number formats: brackets and red for a negative, "-" for zero; a change column points up in blue, down in red.
  const change = columns.map((c, j) => numeric[j] && (CHANGE.test(c.label) || (c.type === 'percent' && values(j).some(v => typeof v === 'number' && v < 0))));
  const decimals = columns.map((c, j) => c.type === 'percent' ? 1 : c.type === 'integer' || values(j).every(v => typeof v !== 'number' || Number.isInteger(v)) ? 0 : 2);
  const base = columns.map((c, j) => c.type === 'percent' ? '0.0%' : `#,##0${decimals[j] ? '.' + '0'.repeat(decimals[j]) : ''}`);
  const format = (j: number, plain: boolean) => !numeric[j] ? null
    : plain ? `${base[j]};-${base[j]};"-"`
    : change[j] ? `[Blue]"▲"${base[j]};[Red]"▼"${base[j]};"-"`
    : `${base[j]};[Red](${base[j]});"-"`;

  // Row labels: the leading text columns. A row is a total when its first label says so, a subtotal when another does.
  let labels = 0;
  while (labels < n && !numeric[labels]) labels++;
  const kinds = g.rows.map(row => {
    const texts = row.slice(0, labels).map(c => (typeof c.value === 'string' ? c.value : '').trim());
    return texts[0] && TOTAL.test(texts[0]) ? 'total' : texts.some(t => TOTAL.test(t) || SUBTOTAL.test(t)) ? 'subtotal' : 'row';
  });

  const body: KCell[][] = g.rows.map((row, i) => row.map((c, j) => {
    const kind = kinds[i];
    const fill = c.fill ?? (kind === 'total' ? KOREAN.total : kind === 'subtotal' ? KOREAN.subtotal : undefined);
    const cell: KCell = {text: '', value: null, format: format(j, !!c.fill), fill, color: c.fill ? c.color ?? KOREAN.ink : KOREAN.ink,
      bold: kind !== 'row', align: numeric[j] ? 'right' : 'left', rowSpan: 1, colSpan: 1, covered: false};
    if (!numeric[j] || typeof c.value !== 'number' || !Number.isFinite(c.value)) {
      // Text, or a missing value: blank, never the "-" of a zero.
      cell.text = c.value === null ? '' : String(c.value);
      cell.value = c.value === null ? null : String(c.value);
      return cell;
    }
    const percent = columns[j].type === 'percent';
    const text = shown(c.value, decimals[j], percent);
    cell.value = excelValue(c);
    if (c.value === 0) cell.text = '-';
    else if (c.fill) cell.text = (c.value < 0 ? '-' : '') + text;
    else if (change[j]) { cell.text = (c.value > 0 ? '▲' : '▼') + text; cell.color = c.value > 0 ? KOREAN.up : KOREAN.down; }
    else if (c.value < 0) { cell.text = `(${text})`; cell.color = KOREAN.down; }
    else cell.text = text;
    return cell;
  }));

  // Merge a label repeated on neighbouring rows, inside the merged label to its left. The last column never merges.
  const merging = Math.min(labels, n - 1);
  let bounds = new Set<number>([0, body.length]);
  for (let j = 0; j < merging; j++) {
    const next = new Set<number>(bounds);
    for (let i = 0; i < body.length;) {
      let end = i + 1;
      while (end < body.length && !bounds.has(end) && body[i][j].text !== '' && body[end][j].text === body[i][j].text
        && kinds[i] !== 'total' && kinds[end] !== 'total') end++;
      body[i][j].rowSpan = end - i;
      for (let k = i + 1; k < end; k++) body[k][j].covered = true;
      next.add(i);
      i = end;
    }
    bounds = next;
  }

  // A total's label runs across the label columns it leaves empty.
  body.forEach((row, i) => {
    if (kinds[i] !== 'total') return;
    let across = 1;
    while (across < labels && row[across].text === '') across++;
    row[0].colSpan = across;
    for (let j = 1; j < across; j++) row[j].covered = true;
  });

  const widths = columns.map((_, j) => {
    const texts = [two && grouped[j] ? below[j].text : top[j].text, ...body.map(r => r[j].covered || r[j].colSpan > 1 ? '' : r[j].text)];
    return Math.min(32, Math.max(numeric[j] ? 12 : 10, ...texts.map(t => span(t) + 3)));
  });
  return {unit: shared ? `(${korean ? '단위' : 'Unit'}: ${shared})` : null, header: two ? [top, below] : [top], body, labels, widths};
}
