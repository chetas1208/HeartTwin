"use client";

/*
 * useTraceStream — opens an EventSource to the backend SSE trace stream for a
 * case and appends decoded events to the Zustand store.
 *
 * - Resume: EventSource sends Last-Event-ID automatically on its own reconnect.
 *   On a fresh mount we resume from the store's lastEventId via the URL param so
 *   a remount (or navigation) does not replay the whole trace.
 * - No polling fallback: the backend SSE endpoint is the single transport.
 * - Cleanup: the connection is closed on unmount or when caseId/enabled change.
 */

import { useEffect, useRef } from "react";
import { traceStreamUrl } from "@/lib/api";
import { useHeartTwinStore } from "@/lib/store";
import type { TraceEvent } from "@/lib/store";

interface UseTraceStreamOptions {
  /** Disable the connection (e.g. before a case exists). Default true. */
  enabled?: boolean;
}

function decode(raw: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(raw);
    return typeof parsed === "object" && parsed !== null
      ? (parsed as Record<string, unknown>)
      : { value: parsed };
  } catch {
    return { raw };
  }
}

function readSource(payload: Record<string, unknown>): "redis" | "local" | "unknown" {
  const source = payload.source;
  if (source === "redis" || source === "local") return source;
  return "unknown";
}

export function useTraceStream(
  caseId: string | null,
  { enabled = true }: UseTraceStreamOptions = {},
): void {
  const appendTraceEvent = useHeartTwinStore((s) => s.appendTraceEvent);
  const setStreamMeta = useHeartTwinStore((s) => s.setStreamMeta);
  const clearTrace = useHeartTwinStore((s) => s.clearTrace);
  const previousCaseId = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled || !caseId) return;

    // A new case must never resume from a previous case's event id (it would
    // skip the new case's opening events). Clear first, then start fresh. A
    // remount of the SAME case resumes from the last id we already hold.
    const isNewCase = previousCaseId.current !== caseId;
    if (isNewCase) {
      clearTrace();
      previousCaseId.current = caseId;
    }
    const lastId = isNewCase
      ? undefined
      : useHeartTwinStore.getState().stream.lastEventId ?? undefined;
    const url = traceStreamUrl(caseId, lastId);
    const source = new EventSource(url);
    let closed = false;

    source.onopen = () => {
      if (!closed) setStreamMeta({ connected: true, error: null });
    };

    const handle = (evt: MessageEvent) => {
      const payload = decode(evt.data);
      const inner =
        payload.payload && typeof payload.payload === "object"
          ? (payload.payload as Record<string, unknown>)
          : payload;
      const kind =
        (typeof inner.kind === "string" && inner.kind) ||
        (typeof payload.kind === "string" && payload.kind) ||
        evt.type ||
        "trace";
      const event: TraceEvent = {
        id: evt.lastEventId || `evt-${Date.now()}`,
        kind,
        receivedAt: Date.now(),
        payload,
      };
      appendTraceEvent(event);

      const streamSource = readSource(payload);
      if (streamSource !== "unknown") {
        setStreamMeta({ source: streamSource });
      }
    };

    // The backend emits typed SSE events (stream_setup, agent_stage,
    // tool_call, ...). EventSource only routes named events to addEventListener,
    // and unnamed ones to onmessage. We cover both: onmessage for default, plus
    // explicit listeners for the known kinds.
    source.onmessage = handle;
    const namedEvents = [
      "stream_setup",
      "agent_stage",
      "tool_call",
      "redis_error",
      "trace",
    ];
    for (const name of namedEvents) {
      source.addEventListener(name, handle as EventListener);
    }

    source.onerror = () => {
      if (closed) return;
      // EventSource auto-reconnects; reflect transient disconnect in the store.
      setStreamMeta({
        connected: false,
        error:
          source.readyState === EventSource.CLOSED
            ? "Trace stream closed"
            : "Reconnecting to trace stream",
      });
    };

    return () => {
      closed = true;
      for (const name of namedEvents) {
        source.removeEventListener(name, handle as EventListener);
      }
      source.close();
      setStreamMeta({ connected: false });
    };
  }, [caseId, enabled, appendTraceEvent, setStreamMeta, clearTrace]);
}
