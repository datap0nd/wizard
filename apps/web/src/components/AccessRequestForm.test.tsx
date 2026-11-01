import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {api} from '@/api';
import {AccessRequestForm} from './AccessRequestForm';
import type {AccessForm, PortalStatus} from '@/types';

const FORM: AccessForm = {
  system: 'bdp', page: '', seen: ['Cost centre'], default_page: 'https://catalog.example.com/', queue: [],
  fields: [
    {label: 'Purpose', value: '', kind: 'text', preset: true, hint: 'What you will use the data for.', example: 'Analytics'},
    {label: 'Purpose', section: 'DPA / DSA', value: '', kind: 'choice', preset: true, hint: 'The option, or its number.', example: '5'},
    {label: 'Subsidiary Name (Full Legal Name)', section: 'DPA / DSA', value: '', kind: 'choice', preset: true, hint: 'h', example: '(ABC) Example'},
    {label: 'Subsidiary Address', section: 'DPA / DSA', value: '', kind: 'text', preset: true, hint: 'h', example: ''},
    {label: 'Duration', value: '6 months'},
  ],
};
const QUEUED = (n: number, opened: string | null = null) => ({
  id: `AR-000000000${n}`, address: `https://catalog.example.com/t/${n}`, tables: [`t${n}`], answers: [], added: '2026-11-01T10:00:00', opened,
});
const OPEN: PortalStatus = {browser: 'Chrome', signing_in: true, window: 'access_request', running: true, last_sign_in: null, portals: [],
  access_request: {system: 'bdp', filled: [], missing: [], queued: {id: 'AR-0000000002', position: 2, total: 3, waiting: 1}}};

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('Access request form', () => {
  it('shows the predefined fields, the DPA / DSA box apart, and saves the answers the person sets', async () => {
    vi.spyOn(api, 'accessForm').mockResolvedValue(FORM);
    const save = vi.spyOn(api, 'saveAccessForm').mockImplementation(async (_s, body) => ({...FORM, fields: body.fields}));
    render(<AccessRequestForm system="bdp" name="Big Data Portal" />);
    const box = await screen.findByRole('group', {name: 'DPA / DSA'});
    expect(within(box).getAllByTestId('access-form-preset').map(row => row.textContent?.split('drop-down')[0].split('free text')[0]))
      .toEqual(['Purpose', 'Subsidiary Name (Full Legal Name)', 'Subsidiary Address']);
    expect(screen.getAllByTestId('access-form-preset')).toHaveLength(4);
    fireEvent.change(screen.getByLabelText('Purpose'), {target: {value: 'Will be used for analytics in the MENA region'}});
    fireEvent.change(screen.getByLabelText('DPA / DSA › Purpose'), {target: {value: '5'}});
    fireEvent.change(screen.getByLabelText('DPA / DSA › Subsidiary Name (Full Legal Name)'), {target: {value: '(ABC) Example Co.'}});
    fireEvent.click(screen.getByTestId('access-form-save'));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][1].fields).toEqual([
      {label: 'Purpose', value: 'Will be used for analytics in the MENA region', kind: 'text'},
      {label: 'Purpose', value: '5', section: 'DPA / DSA', kind: 'choice'},
      {label: 'Subsidiary Name (Full Legal Name)', value: '(ABC) Example Co.', section: 'DPA / DSA', kind: 'choice'},
      {label: 'Subsidiary Address', value: '', section: 'DPA / DSA', kind: 'text'},
      {label: 'Duration', value: '6 months'},
    ]);
    expect(await screen.findByText('Saved on this PC.')).toBeTruthy();
    expect(screen.getByTestId('access-form-seen').textContent).toContain('+ Cost centre');
  });

  it('lists the prepared requests, opens the next one and removes the opened ones', async () => {
    const queue = [QUEUED(1, '2026-11-01T10:05:00'), QUEUED(2), QUEUED(3)];
    const read = vi.spyOn(api, 'accessForm').mockResolvedValue({...FORM, queue});
    const open = vi.spyOn(api, 'openAccessRequest').mockResolvedValue(OPEN);
    const remove = vi.spyOn(api, 'removeQueuedRequests').mockResolvedValue({...FORM, queue: queue.slice(1)});
    render(<AccessRequestForm system="bdp" name="Big Data Portal" />);
    expect((await screen.findByTestId('access-queue')).textContent).toContain('2 not opened of 3');
    expect(screen.getAllByTestId('access-queue-item').map(i => i.getAttribute('data-opened'))).toEqual(['true', 'false', 'false']);
    fireEvent.click(screen.getByTestId('access-queue-next'));
    await waitFor(() => expect(open).toHaveBeenCalledWith('bdp', {queued: 'next'}));
    expect(await screen.findByText(/Prepared request 2 of 3 is open/)).toBeTruthy();
    expect(read).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByTestId('access-queue-clear'));
    await waitFor(() => expect(remove).toHaveBeenCalledWith('bdp', {opened: true}));
    await waitFor(() => expect(screen.getAllByTestId('access-queue-item')).toHaveLength(2));
  });

  it('says how requests get there when none are prepared', async () => {
    vi.spyOn(api, 'accessForm').mockResolvedValue(FORM);
    render(<AccessRequestForm system="bdp" name="Big Data Portal" />);
    expect((await screen.findByTestId('access-queue')).textContent).toContain('None yet.');
    expect(screen.queryByTestId('access-queue-next')).toBeNull();
  });
});
