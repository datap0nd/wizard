/** /roadmap: what Wizard does today and what comes next. Edit this file to change the page (the owner, 28 Oct 2026:
 * a deadline on a Friday, from 30 October, one week at a time; PowerPoint slides take two). Each step is due on the
 * Friday its last week ends, so a longer step moves the ones after it. Dates are calendar days on the viewer's PC. */

export type Icon = 'ask' | 'database' | 'portal' | 'knowledge' | 'files' | 'brief' | 'access' | 'evidence' | 'desktop'
  | 'slides' | 'growth' | 'metrics' | 'strategy';

export interface Capability { icon: Icon; title: string; body: string }

/** One thing a milestone brings, with a system's logo (SystemLogo id) or an icon. */
export interface Item { name: string; detail?: string; logo?: string; icon?: Icon }

export interface Milestone {
  id: string;
  /** How many weeks it takes (1 when not given); it is due on the last one's Friday. */
  weeks?: number;
  icon: Icon;
  /** A product's logo (SystemLogo id) shown instead of the icon. */
  logo?: string;
  title: string;
  body: string;
  items: Item[];
  done?: boolean;
}

/** What Wizard does today (README "What runs today"). */
export const CAPABILITIES: Capability[] = [
  {icon: 'ask', title: 'Answers business questions', body: 'Ask in plain words. Gemini picks the sources, compares, and explains, with the evidence behind every number.'},
  {icon: 'database', title: 'Queries the company database', body: 'Writes its own read-only SQL on the AI Team Database, guided by the notes on each dataset.'},
  {icon: 'portal', title: 'Reads the portals live', body: 'ASAP, GSCM and the Big Data Portal (catalog and Superset), in your own signed-in Wizard browser.'},
  {icon: 'knowledge', title: 'Knows the business', body: 'A company knowledge base of metrics, datasets and platforms, each note marked draft, expert-checked or signed.'},
  {icon: 'files', title: 'Works with your files', body: 'Reads Excel, PowerPoint, Word, email and CSV, totals every row of a sheet, and edits a copy of a workbook for you.'},
  {icon: 'brief', title: 'Recurring briefs', body: 'Turns an analysis into a newsletter email that Metronome sends on a schedule.'},
  {icon: 'access', title: 'Access requests', body: 'Prepares a Big Data Portal access request and fills in your usual answers; you check it and submit it.'},
  {icon: 'evidence', title: 'Shows its work', body: 'Every step Wizard took, the sources it cites, and Check my data to recompute an answer.'},
  {icon: 'desktop', title: 'One click away', body: 'The Ask Wizard tab at the top of the screen, Ctrl+Alt+W from any app, files dropped on it; it updates itself.'},
];

/** The systems Wizard reads today, shown as logos under the capabilities. */
export const SYSTEMS_TODAY: {id: string; name: string}[] = [
  {id: 'postgresql', name: 'AI Team Database'}, {id: 'knowledge', name: 'Knowledge base'}, {id: 'asap', name: 'ASAP'},
  {id: 'gscm', name: 'GSCM'}, {id: 'bdp', name: 'Big Data Portal'}, {id: 'metronome', name: 'Metronome'},
  {id: 'attachment', name: 'Your files'},
];

/** The first step's Friday. */
export const FIRST_FRIDAY = '2026-10-30';

/** What comes next, in order, one week at a time from FIRST_FRIDAY. */
export const MILESTONES: Milestone[] = [
  {
    id: 'portals', icon: 'portal', title: 'More portals, read live',
    body: 'Two more company portals join ASAP, GSCM and the Big Data Portal. Gemini reads them in your own signed-in Wizard browser, under the same read-only rules.',
    items: [{name: 'SC+ Global Dashboard', logo: 'scplus'}, {name: 'NERP BI Portal', logo: 'nerp'}],
  },
  {
    id: 'slides', weeks: 2, icon: 'slides', logo: 'powerpoint', title: 'PowerPoint slides from an answer',
    body: 'Wizard turns its analysis into a slide deck: the story, the charts and the numbers, ready to present.',
    items: [{name: 'A deck from any answer', icon: 'slides'}, {name: 'Charts and tables with their sources', icon: 'metrics'},
      {name: 'Opens and edits in PowerPoint', logo: 'powerpoint'}],
  },
  {
    id: 'knowledge', icon: 'growth', title: 'A richer knowledge base',
    body: 'Meetings with the heads of business and the main PIC of each business area, to compile the most relevant knowledge, so answers go deeper.',
    items: [{name: 'Metrics', detail: 'definitions and how each is calculated', icon: 'metrics'},
      {name: 'Business presentations', detail: 'digested into notes', icon: 'slides'},
      {name: 'Strategy', detail: 'priorities, plans and the reasoning behind them', icon: 'strategy'}],
  },
];

const DAY_MS = 86_400_000;

/** A yyyy-mm-dd date as midnight on the viewer's calendar (not UTC, which could move it a day). */
export function calendarDay(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d);
}

/** Whole calendar days from `now`'s date to `iso` (negative once it has passed). */
export function daysUntil(iso: string, now: Date): number {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((calendarDay(iso).getTime() - today.getTime()) / DAY_MS);
}

/** "Fri 30 Oct". */
export function dayLabel(date: Date): string {
  return new Intl.DateTimeFormat('en-GB', {weekday: 'short', day: 'numeric', month: 'short'}).format(date);
}

export type MilestoneState = 'done' | 'next' | 'planned' | 'late';

export interface PlacedMilestone extends Milestone {
  /** The Friday it is due, yyyy-mm-dd. */
  due: string;
  /** Its weeks, counted from the first Friday's week: "Week 1", "Weeks 2–3". */
  week: string;
  days: number;
  state: MilestoneState;
  when: string;
}

function isoDay(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

/** Each milestone's weeks, Friday, countdown and state on `now`'s date. The first one not done and not past is "next". */
export function placeMilestones(milestones: Milestone[], now: Date, first = FIRST_FRIDAY): PlacedMilestone[] {
  let nextGiven = false;
  let ended = 0;
  const start = calendarDay(first);
  return milestones.map(m => {
    const from = ended + 1;
    ended += Math.max(1, m.weeks ?? 1);
    const due = isoDay(new Date(start.getFullYear(), start.getMonth(), start.getDate() + 7 * (ended - 1)));
    const week = ended === from ? `Week ${from}` : `Weeks ${from}–${ended}`;
    const days = daysUntil(due, now);
    let state: MilestoneState = m.done ? 'done' : days < 0 ? 'late' : 'planned';
    if (state === 'planned' && !nextGiven) { state = 'next'; nextGiven = true; }
    const when = state === 'done' ? 'Delivered' : days < 0 ? 'Due date passed' : days === 0 ? 'Due today'
      : days === 1 ? 'Due tomorrow' : `In ${days} days`;
    return {...m, due, week, days, state, when};
  });
}
