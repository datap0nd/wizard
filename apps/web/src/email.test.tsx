import {describe, expect, it} from 'vitest';
import {buildEmail, emlFile, emlName, finalSources, tookWords, type EmailInput} from './email';
import type {Evidence, EvidenceSummary, Visual} from './types';

function sqlEvidence(id: string, sql: string): Evidence {
  return {
    id, system: 'postgresql', system_name: 'PostgreSQL', report_id: `sql-${id}`, report_name: 'SQL query on meto_db',
    data_mode: 'LIVE', as_of: '2026-10-07T16:00:00+00:00', total_rows: 1, truncated: false, warnings: [], access_note: null,
    tool: 'wizard_query_postgresql', folder_path: [], connector_status: 'READ_ONLY_SQL', request: {sql, database: 'meto_db'},
    columns: [], rows: [], retrieved_at: '2026-10-07T16:00:00+00:00', digest: 'a'.repeat(64), caveats: [],
    locator: {system: 'postgresql', report_id: `sql-${id}`, open_url: null},
  };
}

const gscm: EvidenceSummary = {id: 'E4', system: 'gscm', system_name: 'GSCM', report_id: 'r1', report_name: 'Weekly PSI by market',
  data_mode: 'SYNTHETIC', as_of: null, total_rows: 3, truncated: false, warnings: [], access_note: null};

describe('finalSources', () => {
  it('lists only the sources the answer cites or charts, one line per table or report', () => {
    const evidence = [sqlEvidence('E1', 'SELECT 1 FROM bi_reporting.psi_combined'), sqlEvidence('E2', 'SELECT * FROM bi_reporting.calendar'),
                      sqlEvidence('E3', 'SELECT * FROM bi_reporting.psi_combined JOIN ref.markets USING (code)'), gscm];
    const visual = {id: 'V1', evidence_ids: ['E4']} as Visual;
    expect(finalSources('KSA 265,247 units [E1] [E3].\n\n[V1]', [visual], evidence)).toEqual([
      {system: 'PostgreSQL', name: 'bi_reporting.psi_combined', ids: ['E1', 'E3']},
      {system: 'PostgreSQL', name: 'ref.markets', ids: ['E3']},
      {system: 'GSCM', name: 'Weekly PSI by market', ids: ['E4']},
    ]);
    expect(finalSources('No citations.', [], [gscm]).map(s => s.name)).toEqual(['Weekly PSI by market']);
    expect(finalSources('[E5]', [], [{...gscm, id: 'E5', folder_path: ['Biz Plan']}])).toEqual([
      {system: 'GSCM › Biz Plan', name: 'Weekly PSI by market', ids: ['E5']}]);
  });
});

describe('buildEmail', () => {
  const input: EmailInput = {
    question: 'Sell in by market for last week', model: 'gemini-3.8-flash', dataMode: 'LIVE', checkStatus: 'NOT_CHECKED',
    answer: '## Sell-in, week 40\n\n| Market | Units |\n|---|--:|\n| KSA | 265,247 [E1] |\n\n**Total** 1,116,313 units [E1]. <b>raw</b>',
    visuals: [], evidence: [sqlEvidence('E1', 'SELECT * FROM bi_reporting.psi_combined'), sqlEvidence('E2', 'SELECT * FROM x.unused')],
    createdAt: '2026-10-07T16:00:00.000Z', finishedAt: '2026-10-07T16:04:42.900Z',
  };

  it('carries the question, the answer with inline-styled tables, the time taken and the sources used', async () => {
    const draft = await buildEmail(input);
    expect(draft.subject).toBe('Wizard: Sell in by market for last week');
    expect(draft.html).toContain('Sell in by market for last week');
    expect(draft.html).toContain('Answered by Wizard in 4 min 43 s');
    expect(draft.html).toMatch(/<table[^>]*style="border-collapse:collapse/);
    expect(draft.html).toMatch(/<td style="[^"]*text-align:right[^"]*">265,247 <span[^>]*>\[E1\]<\/span><\/td>/);
    expect(draft.html).toContain('<b>PostgreSQL</b> bi_reporting.psi_combined');
    expect(draft.html).not.toContain('x.unused');
    expect(draft.html).toContain('Live: Read live from the company PostgreSQL database');
    expect(draft.html).toContain('Not checked');
    expect(draft.html).not.toContain('<b>raw</b>');
    expect(draft.html).not.toContain('<button');
  });

  it('can be saved as an unsent .eml message', async () => {
    const draft = await buildEmail(input);
    const text = await emlFile(draft).text();
    expect(text.startsWith('X-Unsent: 1\r\nSubject: =?UTF-8?B?')).toBe(true);
    const body = text.split('\r\n\r\n')[1].replace(/\r\n/g, '');
    const decoded = new TextDecoder().decode(Uint8Array.from(atob(body), c => c.charCodeAt(0)));
    expect(decoded).toContain('Answered by Wizard in 4 min 43 s');
    expect(emlName('Sell in: by market / last week?')).toBe('Wizard - Sell in by market last week.eml');
  });

  it('words the time taken', () => {
    expect(tookWords('2026-10-07T16:00:00Z', '2026-10-07T16:00:42Z')).toBe('42 s');
    expect(tookWords('2026-10-07T16:00:00Z', null)).toBeNull();
  });
});
