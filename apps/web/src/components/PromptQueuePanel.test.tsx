import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {api} from '@/api';
import {PromptQueuePanel, splitPrompts} from './PromptQueuePanel';
import type {PromptItem, PromptQueue} from '@/types';

const EMPTY: PromptQueue = {state: 'empty', items: [], message: null, total: 0, done: 0, failed: 0, current: null, position: null,
  started_at: null, finished_at: null, max_retries: 2, max_prompts: 200};
const item = (key: string, prompt: string, more: Partial<PromptItem> = {}): PromptItem => ({key, prompt, state: 'waiting',
  attempts: 0, conversation_id: null, run_id: null, message: null, started_at: null, finished_at: null, retry_at: null, ...more});

afterEach(() => { cleanup(); vi.restoreAllMocks(); window.localStorage.clear(); });

describe('Settings → Prompt queue', () => {
  it('cuts the text the way Wizard does', () => {
    expect(splitPrompts(' a ; b;;\n c ;', 'semicolon')).toEqual(['a', 'b', 'c']);
    expect(splitPrompts('one\r\ntwo\n\n three ', 'newline')).toEqual(['one', 'two', 'three']);
    expect(splitPrompts('first\nstill first\n  \nsecond', 'blank_line')).toEqual(['first\nstill first', 'second']);
    expect(splitPrompts('a | b', 'pipe')).toEqual(['a', 'b']);
    expect(splitPrompts('a\n---\nb', 'dashes')).toEqual(['a', 'b']);
    expect(splitPrompts('a ## b', 'custom', '##')).toEqual(['a', 'b']);
    expect(splitPrompts('a;b', 'custom', ' ')).toEqual([]);
  });

  it('counts the prompts as they are typed, with the separator chosen, and adds and starts them', async () => {
    vi.spyOn(api, 'promptQueue').mockResolvedValue(EMPTY);
    const ready: PromptQueue = {...EMPTY, state: 'ready', total: 3,
      items: [item('p1', 'Share in UAE?'), item('p2', 'Sell-out by operator?'), item('p3', 'Spend by market?')]};
    const add = vi.spyOn(api, 'addPrompts').mockResolvedValue(ready);
    const start = vi.spyOn(api, 'startPrompts').mockResolvedValue({...ready, state: 'running', current: 'p1', position: 1,
      items: [item('p1', 'Share in UAE?', {state: 'running', attempts: 1, conversation_id: 'c1'}), ready.items[1], ready.items[2]]});
    render(<PromptQueuePanel active />);
    await waitFor(() => expect(api.promptQueue).toHaveBeenCalled());
    fireEvent.change(screen.getByTestId('prompt-text'), {target: {value: 'Share in UAE?; Sell-out by operator?\nSpend by market?'}});
    expect(screen.getByTestId('prompt-count').textContent).toBe('2 prompts');
    fireEvent.change(screen.getByTestId('prompt-separator'), {target: {value: 'newline'}});
    expect(screen.getByTestId('prompt-count').textContent).toBe('2 prompts');
    expect(window.localStorage.getItem('wizard.promptSeparator')).toBe('newline');
    fireEvent.change(screen.getByTestId('prompt-separator'), {target: {value: 'custom'}});
    expect(screen.getByTestId('prompt-count').textContent).toBe('Type the separator.');
    fireEvent.change(screen.getByTestId('prompt-custom'), {target: {value: '?'}});
    expect(screen.getByTestId('prompt-count').textContent).toBe('3 prompts');
    fireEvent.click(screen.getByTestId('prompt-add-start'));
    await waitFor(() => expect(start).toHaveBeenCalled());
    expect(add).toHaveBeenCalledWith('Share in UAE?; Sell-out by operator?\nSpend by market?', 'custom', '?');
    expect((screen.getByTestId('prompt-text') as HTMLTextAreaElement).value).toBe('');
    expect(screen.getByTestId('prompts-status').textContent).toContain('Running 1 of 3');
    expect(screen.getByRole('link', {name: 'Watch it'}).getAttribute('href')).toBe('?c=c1');
    expect(screen.getByTestId('prompts-stop')).toBeTruthy();
  });

  it('shows the tries, how it ended, and puts the failed ones back', async () => {
    const ended: PromptQueue = {...EMPTY, state: 'done', total: 2, done: 1, failed: 1,
      message: '1 of 2 prompts answered, 1 failed after 3 tries.', started_at: '2026-11-04T20:00:00Z', finished_at: '2026-11-05T03:10:00Z',
      items: [item('p1', 'Share?', {state: 'done', attempts: 2, conversation_id: 'c1', finished_at: '2026-11-04T21:00:00Z'}),
        item('p2', 'Spend?', {state: 'failed', attempts: 3, conversation_id: 'c2', message: 'Failed 3 times. Last: Gemini failed.'})]};
    vi.spyOn(api, 'promptQueue').mockResolvedValue(ended);
    const retry = vi.spyOn(api, 'retryFailedPrompts').mockResolvedValue({...ended, state: 'stopped', failed: 0,
      message: '1 failed prompt(s) back in the queue: press Continue.', items: [ended.items[0], item('p2', 'Spend?', {conversation_id: 'c2'})]});
    render(<PromptQueuePanel active />);
    expect((await screen.findByTestId('prompts-status')).textContent).toContain('1 failed after 3 tries');
    expect(screen.getByTestId('prompt-p1').textContent).toContain('try 2 of 3');
    expect(screen.getByRole('link', {name: 'Read the answer'}).getAttribute('href')).toBe('?c=c1');
    expect(screen.getByTestId('prompt-p2').textContent).toContain('Failed 3 times');
    fireEvent.click(screen.getByTestId('prompts-retry-failed'));
    await waitFor(() => expect(retry).toHaveBeenCalled());
    expect(await screen.findByTestId('prompts-continue')).toBeTruthy();
  });
});
