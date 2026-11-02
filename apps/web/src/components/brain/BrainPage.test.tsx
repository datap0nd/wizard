import {afterEach, describe, expect, it} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {BrainPage} from './BrainPage';
import type {BrainMap, BrainNote, BrainSnapshot} from '@/brain';

const note = (id: string, title: string, area: string): BrainNote =>
  ({id, title, area, type: null, stage: 'DRAFT', summary: '', tags: [], terms: null, updated: null});

// Invented content: a portal with five mapped reports, three of which name a note of the knowledge base.
const MAP: BrainMap = {
  content: 'examples', knowledge_synced_at: null, pg_name: 'AI Team Database',
  areas: [{id: 'metrics', name: 'Metrics', description: '', notes: 2}],
  notes: [note('sell-in', 'Sell-in', 'metrics'), note('market-share', 'Market share', 'metrics')],
  links: [{source: 'sell-in', target: 'market-share', kind: 'related'}],
  systems: [{id: 'asap', name: 'ASAP', kind: 'portal', reports: null, documented_by: [],
    mapped: {mapped: 5, found: 6, updated: null, linked: 3, unlinked: 2}}],
  portal_reports: [
    {system: 'asap', id: 'si', name: 'Weekly sell-in by account', path: ['Sales'], status: 'mapped', definitions: ['sell-in'], use_for: ['weekly sell-in', 'SI by account']},
    {system: 'asap', id: 'ms', name: 'Share by vendor', path: ['Market'], status: 'mapped', definitions: ['market-share']},
    {system: 'asap', id: 'both', name: 'Sell-in and share', path: ['Market'], status: 'partial', definitions: ['sell-in', 'market-share']},
    {system: 'asap', id: 'open', name: 'Open orders', path: ['Orders'], status: 'mapped', definitions: []},
    {system: 'asap', id: 'ret', name: 'Returns', path: ['Orders'], status: 'mapped', definitions: []},
  ],
  counts: {notes: 2, areas: 1, links: 1, related: 1, glossary_terms: 0, datasets: 0, metrics: 2, signed: 0, expert_checked: 0, reports: 0,
    mapped_reports: 5, linked_reports: 3, report_links: 4, systems: 1},
};
const SNAPSHOT: BrainSnapshot = {format: 1, published_at: '2026-11-02T09:00:00', map: MAP, live: null};

afterEach(cleanup);

function open(name: string) {
  fireEvent.change(screen.getByTestId('brain-search'), {target: {value: name}});
  fireEvent.keyDown(screen.getByTestId('brain-search'), {key: 'Enter'});
}

describe('the Brain page and the reports mapped in a portal', () => {
  it('says how many mapped reports are linked to notes, and counts the links on their own layer', () => {
    render(<BrainPage snapshot={SNAPSHOT} />);
    const asap = document.querySelector('[data-testid=brain-system][data-system=asap]')!;
    expect(asap.textContent).toContain('5 mapped, 3 linked to notes');
    const layer = document.querySelector('[data-testid=brain-layer][data-layer=definitions]')!;
    expect((layer as HTMLInputElement).checked).toBe(true);
    expect(layer.closest('label')!.textContent).toContain('Reports to their notes');
    expect(layer.closest('label')!.textContent).toContain('4');
  });

  it('shows a report\'s notes and what it is used for, or that it is not linked to a note yet', () => {
    render(<BrainPage snapshot={SNAPSHOT} />);
    open('Weekly sell-in');
    expect(screen.getByTestId('brain-report-use').textContent).toBe('Used for weekly sell-in · SI by account');
    expect(screen.getByTestId('brain-report-notes').textContent).toBe('Defined in Sell-in');
    expect(screen.getByTestId('brain-neighbours').textContent).toContain('definitions');
    open('Open orders');
    expect(screen.getByTestId('brain-report-notes').textContent).toBe('Not linked to a note yet');
    expect(screen.queryByTestId('brain-report-use')).toBeNull();
  });
});
