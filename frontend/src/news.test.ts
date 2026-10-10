import { describe, expect, it } from 'vitest';
import { newsQuery, safeHref } from './news';
import { timeAgo } from './format';

describe('news helpers', () => {
  it('allows only absolute http(s) links', () => {
    expect(safeHref('https://www.coindesk.com/a?b=1')).toBe('https://www.coindesk.com/a?b=1');
    expect(safeHref('http://example.test')).toBe('http://example.test/');
    for (const bad of ['javascript:alert(1)', 'JaVaScRiPt:alert(1)', ' javascript:alert(1)', 'data:text/html,hi', 'vbscript:x', '/relative', '//evil.test/x', 'https://user:pw@example.test/', 'not a url', '', null, 42, 'https://' + 'a'.repeat(2050)]) {
      expect(safeHref(bad)).toBeNull();
    }
  });
  it('formats relative time at each boundary', () => {
    const now = Date.parse('2026-10-10T12:00:00Z');
    const at = (ms: number) => new Date(now - ms).toISOString();
    expect(timeAgo(at(59_000), now)).toBe('just now');
    expect(timeAgo(at(60_000), now)).toBe('1m ago');
    expect(timeAgo(at(59 * 60_000), now)).toBe('59m ago');
    expect(timeAgo(at(3_600_000), now)).toBe('1h ago');
    expect(timeAgo(at(23 * 3_600_000), now)).toBe('23h ago');
    expect(timeAgo(at(86_400_000), now)).toBe('1d ago');
    expect(timeAgo(new Date(now + 60_000).toISOString(), now)).toBe('just now');
    expect(timeAgo('garbage', now)).toBe('—');
    expect(timeAgo(null, now)).toBe('—');
  });
  it('builds encoded, bounded news queries', () => {
    expect(newsQuery({ limit: 20, offset: 0 })).toBe('/news?limit=20&offset=0');
    expect(newsQuery({ source: 'The Block', q: '  eth & etf ', symbol: 'ETH/USDT:USDT', limit: 3, offset: 40 }))
      .toBe('/news?source=The+Block&q=eth+%26+etf&symbol=ETH%2FUSDT%3AUSDT&limit=3&offset=40');
    expect(newsQuery({ q: 'x'.repeat(150), limit: 1, offset: 0 })).toContain(`q=${'x'.repeat(100)}&`);
  });
});
