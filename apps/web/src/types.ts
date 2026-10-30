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
  /** steering: a note reaches Gemini while it works (otherwise a note stops the run and asks again). */
  runtime?: {kind: RuntimeKind; label: string; model: string; ready: boolean; reason: string | null; steering?: boolean};
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
  /** Recurring extractions in Metronome: whether this person can set them up, and the Metronome user that owns them. */
  metronome?: {enabled: boolean; user: string | null};
  /** The Pages site (Brain and Cases): this person may publish to it from this PC. */
  site?: {enabled: boolean};
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
  /** edited: a copy Wizard made with wizard_edit_attachment, to download. */
  origin: 'upload' | 'local' | 'edited';
  status: 'ok' | 'failed' | 'empty';
  method: string | null;
  chars: number;
  note: string | null;
  parts: number;
  created_at: string;
  run_id: string | null;
}

/** A file Wizard saved in the person's Downloads folder itself (Download where Wizard runs on their own PC). */
export interface SavedFile {
  filename: string;
  folder: string;
  /** excel: Excel wrote the copy (protected workbooks stay openable); copy: the bytes were copied. */
  method: 'excel' | 'copy';
  warnings: string[];
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
  /** A report's folders in its system (its module). */
  folder_path?: string[];
  /** A database query's SQL, so the card can name the tables it read. */
  sql?: string | null;
}

export interface Column { key: string; label: string; type: string; unit?: string; aggregation?: string }

