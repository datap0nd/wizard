import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {api} from '@/api';
import {RecurringPanel, state} from './RecurringPanel';
import {RecurringCard} from './RecurringCard';
import type {RecurringItem, Schedule} from '@/types';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const BRIEF: Schedule = {
  id: 'sch_1', label: 'R1', run_id: 'run_1', status: 'proposed', kind: 'brief', title: 'Weekly sell-out by market',
  brief: {title: 'Weekly sell-out by market', intro: null, period_sql: null, sections: [
    {kind: 'numbers', title: null, subtitle: null, sql: 'SELECT units, units_prev FROM s', chart: null},
    {kind: 'chart', title: 'Units by market', subtitle: null, sql: 'SELECT market, units FROM m', chart: 'bar'}]},
  database: null, recipients: ['rafael@corp.test'], frequency: 'weekly', time: '08:00', days: ['monday'], day_of_month: null,
  file_format: 'xlsx', subject: null, schedule_text: 'Every Monday at 08:00 (Dubai time)', evidence_ids: ['E2', 'E3'],
  metronome_user: 'Wizard', requested_by: {name: 'Rafael'}, created_at: '2026-10-23T09:00:00Z',
  preview: {period: 'Week 43', read_at: '2026-10-23T09:00:00Z', rows: [1, 3]}, flow: null, error: null,
};

const ITEM: RecurringItem = {
  ...BRIEF, status: 'created',
  flow: {id: 41, name: 'Wizard · Weekly sell-out by market · for Rafael · a1', owner: 'Wizard', enabled: true,
    next_run_at: '2026-10-26T04:00:00Z', url: 'http://metronome.corp:8000/'},
  metronome: {missing: false, enabled: true, owner: 'Wizard', next_run_at: '2026-11-02T04:00:00Z',
    last_run_at: '2026-10-26T04:01:10Z', last_status: 'succeeded', last_error: null,
    runs: [{id: 901, status: 'succeeded', trigger: 'schedule', at: '2026-10-26T04:01:10Z', error: null, email: 'submitted'},
      {id: 900, status: 'failed', trigger: 'schedule', at: '2026-10-19T04:01:10Z', error: 'view renamed', email: null}]},
};

describe('the recurring brief card', () => {
  it('shows the email it will send and every query behind it', async () => {
    const preview = vi.spyOn(api, 'schedulePreview').mockResolvedValue({html: '<!DOCTYPE html><p>Weekly sell-out</p>'});
    render(<RecurringCard schedule={BRIEF} onCreate={vi.fn()} onDismiss={vi.fn()} />);
    const frame = await screen.findByTestId('email-preview');
    expect(preview).toHaveBeenCalledWith('sch_1');
    expect(frame.getAttribute('srcdoc')).toContain('Weekly sell-out');
    expect(frame.getAttribute('sandbox')).toBe('allow-same-origin');
    const queries = screen.getByTestId('recurring-sql');
    expect(queries.querySelectorAll('li')).toHaveLength(2);
    expect(queries.textContent).toContain('Units by market · bar chart');
    expect(screen.getByText(/The 2 queries it runs each time \(test run cited as E2, E3\)/)).toBeTruthy();
  });

  it('says why the preview is missing', async () => {
    vi.spyOn(api, 'schedulePreview').mockRejectedValue(new Error('Recurring brief not found.'));
    render(<RecurringCard schedule={BRIEF} onCreate={vi.fn()} onDismiss={vi.fn()} />);
    expect((await screen.findByRole('alert')).textContent).toContain('Recurring brief not found.');
  });
});

describe('the Recurring tab', () => {
  it('reads each brief\'s state from Metronome', () => {
    expect(state(ITEM).label).toMatch(/^Sent /);
    expect(state({...ITEM, metronome: {...ITEM.metronome!, enabled: false}}).label).toBe('Off in Metronome');
    expect(state({...ITEM, metronome: {...ITEM.metronome!, last_status: 'failed'}}).label).toBe('Last run failed');
    expect(state({...ITEM, metronome: {missing: true}}).label).toBe('Not in Metronome');
    expect(state({...ITEM, metronome: null}).label).toBe('Scheduled');
  });

  it('lists the briefs, opens one, and deletes it only after confirming', async () => {
    const listed = vi.spyOn(api, 'recurringList')
      .mockResolvedValueOnce({items: [ITEM], sync: {ok: true, message: null}})
      .mockResolvedValueOnce({items: [], sync: {ok: true, message: null}});
    vi.spyOn(api, 'schedulePreview').mockResolvedValue({html: '<p>x</p>'});
    const removed = vi.spyOn(api, 'deleteRecurring').mockResolvedValue({deleted: true, flow_id: 41, missing: false});
    render(<RecurringPanel />);
    fireEvent.click(await screen.findByTestId('recurring-item'));
    const dialog = await screen.findByTestId('recurring-dialog');
    expect(dialog.textContent).toContain('rafael@corp.test');
    expect(screen.getByTestId('recurring-runs').textContent).toContain('Failed');
    fireEvent.click(screen.getByTestId('recurring-delete'));
    expect(removed).not.toHaveBeenCalled();
    expect(dialog.textContent).toContain('Metronome turns the Flow off and keeps its run history.');
    fireEvent.click(screen.getByTestId('recurring-delete-confirm'));
    await waitFor(() => expect(removed).toHaveBeenCalledWith('sch_1'));
    await waitFor(() => expect(listed).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/No recurring briefs yet/)).toBeTruthy();
  });

  it('still lists what Wizard knows when Metronome is down, and shows a refused delete', async () => {
    vi.spyOn(api, 'recurringList').mockResolvedValue({items: [{...ITEM, metronome: null}],
      sync: {ok: false, message: 'Metronome is not reachable at http://metronome.corp:8000.'}});
    vi.spyOn(api, 'deleteRecurring').mockRejectedValue(new Error('Metronome refused to turn the Flow off (403).'));
    const preview = vi.spyOn(api, 'schedulePreview');
    render(<RecurringPanel />);
    expect((await screen.findByRole('status')).textContent).toContain('Metronome could not be reached');
    fireEvent.click(screen.getByTestId('recurring-item'));
    fireEvent.click(await screen.findByTestId('recurring-delete'));
    fireEvent.click(screen.getByTestId('recurring-delete-confirm'));
    expect((await screen.findByRole('alert')).textContent).toContain('refused to turn the Flow off');
    expect(screen.getByTestId('recurring-delete')).toBeTruthy();
    expect(preview).not.toHaveBeenCalled(); // the email loads only when someone opens it
  });
});
