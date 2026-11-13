import type {OrderEntry, OrderSource} from './sourceOrder';

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
  /** The Pages site (Brain and Cases): this person may publish to it from this PC; the Cases page's address when Wizard
   *  knows the site's (the Brain page links to it). */
  site?: {enabled: boolean; cases?: string | null};
}

export type SettingSource = 'environment' | 'env_file' | 'this_pc' | 'company' | 'default';

export interface SettingField {
  key: string;
  label: string;
  section: string;
  help: string;
  placeholder: string;
  choices: string[];
  /** What the person sees for each choice, when not the stored word itself. */
  choice_labels?: string[];
  /** A number between low and high, typed in `unit` (a time limit in minutes; Wizard stores it as it reads it). */
  number?: {low: number; high: number; unit: string; whole: boolean};
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
  /** Settings → Source order: the order when none is saved, the longest "use it for" line, and this PC's data sources. */
  source_order?: {default: OrderEntry[]; max_use: number; sources?: OrderSource[]};
}

/** The settings sections with a test: a connection, or (Dashboards) finding the dashboards in the folder typed. */
export type SettingsTest = 'postgres' | 'knowledge' | 'metronome' | 'dashboards' | 'nerp' | 'site';

export interface SettingsTestResult {
  ok: boolean;
  message: string;
  /** Dashboards: the path Wizard would save (a mapped drive as its network path) and how many dashboards it holds. */
  value?: string;
  count?: number;
}

/** Quick setup imported a settings file: its name, how many settings and secrets it set, and how it applies (as Save). */
export interface SettingsImported {
  name: string;
  settings: number;
  secrets: number;
  apply: 'now' | 'after_run' | 'manual';
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
            steps?: PortalStep[]; page?: string | null; page_title?: string | null; script_name?: string | null;
            /** A dashboard read: its path in the dashboards folder, the part read (text, T1, D2 or a heading) and from where. */
            dashboard?: string; path?: string; part?: string; offset?: number};
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
  kind: 'bar' | 'line' | 'scatter' | 'heatmap' | 'table';
  title: string;
  subtitle: string | null;
  columns: {key: string; label: string; type: string; unit: string | null}[];
  rows: (string | number | null)[][];
  /** Charts: the category or time column. Heatmap: the column naming each row. */
  x: string | null;
  /** Charts: the plotted columns. Heatmap: its shaded columns, in order. */
  series: string[];
  /** Heatmap: sequential (amounts) or diverging (around zero); absent: chosen by the values' signs. */
  scale?: 'sequential' | 'diverging' | null;
  evidence_ids: string[];
  note: string | null;
  derived_by: string;
  /** In the page only (answerTable.ts): the text each cell shows, where a table keeps its own wording. */
  texts?: (string | null)[][];
  /** In the page only: what a copy says its values are, where Gemini did not prepare them (a source's own rows). */
  from?: string;
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
  /** The composer's Output for this question. */
  output?: Output;
  /** Presentations made in this answer (a change is a new version that revises one). */
  decks?: Deck[];
  active: boolean;
}

/** One step of a run, as a note about it names it (Not this). */
export interface StepAbout { call_id: string; name: string | null; label: string | null; detail: string | null; evidence_id: string | null }

export type SteerReason = 'table' | 'filter' | 'period' | 'other';

/** A note the person sent Wizard while it worked: waiting until Gemini's next step, then read. */
export interface Steer { id: string; text: string; reason: SteerReason | null; about: StepAbout | null; at: string; state: 'waiting' | 'read' }

/** Gemini asked for a system the person switched off for this question. */
export interface SystemRequest { system: string; name: string; reason: string }

/** A question Gemini asked the person before going on (wizard_ask_person): each option is a button that asks it. */
export interface PersonQuestion { question: string; options: string[]; why: string | null }

/** What a question asks for (the composer's Output): an analysis in the chat, or a PowerPoint presentation. */
export type Output = 'analysis' | 'presentation';

/** One story a presentation could tell, as Gemini proposed it from the evidence. */
export interface Storyline { title: string; arc: string[]; best_for: string | null }
export interface StorylineQuestion { question: string; storylines: Storyline[]; why: string | null }

export type SlideKind = 'cover' | 'agenda' | 'section' | 'summary' | 'kpis' | 'cards' | 'chart' | 'table' | 'split' | 'grid' | 'text' | 'closing';
export type ChartStyle = 'auto' | 'column' | 'stacked' | 'percent' | 'bar' | 'stacked_bar' | 'line';
export type DeckPoint = string | {text: string; sub?: string[]};
export interface DeckKpi { value: string; label: string; change?: string; tone?: 'good' | 'bad' | 'neutral'; evidence_ids?: string[] }
export interface DeckCardItem { heading: string; points?: DeckPoint[]; value?: string }
export interface DeckHighlight { row: string; column: string; tone: 'good' | 'bad' }
export interface DeckPanel { heading?: string; visual?: string; chart?: ChartStyle; points?: DeckPoint[] }