export interface Evidence extends EvidenceSummary {
  tool: string;
  folder_path: string[];
  connector_status: string;
  /** Report and file queries: filters and grouping. PostgreSQL: the SQL Gemini wrote and the database it ran on. */
  request: {filters?: {field: string; values: string[]}[]; group_by?: string[] | null; measures?: string[] | null; limit?: number;
            sql?: string; database?: string; max_rows?: number;
            /** A portal read: the steps Gemini ran in the person's browser, and the page it ended on. */
            steps?: PortalStep[]; page?: string | null; page_title?: string | null; script_name?: string | null};
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

export type RunKind = 'ask' | 'check' | 'recurring';

/** The Make recurring menu's choices; null: Gemini asks how often. */
export type Cadence = 'daily' | 'weekly' | 'monthly';

/** What a brief section shows; the full spec lives on the server (wizard_connectors/brief.py). */
export interface BriefSection {
  kind: 'numbers' | 'chart' | 'table';
  title: string | null;
  subtitle: string | null;
  sql: string;
  chart: 'bar' | 'line' | null;
}

/** A recurring brief Gemini proposed (R1, R2...): a newsletter email Metronome sends on a schedule. Only the person's
 *  click creates it in Metronome, where the Flow belongs to Metronome's Wizard user. A proposal made before briefs has
 *  one `sql` and no `brief`. */
export interface Schedule {
  id: string;
  label: string;
  run_id: string;
  status: 'proposed' | 'creating' | 'created' | 'failed' | 'uncertain' | 'dismissed' | 'deleting' | 'deleted';
  kind?: 'brief';
  title: string;
  brief?: {title: string; intro: string | null; period_sql: string | null; sections: BriefSection[]};
  sql?: string;
  database: string | null;
  recipients: string[];
  frequency: 'daily' | 'weekly' | 'monthly';
  time: string;
  days: string[];
  day_of_month: number | null;
  file_format: 'xlsx';
  subject: string | null;
  schedule_text: string;
  evidence_id?: string;
  evidence_ids?: string[];
  metronome_user: string;
  requested_by: {name: string | null};
  created_at: string;
  /** A brief's test run (period, read time, rows per section); a proposal from before briefs kept its first rows. */
  preview: {period?: string | null; read_at?: string | null; rows?: unknown[]; columns?: string[]; rows_in_test?: number; more?: boolean};
  flow: {id: number | null; name: string; owner: string; enabled: boolean | null; next_run_at: string | null; url: string} | null;
  error: string | null;
}

/** A Flow as Metronome reports it to the Recurring tab. */
export interface MetronomeFlow {
  missing: boolean;
  name?: string;
  enabled?: boolean;
  owner?: string | null;
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_status?: string | null;
  last_error?: string | null;
  runs?: {id: number; status: string; trigger: string | null; at: string | null; error: string | null; email: string | null}[];
}

export interface RecurringItem extends Schedule { metronome: MetronomeFlow | null }
export interface RecurringList { items: RecurringItem[]; sync: {ok: boolean; message: string | null} }

export interface RunRecord {
  id: string;
  conversation_id: string;
  kind: RunKind;
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
  schedules?: Schedule[];
  /** The systems the person chose for this question; null is Auto. */
  systems?: string[] | null;
  active: boolean;
}

/** One step of a run, as a note about it names it (Not this). */
export interface StepAbout { call_id: string; name: string | null; label: string | null; detail: string | null; evidence_id: string | null }

export type SteerReason = 'table' | 'filter' | 'period' | 'other';

/** A note the person sent Wizard while it worked: waiting until Gemini's next step, then read. */
export interface Steer { id: string; text: string; reason: SteerReason | null; about: StepAbout | null; at: string; state: 'waiting' | 'read' }

/** Gemini asked for a system the person switched off for this question. */
export interface SystemRequest { system: string; name: string; reason: string }

/** A note the person asked Wizard to remember: it goes into every question they ask. */
export interface Memory { id: string; text: string; run_id: string | null; created_at: string }

export interface TimelineItem {
  key: string;
  /** steer: a note the person sent while Wizard worked. */
  kind: 'tool' | 'note' | 'warning' | 'status' | 'steer';
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
  kind: 'reports' | 'portal' | 'database' | 'knowledge' | 'files' | 'schedules';
  data_mode?: DataMode;
  notes?: number;
}

export interface PortalStep { action: string; url?: string; selector?: string; role?: string; name?: string; text?: string; frame?: string;
  value?: string; script?: string }

/** The company portals Gemini reads in this person's own Wizard browser. */
export interface PortalStatus {
  browser: string;
  /** A visible Wizard browser window is open: the person's sign-in, or an access request form. */
  signing_in: boolean;
  window?: 'sign_in' | 'access_request' | null;
  /** The open access request window: the saved answers it filled, and those it found no field for. */
  access_request?: {system: string; filled: string[]; missing: string[]};
  running: boolean;
  last_sign_in: string | null;
  /** parts: the applications of a portal that has several (the Big Data Portal's Superset and information catalog). */
  portals: {id: string; name: string; host: string; parts?: {id: string; name: string; host: string}[]; access_requests?: boolean}[];
  /** What Wizard learned exploring each portal, and the portal being mapped now (one per person). */
  maps?: Record<string, PortalMapStatus>;
  mapping?: PortalMapping | null;
}

/** A portal's map: Gemini's exploration of it, kept on this PC and published to the knowledge base when it can. */
export interface PortalMapStatus {
  system: string;
  updated: string | null;
  has_overview: boolean;
  topics: number;
  reports: number;
  reports_todo: number;
  reports_mapped: number;
  reports_partial: number;
  reports_failed: number;
  reports_skipped: number;
  published?: {at: string; outcome: string; message: string; commit: string | null} | null;
  /** Where the map comes from: this PC's own, the knowledge base's published copy, or none yet. */
  source: 'this_pc' | 'knowledge_base' | 'none';
  can_publish: boolean;
}

export interface PortalMapping {
  system: string;
  conversation_id: string;
  started_at: string;
  round: number;
  run_id: string | null;
  state: 'running' | 'finished' | 'stopped' | 'failed';
  message: string;
}

export interface PortalMapView { map: PortalMapStatus; mapping: PortalMapping | null; message?: string }

/** A task from the Wizard repository's tasks/ folder (Settings → Tasks) and its last run on this PC. */
export interface TaskItem {
  id: string;
  title: string;
  summary: string;
  added: string | null;
  state: 'todo' | 'running' | 'done' | 'failed' | 'stopped';
  conversation_id: string | null;
  at: string | null;
  message: string | null;
}

export interface TasksView {
  tasks: TaskItem[];
  /** github: read from GitHub just now or earlier; bundled: the copy that came with this version. */
  source: 'github' | 'bundled';
  checked: number | null;
  message: string | null;
  /** This PC has the knowledge base's write token, so a task can save what it produces. */
  can_save: boolean;
}

export interface Answer { label: string; value: string }

/** The answers this person gives on every access request in a portal's information catalog, kept on their PC. */
export interface AccessForm {
  system: string;
  /** The catalog's request page, when it has one for every request ('' when not saved). */
  page: string;
  fields: Answer[];
  /** Labels Wizard saw on the request form the last time it was open. */
  seen: string[];
  /** Where a request opens when nothing else names a page: the catalog's start page. */
  default_page: string;
}

/** An access request Gemini prepared: the person opens the form, checks it and submits it themselves. */
export interface AccessRequest {
  id: string;
  system: string;
  portal: string;
  address: string;
  tables: string[];
  /** This request's own answers; the saved ones (by label) are filled too. */
  answers: Answer[];
  saved: string[];
}

export interface PortalCheck {
  portals: {id: string; name: string; signed_in: boolean; title?: string; host?: string; error?: string}[];
}

export interface RunView {
  id: string;
  conversationId: string;
  kind: RunKind;
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
  /** Why the run failed. `details` is what Error details shows (Google's reason and words, the last tool call...),
   * label -> value, as the server recorded it; runs that failed before it was recorded have none. */
  error: {code: string; message: string; details?: Record<string, string>} | null;
  /** Raw diagnostics the server attached to this run (CLI output, setup, tracebacks). */
  diagnostics: Record<string, unknown>[];
  warnings: string[];
  lastSeq: number;
  /** Files sent with this question (F1, F2...). */
  attachments: Attachment[];
  /** Recurring extractions proposed in this answer, with their current state. */
  schedules: Schedule[];
  /** Access requests prepared in this answer, for the person to open and submit. */
  accessRequests: AccessRequest[];
  /** The systems the person chose for this question (null: Auto), as they are now. */
  systems: string[] | null;
  /** Notes the person sent while Wizard worked. */
  steers: Steer[];
  /** Systems Gemini asked the person to switch on. */
  systemRequests: SystemRequest[];
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
  kind: RunKind;
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
