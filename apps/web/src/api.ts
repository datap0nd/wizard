import type {BrainLive, BrainMap} from './brain';
import type {AccessForm, Answer, Attachment, Bootstrap, Cadence, ConversationSummary, Evidence, GeminiAccount, GeminiQuota, LocalFile, Memory, PortalCheck, PortalStatus, RecurringList, Report, RunRecord, SavedFile, Schedule, SettingsSaved, SettingsView, SourceCatalog, SourceSummary, Steer, SteerReason, UpdateInfo} from './types';

/** What a note to Wizard did: reached the running answer (steer), or became the next question (follow_up). */
export interface SteerResult {
  steer?: Steer;
  follow_up?: {run_id: string; conversation_id: string; question: string; systems: string[] | null};
}

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string, public loginRequired = false) { super(message); }
}

/** Signs this page in again when its session has lapsed (set by the app: fixture sign-in, as the same person). */
let renewal: (() => Promise<void>) | null = null;
let renewing: Promise<boolean> | null = null;
/** Called when the session has lapsed and could not be renewed: the app shows sign-in. */
let signedOut: (() => void) | null = null;

export function onSession(handlers: {renew: (() => Promise<void>) | null; signedOut: () => void}) {
  renewal = handlers.renew;
  signedOut = handlers.signedOut;
}

/** One renewal for every request that found the session lapsed at the same time. */
function renew(): Promise<boolean> {
  if (!renewal) return Promise.resolve(false);
  renewing ??= renewal().then(() => true, () => false).finally(() => { renewing = null; });
  return renewing;
}

async function request<T>(path: string, init: {method?: string; body?: unknown; file?: File} = {}, again = true): Promise<T> {
  const method = init.method ?? (init.body === undefined && !init.file ? 'GET' : 'POST');
  const headers: Record<string, string> = {};
  if (method !== 'GET') headers['X-Wizard-Request'] = '1';
  let body: BodyInit | undefined;
  if (init.file) {
    headers['Content-Type'] = 'application/octet-stream';
    headers['X-File-Name'] = encodeURIComponent(init.file.name);
    body = init.file;
  } else if (init.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(init.body);
  }
  const response = await fetch(path, {method, headers, body, credentials: 'same-origin'});
  let payload: Record<string, any> = {};
  try { payload = await response.json(); } catch { /* not JSON */ }
  if (!response.ok) {
    if (payload.login_required) {
      // A Wizard left open outlives its session: sign in again as the same person and send the request once more.
      if (again && await renew()) return request<T>(path, init, false);
      signedOut?.();
    }
    const fallback = response.status === 429 ? 'A question is already running.' : 'The request failed.';
    throw new ApiError(payload.error ?? fallback, response.status, payload.code, !!payload.login_required);
  }
  return payload as T;
}

