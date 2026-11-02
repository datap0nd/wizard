/** Settings → Source order (WIZARD_SOURCE_ORDER): the company's order of the data sources, as the stored compact JSON
 * line and the moves the section offers. Levels are runs of rows where each row after the first says `same` (on the
 * same level as the one above). The server validates what is saved (source_order.py). */

export interface OrderEntry {
  id: string;
  /** On the same level as the source above it. */
  same?: boolean;
  /** What it is for, plain text, at most 200 characters. */
  use?: string;
  /** Used only when the person asks for it: Auto leaves it out. */
  when_asked?: boolean;
}

export interface OrderSource { id: string; name: string }

/** Names for sources the order names but this PC does not have. */
const KNOWN: Record<string, string> = {dashboards: 'Dashboards', postgresql: 'Database', asap: 'ASAP', gscm: 'GSCM',
  nerp: 'NERP', bdp: 'Big Data Portal'};

export function sourceName(id: string, sources: OrderSource[]): string {
  return sources.find(s => s.id === id)?.name ?? KNOWN[id] ?? id.toUpperCase();
}

/** The stored line as entries; the default when it is empty or unreadable. */
export function parseOrder(value: string | null | undefined, defaults: OrderEntry[]): OrderEntry[] {
  if (!value || !value.trim()) return defaults;
  try {
    const raw: unknown = JSON.parse(value);
    if (Array.isArray(raw)) {
      return raw.filter((e): e is OrderEntry => !!e && typeof e === 'object' && typeof (e as OrderEntry).id === 'string')
        .map((e, i) => ({id: e.id, same: i > 0 && e.same === true, use: typeof e.use === 'string' ? e.use : '',
          when_asked: e.when_asked === true}));
    }
  } catch { /* shown as the default; Save writes a valid line */ }
  return defaults;
}

/** The order as the section shows it: every source it names (also one this PC does not have, kept for the other PCs),
 * then this PC's sources it does not name, each on a level of its own (a portal set up later comes last). */
export function withSources(entries: OrderEntry[], sources: OrderSource[]): OrderEntry[] {
  const named = new Set(entries.map(e => e.id));
  return [...entries, ...sources.filter(s => !named.has(s.id)).map(s => ({id: s.id}))];
}

function levels(entries: OrderEntry[]): OrderEntry[][] {
  const out: OrderEntry[][] = [];
  entries.forEach((entry, i) => { if (i > 0 && entry.same) out[out.length - 1].push(entry); else out.push([entry]); });
  return out;
}

function flatten(grouped: OrderEntry[][]): OrderEntry[] {
  return grouped.filter(level => level.length).flatMap(level => level.map((entry, j) => ({...entry, same: j > 0})));
}

/** Each row's level, from 1. */
export function levelNumbers(entries: OrderEntry[]): number[] {
  return levels(entries).flatMap((level, k) => level.map(() => k + 1));
}

/** Move one row up (-1) or down (1). A row that shares its level leaves it and takes a level of its own just above or
 * below; a row alone on its level swaps places with the whole level next to it. */
export function move(entries: OrderEntry[], index: number, direction: -1 | 1): OrderEntry[] {
  const grouped = levels(entries);
  let k = 0;
  let seen = 0;
  while (k < grouped.length && index >= seen + grouped[k].length) { seen += grouped[k].length; k += 1; }
  const level = grouped[k];
  if (!level) return entries;
  const row = level[index - seen];
  if (level.length > 1) {
    const rest = level.filter(e => e !== row);
    grouped.splice(k, 1, ...(direction < 0 ? [[row], rest] : [rest, [row]]));
  } else {
    const other = k + direction;
    if (other < 0 || other >= grouped.length) return entries;
    [grouped[k], grouped[other]] = [grouped[other], grouped[k]];
  }
  return flatten(grouped);
}

export function canMove(entries: OrderEntry[], index: number, direction: -1 | 1): boolean {
  return serialise(move(entries, index, direction)) !== serialise(entries);
}

/** Change one row (its level, its line, only when asked); the first row is never on the level above. */
export function update(entries: OrderEntry[], index: number, change: Partial<OrderEntry>): OrderEntry[] {
  return entries.map((entry, i) => (i === index ? {...entry, ...change} : entry)).map((e, i) => (i === 0 ? {...e, same: false} : e));
}

/** Take one source out of the order; the others keep their levels (its level-mate stays on that level). */
export function remove(entries: OrderEntry[], index: number): OrderEntry[] {
  const gone = entries[index];
  return flatten(levels(entries).map(level => level.filter(e => e !== gone)));
}

/** A "use it for" line as typed: one line, no < or > (it is plain text). */
export function cleanUse(text: string, max: number): string {
  return text.replace(/[\r\n<>]/g, ' ').slice(0, max);
}

/** The stored line: compact JSON with only what differs from a plain entry. */
export function serialise(entries: OrderEntry[]): string {
  return JSON.stringify(entries.map((e, i) => ({id: e.id, ...(i > 0 && e.same ? {same: true} : {}),
    ...(e.use && e.use.trim() ? {use: e.use} : {}), ...(e.when_asked ? {when_asked: true} : {})})));
}
