import type {
  AsrTranscribeResponse,
  BigFivePersonality,
  CoachReport,
  DocumentRecord,
  EmployeeSearchResponse,
  EmployeeProfile,
  GuidanceReport,
  RehearsalContextUpdatePayload,
  RehearsalMessageOptions,
  SessionState,
  SetupOptions,
  TtsSpeechOptions,
} from '../types/domain';
import { getApiBase } from '../utils/format';

const REQUEST_TIMEOUT_MS = 180000;

function redirectToLoginOnUnauthorized(response: Response, path: string) {
  if (response.status !== 401 || path.startsWith('/auth')) return;
  if (!window.location.pathname.startsWith('/login')) {
    window.location.href = '/login';
  }
}

export function getWsApiBase(): string {
  const apiBase = getApiBase();
  const url = new URL(apiBase, window.location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString().replace(/\/$/, '');
}

async function parseResponse(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
}

function detailFromPayload(payload: unknown): string {
  if (!payload || typeof payload !== 'object') return String(payload || '请求失败');
  const data = payload as Record<string, unknown>;
  const detail = data.detail ?? data.error ?? data.message ?? data.raw;
  if (typeof detail === 'string') return detail;
  return JSON.stringify(detail ?? data);
}

async function requestJson<T>(path: string, options: RequestInit & { timeoutMs?: number | null } = {}): Promise<T> {
  const controller = new AbortController();
  const { timeoutMs = REQUEST_TIMEOUT_MS, ...fetchOptions } = options;
  const timeout = typeof timeoutMs === 'number' && timeoutMs > 0
    ? window.setTimeout(() => controller.abort(), timeoutMs)
    : null;
  try {
    const response = await fetch(getApiBase() + path, {
      ...fetchOptions,
      signal: controller.signal,
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(fetchOptions.headers || {}),
      },
    });
    const payload = await parseResponse(response);
    redirectToLoginOnUnauthorized(response, path);
    if (!response.ok) throw new Error(detailFromPayload(payload));
    return payload as T;
  } finally {
    if (timeout !== null) window.clearTimeout(timeout);
  }
}

async function requestForm<T>(
  path: string,
  body: FormData,
  options: { timeoutMs?: number | null } = {},
): Promise<T> {
  const controller = new AbortController();
  const { timeoutMs = REQUEST_TIMEOUT_MS } = options;
  const timeout = typeof timeoutMs === 'number' && timeoutMs > 0
    ? window.setTimeout(() => controller.abort(), timeoutMs)
    : null;
  try {
    const response = await fetch(getApiBase() + path, {
      method: 'POST',
      body,
      signal: controller.signal,
      credentials: 'include',
    });
    const payload = await parseResponse(response);
    redirectToLoginOnUnauthorized(response, path);
    if (!response.ok) throw new Error(detailFromPayload(payload));
    return payload as T;
  } finally {
    if (timeout !== null) window.clearTimeout(timeout);
  }
}

async function requestBlob(path: string, options: RequestInit & { timeoutMs?: number | null } = {}): Promise<Blob> {
  const controller = new AbortController();
  const { timeoutMs = REQUEST_TIMEOUT_MS, ...fetchOptions } = options;
  const timeout = typeof timeoutMs === 'number' && timeoutMs > 0
    ? window.setTimeout(() => controller.abort(), timeoutMs)
    : null;
  try {
    const response = await fetch(getApiBase() + path, {
      ...fetchOptions,
      signal: controller.signal,
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(fetchOptions.headers || {}),
      },
    });
    if (!response.ok) {
      redirectToLoginOnUnauthorized(response, path);
      throw new Error(detailFromPayload(await parseResponse(response)));
    }
    return await response.blob();
  } finally {
    if (timeout !== null) window.clearTimeout(timeout);
  }
}

export async function streamSse<T = Record<string, unknown>>(
  path: string,
  options: RequestInit,
  onEvent: (event: string, data: T) => void,
): Promise<void> {
  const response = await fetch(getApiBase() + path, {
    ...options,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    redirectToLoginOnUnauthorized(response, path);
    throw new Error(detailFromPayload(await parseResponse(response)));
  }
  if (!response.body) throw new Error('当前浏览器不支持流式响应。');

  const nextFrame = () => new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));

  const dispatchChunk = async (chunk: string) => {
    const lines = chunk.split('\n').map((line) => line.trimEnd());
    let eventName = 'message';
    const dataLines: string[] = [];
    for (const line of lines) {
      if (line.startsWith('event:')) eventName = line.slice(6).trim();
      if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
    }
    const dataText = dataLines.join('\n') || '{}';
    const data = JSON.parse(dataText) as T;
    if (eventName === 'error') throw new Error(detailFromPayload(data));
    onEvent(eventName, data);
    await nextFrame();
  };

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const chunks = buffer.split('\n\n');
    buffer = chunks.pop() || '';
    for (const chunk of chunks) {
      if (chunk.trim()) await dispatchChunk(chunk);
    }
    if (done) {
      if (buffer.trim()) await dispatchChunk(buffer);
      break;
    }
  }
}

