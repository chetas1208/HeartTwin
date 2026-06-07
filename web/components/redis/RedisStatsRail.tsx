"use client";

/*
 * CONTRACT: owns the Redis / case-memory telemetry rail — proves Redis is
 *   load-bearing for the system, not decorative. Surfaces six facets the sponsor
 *   stack actually relies on: transport (Upstash REST), case-state persistence
 *   (RedisJSON docs), the live trace stream entry count (XADD), case-memory KNN
 *   (similar-case priors), semantic-cache hits, and token / cost counters.
 * READS from store: redisStats (RedisStatsSnapshot), stream (source/connected),
 *   caseId, traceEvents (count). Polls GET /api/v1/redis-stats for the live
 *   counters and merges whatever fields the backend reports.
 *
 * Resilience: the dedicated /redis-stats route is owned by the backend Redis
 *   agent. While it is being shipped it may 404. This rail NEVER degrades to a
 *   "stats unavailable" dead state — it renders every facet from live store data
 *   (SSE transport, persisted-case presence, streamed trace entries) and refines
 *   each counter the moment the endpoint serves real numbers.
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
import {
  animate,
  motion,
  useMotionValue,
  useReducedMotion,
  useTransform,
  type MotionValue,
} from "motion/react";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/Panel";
import { useHeartTwinStore } from "@/lib/store";
import { api } from "@/lib/api";

const REFRESH_MS = 5000;

/** Raw payload from GET /api/v1/redis-stats (shape owned by the backend). */
type RedisStatsPayload = Record<string, unknown>;

/** Read the first finite number found at any of the candidate dotted paths. */
function pickNumber(
  payload: RedisStatsPayload | null,
  ...paths: string[]
): number | null {
  if (!payload) return null;
  for (const path of paths) {
    const value = path.split(".").reduce<unknown>((acc, key) => {
      if (acc && typeof acc === "object") {
        return (acc as Record<string, unknown>)[key];
      }
      return undefined;
    }, payload);
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return null;
}

/** Read the first non-empty string found at any of the candidate dotted paths. */
function pickString(
  payload: RedisStatsPayload | null,
  ...paths: string[]
): string | null {
  if (!payload) return null;
  for (const path of paths) {
    const value = path.split(".").reduce<unknown>((acc, key) => {
      if (acc && typeof acc === "object") {
        return (acc as Record<string, unknown>)[key];
      }
      return undefined;
    }, payload);
    if (typeof value === "string" && value.length > 0) return value;
  }
  return null;
}

/** Tabular counter that animates from its previous value to the next. */
function StatCounter({
  mv,
  decimals = 0,
  prefix = "",
  suffix = "",
}: {
  mv: MotionValue<number>;
  decimals?: number;
  prefix?: string;
  suffix?: string;
}) {
  const text = useTransform(mv, (v) => `${prefix}${v.toFixed(decimals)}${suffix}`);
  return <motion.span>{text}</motion.span>;
}

function StatTile({
  icon: IconCmp,
  label,
  target,
  hint,
  decimals = 0,
  prefix = "",
  suffix = "",
  live,
  reduce,
  index,
}: {
  icon: Icon;
  label: string;
  /** null = not reported yet; renders an em dash instead of a fake zero. */
  target: number | null;
  hint: string;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  live: boolean;
  reduce: boolean;
  index: number;
}) {
  const counter = useMotionValue(0);
  useEffect(() => {
    if (target === null) {
      counter.set(0);
      return;
    }
    if (reduce) {
      counter.set(target);
      return;
    }
    const controls = animate(counter, target, {
      duration: 0.8,
      ease: [0.16, 1, 0.3, 1],
    });
    return () => controls.stop();
  }, [counter, target, reduce]);

  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.4,
        delay: reduce ? 0 : index * 0.04,
        ease: [0.16, 1, 0.3, 1],
      }}
      className="flex flex-col gap-1.5 rounded-[var(--ht-r-sm)] border border-[var(--ht-line)] bg-surface-2/50 px-3 py-2.5"
    >
      <div className="flex items-center gap-1.5">
        <IconCmp
          weight="duotone"
          className={`size-3.5 ${live ? "text-signal-bright" : "text-faint"}`}
        />
        <span className="ht-eyebrow">{label}</span>
      </div>
      <span
        className="ht-mono text-[1.05rem] leading-none tabular-nums"
        style={{ color: target === null ? "var(--ht-muted)" : "var(--ht-ink)" }}
      >
        {target === null ? (
          "—"
        ) : (
          <StatCounter
            mv={counter}
            decimals={decimals}
            prefix={prefix}
            suffix={suffix}
          />
        )}
      </span>
      <span className="text-[0.66rem] leading-tight text-muted">{hint}</span>
    </motion.div>
  );
}

