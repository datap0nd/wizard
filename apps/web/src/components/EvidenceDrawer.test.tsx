import {afterEach, describe, expect, it} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {EvidenceDrawer} from './EvidenceDrawer';
import {TooltipProvider} from './ui/menu';
import type {Evidence, EvidenceSummary} from '@/types';

const sql = 'SELECT market, sum(units) AS units\nFROM bi_reporting.sell_in_amt_mv\nGROUP BY 1';
const evidence: Evidence = {
  id: 'E1', system: 'postgresql', system_name: 'PostgreSQL', report_id: 'sql-0123456789ab', report_name: 'SQL query on meto_db',
  data_mode: 'LIVE', as_of: '2026-10-06T12:00:00+00:00', total_rows: 2, truncated: false, warnings: [], access_note: null,
  tool: 'wizard_query_postgresql', folder_path: [], connector_status: 'READ_ONLY_SQL',
  request: {sql, database: 'meto_db', max_rows: 200},
  columns: [{key: 'market', label: 'market', type: 'string'}, {key: 'units', label: 'units', type: 'integer'}],
  rows: [['SA', 380], ['EG', 150]], retrieved_at: '2026-10-06T12:00:00+00:00', digest: 'a'.repeat(64), caveats: [],
  locator: {system: 'postgresql', report_id: 'sql-0123456789ab', open_url: null},
};

afterEach(cleanup);

describe('evidence drawer', () => {
  it('shows the SQL Gemini wrote, its database and the rows, labelled Live', () => {
    render(<TooltipProvider><EvidenceDrawer conversationId={null} open focus="E1" items={[evidence]} preloaded={[evidence]} onClose={() => {}} /></TooltipProvider>);
    expect(screen.getByTestId('evidence-sql').textContent).toBe(sql);
    expect(screen.getByText('meto_db')).toBeTruthy();
    expect(screen.getAllByTestId('data-mode').map(b => b.textContent)).toEqual(['Live', 'Live']);
    expect(screen.getByTestId('source-name').textContent).toBe('bi_reporting.sell_in_amt_mv');
    expect(screen.getByText('SA')).toBeTruthy();
    expect(screen.getByText('A live query Gemini wrote')).toBeTruthy();
    expect(screen.queryByText('no filters')).toBeNull();
  });

  it('lists each table, report and file once, and opens a table to its queries, then a query to its SQL', () => {
    const queries: EvidenceSummary[] = Array.from({length: 14}, (_, i) => ({...evidence, id: `E${i + 1}`, report_id: `sql-${i}`,
      sql: `SELECT market, sum(units)\nFROM bi_reporting.sell_in_amt_mv WHERE week = ${i}\nGROUP BY 1`}));
    const report: EvidenceSummary = {id: 'E15', system: 'gscm', system_name: 'GSCM', report_id: 'gscm-sell-in', report_name: 'Sell in',
      folder_path: ['Biz Plan'], data_mode: 'SYNTHETIC', as_of: null, total_rows: 3, truncated: false, warnings: [], access_note: null, sql: null};
    render(<TooltipProvider><EvidenceDrawer conversationId={null} open focus={null} items={[...queries, report]} preloaded={[evidence]} onClose={() => {}} /></TooltipProvider>);
    expect(screen.getAllByTestId('source-name').map(n => n.textContent)).toEqual(['bi_reporting.sell_in_amt_mv', 'Sell in']);
    expect(screen.getAllByTestId('source-uses').map(n => n.textContent)).toEqual(['14 queries', '1 run']);
    expect(screen.getByText(/GSCM › Biz Plan · report/)).toBeTruthy();
    expect(screen.queryByTestId('source-item')).toBeNull();
    fireEvent.click(screen.getByText('bi_reporting.sell_in_amt_mv'));
    const items = screen.getAllByTestId('source-item');
    expect(items).toHaveLength(14);
    expect(items[0].textContent).toContain('… WHERE week = 0 GROUP BY 1');  // what differs between the queries
    expect(items[0].querySelector('[title]')?.getAttribute('title')).toBe('SELECT market, sum(units) FROM bi_reporting.sell_in_amt_mv WHERE week = 0 GROUP BY 1');
    expect(screen.queryByTestId('evidence-sql')).toBeNull();
    fireEvent.click(items[0]);
    expect(screen.getByTestId('evidence-sql').textContent).toBe(sql);
  });

  it('opens on the source and the query a citation points at', () => {
    const other: EvidenceSummary = {...evidence, id: 'E2', report_id: 'sql-2', sql: 'SELECT * FROM ref.markets'};
    const cited: EvidenceSummary = {...evidence, id: 'E3', report_id: 'sql-3', sql};
    render(<TooltipProvider><EvidenceDrawer conversationId={null} open focus="E3" items={[{...evidence, sql}, other, cited]}
      preloaded={[{...evidence, id: 'E3'}]} onClose={() => {}} /></TooltipProvider>);
    expect(screen.getAllByTestId('source-name').map(n => n.textContent)).toEqual(['bi_reporting.sell_in_amt_mv', 'ref.markets']);
    expect(screen.getAllByTestId('evidence').map(e => e.dataset.evidenceId)).toEqual(['E3']);
    expect(document.getElementById('drawer-E3')).toBeTruthy();
  });
});