export const api = {
  createSession: () => requestJson<SessionState>('/sessions', { method: 'POST', body: JSON.stringify({}), timeoutMs: 15000 }),
  listSessions: () => requestJson<SessionState[]>('/sessions', { timeoutMs: 30000 }),
  getSession: (sessionId: string) => requestJson<SessionState>(`/sessions/${sessionId}`, { timeoutMs: 30000 }),
  deleteSession: (sessionId: string) => requestJson<SessionState>(`/sessions/${sessionId}`, { method: 'DELETE', timeoutMs: 30000 }),
  setupOptions: () => requestJson<SetupOptions>('/setup/options', { timeoutMs: 30000 }),
  searchEmployees: (params: URLSearchParams) => requestJson<EmployeeSearchResponse>(`/employees?${params.toString()}`, { timeoutMs: 30000 }),
  uploadDocument: (formData: FormData) => requestForm<DocumentRecord>('/documents/upload', formData, { timeoutMs: null }),
  transcribeAudio: (audio: Blob, sessionId?: string | null, language = 'zh') => {
    const formData = new FormData();
    const ext = audio.type.includes('wav') ? 'wav' : audio.type.includes('mp4') ? 'mp4' : audio.type.includes('ogg') ? 'ogg' : 'webm';
    formData.append('file', audio, `speech.${ext}`);
    if (sessionId) formData.append('session_id', sessionId);
    formData.append('language', language);
    return requestForm<AsrTranscribeResponse>('/asr/transcribe', formData);
  },
  synthesizeSpeech: (text: string, options?: TtsSpeechOptions) => requestBlob('/tts/speech', {
    method: 'POST',
    body: JSON.stringify({
      text,
      voice: options?.voice || undefined,
      response_format: options?.responseFormat || undefined,
      speed: options?.speed || undefined,
    }),
    timeoutMs: null,
  }),
  uploadText: (sessionId: string | null, text: string) => requestJson<DocumentRecord>('/documents/text', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, text, filename: 'employee_profile_combined.txt' }),
  }),
  confirmProfile: (sessionId: string, profile: EmployeeProfile) => requestJson<SessionState>(`/setup/${sessionId}/profile`, {
    method: 'PATCH',
    body: JSON.stringify({ profile }),
  }),
  confirmIntent: (sessionId: string, intentId: string | null, freeText: string | null) => requestJson<SessionState>(`/setup/${sessionId}/intent`, {
    method: 'PATCH',
    body: JSON.stringify({ intent_id: intentId, free_text: freeText }),
  }),
  confirmPersona: (sessionId: string, personaId: string, difficultyId: string) => requestJson<SessionState>(`/setup/${sessionId}/persona`, {
    method: 'PATCH',
    body: JSON.stringify({ persona_id: personaId, difficulty_id: difficultyId, run_mode: 'guidance_then_rehearsal' }),
  }),
  confirmSimulation: (sessionId: string, personality: BigFivePersonality, primaryMotiveId: string, secondaryMotiveIds: string[]) => requestJson<SessionState>(`/setup/${sessionId}/simulation`, {
    method: 'PATCH',
    body: JSON.stringify({ personality, primary_motive_id: primaryMotiveId, secondary_motive_ids: secondaryMotiveIds, run_mode: 'guidance_then_rehearsal' }),
  }),
  completeSetup: (sessionId: string) => requestJson<SessionState>(`/setup/${sessionId}/complete`, { method: 'POST', body: '{}' }),
  generateGuidance: (sessionId: string) => requestJson<GuidanceReport>(`/guidance/${sessionId}`, { method: 'POST', body: '{}' }),
  streamGuidance: (sessionId: string, onEvent: (event: string, data: Record<string, unknown>) => void) =>
    streamSse(`/guidance/${sessionId}/stream`, { method: 'POST', body: '{}' }, onEvent),
  streamRehearsalMessage: (
    sessionId: string,
    message: string,
    options: RehearsalMessageOptions | undefined,
    onEvent: (event: string, data: Record<string, unknown>) => void,
  ) => streamSse(`/rehearsal/${sessionId}/message/stream`, {
    method: 'POST',
    body: JSON.stringify({ message, input_mode: options?.inputMode || 'text', audio_emotion: options?.audioEmotion || null }),
  }, onEvent),
  sendRehearsalMessage: (sessionId: string, message: string, options?: RehearsalMessageOptions) => requestJson<SessionState>(`/rehearsal/${sessionId}/message`, {
    method: 'POST',
    body: JSON.stringify({ message, input_mode: options?.inputMode || 'text', audio_emotion: options?.audioEmotion || null }),
    timeoutMs: null,
  }),
  updateRehearsalContext: (sessionId: string, payload: RehearsalContextUpdatePayload) => requestJson<SessionState>(`/rehearsal/${sessionId}/context`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }),
  endRehearsal: (sessionId: string) => requestJson<SessionState>(`/rehearsal/${sessionId}/end`, { method: 'POST', body: '{}' }),
  streamCoachReport: (sessionId: string, onEvent: (event: string, data: Record<string, unknown>) => void) =>
    streamSse(`/reports/${sessionId}/coach/stream`, { method: 'POST', body: '{}' }, onEvent),
  generateCoachReport: (sessionId: string) => requestJson<CoachReport>(`/reports/${sessionId}/coach`, { method: 'POST', body: '{}', timeoutMs: null }),
};
