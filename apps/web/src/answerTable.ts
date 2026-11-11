// A table Gemini wrote in its answer (Markdown), as a visual: the same copies and downloads as a chart or a data table.
// Its cells keep their wording; a column whose every cell is a number is typed, so Excel receives numbers.
import type {Visual} from './types';

/** The part of react-markdown's tree this reads. */
export interface HastNode { type: string; tagName?: string; value?: string; properties?: Record<string, unknown>; children?: HastNode[] }

const BLANK = /^(|-|–|—|n\/a|na)$/i;
const NUMBER = /^(\()?([+\-−–])?\s*(\$)?\s*(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(%)?(\))?$/;

interface Parsed { value: number; percent: boolean; dollar: boolean; plain: boolean }

function parse(text: string): Parsed | null {
  const m = text.match(NUMBER);
  if (!m || (!!m[1] !== !!m[7])) return null;
  const [, bracket, sign, dollar, whole, fraction, percent] = m;
  const digits = whole.replace(/,/g, '');
  // A code with a leading zero (00123) is a name, not an amount.
  if (digits.length > 1 && digits.startsWith('0') && !fraction) return null;
  const number = Number(digits + (fraction ?? ''));
  if (!Number.isFinite(number)) return null;
  const negative = !!bracket || (!!sign && sign !== '+');
  return {value: negative ? -number : number, percent: !!percent, dollar: !!dollar,
    plain: !bracket && !sign && !dollar && !percent && !fraction && !whole.includes(',')};
}

function cellText(node: HastNode, ids: Set<string>): string {
  if (node.type === 'text') return node.value ?? '';
  if (node.tagName === 'a') {
    const href = String(node.properties?.href ?? '');
    // An evidence chip is where the cell's value came from, not part of the value.
    if (href.startsWith('#evidence-')) { ids.add(href.slice('#evidence-'.length)); return ''; }
    if (href.startsWith('#visual-')) return '';
  }
  if (node.tagName === 'br') return ' ';
  return (node.children ?? []).map(child => cellText(child, ids)).join('');
}

function rowsOf(node: HastNode, ids: Set<string>): string[][] {
  if (node.tagName === 'tr') {
    return [(node.children ?? []).filter(c => c.tagName === 'td' || c.tagName === 'th').map(c => cellText(c, ids).replace(/\s+/g, ' ').trim())];
  }
  return (node.children ?? []).flatMap(child => rowsOf(child, ids));
}

/** The answer's table as a table visual, or null when it has no rows to copy. */
export function tableVisual(table: HastNode): Visual | null {
  const ids = new Set<string>();
  const head = (table.children ?? []).filter(c => c.tagName === 'thead').flatMap(c => rowsOf(c, ids))[0] ?? [];
  const body = (table.children ?? []).filter(c => c.tagName === 'tbody').flatMap(c => rowsOf(c, ids));
  if (!head.length || !body.length) return null;
  const width = head.length;
  const texts = body.map(row => Array.from({length: width}, (_, j) => row[j] ?? ''));
  const columns: Visual['columns'] = [];
  const typed: (string | number | null)[][] = texts.map(() => []);
  for (let j = 0; j < width; j++) {
    const cells = texts.map(row => row[j]);
    const filled = cells.filter(t => !BLANK.test(t));
    const parsed = filled.map(parse);
    const numbers = filled.length > 0 && parsed.every((p): p is Parsed => p !== null);
    // Years and other bare whole numbers in the first column are labels (2025, not 2,025).
    const names = numbers && parsed.every(p => p!.plain && Number.isInteger(p!.value)) && (j === 0 || parsed.every(p => p!.value >= 1900 && p!.value <= 2100));
    const percent = numbers && parsed.every(p => p!.percent);
    const mixed = numbers && !percent && parsed.some(p => p!.percent);
    const dollar = numbers && parsed.every(p => p!.dollar);
    const type = !numbers || names || mixed ? 'string' : percent ? 'percent' : dollar ? 'currency' : parsed.every(p => Number.isInteger(p!.value)) ? 'integer' : 'number';
    columns.push({key: `c${j + 1}`, label: head[j] || `Column ${j + 1}`, type, unit: type === 'percent' ? '%' : type === 'currency' ? 'USD' : null});
    cells.forEach((text, i) => typed[i].push(type === 'string' ? (text === '' ? null : text) : BLANK.test(text) ? null : parse(text)!.value));
  }
  return {id: 'Table', kind: 'table', title: '', subtitle: null, columns, rows: typed, texts, x: null, series: [],
    evidence_ids: [...ids], note: null, derived_by: 'model'};
}
