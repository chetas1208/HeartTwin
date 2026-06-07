"use client";

/*
 * CONTRACT: compact, one-line-per-agent view of the eight-agent pipeline. Folds
 *   the live SSE trace into per-agent spans and renders each as a single row
 *   (status glyph + name + duration/status) — no scroll, no per-step prose. A
 *   running agent shows a spinner. READS from store: traceEvents, stream, status.
 */

import { useEffect, useMemo } from "react";
import type { Icon } from "@phosphor-icons/react";
import {
  CheckCircle,
  CircleNotch,
  SpinnerGap,
  TreeStructure,
  WarningCircle,
  XCircle,
} from "@phosphor-icons/react";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/Panel";
import { AGENT_STAGES, type AgentName } from "@/types/agents";
import { useHeartTwinStore, type TraceEvent } from "@/lib/store";

// ---------------------------------------------------------------------------
// Span model
// ---------------------------------------------------------------------------

type SpanStatus = "pending" | "running" | "success" | "warning" | "failed";

interface AgentSpan {
  name: AgentName;
  status: SpanStatus;
  tools: string[];
  durationMs: number;
  confidence: number | null;
  warnings: string[];
}

const STATUS_ICON: Record<SpanStatus, Icon> = {
  pending: CircleNotch,
  running: SpinnerGap,
  success: CheckCircle,
  warning: WarningCircle,
  failed: XCircle,
};

const STATUS_LABEL: Record<SpanStatus, string> = {
  pending: "Queued",
  running: "Running",
  success: "Done",
  warning: "Warn",
  failed: "Failed",
};

const STATUS_COLOR: Record<SpanStatus, string> = {
  pending: "var(--ht-faint)",
  running: "var(--ht-signal-bright)",
  success: "var(--ht-ecg)",
  warning: "var(--ht-warn)",
  failed: "var(--ht-accent-bright)",
};

const AGENT_NAMES = AGENT_STAGES.map((s) => s.name);

// ---------------------------------------------------------------------------
// Event folding — turn the raw SSE log into per-agent spans.
// ---------------------------------------------------------------------------

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v): v is string => typeof v === "string" && v.length > 0);
}

function fieldsOf(evt: TraceEvent): Record<string, unknown> {
  const top = evt.payload;
  const nested =
    top.payload && typeof top.payload === "object" && !Array.isArray(top.payload)
      ? (top.payload as Record<string, unknown>)
      : null;
  return nested ? { ...top, ...nested } : top;
}

function eventKind(evt: TraceEvent): string {
  const f = fieldsOf(evt);
  return asString(f.kind) ?? asString(f.event) ?? evt.kind ?? "trace";
}

function normalizeStatus(raw: string | null): SpanStatus {
  switch (raw) {
    case "running":
    case "in_progress":
    case "started":
      return "running";
    case "success":
    case "ok":
    case "passed":
    case "completed":
      return "success";
    case "warning":
    case "warn":
    case "degraded":
      return "warning";
    case "failed":
    case "error":
    case "blocked":
      return "failed";
    default:
      return "running";
  }
}

const TERMINAL: SpanStatus[] = ["success", "warning", "failed"];
function mergeStatus(prev: SpanStatus, next: SpanStatus): SpanStatus {
  if (TERMINAL.includes(prev) && next === "running") return prev;
  if (prev === "failed" || next === "failed") return "failed";
  return next;
}

function pickAgent(value: unknown): AgentName | null {
  const candidate = asString(value);
  if (candidate && (AGENT_NAMES as string[]).includes(candidate)) {
    return candidate as AgentName;
  }
  return null;
}

interface FoldResult {
  spans: Record<AgentName, AgentSpan>;
  runFinished: boolean;
  runFailed: boolean;
}

function freshSpan(name: AgentName): AgentSpan {
  return { name, status: "pending", tools: [], durationMs: 0, confidence: null, warnings: [] };
}

function readDuration(p: Record<string, unknown>): number | null {
  const metrics =
    p.metrics && typeof p.metrics === "object" && !Array.isArray(p.metrics)
      ? (p.metrics as Record<string, unknown>)
      : null;
  return asNumber(metrics?.duration_ms) ?? asNumber(p.duration_ms);
}

