import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {api} from '@/api';
import {PortalMaps, mapSummary} from './PortalMaps';
import type {PortalMapStatus, PortalStatus} from '@/types';

const EMPTY: PortalMapStatus = {
  system: 'gscm', updated: null, has_overview: false, topics: 0, reports: 0, reports_todo: 0, reports_mapped: 0,
  reports_partial: 0, reports_failed: 0, reports_skipped: 0, published: null, source: 'none', can_publish: true,
};
const STATUS: PortalStatus = {
  browser: 'Google Chrome', signing_in: false, running: false, last_sign_in: null,
  portals: [{id: 'gscm', name: 'GSCM', host: 'gscm.example.com'}], maps: {gscm: EMPTY}, mapping: null,
};

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('Portal maps', () => {
  it('says what the map holds in words', () => {
    expect(mapSummary(EMPTY)).toBe('Not mapped yet.');
    expect(mapSummary({...EMPTY, has_overview: true, topics: 3, reports: 10, reports_mapped: 6, reports_partial: 1, reports_todo: 3}))
      .toBe('6 reports mapped, 1 partial, 3 to do · 3 technical notes and shortcuts');
    expect(mapSummary({...EMPTY, reports: 1, reports_mapped: 1, source: 'knowledge_base'})).toBe('1 report mapped · from the knowledge base');
  });

  it('starts mapping a portal and shows the round under way with a Stop button', async () => {
    const running: PortalStatus = {...STATUS, maps: {gscm: {...EMPTY, reports: 40, reports_todo: 40, has_overview: true, source: 'this_pc'}},
      mapping: {system: 'gscm', conversation_id: 'c1', started_at: '2026-10-30T10:00:00', round: 2, run_id: 'r2', state: 'running',
                message: 'Round 2 is running.'}};
    const start = vi.spyOn(api, 'mapPortal').mockResolvedValue({map: EMPTY, mapping: null});
    vi.spyOn(api, 'portals').mockResolvedValue(running);
    const onChange = vi.fn();
    render(<PortalMaps status={STATUS} onChange={onChange} />);
    expect(screen.getByTestId('portal-map-summary-gscm').textContent).toBe('Not mapped yet.');
    expect(screen.queryByTestId('portal-map-publish-gscm')).toBeNull();
    fireEvent.click(screen.getByTestId('portal-map-start-gscm'));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(running));
    expect(start).toHaveBeenCalledWith('gscm');
    cleanup();
    render(<PortalMaps status={running} onChange={onChange} />);
    expect(screen.getByTestId('portal-mapping-gscm').textContent).toContain('Mapping now, round 2.');
    expect(screen.getByRole('link', {name: 'Watch it'}).getAttribute('href')).toBe('?c=c1');
    expect(screen.getByTestId('portal-map-stop-gscm')).toBeTruthy();
    expect(screen.queryByTestId('portal-map-start-gscm')).toBeNull();
  });

  it('offers Continue mapping and Publish now for a map of this PC, and says when publishing failed', () => {
    const map: PortalMapStatus = {...EMPTY, reports: 5, reports_mapped: 2, reports_todo: 3, source: 'this_pc',
      published: {at: '2026-10-30T10:00:00', outcome: 'failed', message: 'GitHub refused the write token (HTTP 401).', commit: null}};
    render(<PortalMaps status={{...STATUS, maps: {gscm: map}}} onChange={vi.fn()} />);
    expect(screen.getByTestId('portal-map-start-gscm').textContent).toContain('Continue mapping');
    expect(screen.getByTestId('portal-map-publish-gscm')).toBeTruthy();
    expect(screen.getByText('Publishing failed: GitHub refused the write token (HTTP 401).')).toBeTruthy();
  });
});
