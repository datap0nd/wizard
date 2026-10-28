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
