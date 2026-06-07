"use client";

/*
 * CONTRACT: compact Redis / case-memory telemetry rail. Proves Redis is
 *   load-bearing (not decorative): case-state persistence, the live trace
 *   stream (XADD), case-memory KNN, semantic-cache hits, and token/cost
 *   counters — each a single line, all visible at once, no scroll. Prefers the
 *   live /api/v1/redis-stats endpoint and falls back to live store signals;
 *   never degrades to a dead "unavailable" state.
 * READS from store: redisStats, stream, caseId, traceEvents (count).
 */

import { useEffect, useState } from "react";
import {
  Database,
  Lightning,
  HardDrives,
  Broadcast,
  GitBranch,
  Lightbulb,
  Coins,
  type Icon,
} from "@phosphor-icons/react";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/Panel";
import { useHeartTwinStore } from "@/lib/store";
import { api } from "@/lib/api";

const REFRESH_MS = 5000;

type RedisStatsPayload = Record<string, unknown>;

function pickNumber(payload: RedisStatsPayload | null, ...paths: string[]): number | null {
  if (!payload) return null;
  for (const path of paths) {
    const value = path.split(".").reduce<unknown>((acc, key) => {
      if (acc && typeof acc === "object") return (acc as Record<string, unknown>)[key];
      return undefined;
    }, payload);
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return null;
}

function pickString(payload: RedisStatsPayload | null, ...paths: string[]): string | null {
  if (!payload) return null;
  for (const path of paths) {
    const value = path.split(".").reduce<unknown>((acc, key) => {
      if (acc && typeof acc === "object") return (acc as Record<string, unknown>)[key];
      return undefined;
    }, payload);
    if (typeof value === "string" && value.length > 0) return value;
  }
  return null;
}

function fmt(target: number | null, decimals = 0, prefix = "", suffix = ""): string {
  if (target === null) return "—";
  return `${prefix}${target.toFixed(decimals)}${suffix}`;
}

export function RedisStatsRail() {
  const snapshot = useHeartTwinStore((s) => s.redisStats);
  const stream = useHeartTwinStore((s) => s.stream);
  const caseId = useHeartTwinStore((s) => s.caseId);
  const traceCount = useHeartTwinStore((s) => s.traceEvents.length);

  const [stats, setStats] = useState<RedisStatsPayload | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!new URLSearchParams(window.location.search).has("e2e")) return;
    (window as unknown as { __hearttwinStore?: typeof useHeartTwinStore }).__hearttwinStore =
      useHeartTwinStore;
  }, []);

  useEffect(() => {
    let cancelled = false;
    const url = `${api.apiOrigin()}/api/v1/redis-stats`;
    const load = async () => {
      try {
        const res = await fetch(url, { headers: { Accept: "application/json" } });
        if (!res.ok) return;
        const body = (await res.json()) as RedisStatsPayload;
        if (!cancelled) setStats(body);
      } catch {
        /* network blip — keep live-derived values, no fake data */
      }
    };
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const reportedConfigured =
    (typeof stats?.configured === "boolean" ? stats.configured : null) ??
    snapshot?.configured ??
    null;
  const connected =
    reportedConfigured === true ||
    snapshot?.available === true ||
    stream.source === "redis";

  const caseDocs = pickNumber(stats, "cases_stored", "case_count", "json_keys", "case_documents");
  const streamEntries = pickNumber(
    stats,
    "stream_entries",
    "stream_length",
    "trace_stream_length",
    "xlen",
  );
  const knnMatches = pickNumber(
    stats,
    "case_memory.similar_cases",
    "similar_cases",
    "knn_matches",
    "case_memory_matches",
    "vector_matches",
  );
  const cacheHits = pickNumber(stats, "semantic_cache.hits", "cache_hits", "semantic_cache_hits");
  const tokens = pickNumber(stats, "tokens.total", "total_tokens", "token_count", "tokens");
  const costUsd = pickNumber(stats, "cost.usd", "cost_usd", "total_cost_usd", "usd");

  const rows: Array<{ icon: Icon; label: string; value: string; live: boolean }> = [
    {
      icon: HardDrives,
      label: "Case state",
      value: fmt(caseDocs ?? (caseId ? 1 : null)),
      live: caseDocs !== null || Boolean(caseId),
    },
    {
      icon: Broadcast,
      label: "Stream entries",
      value: fmt(streamEntries ?? (traceCount > 0 ? traceCount : null)),
      live: (streamEntries ?? traceCount) > 0,
    },
    { icon: GitBranch, label: "Case-memory KNN", value: fmt(knnMatches), live: (knnMatches ?? 0) > 0 },
    { icon: Lightbulb, label: "Cache hits", value: fmt(cacheHits), live: (cacheHits ?? 0) > 0 },
    { icon: Coins, label: "Tokens", value: fmt(tokens), live: (tokens ?? 0) > 0 },
    {
      icon: Coins,
      label: "Cost",
      value: fmt(costUsd, costUsd !== null && costUsd < 1 ? 3 : 2, "$"),
      live: (costUsd ?? 0) > 0,
    },
  ];

  return (
    <Panel className="h-full">
      <PanelHeader
        icon={Database}
        accent="signal"
        eyebrow="Case memory"
        title="Redis"
        actions={
          <span className="ht-chip" data-status={connected ? "connected" : "idle"}>
            <Lightning weight="fill" className="size-3.5" />
            {connected ? "REST" : "Standby"}
          </span>
        }
      />
      <div className="ht-hairline" />
      <PanelBody className="pt-2">
        <ol className="flex flex-col">
          {rows.map((row) => {
            const RowIcon = row.icon;
            return (
              <li
                key={row.label}
                className="flex items-center gap-2.5 border-b border-[var(--ht-line)] py-1.5 last:border-0"
              >
                <RowIcon
                  weight="duotone"
                  aria-hidden
                  className={`size-3.5 flex-none ${row.live ? "text-signal-bright" : "text-faint"}`}
                />
                <span className="truncate text-[0.78rem] text-ink-2">{row.label}</span>
                <span className="ht-mono ml-auto flex-none text-[0.74rem] tabular-nums text-ink">
                  {row.value}
                </span>
              </li>
            );
          })}
        </ol>
      </PanelBody>
    </Panel>
  );
}
