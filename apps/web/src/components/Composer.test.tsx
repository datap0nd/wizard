import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {Composer, MAX_QUESTION_CHARS} from './Composer';
import {LongText} from './LongText';
import {TooltipProvider} from './ui/menu';

afterEach(cleanup);

const box = (draft: string, busy = false) => render(<TooltipProvider><Composer busy={busy} draft={draft} onDraftChange={() => {}}
  onSubmit={vi.fn()} steer={busy ? {live: true, onSteer: vi.fn()} : null} /></TooltipProvider>);

describe('a long question', () => {
  it('the box holds 100,000 characters, as a question or as a note while an answer runs', () => {
    expect(MAX_QUESTION_CHARS).toBe(100_000);
    box('Units?');
    expect(screen.getByLabelText('Your question').getAttribute('maxlength')).toBe('100000');
    cleanup();
    box('use the weekly view', true);
    expect(screen.getByLabelText('A note to Wizard while it works').getAttribute('maxlength')).toBe('100000');
  });

  it('says so when a paste fills the box', () => {
    box('x'.repeat(MAX_QUESTION_CHARS - 1));
    expect(screen.getByTestId('composer-hint').textContent).toBe('Check the evidence before acting on a number.');
    cleanup();
    box('x'.repeat(MAX_QUESTION_CHARS));
    expect(screen.getByTestId('composer-hint').textContent).toBe('The box holds 100,000 characters. Attach longer text as a file.');
  });

  it('shows its first lines with Show all; a short one shows whole', () => {
    const pasted = Array.from({length: 40}, (_, i) => `Model ${i + 1}`).join('\n');
    render(<LongText text={pasted} lines={12} chars={1200} clamp="line-clamp-12" testId="user-turn" />);
    expect(screen.getByTestId('user-turn').className).toContain('line-clamp-12');
    expect(screen.getByTestId('user-turn').textContent).toBe(pasted);
    fireEvent.click(screen.getByText(`Show all (${pasted.length} characters)`));
    expect(screen.getByTestId('user-turn').className).not.toContain('line-clamp-12');
    expect(screen.getByTestId('long-text-toggle').textContent).toBe('Show less');
    cleanup();
    render(<LongText text="Units by market?" lines={12} chars={1200} clamp="line-clamp-12" testId="user-turn" />);
    expect(screen.getByTestId('user-turn').className).not.toContain('line-clamp');
    expect(screen.queryByTestId('long-text-toggle')).toBeNull();
  });
});
