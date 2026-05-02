'use client';

/**
 * SSE-based trace stream hook.
 *
 * Why fetch + ReadableStream instead of EventSource:
 *   - EventSource cannot set custom headers, but the API requires a bearer
 *     token. A fetch read of `text/event-stream` lets us pass `Authorization`
 *     while still consuming the same SSE wire format.
 *
 * Why a polling fallback:
 *   - Reverse proxies (nginx default config, some cloud LBs) buffer SSE,
 *     making the stream unusable. The hook keeps a polling timer alive
 *     until the first SSE frame arrives; if we never receive one within
 *     the warm-up window, we abandon SSE and stay on polling.
 *
 * Lifecycle:
 *   - Caller passes querySessionId + token. The hook returns the latest
 *     trace + status. It tears down the SSE reader and the polling timer
 *     when the component unmounts or status reaches a terminal state.
 */

import { useEffect, useRef, useState } from 'react';

import { api } from './api';
import type { QueryTraceResponse } from './api-types';

const TERMINAL_STATUSES = new Set(['completed', 'abstained', 'failed']);
// Wait this long for the first SSE frame before deciding the upstream is
// buffering us into oblivion and falling back to polling.
const SSE_WARMUP_MS = 4_000;
const POLL_INTERVAL_MS = 2_000;

export interface TraceStreamState {
  data: QueryTraceResponse | undefined;
  error: Error | undefined;
  isStreaming: boolean;
  transport: 'sse' | 'poll' | 'idle';
}

export function useTraceStream(
  querySessionId: string | undefined,
  token: string | undefined,
): TraceStreamState {
  const [data, setData] = useState<QueryTraceResponse>();
  const [error, setError] = useState<Error>();
  const [transport, setTransport] = useState<'sse' | 'poll' | 'idle'>('idle');
  const [isStreaming, setIsStreaming] = useState(false);
  const cleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!querySessionId) {
      setTransport('idle');
      setIsStreaming(false);
      return;
    }

    let aborted = false;
    const controller = new AbortController();
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let warmupTimer: ReturnType<typeof setTimeout> | null = null;
    let receivedSseFrame = false;

    const stopPolling = () => {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    };

    const startPolling = () => {
      if (pollTimer) return;
      setTransport('poll');
      pollTimer = setInterval(async () => {
        try {
          const trace = await api.getTrace(querySessionId, token);
          if (aborted) return;
          setData(trace);
          if (TERMINAL_STATUSES.has(trace.status)) {
            stopPolling();
            setIsStreaming(false);
          }
        } catch (e) {
          if (aborted) return;
          setError(e instanceof Error ? e : new Error(String(e)));
        }
      }, POLL_INTERVAL_MS);
    };

    const consumeSse = async () => {
      setIsStreaming(true);
      setTransport('sse');

      const url = `/api/query/${encodeURIComponent(querySessionId)}/trace/stream`;
      try {
        const res = await fetch(url, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: controller.signal,
          cache: 'no-store',
        });
        if (!res.ok || !res.body) {
          throw new Error(`SSE upgrade failed (${res.status})`);
        }

        warmupTimer = setTimeout(() => {
          if (!receivedSseFrame) startPolling();
        }, SSE_WARMUP_MS);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (!aborted) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          // SSE messages are separated by a blank line.
          let sep = buffer.indexOf('\n\n');
          while (sep !== -1) {
            const frame = buffer.slice(0, sep);
            buffer = buffer.slice(sep + 2);
            const parsed = parseSseFrame(frame);
            if (parsed) {
              receivedSseFrame = true;
              // First successful frame — kill the polling fallback if it started.
              stopPolling();
              setTransport('sse');
              if (parsed.event === 'trace' && parsed.data) {
                try {
                  const trace = JSON.parse(parsed.data) as QueryTraceResponse;
                  setData(trace);
                  if (TERMINAL_STATUSES.has(trace.status)) {
                    setIsStreaming(false);
                    return;
                  }
                } catch {
                  // ignore malformed frame
                }
              } else if (parsed.event === 'done' || parsed.event === 'timeout') {
                setIsStreaming(false);
                return;
              }
            }
            sep = buffer.indexOf('\n\n');
          }
        }
        setIsStreaming(false);
      } catch (e) {
        if (aborted) return;
        // SSE failed before terminal — try polling so the user still sees data.
        startPolling();
        setError(e instanceof Error ? e : new Error(String(e)));
      } finally {
        if (warmupTimer) clearTimeout(warmupTimer);
      }
    };

    void consumeSse();

    cleanupRef.current = () => {
      aborted = true;
      controller.abort();
      stopPolling();
      if (warmupTimer) clearTimeout(warmupTimer);
    };
    return () => cleanupRef.current?.();
  }, [querySessionId, token]);

  return { data, error, isStreaming, transport };
}

interface ParsedFrame {
  event: string;
  data: string;
}

function parseSseFrame(frame: string): ParsedFrame | null {
  const lines = frame.split('\n');
  let event = 'message';
  const dataLines: string[] = [];
  for (const raw of lines) {
    if (!raw || raw.startsWith(':')) continue; // comment / keepalive
    const idx = raw.indexOf(':');
    if (idx === -1) continue;
    const field = raw.slice(0, idx);
    // SSE allows an optional space after the colon.
    const value = raw.slice(idx + 1).replace(/^ /, '');
    if (field === 'event') event = value;
    else if (field === 'data') dataLines.push(value);
  }
  if (dataLines.length === 0 && event === 'message') return null;
  return { event, data: dataLines.join('\n') };
}