export interface DeckSlide {
  kind: SlideKind;
  title?: string;
  subtitle?: string;
  meta?: string;
  points?: DeckPoint[];
  kpis?: DeckKpi[];
  cards?: DeckCardItem[];
  visual?: string;
  chart?: ChartStyle;
  highlights?: DeckHighlight[];
  left?: DeckPanel;
  right?: DeckPanel;
  /** grid: two to four panels, side by side (2 or 3) or two by two (4). */
  panels?: DeckPanel[];
  items?: string[];
  evidence_ids?: string[];
  footnote?: string;
  notes?: string;
}

/** The company's look (the knowledge base's presentation-look note), else Wizard's neutral design. */
export interface DesignTokens {
  name: string;
  slide: {width: number; height: number};
  fonts: {title: string; subtitle: string; body: string; labels: string; east_asian: string};
  colors: {brand: string; title: string; text: string; secondary: string; muted: string; background: string; card: string;
    line: string; good_fill: string; good_text: string; bad_fill: string; bad_text: string; positive: string; negative: string;
    series: string[]};
  sizes: {cover_title: number; cover_subtitle: number; cover_meta: number; title: number; subtitle: number; section_title: number;
    agenda: number; heading: number; body: number; kpi: number; table: number; chart_label: number; unit: number; footnote: number};
  cover: {background: 'brand' | 'white'};
  footer: {text: string; page_numbers: boolean};
  rules: {max_highlights: number; max_points: number};
}

export interface DeckSource { name: string; as_of: string | null; data_mode: string | null }

export interface Deck {
  id: string;
  run_id: string;
  title: string;
  storyline: string;
  audience: string | null;
  slides: DeckSlide[];
  design: {tokens: DesignTokens; source: 'knowledge' | 'default'; note: string | null; status: string | null; problems: string[]; about: string};
  /** The deck this one changed, its first version's id and its version number (1 for a new deck). */
  revises: string | null;
  family: string | null;
  version: number;
  visuals: Record<string, Visual>;
  sources: Record<string, DeckSource>;
  evidence_ids: string[];
  data_mode: string | null;
  created_at: string;
}

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
  kind: 'dashboards' | 'reports' | 'portal' | 'database' | 'knowledge' | 'files' | 'schedules';
  data_mode?: DataMode;
  notes?: number;
  /** The company uses it only when asked (Settings → Source order): Auto leaves it out. */
  only_when_asked?: boolean;
}

export interface PortalStep { action: string; url?: string; selector?: string; role?: string; name?: string; text?: string; frame?: string;
  value?: string; script?: string }

/** The company portals Gemini reads in this person's own Wizard browser. */
export interface PortalStatus {
  browser: string;
  /** A visible Wizard browser window is open: the person's sign-in. */
  signing_in: boolean;
  window?: 'sign_in' | null;
  running: boolean;
  last_sign_in: string | null;
  /** parts: the applications of a portal that has several (the Big Data Portal's Superset and information catalog). */
  portals: {id: string; name: string; host: string; parts?: {id: string; name: string; host: string}[]}[];
  /** What Wizard learned exploring each portal, and the portal being mapped now (one per person). */
  maps?: Record<string, PortalMapStatus>;
  mapping?: PortalMapping | null;
  sign_in?: PortalSignInState;
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
  /** What the task asks for before it runs: a folder, a file, or either (both). Absent: nothing. */
  input?: 'folder' | 'file' | 'either' | null;
  input_label?: string | null;
  /** It goes through every file of the folder, in rounds, until each is done. */
  every_file?: boolean;
  /** The path chosen last time on this PC. */
  path?: string | null;
  round?: number | null;
  /** It runs again until done (front matter repeat: until_done), at most this many times. */
  max_runs?: number | null;
  /** Files done in that folder (a task that goes through every file). */
  progress?: {total: number; done: number; left: number} | null;
}

/** A task in the person's queue. waiting: still to run; interrupted: Wizard restarted while it ran. */
export interface QueueItem {
  key: string;
  id: string;
  title: string;
  path: string | null;
  state: 'waiting' | 'running' | 'done' | 'failed' | 'stopped' | 'interrupted';
  conversation_id: string | null;
  run_id: string | null;
  /** Why it failed or stopped, how it ended, or, while it runs, its round or run (Run 2 of up to 5). */
  message: string | null;
  started_at: string | null;
  finished_at: string | null;
}

