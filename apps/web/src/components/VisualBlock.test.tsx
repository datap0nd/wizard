import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import type {Visual} from '@/types';
import {VisualEnvContext, type VisualEnv} from '@/visualEnv';
import {TooltipProvider} from './ui/menu';
import {VisualBlock} from './VisualBlock';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const heat: Visual = {
  id: 'V1', kind: 'heatmap', title: 'Growth by market and month', subtitle: null,
  columns: [{key: 'market', label: 'Market', type: 'string', unit: null}, {key: 'jul', label: 'Jul', type: 'percent', unit: '%'},
    {key: 'aug', label: 'Aug', type: 'percent', unit: '%'}],
  rows: [['Egypt', 12.5, -4], ['UAE', null, 8]], x: 'market', series: ['jul', 'aug'], evidence_ids: ['E1'], note: null, derived_by: 'model',
};

const env: VisualEnv = {dataMode: 'LIVE', rowsBehind: true, sources: async () => ({sources: [], rows: []})};

function show(visual: Visual, value: VisualEnv = env) {
  return render(<TooltipProvider><VisualEnvContext.Provider value={value}><VisualBlock visual={visual} /></VisualEnvContext.Provider></TooltipProvider>);
}

describe('a heatmap in an answer', () => {
  it('is a table of shaded cells with the value in each, a legend, and its data a click away', () => {
    show(heat);
    const map = screen.getByTestId('visual-heatmap');
    expect(map.dataset.scale).toBe('diverging');
    const cells = within(map).getAllByTestId('heat-cell');
    expect(cells.map(c => c.textContent)).toEqual(['12.5%', '-4%', '—', '8%']);
    expect(cells[0].style.background).not.toBe('');
    expect(cells[2].dataset.fill).toBe('#ffffff');
    expect(screen.getByTestId('heat-legend').textContent).toContain('-12.5% (red) to 12.5% (blue); grey is 0');
    expect(screen.getByTestId('heat-legend').textContent).toContain('no data');
    fireEvent.click(screen.getByRole('button', {name: 'Data'}));
    expect(screen.queryByTestId('visual-heatmap')).toBeNull();
  });
});

describe('copying and downloading a visual', () => {
  const open = () => fireEvent.keyDown(screen.getByTestId('visual-export'), {key: 'Enter'});

  it('offers pictures, a table, a PowerPoint slide and an Excel workbook with the rows behind it', () => {
    show(heat);
    open();
    for (const action of ['copy-picture', 'copy-table', 'copy-table-korean', 'pptx', 'xlsx', 'xlsx-korean', 'png']) expect(screen.getByTestId(`visual-export-${action}`)).toBeTruthy();
    expect(screen.getByTestId('visual-export-pptx').textContent).toContain('An editable PowerPoint table');
    expect(screen.getByTestId('visual-export-xlsx').textContent).toContain('the rows behind it');
  });

  it('says on a case that its workbook keeps no rows', () => {
    vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
    show({...heat, kind: 'bar'}, {...env, rowsBehind: false});
    open();
    expect(screen.getByTestId('visual-export-xlsx').textContent).toContain('a case keeps no rows');
    expect(screen.getByTestId('visual-export-pptx').textContent).toContain('An editable PowerPoint chart');
  });

  it('copies the table for Excel and PowerPoint and says so', async () => {
    const write = vi.fn(async () => undefined);
    vi.stubGlobal('ClipboardItem', class { constructor(public items: Record<string, Blob>) {} });
    Object.defineProperty(navigator, 'clipboard', {value: {write}, configurable: true});
    show(heat);
    open();
    fireEvent.click(screen.getByTestId('visual-export-copy-table'));
    await waitFor(() => expect(screen.getByTestId('visual-export-status').textContent).toContain('Table copied'));
    const item = (write.mock.calls[0] as unknown as [{items: Record<string, Blob>}[]])[0][0];
    expect(Object.keys(item.items).sort()).toEqual(['text/html', 'text/plain']);
    expect(await item.items['text/html'].text()).toContain('x:num="0.125"');
  });

  it('saves a download in Downloads on this PC and opens it there', async () => {
    const saved = {id: 'a1', filename: 'Growth by market and month.xlsx', folder: 'C:\\Users\\exec\\Downloads'};
    const opened = vi.fn(async () => undefined);
    show(heat, {...env, save: async () => saved, open: opened});
    open();
    fireEvent.click(screen.getByTestId('visual-export-xlsx'));
    await waitFor(() => expect(screen.getByTestId('visual-export-status').textContent)
      .toContain('Saved in C:\\Users\\exec\\Downloads as Growth by market and month.xlsx.'));
    fireEvent.click(screen.getByTestId('visual-export-open'));
    await waitFor(() => expect(opened).toHaveBeenCalledWith(saved));
  });

  it('says why when a copy is refused', async () => {
    vi.stubGlobal('ClipboardItem', undefined);
    Object.defineProperty(navigator, 'clipboard', {value: undefined, configurable: true});
    show(heat);
    open();
    fireEvent.click(screen.getByTestId('visual-export-copy-picture'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Download the picture (.png) instead'));
  });
});
