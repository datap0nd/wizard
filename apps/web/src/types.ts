export type DataMode = 'SYNTHETIC' | 'DATED_APPROVED_SNAPSHOT' | 'LIVE_VERIFIED';
export type CheckStatus = 'CHECKED' | 'NOT_CHECKED' | 'DISCREPANCY';
export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
export type RuntimeKind = 'gemini-cli' | 'code-assist' | 'replay';

export interface Identity { id: string; name: string; email: string; role: string }

export interface GeminiAccount {
  linked: boolean;
  google_email: string | null;
  linked_at: string | null;
  method: string | null;
  cli_credentials_present: boolean;
  secret_store: string;
  needs_link: boolean;
  /** Set for a synthetic test identity on a work-PC install: no real Google account can be linked to it. */
  link_note?: string | null;
  /** The local Owner: its email becomes the Google account it links. */
  adopts_google_email?: boolean;
}

export interface Bootstrap {
  version: string;
  auth: {mode: 'fixture' | 'trusted-header'; login_required: boolean};
  suggestions: {story: string; question: string}[];
  identity?: Identity;
  runtime?: {kind: RuntimeKind; label: string; model: string; ready: boolean; reason: string | null};
  gemini_account?: GeminiAccount;
  /** Dev mode: show full run diagnostics and the server log. */
  diagnostics?: boolean;
  data_modes?: DataMode[];
}

export interface ConversationSummary { id: string; title: string; created_at: string; updated_at: string }

export interface EvidenceSummary {
  id: string;
  system: string;
  system_name?: string;
  report_id: string;
  report_name: string;
  data_mode: DataMode;
  as_of: string | null;
  total_rows: number;
  truncated: boolean;
  warnings: string[];
  access_note: string | null;
  run_id?: string;
}

export interface Column { key: string; label: string; type: string; unit?: string; aggregation?: string }

export interface Evidence extends EvidenceSummary {
  tool: string;
  folder_path: string[];
  connector_status: string;
  request: {filters: {field: string; values: string[]}[]; group_by: string[] | null; measures: string[] | null; limit: number};
  columns: Column[];
  rows: (string | number | null)[][];
  retrieved_at: string;
  digest: string;
  caveats: string[];
  locator: {system: string; report_id: string; open_url: string | null};
}

export interface Visual {
  id: string;
  kind: 'bar' | 'line' | 'scatter' | 'table';
  title: string;
  subtitle: string | null;
  columns: {key: string; label: string; type: string; unit: string | null}[];
  rows: (string | number | null)[][];
  x: string | null;
  series: string[];
  evidence_ids: string[];
  note: string | null;
  derived_by: string;
}

export interface CheckClaim { label: string; status: 'MATCH' | 'DISCREPANCY' | 'PERIOD_MISMATCH' | 'NOT_VERIFIABLE'; stated_value: number; recomputed_value: number | null; notes: string[] }
export interface CheckResult { overall: 'CHECKED' | 'DISCREPANCY' | 'NOT_VERIFIABLE'; summary: string; claims: CheckClaim[]; replays: {evidence_id: string; status: string; detail: string}[] }

export interface RunEvent { seq: number; type: string; ts: string; payload: Record<string, any> }

export interface RunRecord {
  id: string;
  conversation_id: string;
  kind: 'ask' | 'check';
  question: string;
  status: RunStatus;
  runtime: RuntimeKind;
  runtime_label: string;
  model: string;
  session_id: string | null;
  data_mode: DataMode | null;
  check_status: CheckStatus;
  check_summary: string | null;
  answer: string | null;
  report_id: string | null;
  error_code: string | null;
  error_message: string | null;
  parent_run_id: string | null;
  created_at: string;
  finished_at: string | null;
  events: RunEvent[];
  visuals: Visual[];
  evidence: EvidenceSummary[];
  active: boolean;
}

export interface TimelineItem {
  key: string;
  kind: 'tool' | 'note' | 'warning' | 'status';
  label: string;
  state?: 'running' | 'ok' | 'error';
  name?: string;
  category?: string;
  summary?: string;
  evidence?: EvidenceSummary;
  durationMs?: number;
}

export interface RunView {
  id: string;
  conversationId: string;
  kind: 'ask' | 'check';
  question: string;
  status: RunStatus;
  runtime: RuntimeKind;
  runtimeLabel: string;
  model: string;
  timeline: TimelineItem[];
  streamText: string;
  answer: string | null;
  visuals: Visual[];
  evidence: EvidenceSummary[];
  check: CheckResult | null;
  checkStatus: CheckStatus;
  checkSummary: string | null;
  dataMode: DataMode | null;
  reportId: string | null;
  error: {code: string; message: string} | null;
  /** Raw diagnostics the server attached to this run (CLI output, setup, tracebacks). */
  diagnostics: Record<string, unknown>[];
  warnings: string[];
  lastSeq: number;
  createdAt: string;
  finishedAt: string | null;
  parentRunId: string | null;
}

export interface Report {
  id: string;
  run_id: string;
  conversation_id: string;
  created_at: string;
  expires_at: string;
  question: string;
  kind: 'ask' | 'check';
  answer: string;
  notes: string[];
  visuals: Visual[];
  evidence: Evidence[];
  data_mode: DataMode | null;
  runtime: {kind: RuntimeKind; label: string; model: string; session_id: string | null};
  check: {status: CheckStatus; summary: string | null; checked_by_run?: string; checked_at?: string};
  warnings: string[];
  user: {name: string; role: string};
  timeline: {type: string; payload: Record<string, any>}[];
}

export interface SourceSummary {
  id: string; name: string; description: string; families: string[]; connector_status: string; data_mode: DataMode;
  live_interface: string; owner: string; reports: number; reports_with_rows: number; markets: 'all' | string[];
}

export interface CatalogReport {
  id: string; name: string; folder: string; type: 'report' | 'dossier'; row_access: 'ROWS' | 'NAVIGATION_ONLY';
  description: string; as_of: string | null; refresh: string; prompts: {key: string; label: string}[]; measures: string[];
  sensitivity: string; status: string;
}

export interface SourceCatalog {
  system: {id: string; name: string; connector_status: string; data_mode: DataMode; open_url_template: string | null};
  folders: {id: string; name: string; parent: string | null}[];
  reports: CatalogReport[];
}
