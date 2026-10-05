import type {RunEvent, RunRecord, RunView, TimelineItem} from './types';

export const TERMINAL = new Set(['run_finished', 'run_failed']);

export function emptyRun(id: string, conversationId: string, question: string, kind: 'ask' | 'check' = 'ask'): RunView {
  return {id, conversationId, kind, question, status: 'queued', runtime: 'replay', runtimeLabel: '', model: '', timeline: [],
    streamText: '', answer: null, visuals: [], evidence: [], check: null, checkStatus: 'NOT_CHECKED', checkSummary: null,
    dataMode: null, reportId: null, error: null, warnings: [], lastSeq: 0, createdAt: new Date().toISOString(), finishedAt: null,
    parentRunId: null, diagnostics: []};
}

/** Apply one observed run event. Pure: the same reducer rebuilds a stored run and follows a live one. */
export function applyEvent(run: RunView, event: RunEvent): RunView {
  if (event.seq <= run.lastSeq) return run;
  const p = event.payload;
  const next: RunView = {...run, lastSeq: event.seq};
  switch (event.type) {
    case 'run_started':
      return {...next, status: 'running', runtime: p.runtime, runtimeLabel: p.runtime_label, model: p.model};
    case 'agent_session':
      return {...next, model: p.model ?? next.model};
    case 'status':
      return {...next, timeline: [...next.timeline, {key: `s${event.seq}`, kind: 'status', label: String(p.message)}]};
    case 'text_delta':
      return {...next, streamText: next.streamText + String(p.text ?? '')};
    case 'note':
      return {...next, streamText: '', timeline: [...next.timeline, {key: `n${event.seq}`, kind: 'note', label: String(p.text)}]};
    case 'tool_started': {
      const item: TimelineItem = {key: String(p.call_id), kind: 'tool', label: String(p.label), state: 'running', name: p.name, category: p.category};
      return {...next, timeline: [...next.timeline, item]};
    }
    case 'tool_finished':
      return {...next,
        evidence: p.evidence ? [...next.evidence.filter(e => e.id !== p.evidence.id), p.evidence] : next.evidence,
        timeline: next.timeline.map(item => item.key === String(p.call_id) && item.kind === 'tool'
          ? {...item, state: p.ok ? 'ok' : 'error', summary: String(p.summary ?? ''), evidence: p.evidence, durationMs: p.duration_ms} : item)};
    case 'visual_added':
      return {...next, visuals: [...next.visuals.filter(v => v.id !== p.visual.id), p.visual]};
    case 'check_result':
      return {...next, check: {overall: p.overall, summary: p.summary, claims: p.claims ?? [], replays: p.replays ?? []}};
    case 'warning':
      return {...next, warnings: [...next.warnings, String(p.message)], timeline: [...next.timeline, {key: `w${event.seq}`, kind: 'warning', label: String(p.message)}]};
    case 'diagnostic':
      return {...next, diagnostics: [...next.diagnostics, p as Record<string, unknown>]};
    case 'run_finished':
      return {...next, status: 'succeeded', streamText: '', answer: String(p.answer ?? ''), reportId: p.report_id, dataMode: p.data_mode,
        checkStatus: p.check_status ?? 'NOT_CHECKED', checkSummary: p.check_summary ?? null,
        warnings: Array.from(new Set([...next.warnings, ...(p.warnings ?? [])])), finishedAt: event.ts};
    case 'run_failed':
      return {...next, status: p.status === 'cancelled' ? 'cancelled' : 'failed', error: {code: String(p.code), message: String(p.message)},
        finishedAt: event.ts, timeline: next.timeline.map(item => item.state === 'running' ? {...item, state: 'error', summary: 'Stopped'} : item)};
    default:
      return next;
  }
}

export function fromRecord(record: RunRecord): RunView {
  let view = emptyRun(record.id, record.conversation_id, record.question, record.kind);
  view = {...view, runtime: record.runtime, runtimeLabel: record.runtime_label, model: record.model, createdAt: record.created_at,
    parentRunId: record.parent_run_id, status: record.status};
  for (const event of record.events) view = applyEvent(view, event);
  return {...view, status: record.status, answer: record.answer ?? view.answer, reportId: record.report_id ?? view.reportId,
    dataMode: record.data_mode ?? view.dataMode, checkStatus: record.check_status, checkSummary: record.check_summary,
    visuals: record.visuals.length ? record.visuals : view.visuals, evidence: record.evidence.length ? record.evidence : view.evidence,
    error: record.error_code ? {code: record.error_code, message: record.error_message ?? ''} : view.error,
    finishedAt: record.finished_at};
}

export function sourcesConsulted(run: RunView): string[] {
  return Array.from(new Set(run.timeline.filter(t => t.kind === 'tool' && t.state === 'ok' && t.evidence).map(t => t.evidence!.system.toUpperCase())));
}
