import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {api} from '@/api';
import {AccessRequestCard} from './AccessRequestCard';
import type {AccessRequest, PortalStatus} from '@/types';

const REQUEST: AccessRequest = {
  id: 'AR-0123456789', system: 'bdp', portal: 'Big Data Portal', address: 'https://catalog.example.com/dis', tables: ['t_daily'],
  answers: [], saved: ['Purpose', 'DPA / DSA › Purpose'], form_button: 'Request access',
  open_steps: [{action: 'fill', selector: '#q', value: 't_daily'}, {action: 'press', value: 'Enter'}, {action: 'click', text: 't_daily'}],
};

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('Access request card', () => {
  it("says it reaches the table's page and opens the form, and opens the prepared request with its way there", async () => {
    const status: PortalStatus = {browser: 'Chrome', signing_in: true, window: 'access_request', running: true, last_sign_in: null,
      portals: [], access_request: {system: 'bdp', filled: [], missing: [], note: 'Wizard pressed Request access to open the request form.'}};
    const open = vi.spyOn(api, 'openAccessRequest').mockResolvedValue(status);
    render(<AccessRequestCard request={REQUEST} />);
    expect(screen.getByTestId('access-request-card').textContent).toContain("catalog.example.com/dis, then 3 steps to the table's page, and presses Request access");
    fireEvent.click(screen.getByTestId('access-request-open-form'));
    await waitFor(() => expect(open).toHaveBeenCalledWith('bdp', {queued: 'AR-0123456789', address: REQUEST.address, tables: ['t_daily'],
      answers: [], open_steps: REQUEST.open_steps, form_button: 'Request access'}));
    expect((await screen.findByTestId('access-request-open')).textContent).toContain('Wizard pressed Request access to open the request form.');
  });

  it('offers Send request once sending is on, as the permission to fill and submit it', async () => {
    const status: PortalStatus = {browser: 'Chrome', signing_in: true, window: 'access_request', running: true, last_sign_in: null,
      portals: [], access_request: {system: 'bdp', filled: [], missing: [], sending: {left: 1, sent: 0}}};
    const send = vi.spyOn(api, 'sendAccessRequests').mockResolvedValue(status);
    const open = vi.spyOn(api, 'openAccessRequest');
    render(<AccessRequestCard request={{...REQUEST, can_send: true}} />);
    fireEvent.click(screen.getByTestId('access-request-send'));
    await waitFor(() => expect(send).toHaveBeenCalledWith('bdp', {ids: ['AR-0123456789']}));
    expect((await screen.findByTestId('access-request-sending')).textContent).toContain('presses Submit');
    expect(open).not.toHaveBeenCalled();
    cleanup();
    render(<AccessRequestCard request={REQUEST} />);
    expect(screen.queryByTestId('access-request-send')).toBeNull();
  });
});
