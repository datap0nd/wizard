import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {api, ApiError} from '@/api';
import {QuickSetup, STEPS} from './QuickSetup';
import {SettingsDialog} from './SettingsDialog';
import type {Bootstrap, SettingField, SettingsView} from '@/types';

const BOOT: Bootstrap = {
  version: '0.1.0', auth: {mode: 'fixture', login_required: false}, suggestions: [], settings_editable: true,
  identity: {id: 'local-owner', name: 'Owner', email: 'person@example.test', role: 'Owner'},
  runtime: {kind: 'code-assist', label: 'Gemini Code Assist', model: 'gemini', ready: false, reason: 'Link your Gemini account first.'},
  gemini_account: {linked: false, google_email: null, linked_at: null, method: null, cli_credentials_present: false,
    secret_store: 'DPAPI', needs_link: true},
};
const field = (key: string, section: string, set: boolean): SettingField => ({key, label: key, section, help: '', placeholder: '',
  choices: [], secret: false, source: set ? 'company' : 'default', value: set ? 'x' : null, set, company_value: null, editable: true});
const VIEW: SettingsView = {
  sections: [{id: 'knowledge', title: 'Knowledge base', about: ''}, {id: 'postgres', title: 'Company database', about: ''},
    {id: 'portals', title: 'Portals', about: ''}],
  fields: [field('WIZARD_KB_REPO', 'knowledge', true), field('WIZARD_PG_HOST', 'postgres', false)],
  company_file: null, restart: 'automatic', model: 'gemini', runtime: 'code-assist', desktop: true, build: {}, version: '0.1.0',
};