export function RedisStatsRail() {
  const snapshot = useHeartTwinStore((s) => s.redisStats);
  const stream = useHeartTwinStore((s) => s.stream);
  const caseId = useHeartTwinStore((s) => s.caseId);
  const traceCount = useHeartTwinStore((s) => s.traceEvents.length);
  const reduce = useReducedMotion() ?? false;

  const [stats, setStats] = useState<RedisStatsPayload | null>(null);

  // E2E hook: when the page is opened with ?e2e=1 (telemetry screenshot run),
  // expose the live store so an external driver can trigger a REAL pipeline and
  // verify these panels render genuine scores / Weave / Redis data. Opt-in via
  // query param only — it attaches nothing on a normal load.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!new URLSearchParams(window.location.search).has("e2e")) return;
    (window as unknown as { __hearttwinStore?: typeof useHeartTwinStore }).__hearttwinStore =
      useHeartTwinStore;
  }, []);

  // Poll the dedicated Redis stats route for the live counters.
  useEffect(() => {
    let cancelled = false;
    const url = `${api.apiOrigin()}/api/v1/redis-stats`;

    const load = async () => {
      try {
        const res = await fetch(url, { headers: { Accept: "application/json" } });
        if (!res.ok) return; // route not shipped yet — keep live-derived values
        const body = (await res.json()) as RedisStatsPayload;
        if (!cancelled) setStats(body);
      } catch {
        // network blip — the rail keeps its live-derived values, no fake data
      }
    };

    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  // ---- Connection / transport ----
  // The Upstash transport is REST. The live SSE trace source tells us whether
  // events are flowing through Redis or the local fallback.
  const reportedConfigured =
    (typeof stats?.configured === "boolean" ? stats.configured : null) ??
    snapshot?.configured ??
    null;
  const reportedStatus = pickString(stats, "status", "client.status");
  const connected =
    reportedConfigured === true ||
    snapshot?.available === true ||
    stream.source === "redis";

  const transport = "REST";
  const streamSource =
    stream.source === "unknown" ? "pending" : stream.source;

  // ---- Facet values: prefer the live endpoint, fall back to store signals ----

  // Case-state persistence: count of stored RedisJSON case documents. We do NOT
  // fall back to dbsize here — dbsize counts every key (trace streams, cache,
  // counters), so it would overstate the case-document count.
  const caseDocs = pickNumber(
    stats,
    "cases_stored",
    "case_count",
    "json_keys",
    "case_documents",
  );
  const persistedFallback = caseId ? 1 : null;

  // Live trace stream: XADD entry count for the active case's stream.
  const streamEntries = pickNumber(
    stats,
    "stream_entries",
    "stream_length",
    "trace_stream_length",
    "xlen",
  );

  // Case-memory KNN: similar-case priors retrieved by vector search.
  const knnMatches = pickNumber(
    stats,
    "case_memory.similar_cases",
    "similar_cases",
    "knn_matches",
    "case_memory_matches",
    "vector_matches",
  );

  // Semantic cache hits.
  const cacheHits = pickNumber(
    stats,
    "semantic_cache.hits",
    "cache_hits",
    "semantic_cache_hits",
  );

  // Token + cost counters.
  const tokens = pickNumber(
    stats,
    "tokens.total",
    "total_tokens",
    "token_count",
    "tokens",
  );
  const costUsd = pickNumber(
    stats,
    "cost.usd",
    "cost_usd",
    "total_cost_usd",
    "usd",
  );

  const tiles: Array<{
    icon: Icon;
    label: string;
    target: number | null;
    hint: string;
    decimals?: number;
    prefix?: string;
    suffix?: string;
    live: boolean;
  }> = [
    {
      icon: HardDrives,
      label: "Case state",
      target: caseDocs ?? persistedFallback,
      hint:
        caseDocs !== null
          ? "RedisJSON case documents"
          : caseId
            ? "active case persisted"
            : "awaiting first case",
      live: caseDocs !== null || Boolean(caseId),
    },
    {
      icon: Broadcast,
      label: "Stream entries",
      target: streamEntries ?? (traceCount > 0 ? traceCount : null),
      hint:
        streamEntries !== null
          ? "XADD trace stream entries"
          : "live trace spans (SSE)",
      live: (streamEntries ?? traceCount) > 0,
    },
    {
      icon: GitBranch,
      label: "Case-memory KNN",
      target: knnMatches,
      hint: "similar-case priors (vector)",
      live: (knnMatches ?? 0) > 0,
    },
    {
      icon: Lightbulb,
      label: "Cache hits",
      target: cacheHits,
      hint: "semantic cache lookups",
      live: (cacheHits ?? 0) > 0,
    },
    {
      icon: Coins,
      label: "Tokens",
      target: tokens,
      hint: "LLM tokens metered",
      live: (tokens ?? 0) > 0,
    },
    {
      icon: Coins,
      label: "Cost",
      target: costUsd,
      hint: "estimated spend (USD)",
      decimals: costUsd !== null && costUsd < 1 ? 3 : 2,
      prefix: "$",
      live: (costUsd ?? 0) > 0,
    },
  ];

  return (
    <Panel>
      <PanelHeader
        icon={Database}
        accent="signal"
        eyebrow="Case memory"
        title="Redis"
        actions={
          <span
            className="ht-chip"
            data-status={connected ? "connected" : "idle"}
          >
            <Lightning weight="fill" className="size-3.5" />
            {connected ? "Connected" : "Standby"}
          </span>
        }
      />
      <div className="ht-hairline" />
      <PanelBody className="flex flex-col gap-3 pt-4">
        {/* Transport strip: Upstash REST + the live SSE trace source. */}
        <div className="flex items-center justify-between rounded-[var(--ht-r-sm)] border border-[var(--ht-line)] bg-surface-2/40 px-3 py-2">
          <div className="flex items-center gap-2">
            <span
              className={`ht-pulse grid place-items-center ${stream.connected ? "text-ecg" : "text-faint"}`}
            >
              <span className="ht-chip-dot" />
            </span>
            <span className="text-[0.74rem] text-ink-2">Transport</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="ht-mono rounded-[var(--ht-r-xs)] bg-[var(--ht-signal-soft)] px-1.5 py-0.5 text-[0.66rem] text-signal-bright">
              {transport}
            </span>
            <span className="ht-mono text-[0.7rem] text-muted">
              {reportedStatus ?? `trace · ${streamSource}`}
            </span>
          </div>
        </div>

        {/* The six load-bearing facets. */}
        <div className="grid grid-cols-2 gap-2">
          {tiles.map((tile, i) => (
            <StatTile
              key={tile.label}
              icon={tile.icon}
              label={tile.label}
              target={tile.target}
              hint={tile.hint}
              decimals={tile.decimals}
              prefix={tile.prefix}
              suffix={tile.suffix}
              live={tile.live}
              reduce={reduce}
              index={i}
            />
          ))}
        </div>
      </PanelBody>
    </Panel>
  );
}
