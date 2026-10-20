import {describe, expect, it} from 'vitest';
import {distinctLines, sourceCount, sourceGroups, sqlRelations} from './sources';
import type {EvidenceSummary} from './types';

const base: EvidenceSummary = {id: 'E1', system: 'postgresql', system_name: 'PostgreSQL', report_id: 'sql-1', report_name: 'SQL query on meto_db',
  data_mode: 'LIVE', as_of: '2026-10-07T16:00:00+00:00', total_rows: 1, truncated: false, warnings: [], access_note: null};
const query = (id: string, sql: string, asOf = base.as_of): EvidenceSummary => ({...base, id, report_id: `sql-${id}`, sql, as_of: asOf});

describe('sqlRelations', () => {
  it('names the tables and views a query reads, not CTEs, functions or EXTRACT ... FROM', () => {
    const sql = `-- last week by market
      WITH wk AS (SELECT * FROM bi_reporting.psi_combined p WHERE EXTRACT(week FROM p.week_start) = 40),
           plan(market, units) AS (SELECT market, sum(units) FROM "BI_Reporting"."Sell_In_Plan" GROUP BY 1)
      SELECT w.market, sum(w.units), max(pl.units)
      FROM wk w JOIN plan pl ON pl.market = w.market
      LEFT JOIN LATERAL (SELECT name FROM ref.markets m WHERE m.code = w.market) n ON true
      CROSS JOIN generate_series(1, 3) g, ref.subsidiaries s
      WHERE w.market IN (SELECT code FROM ref.active_markets) AND substring(w.note FROM 1 FOR 3) <> 'x FROM y'
      GROUP BY 1`;
    expect(sqlRelations(sql)).toEqual(['bi_reporting.psi_combined', 'BI_Reporting.Sell_In_Plan', 'ref.markets', 'ref.subsidiaries',
                                       'ref.active_markets']);
    expect(sqlRelations('select * from a.b x, c.d as y, e where 1 = 1')).toEqual(['a.b', 'c.d', 'e']);
  });
});

describe('sourceGroups', () => {
  it('makes fourteen queries on one table one source, and names reports with their module and files by name', () => {
    const queries = Array.from({length: 14}, (_, i) => query(`E${i + 1}`, `SELECT market, sum(units) FROM bi_reporting.sell_in_amt_mv WHERE week = ${i} GROUP BY 1`,
      `2026-10-07T16:${String(i).padStart(2, '0')}:00+00:00`));
    const report: EvidenceSummary = {...base, id: 'E15', system: 'gscm', system_name: 'GSCM', report_id: 'gscm-sell-in', report_name: 'Sell in',
      folder_path: ['Biz Plan'], data_mode: 'SYNTHETIC', sql: null, access_note: 'Rows limited to your markets.'};
    const file: EvidenceSummary[] = [
      {...base, id: 'E16', system: 'attachment', system_name: 'Attached file', report_id: 'att_1', report_name: 'plan.xlsx', data_mode: 'USER_PROVIDED'},
      {...base, id: 'E17', system: 'attachment', system_name: 'Attached file', report_id: 'att_1', report_name: 'plan.xlsx › Q4', data_mode: 'USER_PROVIDED'},
    ];
    const sources = sourceGroups([...queries, report, ...file, report]);
    expect(sources.map(s => [s.kind, s.system, s.path, s.name, s.ids.length])).toEqual([
      ['table', 'PostgreSQL', [], 'bi_reporting.sell_in_amt_mv', 14],
      ['report', 'GSCM', ['Biz Plan'], 'Sell in', 1],
      ['file', 'Attached file', [], 'plan.xlsx', 2],
    ]);
    expect(sources[0].asOf).toBe('2026-10-07T16:13:00+00:00');
    expect(sources[0].dataModes).toEqual(['LIVE']);
    expect(sources[1].accessNotes).toEqual(['Rows limited to your markets.']);
    expect(sourceCount(sources)).toBe(3);
  });

  it('counts a join under each table, and lists catalog lookups last without counting them', () => {
    const sources = sourceGroups([
      query('E1', 'SELECT column_name FROM information_schema.columns WHERE table_name = $$psi$$'),
      query('E2', 'SELECT * FROM bi_reporting.psi p JOIN ref.markets m USING (code)'),
      query('E3', 'SELECT * FROM pg_catalog.pg_views'),
      query('E4', 'SELECT current_date'),
    ]);
    expect(sources.map(s => [s.kind, s.name, s.ids])).toEqual([
      ['table', 'bi_reporting.psi', ['E2']],
      ['table', 'ref.markets', ['E2']],
      ['query', 'SQL query on meto_db', ['E4']],
      ['catalog', 'Table and column definitions', ['E1', 'E3']],
    ]);
    expect(sourceCount(sources)).toBe(3);
  });

  it('reads the SQL from full evidence too', () => {
    const {sql, ...summary} = query('E1', 'SELECT * FROM bi_reporting.psi');
    expect(sourceGroups([{...summary, request: {sql: sql!}} as never]).map(s => s.name)).toEqual(['bi_reporting.psi']);
  });
});

describe('distinctLines', () => {
  it('cuts the opening that queries on one table share, so what differs shows', () => {
    expect(distinctLines([
      'SELECT market, sum(units) FROM bi_reporting.sell_in_amt_mv WHERE week = 1 GROUP BY 1',
      'SELECT market, sum(units) FROM bi_reporting.sell_in_amt_mv WHERE week = 2 GROUP BY 1',
    ])).toEqual(['… WHERE week = 1 GROUP BY 1', '… WHERE week = 2 GROUP BY 1']);
    expect(distinctLines(['SELECT a FROM t', 'SELECT b FROM t'])).toEqual(['SELECT a FROM t', 'SELECT b FROM t']);
    expect(distinctLines(['SELECT * FROM bi_reporting.sell_in_amt_mv'])).toEqual(['SELECT * FROM bi_reporting.sell_in_amt_mv']);
    const same = 'SELECT market, sum(units) FROM bi_reporting.sell_in_amt_mv';
    expect(distinctLines([same, `${same} LIMIT 5`])).toEqual([same, `${same} LIMIT 5`]);  // too little to cut before the difference
    expect(distinctLines([same, same])).toEqual([same, same]);
  });
});
