import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {VisualEnvContext, type VisualEnv} from '@/visualEnv';
import {AnswerMarkdown} from './AnswerMarkdown';
import {TooltipProvider} from './ui/menu';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const env: VisualEnv = {dataMode: 'SYNTHETIC', rowsBehind: true, sources: async () => ({sources: [], rows: []})};
const answer = 'Spend by market:\n\n| Market | Spend | Growth |\n| --- | ---: | ---: |\n| Egypt | $1,200 | 12.5% |\n| UAE | $800 | -4% [E1] |\n';

describe("a table in Gemini's answer", () => {
  it('copies as a table for Excel and PowerPoint, plain or in the Korean report style, with its data label', async () => {
    const write = vi.fn(async (_items: unknown[]) => undefined);
    vi.stubGlobal('ClipboardItem', class { constructor(public items: Record<string, Blob>) {} });
    vi.stubGlobal('navigator', {...navigator, clipboard: {write}});
    render(<TooltipProvider><VisualEnvContext.Provider value={env}><AnswerMarkdown text={answer} visuals={[]} onEvidence={() => undefined} /></VisualEnvContext.Provider></TooltipProvider>);
    expect(screen.getByTestId('answer-table').querySelectorAll('tbody tr')).toHaveLength(2);
    const html = async () => (write.mock.calls.at(-1)![0][0] as {items: Record<string, Blob>}).items['text/html'].text();
    fireEvent.keyDown(screen.getByTestId('visual-export'), {key: 'Enter'});
    fireEvent.click(screen.getByTestId('visual-export-copy-table'));
    await waitFor(() => expect(screen.getByTestId('visual-export-status').textContent).toContain('Table copied'));
    expect(await html()).toContain('x:num="1200"');
    expect(await html()).toContain('>-4%</td>');          // the cell as the answer words it, without its citation chip
    expect(await html()).toContain('SYNTHETIC test data, not corporate figures');
    fireEvent.keyDown(screen.getByTestId('visual-export'), {key: 'Enter'});
    fireEvent.click(screen.getByTestId('visual-export-copy-table-korean'));
    await waitFor(() => expect(screen.getByTestId('visual-export-status').textContent).toContain('Korean report style'));
    expect(await html()).toContain('Malgun Gothic');
    expect(await html()).toContain('>▼4.0%</td>');
    expect(await html()).toContain('SYNTHETIC test data, not corporate figures');
  });
});
