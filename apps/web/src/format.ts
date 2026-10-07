export function formatValue(value: unknown, type?: string, unit?: string | null): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value !== 'number') return String(value);
  if (type === 'percent') return `${value.toLocaleString(undefined, {maximumFractionDigits: 1})}${unit && unit !== '%' ? ` ${unit}` : '%'}`;
  if (type === 'currency') {
    const abs = Math.abs(value);
    const body = abs >= 1e6 ? `${(value / 1e6).toLocaleString(undefined, {maximumFractionDigits: 2})}M` : value.toLocaleString(undefined, {maximumFractionDigits: 0});
    return unit && unit !== 'USD' ? `${body} ${unit}` : `$${body}`;
  }
  const digits = Number.isInteger(value) ? 0 : Math.abs(value) >= 100 ? 1 : 2;
  const text = value.toLocaleString(undefined, {maximumFractionDigits: digits});
  return unit && !['units', 'devices', 'transfers'].includes(unit) ? `${text} ${unit}` : text;
}

export function compact(value: number): string {
  return new Intl.NumberFormat(undefined, {notation: 'compact', maximumFractionDigits: 1}).format(value);
}

export function formatDate(iso: string | null | undefined, withTime = false): string {
  if (!iso) return 'unknown';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return 'unknown';
  return new Intl.DateTimeFormat(undefined, withTime ? {dateStyle: 'medium', timeStyle: 'short'} : {dateStyle: 'medium'}).format(date);
}

export function duration(start: string, end: string | null): string | null {
  if (!end) return null;
  const ms = new Date(end).getTime() - new Date(start).getTime();
  return Number.isFinite(ms) && ms >= 0 ? spoken(ms) : null;
}

/** 850 ms · 12.4 s · 4 min 12 s */
export function spoken(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const seconds = Math.round(ms / 1000);
  return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
}

/** Elapsed time as a clock: 0:07, 4:12, 1:02:09. */
export function clock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const [h, m, s] = [Math.floor(total / 3600), Math.floor(total / 60) % 60, total % 60];
  const pad = (n: number) => String(n).padStart(2, '0');
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

export const DATA_MODE_TEXT: Record<string, {label: string; hint: string}> = {
  SYNTHETIC: {label: 'Synthetic data', hint: 'Invented test data. Not corporate figures.'},
  DATED_APPROVED_SNAPSHOT: {label: 'Approved snapshot', hint: 'An approved, dated copy of source data.'},
  LIVE_VERIFIED: {label: 'Live · verified retrieval', hint: 'Retrieved live; retrieval parity-checked against the source. Interpretation is reviewed separately.'},
  LIVE: {label: 'Live', hint: 'Read live from the company PostgreSQL database with a query Gemini wrote. Open the sources to see the query.'},
  USER_PROVIDED: {label: 'Your file', hint: 'Figures from a file attached to the question. Not checked against a source system.'},
};

export const CHECK_TEXT: Record<string, {label: string; hint: string}> = {
  CHECKED: {label: 'Checked', hint: 'Figures were recomputed from the cited evidence and matched.'},
  NOT_CHECKED: {label: 'Not checked', hint: 'Figures have not been independently recomputed. Use Check my data.'},
  DISCREPANCY: {label: 'Discrepancy found', hint: 'A recomputation did not match. See the check details.'},
};
