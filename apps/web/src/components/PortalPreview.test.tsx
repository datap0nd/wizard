import {afterEach, describe, expect, it} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {PortalPreview, targetBox} from './PortalPreview';
import {TrailView} from './TrailView';
import {applyEvent, emptyRun, sourceName} from '@/runState';
import {moduleOf, stageModel} from '@/stage';
import type {RunEvent, RunView} from '@/types';

afterEach(cleanup);

let seq = 0;
const ev = (type: string, payload: Record<string, unknown>): RunEvent => ({seq: ++seq, type, ts: '2026-10-20T09:00:00Z', payload});
const frame = (callId: string, id: string, phase: 'before' | 'after', action: string, target: Record<string, number> | null = null) =>
  ev('browser_frame', {call_id: callId, frame: id, portal: 'gscm', phase, action, url: 'https://gscm.corp.example/folder/sell-in?x=1',
    title: 'Sell-in reports', target, viewport: {width: 1280, height: 800}});

function exploring(): RunView {
  seq = 0;
  let run = applyEvent(emptyRun('run_1', 'cnv_1', 'Sell-in on GSCM'), ev('run_started', {runtime: 'code-assist', runtime_label: 'x', model: 'm'}));
  run = applyEvent(run, ev('tool_started', {call_id: 'c1', name: 'wizard_portal_open', label: 'Opened the GSCM portal', category: 'source', arguments: {portal: 'gscm'}}));
  run = applyEvent(run, frame('c1', 'f1', 'after', 'Opened GSCM'));
  run = applyEvent(run, ev('tool_finished', {call_id: 'c1', name: 'wizard_portal_open', ok: true, duration_ms: 900, summary: 'Reports home · 7 controls'}));
  run = applyEvent(run, ev('tool_started', {call_id: 'c2', name: 'wizard_portal_click', label: 'Clicked on GSCM', category: 'source', arguments: {portal: 'gscm', element: 1}}));
  run = applyEvent(run, frame('c2', 'f2', 'before', 'Clicking “Sell-in reports”', {x: 128, y: 80, width: 256, height: 40}));
  return run;
}

describe('the click preview', () => {
  it('collects each portal picture on its step and on the run', () => {
    const run = exploring();
    expect(run.frames.map(f => f.frame)).toEqual(['f1', 'f2']);
    expect(run.timeline.find(t => t.key === 'c2')?.frames?.[0].action).toBe('Clicking “Sell-in reports”');
    expect(moduleOf('wizard_portal_click', {portal: 'gscm'})).toBe('gscm');
    const model = stageModel(run, [{id: 'knowledge', name: 'Knowledge base', kind: 'knowledge'}]);
    expect(model.modules.find(m => m.id === 'gscm')).toMatchObject({kind: 'portal', name: 'GSCM'});
    expect(sourceName({system: 'portal', system_name: 'GSCM (portal page)'})).toBe('GSCM');
  });

  it('shows the page live with the target outlined where Wizard is about to click', () => {
    render(<PortalPreview run={exploring()} systems={[{id: 'gscm', name: 'GSCM', kind: 'reports', portal: true}]} />);
    expect(screen.getByTestId('portal-live')).toBeTruthy();
    expect(screen.getByTestId('portal-action').textContent).toContain('Clicking “Sell-in reports”');
    expect(screen.getByTestId('portal-address').textContent).toBe('gscm.corp.example/folder/sell-in?x=1');
    expect((screen.getByTestId('portal-picture') as HTMLImageElement).getAttribute('src')).toBe('/api/v1/runs/run_1/frames/f2');
    const target = screen.getByTestId('portal-target');
    expect([target.style.left, target.style.top, target.style.width, target.style.height]).toEqual(['10%', '10%', '20%', '5%']);
  });

  it('lets the person step back through the pictures, then return to live', () => {
    render(<PortalPreview run={exploring()} />);
    fireEvent.click(screen.getByRole('button', {name: 'Picture 1: Opened GSCM'}));
    expect(screen.getByTestId('portal-action').textContent).toBe('Opened GSCM');
    expect(screen.queryByTestId('portal-target')).toBeNull();
    fireEvent.click(screen.getByRole('button', {name: 'Back to live'}));
    expect(screen.getByTestId('portal-action').textContent).toContain('Clicking');
  });

  it('folds into a line once the answer is in, and opens again', () => {
    const done = {...exploring(), status: 'succeeded' as const};
    render(<PortalPreview run={done} />);
    fireEvent.click(screen.getByTestId('portal-preview-folded'));
    expect(screen.getByTestId('portal-preview')).toBeTruthy();
    expect(screen.queryByTestId('portal-live')).toBeNull();
  });

  it('places the outline proportionally and ignores a frame without a target', () => {
    expect(targetBox({callId: 'c', frame: 'f', portal: 'p', phase: 'after', action: '', url: '', title: '', target: null,
      viewport: {width: 1280, height: 800}})).toBeNull();
  });
});

describe('the navigation trail', () => {
  it('shows search results as folder paths, a report with its prompts, and the first rows', () => {
    const {rerender} = render(<TrailView trail={{kind: 'search', results: [{name: 'Sell-in by model', folder_path: ['GSCM', 'Sell-in'], row_access: 'ROWS', report_id: 'r1'}]}} />);
    expect(screen.getByTestId('trail-crumbs').textContent).toBe('GSCMSell-inSell-in by model');
    rerender(<TrailView trail={{kind: 'report', name: 'Sell-in by model', folder_path: ['GSCM'], row_access: 'ROWS',
      open_url: 'https://gscm.corp.example/r/r1', prompts: ['Market', 'Month'], measures: []}} />);
    expect(screen.getByText('Market')).toBeTruthy();
    expect(screen.getByTestId('trail-open').getAttribute('href')).toBe('https://gscm.corp.example/r/r1');
    rerender(<TrailView trail={{kind: 'rows', name: 'Sell-in', columns: ['Market', 'Units'], rows: [['SA', 1234], ['AE', null]], total_rows: 40, filters: []}} />);
    expect(screen.getAllByRole('row')).toHaveLength(3);
    expect(screen.getByText('1,234')).toBeTruthy();
    expect(screen.getByText('first 2 of 40 rows')).toBeTruthy();
  });
});