function setup(overrides: Partial<Parameters<typeof QuickSetup>[0]> = {}) {
  const props = {boot: BOOT, view: VIEW, onExit: vi.fn(), onFinish: vi.fn(), onAccount: vi.fn(),
    onImported: vi.fn(async () => undefined), waitForRestart: vi.fn(async () => undefined), ...overrides};
  render(<QuickSetup {...props} />);
  return props;
}
const go = (id: string) => fireEvent.click(screen.getByTestId(`setup-step-${id}`));

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('Quick setup', () => {
  it('sits at the top of Settings and walks through every step to Finish', async () => {
    vi.spyOn(api, 'settings').mockResolvedValue(VIEW);
    vi.spyOn(api, 'updates').mockResolvedValue({installed: null, download: '', message: ''});
    vi.spyOn(api, 'portals').mockRejectedValue(new ApiError('No portals.', 404));
    const onClose = vi.fn();
    render(<SettingsDialog open onClose={onClose} onSaved={vi.fn()} boot={BOOT} />);
    fireEvent.click(await screen.findByTestId('quick-setup-open'));
    expect(screen.getByTestId('setup-panel-welcome').textContent).toContain('Welcome to Wizard');
    for (const step of STEPS.slice(1)) {
      fireEvent.click(screen.getByTestId('setup-next'));
      expect(screen.getByTestId(`setup-panel-${step.id}`)).toBeTruthy();
    }
    expect(screen.getByTestId('setup-panel-done').textContent).toContain('No settings file yet');
    fireEvent.click(screen.getByTestId('setup-finish'));
    expect(onClose).toHaveBeenCalled();
  });

  it('is not offered without the bootstrap, and All settings leads back to them', async () => {
    vi.spyOn(api, 'settings').mockResolvedValue(VIEW);
    vi.spyOn(api, 'updates').mockResolvedValue({installed: null, download: '', message: ''});
    vi.spyOn(api, 'portals').mockRejectedValue(new ApiError('No portals.', 404));
    render(<SettingsDialog open onClose={vi.fn()} onSaved={vi.fn()} />);
    await screen.findByTestId('settings-dialog');
    expect(screen.queryByTestId('quick-setup-open')).toBeNull();
    cleanup();
    render(<SettingsDialog open onClose={vi.fn()} onSaved={vi.fn()} boot={BOOT} setup />);
    fireEvent.click(await screen.findByTestId('setup-exit'));
    expect(screen.getByTestId('settings-dialog')).toBeTruthy();
  });

  it('imports the settings file the person chose, waits for the restart and reads the settings again', async () => {
    vi.spyOn(api, 'portals').mockRejectedValue(new ApiError('No portals.', 404));
    const imported = vi.spyOn(api, 'importSettings').mockResolvedValue({name: 'ACME Wizard', settings: 7, secrets: 2, apply: 'now'});
    const props = setup();
    go('file');
    const text = '{"wizard_provision": 1, "settings": {"WIZARD_PG_HOST": "db.corp"}}';
    fireEvent.change(screen.getByTestId('setup-file-input'), {target: {files: [new File([text], 'wizard.provision')]}});
    expect(await screen.findByText(/Imported ACME Wizard: 7 settings and 2 passwords or tokens/)).toBeTruthy();
    expect(imported).toHaveBeenCalledWith(text);
    expect(props.waitForRestart).toHaveBeenCalled();
    expect(props.onImported).toHaveBeenCalled();
    expect(screen.getByText(/Delete wizard.provision now/)).toBeTruthy();
  });

  it('says why a file was refused and stores nothing', async () => {
    vi.spyOn(api, 'portals').mockRejectedValue(new ApiError('No portals.', 404));
    vi.spyOn(api, 'importSettings').mockRejectedValue(new ApiError('Wizard cannot import this file: not a Wizard provisioning file.', 400));
    const props = setup();
    go('file');
    fireEvent.change(screen.getByTestId('setup-file-input'), {target: {files: [new File(['{}'], 'notes.json')]}});
    expect(await screen.findByText(/not a Wizard provisioning file/)).toBeTruthy();
    expect(props.waitForRestart).not.toHaveBeenCalled();
  });

  it('shows the Gemini sign-in, and the linked account once it is done', () => {
    vi.spyOn(api, 'portals').mockRejectedValue(new ApiError('No portals.', 404));
    setup();
    go('gemini');
    expect(screen.getByTestId('link-start')).toBeTruthy();
    expect(screen.getByTestId('setup-next').textContent).toContain('Skip for now');
    cleanup();
    setup({boot: {...BOOT, gemini_account: {...BOOT.gemini_account!, linked: true, google_email: 'person@example.test'}}});
    go('gemini');
    expect(screen.getByTestId('gemini-linked').textContent).toContain('person@example.test');
    expect(screen.queryByText('Unlink')).toBeNull();
    expect(screen.getByTestId('setup-next').textContent).toContain('Next');
  });

  it('opens the portals sign-in window and says when there are no portals', async () => {
    const status = {browser: 'Microsoft Edge', signing_in: false, running: false, last_sign_in: null,
      portals: [{id: 'bdp', name: 'Big Data Portal', host: 'bdp.example.test'}]};
    vi.spyOn(api, 'portals').mockResolvedValue(status);
    const open = vi.spyOn(api, 'portalSignIn').mockResolvedValue({...status, signing_in: true, window: 'sign_in'});
    setup();
    go('portals');
    fireEvent.click(await screen.findByTestId('setup-portal-sign-in'));
    expect(await screen.findByTestId('setup-portal-done')).toBeTruthy();
    expect(open).toHaveBeenCalled();
    cleanup();
    vi.spyOn(api, 'portals').mockRejectedValue(new ApiError('No portals.', 404));
    setup();
    go('portals');
    expect(await screen.findByTestId('setup-portals-none')).toBeTruthy();
  });

  it('tests only the connections this PC has set, with their saved settings', async () => {
    vi.spyOn(api, 'portals').mockRejectedValue(new ApiError('No portals.', 404));
    const test = vi.spyOn(api, 'testSettings').mockResolvedValue({ok: true, message: 'Connected: acme/kb at main.'});
    setup();
    go('check');
    fireEvent.click(screen.getByTestId('setup-check'));
    await waitFor(() => expect(screen.getByTestId('setup-check-results').textContent).toContain('Connected: acme/kb at main.'));
    expect(test).toHaveBeenCalledTimes(1);
    expect(test).toHaveBeenCalledWith('knowledge', {});
    cleanup();
    setup({view: {...VIEW, fields: [field('WIZARD_KB_REPO', 'knowledge', false)]}});
    go('check');
    expect(screen.getByTestId('setup-nothing-to-check')).toBeTruthy();
  });
});