/** Tasks run one after another, the next only when the one before succeeded (Settings → Tasks). */
export interface TaskQueue {
  /** ready: filled, not started; failed / stopped / interrupted: Continue runs the task where it stopped. */
  state: 'empty' | 'ready' | 'running' | 'done' | 'failed' | 'stopped' | 'interrupted';
  items: QueueItem[];
  message: string | null;
  total: number;
  done: number;
  /** The task running, or where the queue stopped, and its place (1 is the first). */
  current: string | null;
  position: number | null;
  /** Tasks ticked for Run selected, kept until the queue starts. */
  selected: string[];
  /** Tasks Run all or Run selected left out (a path task without a path), and why. */
  left_out: {id: string; title: string; reason: string}[];
  started_at: string | null;
  finished_at: string | null;
}

/** A question in the prompt queue (Settings → Prompt queue). retry_wait: it failed and is tried again at retry_at. */
export interface PromptItem {
  key: string;
  prompt: string;
  state: 'waiting' | 'running' | 'retry_wait' | 'done' | 'failed' | 'skipped' | 'stopped' | 'interrupted';
  /** Tries so far: the first, then up to max_retries more. */
  attempts: number;
  conversation_id: string | null;
  run_id: string | null;
  message: string | null;
  started_at: string | null;
  finished_at: string | null;
  retry_at: string | null;
}

/** The person's questions one after another, each in a chat of its own, while they are away. */
export interface PromptQueue {
  state: 'empty' | 'ready' | 'running' | 'done' | 'failed' | 'stopped' | 'interrupted';
  items: PromptItem[];
  message: string | null;
  total: number;
  done: number;
  failed: number;
  current: string | null;
  position: number | null;
  started_at: string | null;
  finished_at: string | null;
  max_retries: number;
  max_prompts: number;
}

export type PromptSeparator = 'semicolon' | 'newline' | 'blank_line' | 'pipe' | 'dashes' | 'custom';

export interface TasksView {
  tasks: TaskItem[];
  /** app: the tasks come packaged with the installed version; a new task arrives with an update. */
  source: 'app';
  /** The installed version (none where Wizard was not installed from a release). */
  version?: string | null;
  /** This PC has the knowledge base's write token, so a task can save what it produces. */
  can_save: boolean;
  queue?: TaskQueue | null;
}

export interface PortalCheck {
  portals: {id: string; name: string; signed_in: boolean; portal?: string; state?: PortalSignInState['portals'][number]['state'];
    title?: string; host?: string; error?: string}[];
}

/** Whether the person is still signed in to each portal (each application of one that has several), as Wizard's
 * check in code found it (owner, 13 Nov 2026: docs/decisions/2026-11-13-portal-sign-in-check.md). Each question checks
 * the portals it may read; GET /api/v1/portals says how all of them stand. */
export interface PortalSignInState {
  portals: {
    /** The application: "gscm", or "bdp-superset" for one part of the Big Data Portal. */
    id: string;
    /** The portal it belongs to: the system id on the stage. */
    portal: string;
    name: string;
    /** signed_out: the portal showed its sign-in page. unreachable: it did not load (off the VPN, the portal down),
     * which signing in does not fix. unknown: not checked since Wizard started. */
    state: 'signed_in' | 'signed_out' | 'unreachable' | 'unknown';
    signed_in: boolean;
    /** A check of it is queued or running; `state` is what Wizard found before. */
    checking?: boolean;
    checked_at?: string;
    error?: string;
  }[];
  /** A check is queued or running (after a question, or after the sign-in window closed). */
  checking: boolean;
  /** The person's sign-in window is open. */
  signing_in: boolean;
  checked_at: string | null;
  /** Why the person signs in again now and then, in Wizard's words. */
  why: string;
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
  /** The systems the person chose for this question (null: Auto), as they are now. */
  systems: string[] | null;
  /** Notes the person sent while Wizard worked. */
  steers: Steer[];
  /** Systems Gemini asked the person to switch on. */
  systemRequests: SystemRequest[];
  questions: PersonQuestion[];
  /** Storylines Gemini proposed for a presentation: the one clicked is the next question. */
  storylines: StorylineQuestion[];
  /** Presentations made in this answer, in order (a change adds a newer version). */
  decks: Deck[];
  output: Output;
  /** The portals' sign-in check that ran beside this answer: the stage shows a portal that ended it with Sign in. */
  signIn: PortalSignInState | null;
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
