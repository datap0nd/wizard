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
    expect(run).toHaveBeenCalledWith('where-to-get-it', {});
    expect((screen.getByTestId('run-where-to-get-it') as HTMLButtonElement).disabled).toBe(true);
  });

  it('says when it cannot save and when GitHub did not answer', async () => {
    vi.spyOn(api, 'tasks').mockResolvedValue({...VIEW, source: 'bundled', message: 'timed out', can_save: false});
    render(<TasksPanel active />);
    expect((await screen.findByTestId('tasks-panel')).textContent).toContain('came with this version');
    expect(screen.getByTestId('tasks-panel').textContent).toContain('GitHub did not answer (timed out)');
    expect(screen.getByTestId('tasks-panel').textContent).toContain('write token');
  });

  it('asks for the folder before a task that reads one runs, and sends the path typed', async () => {
    const digest: TaskItem = {...TASK, id: 'digest', title: 'Digest presentations', input: 'folder',
      input_label: 'The folder with the presentations', every_file: true, path: null, progress: null};
    vi.spyOn(api, 'tasks').mockResolvedValue({...VIEW, tasks: [digest]});
    const run = vi.spyOn(api, 'runTask').mockResolvedValue({...VIEW, tasks: [{...digest, state: 'running', conversation_id: 'c2',
      path: 'C:\\Decks', round: 1, progress: {total: 300, done: 0, left: 300}}]});
    render(<TasksPanel active />);
    const button = await screen.findByTestId('run-digest') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByLabelText('The folder with the presentations')).toBeTruthy();
    fireEvent.change(screen.getByTestId('path-digest'), {target: {value: 'C:\\Decks'}});
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    await waitFor(() => expect(screen.getByTestId('task-digest').textContent).toContain('Round 1 · 0 of 300 files done'));
    expect(run).toHaveBeenCalledWith('digest', {path: 'C:\\Decks', fresh: false});
  });

  it('continues a folder where it stopped, or starts it over', async () => {
    const paused: TaskItem = {...TASK, id: 'digest', title: 'Digest presentations', input: 'folder', input_label: null,
      every_file: true, path: 'C:\\Decks', state: 'stopped', message: 'Stopped during round 4: 120 of 300 files done.',
      round: 4, progress: {total: 300, done: 120, left: 180}};
    vi.spyOn(api, 'tasks').mockResolvedValue({...VIEW, tasks: [paused]});
    const run = vi.spyOn(api, 'runTask').mockResolvedValue({...VIEW, tasks: [paused]});
    render(<TasksPanel active />);
    expect((await screen.findByTestId('run-digest')).textContent).toBe('Continue');
    expect(screen.getByTestId('task-digest').textContent).toContain('120 of 300 files done');
    expect((screen.getByTestId('path-digest') as HTMLInputElement).value).toBe('C:\\Decks');
    fireEvent.click(screen.getByTestId('run-digest'));
    await waitFor(() => expect(run).toHaveBeenCalledWith('digest', {path: 'C:\\Decks', fresh: false}));
    fireEvent.click(screen.getByTestId('fresh-digest'));
    await waitFor(() => expect(run).toHaveBeenCalledWith('digest', {path: 'C:\\Decks', fresh: true}));
  });
});
