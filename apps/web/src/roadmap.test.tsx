import {afterEach, describe, expect, it} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {RoadmapPage} from './components/roadmap/RoadmapPage';
import {calendarDay, dayLabel, MILESTONES, placeMilestones} from './roadmap';

afterEach(cleanup);

describe('the roadmap', () => {
  it('puts each step on the Friday its last week ends, from Friday 30 October 2026; slides take two weeks', () => {
    const placed = placeMilestones(MILESTONES, new Date(2026, 9, 28, 23, 30));
    expect(placed.map(m => [m.id, m.week, m.due])).toEqual([
      ['portals', 'Week 1', '2026-10-30'], ['slides', 'Weeks 2–3', '2026-11-13'], ['knowledge', 'Week 4', '2026-11-20']]);
    expect(placed.every(m => calendarDay(m.due).getDay() === 5)).toBe(true);
    expect(placeMilestones([{...MILESTONES[0], weeks: 3}, ...MILESTONES.slice(1)], new Date(2026, 9, 28)).map(m => m.due))
      .toEqual(['2026-11-13', '2026-11-27', '2026-12-04']);
    expect(MILESTONES.find(m => m.id === 'knowledge')!.body).toMatch(/heads of business and the main PIC of each business area/);
    expect(MILESTONES.flatMap(m => m.items).every(item => item.logo || item.icon)).toBe(true);
    expect(dayLabel(calendarDay('2026-10-30'))).toBe('Fri 30 Oct');
  });

  it('counts down in calendar days, and the first step not done or past is next', () => {
    const wednesday = placeMilestones(MILESTONES, new Date(2026, 9, 28, 23, 30));
    expect(wednesday.map(m => [m.state, m.when])).toEqual([['next', 'In 2 days'], ['planned', 'In 16 days'], ['planned', 'In 23 days']]);
    expect(placeMilestones(MILESTONES, new Date(2026, 9, 29, 8))[0].when).toBe('Due tomorrow');
    expect(placeMilestones(MILESTONES, new Date(2026, 9, 30, 8))[0].when).toBe('Due today');
    const saturday = placeMilestones(MILESTONES, new Date(2026, 9, 31));
    expect(saturday.map(m => m.state)).toEqual(['late', 'next', 'planned']);
    expect(saturday[0].when).toBe('Due date passed');
    const delivered = placeMilestones([{...MILESTONES[0], done: true}, ...MILESTONES.slice(1)], new Date(2026, 9, 31));
    expect(delivered.map(m => [m.state, m.when])).toEqual([['done', 'Delivered'], ['next', 'In 13 days'], ['planned', 'In 20 days']]);
  });

  it('shows what Wizard does at once, and the next Friday on each → (← takes it back)', () => {
    render(<RoadmapPage />);
    expect(screen.getAllByTestId('roadmap-capability').length).toBeGreaterThanOrEqual(6);
    expect(screen.queryAllByTestId('roadmap-milestone')).toHaveLength(0);
    expect(screen.getByTestId('roadmap-start')).toBeTruthy();
    fireEvent.keyDown(window, {key: 'ArrowRight'});
    expect(screen.getAllByTestId('roadmap-milestone')).toHaveLength(1);
    expect(screen.getByTestId('roadmap-milestone').textContent).toContain('SC+ Global Dashboard');
    fireEvent.keyDown(window, {key: 'ArrowRight'});
    fireEvent.keyDown(window, {key: 'ArrowRight'});
    fireEvent.keyDown(window, {key: 'ArrowRight'});
    expect(screen.getAllByTestId('roadmap-milestone')).toHaveLength(3);
    fireEvent.keyDown(window, {key: 'ArrowLeft'});
    expect(screen.getAllByTestId('roadmap-milestone').map(m => m.querySelector('[data-testid=roadmap-due]')!.textContent)).toEqual(['Fri 30 Oct', 'Fri 13 Nov']);
    fireEvent.keyDown(window, {key: 'Home'});
    expect(screen.queryAllByTestId('roadmap-milestone')).toHaveLength(0);
    fireEvent.keyDown(window, {key: 'End'});
    expect(screen.getAllByTestId('roadmap-milestone')).toHaveLength(3);
    fireEvent.click(screen.getByTestId('roadmap-previous'));
    expect(screen.getAllByTestId('roadmap-milestone')).toHaveLength(2);
  });
});
