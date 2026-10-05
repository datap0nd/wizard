import type {Attachment, Bootstrap, ConversationSummary, Evidence, GeminiAccount, GeminiQuota, LocalFile, Report, RunRecord, SourceCatalog, SourceSummary} from './types';

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string, public loginRequired = false) { super(message); }
}

async function request<T>(path: string, init: {method?: string; body?: unknown; file?: File} = {}): Promise<T> {
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
    const fallback = response.status === 429 ? 'A question is already running.' : 'The request failed.';
    throw new ApiError(payload.error ?? fallback, response.status, payload.code, !!payload.login_required);
  }
  return payload as T;
}

export const api = {
  bootstrap: () => request<Bootstrap>('/api/v1/bootstrap'),
  devLog: () => request<{lines: string[]}>('/api/v1/dev/log'),
  quota: (refresh = false) => request<GeminiQuota>(`/api/v1/account/gemini/quota${refresh ? '?refresh=true' : ''}`),
  identities: () => request<{identities: {id: string; name: string; role: string; email: string}[]; notice: string}>('/api/v1/session/identities'),
  login: (userId: string) => request<{ok: true}>('/api/v1/session/login', {body: {user_id: userId}}),
  logout: () => request<{ok: true}>('/api/v1/session/logout', {body: {}}),
  conversations: (q?: string) => request<{conversations: ConversationSummary[]}>('/api/v1/conversations' + (q ? `?q=${encodeURIComponent(q)}` : '')),
  conversation: (id: string) => request<{conversation: ConversationSummary; runs: RunRecord[]}>(`/api/v1/conversations/${encodeURIComponent(id)}`),
  rename: (id: string, title: string) => request<{ok: true}>(`/api/v1/conversations/${encodeURIComponent(id)}`, {method: 'PATCH', body: {title}}),
  remove: (id: string) => request<{ok: true}>(`/api/v1/conversations/${encodeURIComponent(id)}`, {method: 'DELETE'}),
  ask: (question: string, conversationId: string | null, attachmentIds: string[] = []) => request<{run_id: string; conversation_id: string; attachments: Attachment[]}>('/api/v1/runs', {body: {question, conversation_id: conversationId, attachment_ids: attachmentIds}}),
  upload: (file: File) => request<{attachment: Attachment}>('/api/v1/attachments', {file}),
  localFiles: (q = '') => request<{enabled: boolean; folders: string[]; files: LocalFile[]}>('/api/v1/attachments/local' + (q ? `?q=${encodeURIComponent(q)}` : '')),
  attachLocal: (path: string) => request<{attachment: Attachment}>('/api/v1/attachments/local', {body: {path}}),
  removeAttachment: (id: string) => request<{ok: true}>(`/api/v1/attachments/${encodeURIComponent(id)}`, {method: 'DELETE'}),
  check: (runId: string) => request<{run_id: string; conversation_id: string}>(`/api/v1/runs/${encodeURIComponent(runId)}/check`, {body: {}}),
  run: (runId: string) => request<RunRecord>(`/api/v1/runs/${encodeURIComponent(runId)}`),
  cancel: (runId: string) => request<{cancelled: boolean}>(`/api/v1/runs/${encodeURIComponent(runId)}/cancel`, {body: {}}),
  feedback: (runId: string, category: string, note = '') => request<{ok: true}>(`/api/v1/runs/${encodeURIComponent(runId)}/feedback`, {body: {category, note}}),
  evidence: (conversationId: string, evidenceId: string) => request<{evidence: Evidence}>(`/api/v1/conversations/${encodeURIComponent(conversationId)}/evidence/${encodeURIComponent(evidenceId)}`),
  report: (id: string) => request<{report: Report}>(`/api/v1/reports/${encodeURIComponent(id)}`),
  sources: () => request<{sources: SourceSummary[]}>('/api/v1/sources'),
  catalog: (system: string) => request<SourceCatalog>(`/api/v1/sources/${encodeURIComponent(system)}/catalog`),
  account: () => request<GeminiAccount>('/api/v1/account/gemini'),
  linkStart: () => request<{authorize_url: string; state: string; instructions: string}>('/api/v1/account/gemini/link', {body: {}}),
  linkComplete: (state: string, code: string) => request<GeminiAccount>('/api/v1/account/gemini/link/complete', {body: {state, code}}),
  unlink: () => request<GeminiAccount>('/api/v1/account/gemini', {method: 'DELETE'}),
};

export function eventsUrl(runId: string, after: number) {
  return `/api/v1/runs/${encodeURIComponent(runId)}/events?after=${after}`;
}
