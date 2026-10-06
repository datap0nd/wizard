import {afterEach, describe, expect, it} from 'vitest';
import {cleanup, render, screen} from '@testing-library/react';
import {EvidenceDrawer} from './EvidenceDrawer';
import {TooltipProvider} from './ui/menu';
import type {Evidence} from '@/types';

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
    expect(screen.getByTestId('data-mode').textContent).toBe('Live');
    expect(screen.getByText('SA')).toBeTruthy();
    expect(screen.getByText('A live query Gemini wrote')).toBeTruthy();
    expect(screen.queryByText('no filters')).toBeNull();
  });
});
