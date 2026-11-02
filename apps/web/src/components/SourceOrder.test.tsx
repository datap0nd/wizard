import {useState} from 'react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {api} from '@/api';
import {SourceOrder} from './SourceOrder';
import {SettingsDialog} from './SettingsDialog';
import type {OrderEntry} from '@/sourceOrder';
import type {SettingsView} from '@/types';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const DEFAULT: OrderEntry[] = [{id: 'dashboards'}, {id: 'postgresql'}, {id: 'asap'}, {id: 'gscm', same: true}, {id: 'nerp'}, {id: 'bdp'}];
const SOURCES = [{id: 'dashboards', name: 'Team dashboards'}, {id: 'postgresql', name: 'AI Team Database'}, {id: 'asap', name: 'ASAP'},
  {id: 'gscm', name: 'GSCM'}, {id: 'nerp', name: 'NERP'}, {id: 'crm', name: 'CRM portal'}];

/** The section as Settings holds it: the stored line in a draft. */
function Harness({initial = '', onChange}: {initial?: string; onChange?: (next: string) => void}) {
  const [value, setValue] = useState(initial);
  return <SourceOrder value={value} defaults={DEFAULT} sources={SOURCES} onChange={next => { setValue(next); onChange?.(next); }} />;
}

const rows = () => screen.getAllByTestId('source-order-row').map(r => `${r.dataset.level}:${r.dataset.source}`);

describe('Settings → Source order', () => {
  it('shows the default order, a portal set up later at the end, and a named source this PC does not have', () => {
    render(<Harness />);
    expect(rows()).toEqual(['1:dashboards', '2:postgresql', '3:asap', '3:gscm', '4:nerp', '5:bdp', '6:crm']);
    expect(screen.getByText('Team dashboards')).toBeTruthy();
    const bdp = screen.getAllByTestId('source-order-row')[5];
    expect(bdp.textContent).toContain('Big Data Portal');
    expect(bdp.textContent).toContain('not on this PC');
    expect(screen.getByLabelText('Remove Big Data Portal from the order')).toBeTruthy();
    expect(screen.queryByLabelText('Remove ASAP from the order')).toBeNull();
  });

  it('reorders with the buttons, keeping focus on the moved source for the keyboard', () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    expect((screen.getByLabelText('Move Team dashboards up') as HTMLButtonElement).disabled).toBe(true);
    const nerpUp = screen.getByLabelText('Move NERP up');
    nerpUp.focus();
    fireEvent.click(nerpUp);
    expect(rows()).toEqual(['1:dashboards', '2:postgresql', '3:nerp', '4:asap', '4:gscm', '5:bdp', '6:crm']);
    expect(document.activeElement).toBe(screen.getByLabelText('Move NERP up'));
    fireEvent.click(document.activeElement as HTMLElement);
    fireEvent.click(document.activeElement as HTMLElement);
    expect(rows().slice(0, 3)).toEqual(['1:nerp', '2:dashboards', '3:postgresql']);
    expect(document.activeElement).toBe(screen.getByLabelText('Move NERP down'));  // at the top: the other button
    expect(onChange).toHaveBeenLastCalledWith(
      '[{"id":"nerp"},{"id":"dashboards"},{"id":"postgresql"},{"id":"asap"},{"id":"gscm","same":true},{"id":"bdp"},{"id":"crm"}]');
  });

  it('puts a source on the level above, writes what it is for, and keeps it for when asked', () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const same = screen.getAllByTestId('source-same') as HTMLInputElement[];
    expect(same[0].disabled).toBe(true);
    expect(same[3].checked).toBe(true);
    fireEvent.click(same[3]);
    expect(rows().slice(2, 4)).toEqual(['3:asap', '4:gscm']);
    fireEvent.click(screen.getAllByTestId('source-same')[1]);
    expect(rows().slice(0, 2)).toEqual(['1:dashboards', '1:postgresql']);
    fireEvent.change(screen.getByLabelText('What ASAP is for'), {target: {value: 'Customer segmentation <age, channel>'}});
    fireEvent.click(screen.getAllByTestId('source-when-asked')[4]);
    const stored = JSON.parse(onChange.mock.calls.at(-1)![0]);
    expect(stored[2]).toEqual({id: 'asap', use: 'Customer segmentation  age, channel '});
    expect(stored[4]).toEqual({id: 'nerp', when_asked: true});
    expect((screen.getByLabelText('What ASAP is for') as HTMLInputElement).maxLength).toBe(200);
  });

  it('removes a source this PC does not have', () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    fireEvent.click(screen.getByLabelText('Remove Big Data Portal from the order'));
    expect(rows()).not.toContain('5:bdp');
    expect(onChange.mock.calls.at(-1)![0]).not.toContain('bdp');
  });
});

describe('the Source order section in Settings', () => {
  const VIEW: SettingsView = {
    sections: [{id: 'sources', title: 'Source order', about: 'Where Wizard starts.'}],
    fields: [{key: 'WIZARD_SOURCE_ORDER', label: 'Order', section: 'sources', help: 'Move a source up or down.', placeholder: '',
      choices: [], secret: false, source: 'company', value: '[{"id":"postgresql"},{"id":"asap"}]', set: true, company_value: '[]',
      editable: true}],
    company_file: null, restart: 'automatic', model: 'gemini', runtime: 'code-assist', desktop: true, build: {}, version: '0.1.0',
    source_order: {default: DEFAULT, max_use: 200, sources: SOURCES.slice(1, 3)},
  };

  it('arranges the company order and saves it as one setting', async () => {
    vi.spyOn(api, 'settings').mockResolvedValue(VIEW);
    vi.spyOn(api, 'updates').mockRejectedValue(new Error('offline'));
    const save = vi.spyOn(api, 'saveSettings').mockResolvedValue({...VIEW, changed: ['WIZARD_SOURCE_ORDER'], apply: 'none'});
    render(<SettingsDialog open onClose={vi.fn()} onSaved={vi.fn()} />);
    await screen.findByTestId('source-order');
    expect(rows()).toEqual(['1:postgresql', '2:asap']);
    expect(screen.getByTestId('setting-WIZARD_SOURCE_ORDER').textContent).toContain('From the company settings file');
    fireEvent.click(screen.getByLabelText('Move ASAP up'));
    expect(screen.getByTestId('setting-WIZARD_SOURCE_ORDER').textContent).toContain('Changed');
    fireEvent.click(screen.getByTestId('settings-save'));
    await vi.waitFor(() => expect(save).toHaveBeenCalledWith({WIZARD_SOURCE_ORDER: '[{"id":"asap"},{"id":"postgresql"}]'}));
  });
});
