import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, render, screen} from '@testing-library/react';
import {NewsPanel} from './NewsPanel';
import type {BrainNews} from '@/brain';

const NEWS: BrainNews = {
  status: 'ok', table: 'public.news', database: 'postgres', total: 1512, first: '2026-04-06', last_7_days: 96,
  categories: [{name: 'Pricing', count: 400}, {name: 'Retail', count: 320}],
  weekly: [{week: '2026-10-12', count: 40}, {week: '2026-10-19', count: 52}],
  latest: [{title: 'A synthetic headline', category: 'Pricing', date: '2026-10-28T06:00:00Z'}], queries: [],
};

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('the news panel', () => {
  it('in the simple view shows the total at once and never scrolls the headlines', () => {
    const tick = vi.spyOn(globalThis, 'setInterval');
    render(<NewsPanel news={NEWS} fresh={new Set()} incoming={[]} category={null} onCategory={vi.fn()} name="AI Team Database" still />);
    expect(screen.getByTestId('news-total').textContent).toBe('1,512');
    expect(tick.mock.calls.filter(([, ms]) => ms === 45)).toHaveLength(0);
    expect(screen.getByTestId('news-latest').textContent).toContain('A synthetic headline');
  });

  it('in the advanced view counts up to the total and scrolls the headlines', () => {
    const tick = vi.spyOn(globalThis, 'setInterval');
    render(<NewsPanel news={NEWS} fresh={new Set()} incoming={[]} category={null} onCategory={vi.fn()} name="AI Team Database" />);
    expect(screen.getByTestId('news-total').textContent).toBe('0');
    expect(tick.mock.calls.filter(([, ms]) => ms === 45)).toHaveLength(1);
  });
});
