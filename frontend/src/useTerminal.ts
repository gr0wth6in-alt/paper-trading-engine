import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';
import type { Snapshot } from './types';

export function useTerminal(token: string, initial: Snapshot, onExpired: () => void) {
  const [snapshot, setSnapshot] = useState(initial);
  const [receivedAt, setReceivedAt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [socketState, setSocketState] = useState('connecting');
  const [socketReceivedAt, setSocketReceivedAt] = useState(0);
  const [refreshError, setRefreshError] = useState('');
  const expireRef = useRef(onExpired);
  expireRef.current = onExpired;
  const accept = useCallback((data: Snapshot) => {
    if (data.type !== 'snapshot' || data.mode !== 'paper' || !data.account || !data.markets || !Array.isArray(data.positions)) throw new Error('Invalid snapshot');
    setSnapshot(data);
    setReceivedAt(Date.now());
  }, []);
  const refresh = useCallback(async () => {
    try {
      accept(await api<Snapshot>(token, '/status'));
      setRefreshError('Backend responded. Waiting for a live snapshot connection.');
    } catch (error) {
      setRefreshError(error instanceof Error ? error.message : 'Backend check failed.');
      if (error instanceof ApiError && error.status === 401) expireRef.current();
    }
  }, [token, accept]);

  useEffect(() => {
    let disposed = false;
    let socket: WebSocket | null = null;
    let retryTimer = 0;
    let backoff = 1000;
    let lastMessage = Date.now();
    const connect = () => {
      if (disposed) return;
      setSocketState('connecting');
      lastMessage = Date.now();
      socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`);
      socket.onopen = () => socket?.send(JSON.stringify({ token }));
      socket.onmessage = (event) => {
        if (disposed) return;
        try {
          accept(JSON.parse(event.data));
          lastMessage = Date.now();
          setSocketReceivedAt(lastMessage);
          setRefreshError('');
          backoff = 1000;
          setSocketState('connected');
        } catch { socket?.close(); }
      };
      socket.onclose = (event) => {
        if (disposed) return;
        setSocketState('disconnected');
        if (event.code === 1008) {
          setSocketState('rejected');
          void api<Snapshot>(token, '/status').catch((error) => {
            if (error instanceof ApiError && error.status === 401) expireRef.current();
          });
          return;
        }
        retryTimer = window.setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, 15000);
      };
      socket.onerror = () => socket?.close();
    };
    connect();
    const clock = window.setInterval(() => {
      setNow(Date.now());
      if (Date.now() - lastMessage > 6000 && socket && socket.readyState < WebSocket.CLOSING) {
        setSocketState('disconnected');
        socket.close();
      }
    }, 500);
    return () => { disposed = true; clearTimeout(retryTimer); clearInterval(clock); socket?.close(); };
  }, [token, accept]);

  const elapsed = receivedAt ? Math.max(0, now - receivedAt) : Infinity;
  const socketAge = socketReceivedAt ? Math.max(0, now - socketReceivedAt) : Infinity;
  return { snapshot, socketState, elapsed, refreshError, live: socketState === 'connected' && socketAge < 4000, refresh };
}