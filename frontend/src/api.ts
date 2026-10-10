export class ApiError extends Error {
  constructor(message: string, public status: number, public code: string = 'request_failed') {
    super(message);
    this.name = 'ApiError';
  }
}

export async function api<T>(token: string, path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  options.signal?.addEventListener('abort', abort, { once: true });
  if (options.signal?.aborted) controller.abort();
  const timer = window.setTimeout(abort, 18000);
  try {
    const response = await fetch(`/api/v1${path}`, {
      ...options, cache: 'no-store', signal: controller.signal,
      headers: { Authorization: `Bearer ${token}`, ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers },
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = typeof data?.detail === 'string' ? data.detail : 'Check the submitted values.';
      throw new ApiError(data?.error?.message || (response.status === 401 ? 'API token rejected. Reconnect with your local token.' : detail), response.status, data?.error?.code);
    }
    if (data === null) throw new ApiError('The backend returned an unreadable response.', 0);
    return data as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError('Backend unreachable or request timed out. Keep start.cmd open on this computer.', 0, 'connection_error');
  } finally {
    window.clearTimeout(timer);
    options.signal?.removeEventListener('abort', abort);
  }
}

export function uncertain(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true;
  const rejectedBeforeExecution = ['feed_unavailable', 'stale_quote'];
  return error.status === 0 || (error.status >= 500 && !rejectedBeforeExecution.includes(error.code));
}
export async function apiBlob(token: string, path: string, signal?: AbortSignal): Promise<Blob> {
  const timeout = AbortSignal.timeout(10000);
  const response = await fetch(`/api/v1${path}`, { cache: 'no-store', headers: { Authorization: `Bearer ${token}` }, signal: signal ? AbortSignal.any([signal, timeout]) : timeout });
  if (!response.ok) throw new ApiError('Local image unavailable.', response.status);
  return response.blob();
}
export function message(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed. Please retry.';
}