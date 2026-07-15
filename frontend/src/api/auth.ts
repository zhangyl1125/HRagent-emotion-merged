import type { AdminAccount, AdminAccountsResponse, AuthMeResponse, AuthResponse } from '../types/auth';
import { getApiBase } from '../utils/format';

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

let csrfToken: string | null = null;

async function getCsrfToken(): Promise<string> {
  if (csrfToken) return csrfToken;
  const response = await fetch(`${getApiBase()}/auth/csrf`, { credentials: 'include' });
  if (!response.ok) throw new Error('无法获取安全令牌。');
  csrfToken = (await response.json() as { csrf_token: string }).csrf_token;
  return csrfToken;
}

async function authRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isAdminWrite = (path.startsWith('/admin/') || path.startsWith('/auth/admin/')) && !['GET', 'HEAD'].includes((options.method || 'GET').toUpperCase());
  const headers = new Headers(options.headers);
  headers.set('Content-Type', 'application/json');
  if (isAdminWrite) headers.set('X-CSRF-Token', await getCsrfToken());
  const response = await fetch(`${getApiBase()}${path}`, {
    ...options,
    credentials: 'include',
    headers,
  });
  const payload = await parseResponse(response);
  if (!response.ok) throw new Error(detailFromPayload(payload));
  return payload as T;
}

export async function login(email: string, password: string) {
  return authRequest<AuthResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
}

export async function register(email: string, password: string, displayName?: string) {
  return authRequest<AuthResponse>('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password, display_name: displayName || null }),
  });
}

export async function getMe() {
  return authRequest<AuthMeResponse>('/auth/me');
}

export async function logout() {
  return authRequest<AuthResponse>('/auth/logout', { method: 'POST', body: '{}' });
}


export async function listAdminAccounts() {
  return authRequest<AdminAccountsResponse>('/auth/admin/accounts');
}

export async function createAdminAccount(email: string, password: string, displayName?: string) {
  return authRequest<AdminAccount>('/auth/admin/accounts', {
    method: 'POST',
    body: JSON.stringify({ email, password, display_name: displayName || null }),
  });
}

export async function deleteAdminAccount(email: string) {
  return authRequest<AuthResponse>(`/auth/admin/accounts/${encodeURIComponent(email)}`, {
    method: 'DELETE',
  });
}

export async function resetAdminPassword(email: string, password: string) {
  return authRequest<AdminAccount>(`/auth/admin/accounts/${encodeURIComponent(email)}/password`, {
    method: 'PATCH',
    body: JSON.stringify({ password }),
  });
}

export async function updateAdminWhitelist(email: string, enabled: boolean) {
  return authRequest<AdminAccount>('/auth/admin/whitelist', {
    method: 'PUT',
    body: JSON.stringify({ email, enabled }),
  });
}
