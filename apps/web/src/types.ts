export type DataMode = 'SYNTHETIC' | 'DATED_APPROVED_SNAPSHOT' | 'LIVE' | 'LIVE_VERIFIED' | 'USER_PROVIDED';
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

export interface QuotaBucket {
  model_id: string;
  token_type: string | null;
  remaining_fraction: number;
  used_fraction: number;
  remaining: number | null;
  limit: number | null;
  reset_time: string | null;
}

export interface GeminiQuota {
  available: boolean;
  reason?: string;
  code?: string;
  model?: string;
  selected?: QuotaBucket | null;
  buckets?: QuotaBucket[];
  fetched_at?: string;
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
  attachments?: {from_this_pc: boolean; max_mb: number};
  /** The desktop app (WizardBar) runs this copy. */
  desktop?: boolean;
  /** The person at this PC may change its settings (their own install). */
  settings_editable?: boolean;
  systems?: SystemInfo[];
}

export type SettingSource = 'environment' | 'env_file' | 'this_pc' | 'company' | 'default';

export interface SettingField {
  key: string;
  label: string;
  section: string;
  help: string;
  placeholder: string;
  choices: string[];
  secret: boolean;
  source: SettingSource;
  /** Never sent for a secret. */
  value: string | null;
  set: boolean;
  /** The company file's value (true/false for a secret). */
  company_value: string | boolean | null;
  editable: boolean;
}

export interface SettingsView {
  sections: {id: string; title: string; about: string}[];
  fields: SettingField[];
  company_file: {name: string | null; imported_at: string | null} | null;
  restart: 'automatic' | 'manual';
  model: string;
  runtime: RuntimeKind;
  desktop: boolean;
  build: {version?: string; commit?: string; built_at?: string};
  version: string;
}

export interface SettingsSaved extends SettingsView {
  changed: string[];
  /** How the change applies: now / after_run (the service restarts itself), manual (restart Wizard yourself), none. */
  apply: 'now' | 'after_run' | 'manual' | 'none';
}

export interface ModelList {current: string; options: string[]; reason: string | null; editable: boolean}

export interface UpdateInfo {
  ok?: boolean;
  installed: string | null;
  latest?: string | null;
  available?: boolean;
  download: string;
  message: string;
}

/** A file attached to a question: converted to text that Gemini reads with wizard_read_attachment. */
export interface Attachment {
  id: string;
  /** F1, F2... once sent with a question. */
  label: string | null;
  filename: string;
  kind: 'slides' | 'spreadsheet' | 'document' | 'email' | 'text';
  bytes: number;
  origin: 'upload' | 'local';
  status: 'ok' | 'failed' | 'empty';
  method: string | null;
  chars: number;
  note: string | null;
  parts: number;
  created_at: string;
  run_id: string | null;
}

export interface LocalFile { path: string; name: string; kind: Attachment['kind']; bytes: number; folder: string; modified: string }

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
  /** Report and file queries: filters and grouping. PostgreSQL: the SQL Gemini wrote and the database it ran on. */
  request: {filters?: {field: string; values: string[]}[]; group_by?: string[] | null; measures?: string[] | null; limit?: number;
            sql?: string; database?: string; max_rows?: number};
  columns: Column[];
  rows: (string | number | null)[][];
  retrieved_at: string;
  digest: string;
  caveats: string[];
  locator: {system: string; report_id: string; open_url: string | null};
  /** Attached files: the text Gemini read (no rows). */
  excerpt?: string;
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
  attachments?: Attachment[];
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
  /** Server time the step started; with RunView.startedAt it shows where a run's time went. */
  at?: string;
  /** The arguments Gemini called the tool with (the SQL, the search words, the report and filters). */
  args?: Record<string, unknown>;
}

/** A system this person's Wizard can draw on, shown on the systems stage. */
export interface SystemInfo {
  id: string;
  name: string;
  kind: 'reports' | 'database' | 'knowledge' | 'files';
  data_mode?: DataMode;
  notes?: number;
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
  /** Files sent with this question (F1, F2...). */
  attachments: Attachment[];
  createdAt: string;
  /** Server time the agent started (run_started), the zero point for each step's start time. */
  startedAt: string | null;
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
