/** Returns an absolute http(s) URL safe for an href, or null. Defence in depth: the backend
 *  already drops other schemes, but the browser never trusts feed data on its own. */
export function safeHref(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 2048) return null;
  let url: URL;
  try { url = new URL(value); } catch { return null; }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
  if (!url.hostname || url.username || url.password) return null;
  return url.href;
}

export function newsQuery(params: { source?: string; q?: string; symbol?: string; limit: number; offset: number }): string {
  const search = new URLSearchParams();
  if (params.source) search.set('source', params.source);
  const q = params.q?.trim().slice(0, 100);
  if (q) search.set('q', q);
  if (params.symbol) search.set('symbol', params.symbol);
  search.set('limit', String(params.limit));
  search.set('offset', String(params.offset));
  return `/news?${search.toString()}`;
}
