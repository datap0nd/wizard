import {afterEach, describe, expect, it, vi} from 'vitest';
import {api, ApiError, onSession} from './api';

const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), {status, headers: {'Content-Type': 'application/json'}});
const lapsed = () => reply(401, {error: 'Sign in to use Wizard.', login_required: true});

afterEach(() => { vi.unstubAllGlobals(); onSession({renew: null, signedOut: () => undefined}); });

describe('a lapsed session', () => {
  it('is renewed once, as the same person, and the request sent again', async () => {
    // The owner, 23 Oct: WizardBar said "Your session expired. Reload the page" and has no reload button.
    const fetch = vi.fn().mockResolvedValueOnce(lapsed()).mockResolvedValueOnce(lapsed())
      .mockResolvedValueOnce(reply(200, {conversations: [{id: 'cnv_1'}]})).mockResolvedValueOnce(reply(200, {conversations: []}));
    vi.stubGlobal('fetch', fetch);
    const renew = vi.fn(() => Promise.resolve());
    const signedOut = vi.fn();
    onSession({renew, signedOut});
    const [first, second] = await Promise.all([api.conversations(), api.conversations()]);
    expect(first.conversations.length + second.conversations.length).toBe(1);
    expect(renew).toHaveBeenCalledTimes(1);
    expect(signedOut).not.toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledTimes(4);
  });

  it('shows sign-in when it cannot be renewed', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(lapsed()));
    const signedOut = vi.fn();
    onSession({renew: () => Promise.reject(new Error('Unknown test identity.')), signedOut});
    const failure = await api.conversations().catch((e: unknown) => e);
    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).loginRequired).toBe(true);
    expect(signedOut).toHaveBeenCalledTimes(1);
  });

  it('is not renewed where sign-in is not Wizard\'s to do (company SSO)', async () => {
    const fetch = vi.fn().mockResolvedValue(lapsed());
    vi.stubGlobal('fetch', fetch);
    const signedOut = vi.fn();
    onSession({renew: null, signedOut});
    await expect(api.conversations()).rejects.toThrow('Sign in to use Wizard.');
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(signedOut).toHaveBeenCalledTimes(1);
  });
});
