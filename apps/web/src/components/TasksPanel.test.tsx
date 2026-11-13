import {afterEach, describe, expect, it, vi} from 'vitest';
import {act, cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {api} from '@/api';
import {LIST_MS, TasksPanel} from './TasksPanel';
import type {QueueItem, TaskItem, TaskQueue, TasksView} from '@/types';

const TASK: TaskItem = {id: 'where-to-get-it', title: 'Add portal reports to Where to get it', summary: 'One line.', added: '2026-10-31',
  state: 'todo', conversation_id: null, at: null, message: null};
const VIEW: TasksView = {tasks: [TASK], source: 'app', version: '1.0.222.0', can_save: true};

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('Settings → Tasks', () => {
  it('reads the tasks only once the section is opened', async () => {
    const list = vi.spyOn(api, 'tasks').mockResolvedValue(VIEW);
    const {rerender} = render(<TasksPanel active={false} />);
    expect(list).not.toHaveBeenCalled();
    rerender(<TasksPanel active />);
    await screen.findByTestId('task-where-to-get-it');
    expect(list).toHaveBeenCalled();
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

  it('says so when the list does not come, instead of loading for ever', async () => {
    vi.useFakeTimers();
    try {
      vi.spyOn(api, 'tasks').mockReturnValue(new Promise(() => undefined));
      render(<TasksPanel active />);
      expect(screen.getByText('Loading…')).toBeTruthy();
      await act(async () => { vi.advanceTimersByTime(LIST_MS + 10); });
      expect(screen.getByRole('alert').textContent).toContain('did not list its tasks within 20 seconds');
    } finally {
      vi.useRealTimers();
    }
  });

  it('says the tasks came with this version, and when it cannot save', async () => {
    vi.spyOn(api, 'tasks').mockResolvedValue({...VIEW, can_save: false});
    render(<TasksPanel active />);
    expect((await screen.findByTestId('tasks-source')).textContent).toBe(
      "The tasks that came with Wizard 1.0.222.0. New tasks arrive with Wizard's updates (Version and updates, in Settings).");
    expect(screen.queryByText('Check for new tasks')).toBeNull();
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

const EMPTY: TaskQueue = {state: 'empty', items: [], message: null, total: 0, done: 0, current: null, position: null,
  selected: [], left_out: [], started_at: null, finished_at: null};
const REVIEW: TaskItem = {...TASK, id: 'kb-review-1', title: 'Knowledge review 1 of 7', added: '2026-11-02', max_runs: 5};
const DIGEST: TaskItem = {...TASK, id: 'digest', title: 'Digest presentations', input: 'folder', input_label: 'The folder',
  every_file: true, path: null, progress: null};
const item = (task: TaskItem, n: number, extra: Partial<QueueItem> = {}): QueueItem => ({key: `q${n}`, id: task.id,
  title: task.title, path: null, state: 'waiting', conversation_id: null, run_id: null, message: null, started_at: null,
  finished_at: null, ...extra});
const QUEUED: TasksView = {...VIEW, tasks: [REVIEW, TASK, DIGEST], queue: EMPTY};

describe('Settings → Tasks: the queue', () => {
  it('queues every task with Run all, says which it left out, and starts it', async () => {
    vi.spyOn(api, 'tasks').mockResolvedValue(QUEUED);
    const ready: TaskQueue = {...EMPTY, state: 'ready', total: 2, items: [item(TASK, 1), item(REVIEW, 2)],
      left_out: [{id: 'digest', title: 'Digest presentations', reason: 'it asks for a folder: type its path in its box, then add it to the queue'}]};
    const fill = vi.spyOn(api, 'fillQueue').mockResolvedValue({...QUEUED, queue: ready});
    const running: TaskQueue = {...ready, state: 'running', current: 'q2', position: 2, done: 1,
      items: [item(TASK, 1, {state: 'done', conversation_id: 'c1', finished_at: '2026-11-02T10:00:00Z'}),
        item(REVIEW, 2, {state: 'running', conversation_id: 'c2', message: 'Run 2 of up to 5: 12 left after run 1.'})]};
    const start = vi.spyOn(api, 'startQueue').mockResolvedValue({...QUEUED, queue: running,
      tasks: [{...REVIEW, state: 'running', conversation_id: 'c2', round: 2, message: 'Run 2 of up to 5: 12 left after run 1.'}, TASK, DIGEST]});
    render(<TasksPanel active />);
    expect(screen.queryByTestId('task-queue')).toBeNull();
    fireEvent.click(await screen.findByTestId('queue-all'));
    await screen.findByTestId('task-queue');
    expect(fill).toHaveBeenCalledWith(null, {});
    expect(screen.getByTestId('queue-status').textContent).toContain('2 tasks in this order, not started yet');
    expect(screen.getByTestId('queue-left-out').textContent).toContain('Digest presentations (it asks for a folder');
    expect(screen.getByTestId('task-where-to-get-it').textContent).toContain('In the queue, 1');
    fireEvent.click(screen.getByTestId('queue-start'));
    await waitFor(() => expect(screen.getByTestId('queue-status').textContent).toContain('Running 2 of 2: Knowledge review 1 of 7'));
    expect(start).toHaveBeenCalled();
    expect(screen.getByTestId('queue-status').textContent).toContain('Run 2 of up to 5: 12 left after run 1.');
    expect(screen.getByTestId('task-kb-review-1').textContent).toContain('Run 2 of up to 5');
    expect(screen.getByTestId('queued-where-to-get-it').textContent).toContain('Succeeded');
    expect(screen.getByTestId('queue-stop')).toBeTruthy();
    expect((screen.getByTestId('run-where-to-get-it') as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId('queue-all') as HTMLButtonElement).disabled).toBe(true);
  });

  it('keeps the ticks and runs the selected tasks with the paths typed', async () => {
    vi.spyOn(api, 'tasks').mockResolvedValue(QUEUED);
    const select = vi.spyOn(api, 'selectTasks').mockImplementation(async ids => ({...QUEUED, queue: {...EMPTY, selected: ids}}));
    const fill = vi.spyOn(api, 'fillQueue').mockResolvedValue({...QUEUED, queue: {...EMPTY, state: 'ready', total: 1, items: [item(TASK, 1)]}});
    render(<TasksPanel active />);
    const selected = await screen.findByTestId('queue-selected') as HTMLButtonElement;
    expect(selected.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText('Select Add portal reports to Where to get it'));
    fireEvent.click(screen.getByLabelText('Select Digest presentations'));
    expect(select).toHaveBeenLastCalledWith(['where-to-get-it', 'digest']);
    expect(selected.textContent).toBe('Run selected (2)');
    fireEvent.change(screen.getByTestId('path-digest'), {target: {value: 'C:\\Decks'}});
    fireEvent.click(selected);
    await waitFor(() => expect(fill).toHaveBeenCalledWith(['where-to-get-it', 'digest'], {digest: 'C:\\Decks'}));
  });

  it('shows the ticks the person left last time', async () => {
    vi.spyOn(api, 'tasks').mockResolvedValue({...QUEUED, queue: {...EMPTY, selected: ['kb-review-1', 'gone-task']}});
    render(<TasksPanel active />);
    expect((await screen.findByLabelText('Select Knowledge review 1 of 7') as HTMLInputElement).checked).toBe(true);
    expect(screen.getByTestId('queue-selected').textContent).toBe('Run selected (1)');
  });

  it('reorders and removes queued tasks before Start, and adds one with its path', async () => {
    const ready: TaskQueue = {...EMPTY, state: 'ready', total: 2, items: [item(TASK, 1), item(REVIEW, 2)]};
    vi.spyOn(api, 'tasks').mockResolvedValue({...QUEUED, queue: ready});
    const move = vi.spyOn(api, 'moveQueued').mockResolvedValue({...QUEUED, queue: ready});
    const remove = vi.spyOn(api, 'removeQueued').mockResolvedValue({...QUEUED, queue: ready});
    const add = vi.spyOn(api, 'queueTask').mockResolvedValue({...QUEUED, queue: ready});
    render(<TasksPanel active />);
    await screen.findByTestId('task-queue');
    expect((screen.getByLabelText('Move Add portal reports to Where to get it up') as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText('Move Knowledge review 1 of 7 down') as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByLabelText('Move Add portal reports to Where to get it down'));
    await waitFor(() => expect(move).toHaveBeenCalledWith('q1', 1));
    fireEvent.click(screen.getByLabelText('Remove Knowledge review 1 of 7 from the queue'));
    await waitFor(() => expect(remove).toHaveBeenCalledWith('q2'));
    expect((screen.getByTestId('queue-where-to-get-it') as HTMLButtonElement).disabled).toBe(true);
    const addDigest = screen.getByTestId('queue-digest') as HTMLButtonElement;
    expect(addDigest.disabled).toBe(true);
    fireEvent.change(screen.getByTestId('path-digest'), {target: {value: 'C:\\Decks'}});
    fireEvent.click(addDigest);
    await waitFor(() => expect(add).toHaveBeenCalledWith('digest', 'C:\\Decks'));
  });

  it('says where the queue stopped and why, with Continue', async () => {
    const failed: TaskQueue = {...EMPTY, state: 'failed', total: 3, done: 1, current: 'q2', position: 2,
      message: 'Stopped at “Knowledge review 1 of 7”, which failed: Gemini\'s quota is used up.',
      started_at: '2026-11-02T09:00:00Z', finished_at: '2026-11-02T10:00:00Z',
      items: [item(TASK, 1, {state: 'done', conversation_id: 'c1', finished_at: '2026-11-02T09:30:00Z'}),
        item(REVIEW, 2, {state: 'failed', conversation_id: 'c2', message: 'Gemini\'s quota is used up.'}), item(DIGEST, 3)]};
    vi.spyOn(api, 'tasks').mockResolvedValue({...QUEUED, queue: failed});
    const start = vi.spyOn(api, 'startQueue').mockResolvedValue({...QUEUED, queue: {...failed, state: 'running'}});
    render(<TasksPanel active />);
    const status = await screen.findByTestId('queue-status');
    expect(status.textContent).toContain('which failed: Gemini\'s quota is used up. 1 of 3 done.');
    expect(screen.getByTestId('queued-kb-review-1').textContent).toContain('Failed');
    expect(screen.getByRole('link', {name: 'See what it did'}).getAttribute('href')).toBe('?c=c1');
    expect(screen.getByRole('link', {name: 'See why'}).getAttribute('href')).toBe('?c=c2');
    expect(screen.getByTestId('queued-digest').textContent).toContain('Waiting');
    fireEvent.click(screen.getByTestId('queue-continue'));
    await waitFor(() => expect(start).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId('queue-continue')).toBeNull());
    expect(screen.getByTestId('queue-stop')).toBeTruthy();
  });

  it('offers Continue and Clear after a restart interrupted the queue', async () => {
    const interrupted: TaskQueue = {...EMPTY, state: 'interrupted', total: 2, current: 'q1', position: 1,
      message: 'Interrupted at “Knowledge review 1 of 7”: Wizard restarted before it finished. Press Continue to run it again and go on.',
      items: [item(REVIEW, 1, {state: 'interrupted', conversation_id: 'c1'}), item(TASK, 2)]};
    vi.spyOn(api, 'tasks').mockResolvedValue({...QUEUED, queue: interrupted});
    const clear = vi.spyOn(api, 'clearQueue').mockResolvedValue({...QUEUED, queue: EMPTY});
    render(<TasksPanel active />);
    expect((await screen.findByTestId('queue-status')).textContent).toContain('Interrupted at “Knowledge review 1 of 7”');
    expect(screen.getByTestId('queue-continue')).toBeTruthy();
    fireEvent.click(screen.getByTestId('queue-clear'));
    await waitFor(() => expect(clear).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId('task-queue')).toBeNull());
  });

  it('stops a running queue', async () => {
    const running: TaskQueue = {...EMPTY, state: 'running', total: 1, current: 'q1', position: 1,
      items: [item(TASK, 1, {state: 'running', conversation_id: 'c1'})]};
    vi.spyOn(api, 'tasks').mockResolvedValue({...QUEUED, queue: running});
    const stop = vi.spyOn(api, 'stopQueue').mockResolvedValue({...QUEUED, queue: {...running, state: 'stopped',
      message: 'You stopped the queue at “Add portal reports to Where to get it”.'}});
    render(<TasksPanel active />);
    expect((await screen.findByTestId('queue-status')).querySelector('a')?.getAttribute('href')).toBe('?c=c1');
    expect(screen.queryByTestId('queue-clear')).toBeNull();
    fireEvent.click(screen.getByTestId('queue-stop'));
    await waitFor(() => expect(stop).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByTestId('queue-status').textContent).toContain('You stopped the queue'));
  });
});
