import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {api} from '@/api';
import {TasksPanel} from './TasksPanel';
import type {TaskItem, TasksView} from '@/types';

const TASK: TaskItem = {id: 'where-to-get-it', title: 'Add portal reports to Where to get it', summary: 'One line.', added: '2026-10-31',
  state: 'todo', conversation_id: null, at: null, message: null};
const VIEW: TasksView = {tasks: [TASK], source: 'github', checked: 1793400000, message: null, can_save: true};

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('Settings → Tasks', () => {
  it('reads the tasks only once the section is opened', async () => {
    const list = vi.spyOn(api, 'tasks').mockResolvedValue(VIEW);
    const {rerender} = render(<TasksPanel active={false} />);
    expect(list).not.toHaveBeenCalled();
    rerender(<TasksPanel active />);
    await screen.findByTestId('task-where-to-get-it');
    expect(list).toHaveBeenCalledWith(true);
    expect(screen.getByTestId('run-where-to-get-it').textContent).toBe('Run');
  });

  it('runs a task and links to its conversation while it runs', async () => {
    vi.spyOn(api, 'tasks').mockResolvedValue(VIEW);
    const running: TasksView = {...VIEW, tasks: [{...TASK, state: 'running', conversation_id: 'c1'}]};
    const run = vi.spyOn(api, 'runTask').mockResolvedValue(running);
    render(<TasksPanel active />);
    fireEvent.click(await screen.findByTestId('run-where-to-get-it'));
    await waitFor(() => expect(screen.getByRole('link', {name: 'Watch it'}).getAttribute('href')).toBe('?c=c1'));
    expect(run).toHaveBeenCalledWith('where-to-get-it');
    expect((screen.getByTestId('run-where-to-get-it') as HTMLButtonElement).disabled).toBe(true);
  });

  it('says when it cannot save and when GitHub did not answer', async () => {
    vi.spyOn(api, 'tasks').mockResolvedValue({...VIEW, source: 'bundled', message: 'timed out', can_save: false});
    render(<TasksPanel active />);
    expect((await screen.findByTestId('tasks-panel')).textContent).toContain('came with this version');
    expect(screen.getByTestId('tasks-panel').textContent).toContain('GitHub did not answer (timed out)');
    expect(screen.getByTestId('tasks-panel').textContent).toContain('write token');
  });
});