export const api = {
  bootstrap: () => request<Bootstrap>('/api/v1/bootstrap'),
  brain: () => request<BrainMap>('/api/v1/brain'),
  brainLive: () => request<BrainLive>('/api/v1/brain/live'),
  devLog: () => request<{lines: string[]}>('/api/v1/dev/log'),
  quota: (refresh = false) => request<GeminiQuota>(`/api/v1/account/gemini/quota${refresh ? '?refresh=true' : ''}`),
  identities: () => request<{identities: {id: string; name: string; role: string; email: string}[]; notice: string}>('/api/v1/session/identities'),
  login: (userId: string) => request<{ok: true}>('/api/v1/session/login', {body: {user_id: userId}}),
  logout: () => request<{ok: true}>('/api/v1/session/logout', {body: {}}),
  conversations: (q?: string) => request<{conversations: ConversationSummary[]}>('/api/v1/conversations' + (q ? `?q=${encodeURIComponent(q)}` : '')),
  conversation: (id: string) => request<{conversation: ConversationSummary; runs: RunRecord[]}>(`/api/v1/conversations/${encodeURIComponent(id)}`),
  rename: (id: string, title: string) => request<{ok: true}>(`/api/v1/conversations/${encodeURIComponent(id)}`, {method: 'PATCH', body: {title}}),
  remove: (id: string) => request<{ok: true}>(`/api/v1/conversations/${encodeURIComponent(id)}`, {method: 'DELETE'}),
  ask: (question: string, conversationId: string | null, attachmentIds: string[] = [], systems: string[] | null = null) =>
    request<{run_id: string; conversation_id: string; attachments: Attachment[]}>('/api/v1/runs', {body: {question, conversation_id: conversationId, attachment_ids: attachmentIds, systems}}),
  steer: (runId: string, note: {text?: string; call_id?: string; reason?: SteerReason}) =>
    request<SteerResult>(`/api/v1/runs/${encodeURIComponent(runId)}/steer`, {body: {text: note.text ?? '', call_id: note.call_id ?? null, reason: note.reason ?? null}}),
  setSystems: (runId: string, systems: string[] | null) => request<{systems: string[] | null}>(`/api/v1/runs/${encodeURIComponent(runId)}/systems`, {body: {systems}}),
  memories: () => request<{memories: Memory[]}>('/api/v1/memories'),
  remember: (text: string, runId: string | null = null) => request<{memory: Memory}>('/api/v1/memories', {body: {text, run_id: runId}}),
  editMemory: (id: string, text: string) => request<{ok: true}>(`/api/v1/memories/${encodeURIComponent(id)}`, {method: 'PATCH', body: {text}}),
  forget: (id: string) => request<{ok: true}>(`/api/v1/memories/${encodeURIComponent(id)}`, {method: 'DELETE'}),
  upload: (file: File) => request<{attachment: Attachment}>('/api/v1/attachments', {file}),
  localFiles: (q = '') => request<{enabled: boolean; folders: string[]; files: LocalFile[]}>('/api/v1/attachments/local' + (q ? `?q=${encodeURIComponent(q)}` : '')),
  attachLocal: (path: string) => request<{attachment: Attachment}>('/api/v1/attachments/local', {body: {path}}),
  removeAttachment: (id: string) => request<{ok: true}>(`/api/v1/attachments/${encodeURIComponent(id)}`, {method: 'DELETE'}),
  saveFile: (id: string) => request<{saved: SavedFile}>(`/api/v1/attachments/${encodeURIComponent(id)}/save`, {body: {}}),
  openFile: (id: string) => request<{ok: true}>(`/api/v1/attachments/${encodeURIComponent(id)}/open`, {body: {}}),
  check: (runId: string) => request<{run_id: string; conversation_id: string}>(`/api/v1/runs/${encodeURIComponent(runId)}/check`, {body: {}}),
  run: (runId: string) => request<RunRecord>(`/api/v1/runs/${encodeURIComponent(runId)}`),
  recurring: (runId: string, cadence: Cadence | null) => request<{run_id: string; conversation_id: string; question: string}>(`/api/v1/runs/${encodeURIComponent(runId)}/recurring`, {body: {cadence}}),
  createSchedule: (id: string) => request<{schedule: Schedule}>(`/api/v1/schedules/${encodeURIComponent(id)}/create`, {body: {}}),
  dismissSchedule: (id: string) => request<{schedule: Schedule}>(`/api/v1/schedules/${encodeURIComponent(id)}/dismiss`, {body: {}}),
  schedulePreview: (id: string) => request<{html: string}>(`/api/v1/schedules/${encodeURIComponent(id)}/preview`),
  recurringList: () => request<RecurringList>('/api/v1/recurring'),
  deleteRecurring: (id: string) => request<{deleted: boolean; flow_id: number | null; missing: boolean}>(`/api/v1/recurring/${encodeURIComponent(id)}/delete`, {body: {}}),
  cancel: (runId: string) => request<{cancelled: boolean}>(`/api/v1/runs/${encodeURIComponent(runId)}/cancel`, {body: {}}),
  emailDraft: (runId: string, subject: string, html: string) => request<{ok: true}>(`/api/v1/runs/${encodeURIComponent(runId)}/email`, {body: {subject, html}}),
  feedback: (runId: string, category: string, note = '') => request<{ok: true}>(`/api/v1/runs/${encodeURIComponent(runId)}/feedback`, {body: {category, note}}),
  evidence: (conversationId: string, evidenceId: string) => request<{evidence: Evidence}>(`/api/v1/conversations/${encodeURIComponent(conversationId)}/evidence/${encodeURIComponent(evidenceId)}`),
  report: (id: string) => request<{report: Report}>(`/api/v1/reports/${encodeURIComponent(id)}`),
  sources: () => request<{sources: SourceSummary[]}>('/api/v1/sources'),
  catalog: (system: string) => request<SourceCatalog>(`/api/v1/sources/${encodeURIComponent(system)}/catalog`),
  account: () => request<GeminiAccount>('/api/v1/account/gemini'),
  linkStart: () => request<{authorize_url: string; state: string; instructions: string}>('/api/v1/account/gemini/link', {body: {}}),
  linkComplete: (state: string, code: string) => request<GeminiAccount>('/api/v1/account/gemini/link/complete', {body: {state, code}}),
  unlink: () => request<GeminiAccount>('/api/v1/account/gemini', {method: 'DELETE'}),
  settings: () => request<SettingsView>('/api/v1/settings'),
  saveSettings: (values: Record<string, string | null>) => request<SettingsSaved>('/api/v1/settings', {method: 'PUT', body: {values}}),
  testSettings: (section: 'postgres' | 'knowledge' | 'metronome', values: Record<string, string | null>) =>
    request<{ok: boolean; message: string}>('/api/v1/settings/test', {body: {section, values}}),
  updates: (refresh = false) => request<UpdateInfo>(`/api/v1/updates${refresh ? '?refresh=true' : ''}`),
  portals: () => request<PortalStatus>('/api/v1/portals'),
  portalSignIn: () => request<PortalStatus>('/api/v1/portals/sign-in', {body: {}}),
  portalSignedIn: () => request<PortalStatus>('/api/v1/portals/sign-in/done', {body: {}}),
  portalCheck: () => request<PortalCheck>('/api/v1/portals/check', {body: {}}),
  accessForm: (system: string) => request<AccessForm>(`/api/v1/portals/${encodeURIComponent(system)}/access-form`),
  saveAccessForm: (system: string, form: {page: string; fields: Answer[]}) =>
    request<AccessForm>(`/api/v1/portals/${encodeURIComponent(system)}/access-form`, {body: form}),
  openAccessRequest: (system: string, request_: {address?: string; tables?: string[]; answers?: Answer[]} = {}) =>
    request<PortalStatus>(`/api/v1/portals/${encodeURIComponent(system)}/access-request`, {body: request_}),
  health: () => request<{status: string; version: string}>('/api/v1/health'),
};

export function eventsUrl(runId: string, after: number) {
  return `/api/v1/runs/${encodeURIComponent(runId)}/events?after=${after}`;
}
