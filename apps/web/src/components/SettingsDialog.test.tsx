import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {api} from '@/api';
import {SettingsDialog} from './SettingsDialog';
import type {SettingsView, UpdateInfo} from '@/types';

const VIEW: SettingsView = {
  sections: [], fields: [], company_file: null, restart: 'automatic', model: 'gemini', runtime: 'code-assist',
  desktop: true, build: {version: '1.0.59.0', commit: 'ff4a9e2304fa46732da5c3c77f7bc4d9070739a8'}, version: '0.1.0',
};
const FAILED: UpdateInfo = {ok: false, installed: '1.0.59.0', download: 'https://example.test/WizardSetup.exe',
  message: 'Could not read the release: Wizard could not reach release-assets.githubusercontent.com: the connection timed out.'};

function inWizardBar() {
  const postMessage = vi.fn();
  (window as unknown as {chrome?: unknown}).chrome = {webview: {postMessage, addEventListener: vi.fn(), removeEventListener: vi.fn()}};
  return postMessage;
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); delete (window as unknown as {chrome?: unknown}).chrome; });

describe('Dashboards', () => {
  const REPOS = 'WIZARD_DASHBOARDS_REPOS';
  const DASHBOARDS: SettingsView = {...VIEW,
    sections: [{id: 'dashboards', title: 'Dashboards', about: "The team's HTML dashboards, on the company GitHub."}],
    fields: [{key: REPOS, label: 'Repositories', section: 'dashboards', help: '', placeholder: 'sales-bi/weekly-kpi', choices: [],
      secret: false, source: 'default', value: null, set: false, company_value: null, editable: true}]};

  it('finds the dashboards the token reads on GitHub and leaves what was typed as it is', async () => {
    vi.spyOn(api, 'settings').mockResolvedValue(DASHBOARDS);
    vi.spyOn(api, 'updates').mockResolvedValue(FAILED);
    const test = vi.spyOn(api, 'testSettings').mockResolvedValue({ok: true, count: 5,
      repos: [{repository: 'sales-bi/weekly-kpi', dashboards: 3}, {repository: 'finance-bi/margin', dashboards: 2}],
      message: 'Found 5 dashboards in 2 repositories (sales-bi/*): finance-bi/margin (2), sales-bi/weekly-kpi (3). Save to keep it.'});
    render(<SettingsDialog open onClose={vi.fn()} onSaved={vi.fn()} />);
    const input = await screen.findByTestId(`setting-${REPOS}`) as HTMLInputElement;
    fireEvent.change(input, {target: {value: 'sales-bi/*'}});
    const button = screen.getByTestId('test-dashboards');
    expect(button.textContent).toBe('Find dashboards');
    fireEvent.click(button);
    expect(await screen.findByText(/Found 5 dashboards in 2 repositories/)).toBeTruthy();
    expect(test).toHaveBeenCalledWith('dashboards', {[REPOS]: 'sales-bi/*'});
    expect(input.value).toBe('sales-bi/*');
  });
});

describe('Runs', () => {
  const LIMIT = 'WIZARD_RUN_TIMEOUT_S';
  const RUNS: SettingsView = {...VIEW,
    sections: [{id: 'runs', title: 'Runs', about: 'How long one answer may take.'}],
    fields: [
      {key: LIMIT, label: 'Time limit per run', section: 'runs', help: 'Up to 600 minutes (10 hours).', placeholder: '30', choices: [],
        number: {low: 1, high: 600, unit: 'minutes', whole: false}, secret: false, source: 'default', value: '', set: false,
        company_value: null, editable: true},
      {key: 'WIZARD_DIAGNOSTICS', label: 'Diagnostics in the app', section: 'runs', help: '', placeholder: 'true',
        choices: ['true', 'false'], choice_labels: ['Shown', 'Hidden'], secret: false, source: 'env_file', value: 'false',
        set: true, company_value: null, editable: true}]};

  it('takes the time limit in minutes, up to 10 hours, and shows choices in words', async () => {
    vi.spyOn(api, 'settings').mockResolvedValue(RUNS);
    vi.spyOn(api, 'updates').mockResolvedValue(FAILED);
    const save = vi.spyOn(api, 'saveSettings').mockResolvedValue({...RUNS, changed: [LIMIT], apply: 'none'});
    render(<SettingsDialog open onClose={vi.fn()} onSaved={vi.fn()} />);
    const input = await screen.findByTestId(`setting-${LIMIT}`) as HTMLInputElement;
    expect([input.type, input.min, input.max, input.placeholder]).toEqual(['number', '1', '600', '30']);
    expect(screen.getByText('minutes')).toBeTruthy();
    const diagnostics = screen.getByLabelText('Diagnostics in the app') as HTMLSelectElement;
    expect([...diagnostics.options].map(o => o.textContent)).toEqual(['Shown', 'Hidden']);
    expect(diagnostics.value).toBe('false');
    fireEvent.change(input, {target: {value: '600'}});
    fireEvent.click(screen.getByTestId('settings-save'));
    expect(save).toHaveBeenCalledWith({[LIMIT]: '600'});
  });
});

describe('Version and updates', () => {
  it('in the desktop app, offers WizardBar\'s own update check when the service could not read the release', async () => {
    const postMessage = inWizardBar();
    vi.spyOn(api, 'settings').mockResolvedValue(VIEW);
    vi.spyOn(api, 'updates').mockResolvedValue(FAILED);
    render(<SettingsDialog open onClose={vi.fn()} onSaved={vi.fn()} />);
    expect((await screen.findByTestId('update-message')).textContent).toContain('release-assets.githubusercontent.com');
    fireEvent.click(screen.getByTestId('update-with-windows'));
    expect(postMessage).toHaveBeenCalledWith({type: 'update'});
    expect(screen.queryByTestId('update-now')).toBeNull();
  });

  it('in a browser, or when the check worked, shows no such button', async () => {
    vi.spyOn(api, 'settings').mockResolvedValue(VIEW);
    vi.spyOn(api, 'updates').mockResolvedValue(FAILED);
    render(<SettingsDialog open onClose={vi.fn()} onSaved={vi.fn()} />);
    await screen.findByTestId('update-message');
    expect(screen.queryByTestId('update-with-windows')).toBeNull();
    cleanup();
    inWizardBar();
    vi.spyOn(api, 'updates').mockResolvedValue({ok: true, installed: '1.0.59.0', latest: '1.0.66.0', available: true,
      download: FAILED.download, message: 'Version 1.0.66.0 is available.'});
    render(<SettingsDialog open onClose={vi.fn()} onSaved={vi.fn()} />);
    expect((await screen.findByTestId('update-now')).textContent).toContain('Update to 1.0.66.0');
    expect(screen.queryByTestId('update-with-windows')).toBeNull();
  });
});
