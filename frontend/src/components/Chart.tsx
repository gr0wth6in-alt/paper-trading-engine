import { useEffect, useRef, useState } from 'react';
import { CandlestickSeries, ColorType, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from 'lightweight-charts';
import { ArrowClockwise, ChartLineUp, WarningCircle } from '../icons';
import { api, message } from '../api';
import { date, price } from '../format';
import type { CandleResponse, Config } from '../types';

export function Chart({ token, symbol, config }: { token: string; symbol: string; config: Config }) {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const [timeframe, setTimeframe] = useState('5m');
  const [data, setData] = useState<CandleResponse | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const fitted = useRef(false);

  useEffect(() => {
    if (!container.current) return;
    const instance = createChart(container.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: '#131619' }, textColor: '#a7adb6', fontFamily: 'Geist Variable, sans-serif', fontSize: 11, attributionLogo: false },
      grid: { vertLines: { color: '#20252b' }, horzLines: { color: '#20252b' } },
      rightPriceScale: { borderColor: '#333a43', scaleMargins: { top: .14, bottom: .12 } },
      timeScale: { borderColor: '#333a43', timeVisible: true, secondsVisible: false },
      crosshair: { vertLine: { color: '#828991', labelBackgroundColor: '#41474f' }, horzLine: { color: '#828991', labelBackgroundColor: '#41474f' } },
      handleScroll: { vertTouchDrag: false },
    });
    chart.current = instance;
    series.current = instance.addSeries(CandlestickSeries, {
      upColor: '#56c49a', downColor: '#ef8185', borderVisible: false,
      wickUpColor: '#56c49a', wickDownColor: '#ef8185', priceLineVisible: true,
    });
    return () => { instance.remove(); chart.current = null; series.current = null; };
  }, []);

  useEffect(() => {
    let disposed = false;
    let timer = 0;
    const controller = new AbortController();
    fitted.current = false;
    setData(null); setError(''); setLoading(true);
    series.current?.setData([]);
    const load = async () => {
      try {
        const response = await api<CandleResponse>(token, `/candles?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}`, { signal: controller.signal });
        if (disposed) return;
        setData(response); setError('');
        series.current?.applyOptions({ priceFormat: { type: 'custom', formatter: price, minMove: Math.min(.01, ...response.candles.map(c => c.close > 0 ? 10 ** (Math.floor(Math.log10(c.close)) - 4) : .01)) } });
        series.current?.setData(response.candles.map(c => ({ ...c, time: c.time as UTCTimestamp })));
        if (!fitted.current && response.candles.length) { chart.current?.timeScale().fitContent(); fitted.current = true; }
      } catch (err) { if (!disposed) setError(message(err)); }
      finally { if (!disposed) { setLoading(false); timer = window.setTimeout(load, 20000); } }
    };
    void load();
    return () => { disposed = true; controller.abort(); clearTimeout(timer); };
  }, [token, symbol, timeframe, retry]);

  const last = data?.candles.at(-1);
  return <section className="chart-section" aria-label="Market chart">
    <div className="chart-toolbar">
      <div className="timeframes" aria-label="Candle timeframe">
        {config.timeframes.map(tf => <button key={tf} className={tf === timeframe ? 'selected' : ''} aria-pressed={tf === timeframe} onClick={() => setTimeframe(tf)}>{tf}</button>)}
      </div>
      <button className="icon-button" title="Reset chart view" aria-label="Reset chart view" onClick={() => chart.current?.timeScale().fitContent()}><ChartLineUp size={18} /></button>
    </div>
    <div className="ohlc mono" aria-label="Latest candle prices">
      <span>O <b>{price(last?.open)}</b></span><span>H <b>{price(last?.high)}</b></span>
      <span>L <b>{price(last?.low)}</b></span><span>C <b>{price(last?.close)}</b></span>
      <span className="muted">{last ? last.closed ? 'Closed candle' : 'Forming candle' : 'Exchange OHLCV'}</span>
    </div>
    <div className="chart-area">
      <div ref={container} className="chart-canvas" role="img" aria-label={`${symbol} ${timeframe} candlestick chart. Latest prices are listed above.`} />
      {!last && <div className="chart-empty">
        {error ? <WarningCircle size={28} weight="light" /> : <ChartLineUp size={32} weight="light" />}
        <h3>{loading ? 'Requesting exchange candles' : error ? 'Chart feed unavailable' : 'No candles returned'}</h3>
        <p>{loading ? 'Loading public OHLCV data. Quotes and paper execution use a separate feed.' : error || 'The exchange has no candles for this market and timeframe.'}</p>
        {!loading && <button className="button secondary" onClick={() => setRetry(v => v + 1)}><ArrowClockwise size={16} /> Retry candles</button>}
      </div>}
    </div>
    <div className={`chart-caption ${error && last ? 'warning-text' : ''}`}>
      <span>{error && last ? 'Refresh failed · displayed candles may be outdated' : data ? `Exchange candles · fetched ${date(data.fetched_at)}` : 'No synthetic prices · no interpolated history'}</span>
      <span>Charts by <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView</a></span>
    </div>
  </section>;
}