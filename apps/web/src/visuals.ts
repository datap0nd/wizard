// What a visual shows, as plain data: the heatmap's colour scale and the grid of cells every copy and download is built
// from (VisualBlock draws it; visualExport.ts writes it to PowerPoint, Excel, the clipboard and pictures). Pure, so the
// app, the Pages site and the tests share one definition of what a heatmap cell looks like.
import {DATA_MODE_TEXT, formatValue} from './format';
import type {DataMode, Visual} from './types';

export const INK = '#18233b';
export const INK_2 = '#4b5871';
export const LINE = '#e0e4eb';
export const HEAD = '#f1f2f5';
export const COLORS = ['#315bd6', '#0891b2', '#b45309', '#7c3aed', '#be123c', '#4b5871'];

// Sequential: one hue, light to dark (amounts). Diverging: red below zero, a neutral grey at zero, blue above (growth,
// change, variance), the same number of steps on each arm. The values are printed in every cell, so colour is never the
// only way to read one.
const SEQUENTIAL = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'];
const NEUTRAL = '#f0efec';
const POSITIVE = [NEUTRAL, '#b7d3f6', '#6da7ec', '#2a78d6', '#184f95', '#0d366b'];
const NEGATIVE = [NEUTRAL, '#f7c6c4', '#ee8a88', '#e34948', '#b3302f', '#7c1e1e'];
export const MISSING = '#ffffff';

export type Cell = string | number | null;

function rgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function hex([r, g, b]: [number, number, number]): string {
  return '#' + [r, g, b].map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
}

/** A colour `t` (0..1) of the way along a ramp of stops. */
export function along(stops: string[], t: number): string {
  const x = Math.min(1, Math.max(0, Number.isFinite(t) ? t : 0)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(x));
  const a = rgb(stops[i]), b = rgb(stops[i + 1]), f = x - i;
  return hex([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f]);
}

function luminance(color: string): number {
  const [r, g, b] = rgb(color).map(v => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

/** The text colour that reads best on a fill: the app's ink or white. */
export function textOn(fill: string): string {
  return contrast(fill, '#ffffff') > contrast(fill, INK) ? '#ffffff' : INK;
}

export interface HeatScale {
  kind: 'sequential' | 'diverging';
  min: number;
  max: number;
  /** The fill of a cell; missing values are white (missing, never zero). */
  fill: (value: Cell) => string;
  /** The legend's gradient stops, low to high. */
  stops: string[];
}

function numbers(visual: Visual, keys: string[]): number[] {
  const index = keys.map(k => visual.columns.findIndex(c => c.key === k)).filter(i => i >= 0);
  return visual.rows.flatMap(r => index.map(i => r[i])).filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
}

/** The heatmap's scale over all its cells: diverging around zero when asked, or when the values have both signs. */
export function heatScale(visual: Visual): HeatScale {
  const values = numbers(visual, visual.series);
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 0;
  const kind = visual.scale ?? (min < 0 && max > 0 ? 'diverging' : 'sequential');
  if (kind === 'diverging') {
    const reach = Math.max(Math.abs(min), Math.abs(max)) || 1;
    return {kind, min, max, stops: [...NEGATIVE].reverse().concat(POSITIVE.slice(1)), fill: value => {
      if (typeof value !== 'number' || !Number.isFinite(value)) return MISSING;
      return value < 0 ? along(NEGATIVE, -value / reach) : along(POSITIVE, value / reach);
    }};
  }
  const span = max - min;
  return {kind, min, max, stops: SEQUENTIAL, fill: value => {
    if (typeof value !== 'number' || !Number.isFinite(value)) return MISSING;
    return along(SEQUENTIAL, span ? (value - min) / span : 0.5);
  }};
}

export interface GridCell { value: Cell; text: string; numeric: boolean; fill?: string; color?: string; type: string; unit: string | null }
export interface Grid { header: string[]; types: string[]; units: (string | null)[]; rows: GridCell[][] }

function header(c: Visual['columns'][number]): string {
  return c.label + (c.unit && !['%', 'USD'].includes(c.unit) && c.type !== 'string' ? ` (${c.unit})` : '');
}

/** The cells a visual shows as a table: a heatmap's row labels and its shaded columns (`all`: every column, the
 *  shaded ones still shaded), any other visual every column. */
export function grid(visual: Visual, all = false): Grid {
  const heat = visual.kind === 'heatmap';
  const keys = heat && !all ? [visual.x ?? '', ...visual.series] : visual.columns.map(c => c.key);
  const columns = keys.map(k => visual.columns.find(c => c.key === k)).filter((c): c is Visual['columns'][number] => !!c);
  const index = columns.map(c => visual.columns.indexOf(c));
  const scale = heat ? heatScale(visual) : null;
  const shaded = new Set(heat ? visual.series : []);
  return {
    header: columns.map(header), types: columns.map(c => c.type), units: columns.map(c => c.unit),
    rows: visual.rows.map(row => columns.map((c, j) => {
      const value = row[index[j]] ?? null;
      const cell: GridCell = {value, text: formatValue(value, c.type, c.unit), numeric: c.type !== 'string', type: c.type, unit: c.unit};
      if (scale && shaded.has(c.key)) { cell.fill = scale.fill(value); cell.color = textOn(cell.fill); }
      return cell;
    })),
  };
}

/** A cell's value as Excel keeps it: a percent as a fraction (12.5 → 0.125, shown 12.5%), text as text. */
export function excelValue(cell: Pick<GridCell, 'value' | 'type'>): string | number | null {
  if (typeof cell.value !== 'number' || !Number.isFinite(cell.value)) return cell.value === null ? null : String(cell.value);
  return cell.type === 'percent' ? cell.value / 100 : cell.value;
}

const COUNTED = ['units', 'devices', 'transfers'];

/** The Excel number format that shows a column as Wizard does. */
export function excelFormat(type: string, unit: string | null, values: Cell[]): string | null {
  if (type === 'string') return null;
  if (type === 'percent') return '0.0%';  // as Wizard shows it: one decimal
  const quoted = (text: string) => `"${text.replace(/"/g, '')}"`;
  if (type === 'currency') return !unit || unit === 'USD' ? '"$"#,##0' : `#,##0 ${quoted(unit)}`;
  const body = type === 'integer' || values.every(v => typeof v !== 'number' || Number.isInteger(v)) ? '#,##0' : '#,##0.00';
  return unit && !COUNTED.includes(unit) ? `${body} ${quoted(unit)}` : body;
}

/** What a copied or downloaded visual says under it: where its values came from and their data label. */
export function sourceLine(visual: Visual, mode: DataMode | null | undefined, names: string[] = []): string {
  const from = visual.evidence_ids.length ? `Prepared by Gemini in Wizard from ${visual.evidence_ids.join(', ')}` : 'Prepared by Gemini in Wizard; no cited evidence';
  const label = mode ? (mode === 'SYNTHETIC' ? 'SYNTHETIC test data, not corporate figures' : DATA_MODE_TEXT[mode]?.label) : null;
  return [`${from}${names.length ? ` (${names.join('; ')})` : ''}`, label, visual.note].filter(Boolean).join(' · ');
}

/** A file name from the visual's title: letters, digits, spaces and a few marks, at most 80 characters. */
export function fileName(visual: Visual, extension: string): string {
  const stem = visual.title.replace(/[\\/:*?"<>|\u0000-\u001f]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80).trim() || `Wizard ${visual.id}`;
  return `${stem}.${extension}`;
}
