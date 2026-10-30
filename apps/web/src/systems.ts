import type {RunView, SystemInfo} from './types';

/** The systems the picker offers: every system this person can use, except Metronome (it sends emails, it is not a source). */
export function choosable(systems: SystemInfo[]): SystemInfo[] {
  return systems.filter(s => s.kind !== 'schedules');
}

function ordered(ids: string[], available: SystemInfo[]): string[] {
  const order = available.map(s => s.id);
  return Array.from(new Set(ids)).sort((a, b) => order.indexOf(a) - order.indexOf(b));
}

/** Tick or untick one system. From Auto, the first system ticked comes with the knowledge base (it keeps Gemini on the
 * right table and definitions; it can be unticked). Unticking the last one goes back to Auto. */
export function toggleSystem(chosen: string[] | null, id: string, available: SystemInfo[]): string[] | null {
  if (chosen === null) {
    const start = id !== 'knowledge' && available.some(s => s.id === 'knowledge') ? [id, 'knowledge'] : [id];
    return ordered(start, available);
  }
  const next = chosen.includes(id) ? chosen.filter(s => s !== id) : [...chosen, id];
  return next.length ? ordered(next, available) : null;
}

/** Attaching a file switches Attached files on. */
export function withFiles(chosen: string[] | null, available: SystemInfo[]): string[] | null {
  return chosen === null || chosen.includes('attachment') ? chosen : ordered([...chosen, 'attachment'], available);
}

/** What the picker's button says: Auto, the one system, or how many. */
export function choiceLabel(chosen: string[] | null, available: SystemInfo[]): string {
  if (chosen === null) return 'Auto';
  if (chosen.length === 1) return available.find(s => s.id === chosen[0])?.name ?? chosen[0];
  return `${chosen.length} systems`;
}

/** The names of the systems a run was allowed to use, for "Only: ..." on its card. */
export function onlyNames(ids: string[], available: SystemInfo[]): string[] {
  return ids.map(id => available.find(s => s.id === id)?.name ?? id.toUpperCase());
}

/** The conversation's choice as its latest question left it (a new conversation starts on Auto). */
export function conversationChoice(runs: RunView[]): string[] | null {
  const last = [...runs].reverse().find(r => r.kind === 'ask');
  return last?.systems ?? null;
}
