"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, LogEntry, Run, StreamEvent, api, isTerminal, streamUrl } from "./api";

/**
 * Poll an async source on an interval that can depend on the data itself.
 *
 * The previous dashboard scheduled its next poll from inside an effect with an
 * empty dependency array, so the closure captured `runs` from the *first*
 * render — permanently empty. "Is anything running?" was therefore always
 * false and the fast refresh path never activated. Here the interval is
 * recomputed from a ref holding the latest value, so it stays correct without
 * tearing down and rebuilding the timer on every tick.
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalFor: (data: T | null) => number,
  deps: unknown[] = [],
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  const dataRef = useRef<T | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelledRef = useRef(false);
  const intervalForRef = useRef(intervalFor);
  const fetcherRef = useRef(fetcher);

  // Kept fresh in an effect rather than assigned during render: a render can be
  // discarded or replayed, and mutating a ref there makes the stored callback
  // depend on which renders happened to commit.
  useEffect(() => {
    intervalForRef.current = intervalFor;
    fetcherRef.current = fetcher;
  });

  const hasLoadedRef = useRef(false);

  const load = useCallback(async () => {
    try {
      const result = await fetcherRef.current();
      if (cancelledRef.current) return;
      hasLoadedRef.current = true;
      dataRef.current = result;
      setData(result);
      setError(null);
    } catch (err) {
      if (cancelledRef.current) return;
      setError(err instanceof ApiError ? err : new ApiError(0, "Unexpected error"));
    } finally {
      if (!cancelledRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    cancelledRef.current = false;

    const tick = async () => {
      // Skip *repeat* polls while the tab is hidden, but always perform the
      // first one: a tab opened in the background is hidden from the moment it
      // mounts, and skipping its initial fetch leaves it stuck on skeletons
      // until the user happens to focus it.
      if (!document.hidden || !hasLoadedRef.current) await load();
      if (cancelledRef.current) return;
      timerRef.current = setTimeout(tick, intervalForRef.current(dataRef.current));
    };

    void tick();

    // A hidden tab that becomes visible should refresh immediately rather than
    // showing stale data until the timer next fires.
    const onVisible = () => {
      if (!document.hidden) void load();
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      cancelledRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      document.removeEventListener("visibilitychange", onVisible);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, refresh: load };
}

export interface StreamState {
  logs: LogEntry[];
  connected: boolean;
  reconnecting: boolean;
  droppedCount: number;
}

const MAX_BUFFERED_LOGS = 5000;
const MAX_RECONNECT_DELAY_MS = 15_000;

/**
 * Subscribe to a run's event stream.
 *
 * Three things the previous implementation did not do:
 *
 *  - **Backfill.** It only rendered events that arrived after the socket
 *    opened, so opening a run already in progress showed an empty console.
 *    History is fetched first, and the socket resumes from the last sequence
 *    number held.
 *  - **Reconnect.** A dropped socket stayed dropped; the UI kept claiming it
 *    was live. Reconnection uses exponential backoff and resumes from the last
 *    sequence rather than replaying from zero.
 *  - **Deduplicate.** Backfill and the live feed overlap at the boundary.
 *    Events are keyed by sequence number so a reconnect cannot double-render.
 *
 * `runId` is expected to be stable for the lifetime of the component. Render the
 * consumer with `key={runId}` so switching runs remounts it — that is cheaper
 * and less error-prone than resetting six pieces of state in an effect.
 */
export function useRunStream(runId: string, live: boolean): StreamState {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [droppedCount, setDroppedCount] = useState(0);

  const seenSeqRef = useRef<Set<number>>(new Set());
  const lastSeqRef = useRef(0);
  const socketRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const closedRef = useRef(false);

  const append = useCallback((entry: LogEntry) => {
    if (entry.seq > 0) {
      if (seenSeqRef.current.has(entry.seq)) return;
      seenSeqRef.current.add(entry.seq);
      lastSeqRef.current = Math.max(lastSeqRef.current, entry.seq);
    }
    setLogs((previous) => {
      const next = [...previous, entry];
      if (next.length <= MAX_BUFFERED_LOGS) return next;
      // Drop from the head: a long run must not grow the DOM without bound.
      const overflow = next.length - MAX_BUFFERED_LOGS;
      setDroppedCount((count) => count + overflow);
      return next.slice(overflow);
    });
  }, []);

  // Archived runs: one fetch, no socket.
  useEffect(() => {
    if (live) return;
    let cancelled = false;
    api
      .getLogs(runId, 0)
      .then(({ logs: history }) => {
        if (cancelled) return;
        history.forEach(append);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [runId, live, append]);

  // Live runs: backfill, then hold a socket open with reconnection.
  useEffect(() => {
    if (!live) return;
    closedRef.current = false;

    const connect = () => {
      if (closedRef.current) return;

      const socket = new WebSocket(streamUrl(runId, lastSeqRef.current));
      socketRef.current = socket;

      socket.onopen = () => {
        retryRef.current = 0;
        setConnected(true);
        setReconnecting(false);
      };

      socket.onmessage = (event) => {
        let parsed: StreamEvent;
        try {
          parsed = JSON.parse(event.data);
        } catch {
          return;
        }

        // Control frames carry no agent and are not log lines.
        if (parsed.type === "ping") {
          socket.send("pong");
          return;
        }
        if (parsed.type === "ready" || !parsed.agent) return;

        append({
          id: `${parsed.seq ?? Date.now()}`,
          seq: parsed.seq ?? 0,
          agent: parsed.agent,
          log_type: parsed.type,
          content: parsed.content ?? "",
          timestamp: parsed.timestamp ?? new Date().toISOString(),
        });
      };

      socket.onclose = () => {
        setConnected(false);
        if (closedRef.current) return;

        setReconnecting(true);
        retryRef.current += 1;
        const delay = Math.min(500 * 2 ** retryRef.current, MAX_RECONNECT_DELAY_MS);
        window.setTimeout(connect, delay);
      };

      socket.onerror = () => socket.close();
    };

    connect();

    return () => {
      closedRef.current = true;
      socketRef.current?.close();
      setConnected(false);
      setReconnecting(false);
    };
  }, [runId, live, append]);

  return { logs, connected, reconnecting, droppedCount };
}

/** Poll a single run, backing off once it reaches a terminal state. */
export function useRun(runId: string) {
  return usePolling<Run>(
    () => api.getRun(runId),
    (run) => (run && isTerminal(run.status) ? 60_000 : 4_000),
    [runId],
  );
}

/** Close on Escape and trap focus inside a dialog. */
export function useDialog(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    const previouslyFocused = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("input, button, textarea")?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab" || !ref.current) return;

      const focusable = ref.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    // Prevent the page behind the dialog from scrolling.
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = overflow;
      previouslyFocused?.focus();
    };
  }, [open, onClose]);

  return ref;
}