function foldTrace(events: TraceEvent[]): FoldResult {
  const spans = {} as Record<AgentName, AgentSpan>;
  for (const name of AGENT_NAMES) spans[name] = freshSpan(name);

  let runFinished = false;
  let runFailed = false;
  const toolOwner = new Map<string, AgentName | null>();

  for (const evt of events) {
    const kind = eventKind(evt);
    const p = fieldsOf(evt);

    if (kind === "agent_stage") {
      const agent = pickAgent(p.agent);
      if (!agent) continue;
      const span = spans[agent];
      span.status = mergeStatus(span.status, normalizeStatus(asString(p.status)));

      const confidence = asNumber(p.confidence);
      if (confidence !== null) span.confidence = confidence;

      for (const tool of asStringList(p.tools_called)) {
        if (!span.tools.includes(tool)) span.tools.push(tool);
        const existing = toolOwner.get(tool);
        if (existing === undefined) toolOwner.set(tool, agent);
        else if (existing !== agent) toolOwner.set(tool, null);
      }
      for (const warning of asStringList(p.warnings)) {
        if (!span.warnings.includes(warning)) span.warnings.push(warning);
      }
      continue;
    }

    if (kind === "run_finish" || kind === "finish_run") {
      runFinished = true;
      if (normalizeStatus(asString(p.status)) === "failed") runFailed = true;
      continue;
    }
  }

  for (const evt of events) {
    if (eventKind(evt) !== "tool_call") continue;
    const p = fieldsOf(evt);
    const tool = asString(p.tool_name) ?? asString(p.tool);
    const owner = pickAgent(p.agent) ?? (tool ? toolOwner.get(tool) ?? null : null);
    if (!owner) continue;
    const span = spans[owner];
    if (tool && !span.tools.includes(tool)) span.tools.push(tool);
    const duration = readDuration(p);
    if (duration !== null) span.durationMs += duration;
    if (span.status === "pending") span.status = "running";
  }

  return { spans, runFinished, runFailed };
}

function formatDuration(ms: number): string {
  if (ms <= 0) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AgentTraceTimeline() {
  const traceEvents = useHeartTwinStore((s) => s.traceEvents);
  const stream = useHeartTwinStore((s) => s.stream);

  useEffect(() => {
    if (typeof window === "undefined") return;
    (window as unknown as { hearttwin?: typeof useHeartTwinStore }).hearttwin =
      useHeartTwinStore;
  }, []);

  const { spans, runFinished, runFailed } = useMemo(
    () => foldTrace(traceEvents),
    [traceEvents],
  );
  const doneCount = useMemo(
    () => Object.values(spans).filter((s) => TERMINAL.includes(s.status)).length,
    [spans],
  );

  const chip = stream.connected
    ? { status: "running", label: "Live" }
    : stream.error
      ? { status: "warning", label: "Reconnecting" }
      : runFinished
        ? { status: runFailed ? "failed" : "success", label: "Closed" }
        : { status: "idle", label: "Standby" };

  return (
    <Panel className="h-full">
      <PanelHeader
        icon={TreeStructure}
        accent="signal"
        eyebrow="Orchestration"
        title="Agent trace"
        actions={
          <span className="ht-chip" data-status={chip.status}>
            <span className={`ht-chip-dot ${stream.connected ? "ht-pulse" : ""}`} />
            {chip.label} · {doneCount}/{AGENT_NAMES.length}
          </span>
        }
      />
      <div className="ht-hairline" />
      <PanelBody className="pt-2">
        <ol className="flex flex-col">
          {AGENT_STAGES.map((meta) => {
            const span = spans[meta.name];
            const st = span?.status ?? "pending";
            const Glyph = STATUS_ICON[st];
            const dur = span ? formatDuration(span.durationMs) : "";
            return (
              <li
                key={meta.name}
                className="flex items-center gap-2.5 border-b border-[var(--ht-line)] py-1.5 last:border-0"
              >
                <Glyph
                  weight="bold"
                  aria-hidden
                  className={`size-3.5 flex-none ${st === "running" ? "animate-spin" : ""}`}
                  style={{ color: STATUS_COLOR[st] }}
                />
                <span className="truncate text-[0.78rem] text-ink-2">
                  {meta.displayName}
                </span>
                <span className="ht-mono ml-auto flex-none text-[0.66rem] text-muted">
                  {dur || STATUS_LABEL[st]}
                </span>
              </li>
            );
          })}
        </ol>
      </PanelBody>
    </Panel>
  );
}
