// Cases: analyses people shared from Wizard, as the Pages site shows them (services/api/wizard_api/site.py writes them).
// A case is one chat: each prompt and Wizard's answer with its charts, tables, data labels and the names of its sources,
// never their rows. This file holds the shapes and the pure helpers (the snake layout, the gallery's search), tested
// without a browser.
import type {CheckStatus, DataMode, Visual} from './types';

export interface CaseSource {
  id: string; system?: string | null; system_name?: string | null; report_name?: string | null; data_mode?: DataMode | null;
  as_of?: string | null; total_rows?: number | null; truncated?: boolean | null;
}
/** One thing Wizard did for an answer: a tool call, how it ended and the evidence it gave. */
export interface CaseStep { label: string; summary: string; ok: boolean; evidence?: string | null }
export interface CaseTurn {
  n: number; kind: 'ask' | 'check'; prompt: string; asked_at: string; answer: string; data_mode: DataMode | null;
  check: {status: CheckStatus; summary: string | null}; visuals: Visual[]; sources: CaseSource[]; steps: CaseStep[];
  model?: string | null; run_id?: string;
}
export interface Case {
  format: number; id: string; title: string; takeaway: string; author: string | null; published_at: string;
  systems: string[]; data_modes: DataMode[]; turns: CaseTurn[];
}
/** A case as the gallery lists it (cases/cases.json). */
export interface CaseEntry {
  id: string; title: string; takeaway: string; author: string | null; published_at: string; updated_at: string;
  prompts: number; systems: string[]; data_modes: DataMode[]; first_prompt: string;
}
export interface CaseIndex { format: number; updated: string; cases: CaseEntry[] }

export interface SiteStatus {
  enabled: boolean; problem: string | null; repo: string | null; branch: string; url: string | null;
  pages: {brain: string | null; cases: string | null}; setup: string | null; allowed: boolean;
}
export interface PublishedCase { id: string; title: string; takeaway: string; runs: string[]; published_at: string; url: string | null }
export interface CasePreview { case: (Case & {problem?: undefined}) | {problem: string} | null; published: PublishedCase | null; site: SiteStatus }
export interface CasePublished { outcome: string; message: string; commit: string | null; url: string | null; published: PublishedCase | null }

export const CASE_ID = /^c[0-9a-f]{14}$/;

/** The snake (owner, 30 Oct 2026): the first prompt on the left with its answer to the right; a follow-up drops down on
 *  the side the answer ended and runs the other way (answer to the left of its prompt), and so on. `reversed`: the
 *  prompt is on the right. `drop`: the side of the arrow down to the next prompt. */
export function flowRows<T>(turns: T[]): {turn: T; reversed: boolean; drop: 'left' | 'right' | null}[] {
  return turns.map((turn, i) => ({turn, reversed: i % 2 === 1, drop: i === turns.length - 1 ? null : i % 2 === 1 ? 'left' : 'right'}));
}

/** The gallery's search and system filter: every word in the title, takeaway, first prompt or systems. */
export function filterCases(cases: CaseEntry[], query: string, system: string | null): CaseEntry[] {
  const words = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return cases.filter(c => {
    if (system && !c.systems.includes(system)) return false;
    const text = `${c.title} ${c.takeaway} ${c.first_prompt} ${c.systems.join(' ')} ${c.author ?? ''}`.toLocaleLowerCase();
    return words.every(w => text.includes(w));
  });
}

export function systemsOf(cases: CaseEntry[]): string[] {
  return [...new Set(cases.flatMap(c => c.systems))].sort((a, b) => a.localeCompare(b));
}

/** The turns a preview shows: those chosen in Share as case (all when none are), numbered again. */
export function chosenTurns(turns: CaseTurn[], runIds: string[] | null): CaseTurn[] {
  const kept = runIds && runIds.length ? turns.filter(t => t.run_id && runIds.includes(t.run_id)) : turns;
  return kept.map((t, i) => ({...t, n: i + 1}));
}
