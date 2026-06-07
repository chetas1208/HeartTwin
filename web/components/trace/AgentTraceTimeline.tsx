"use client";

/*
 * CONTRACT: owns the live agent-orchestration trace — the WeaveHacks "trace
 *   tree / spans / telemetry" view. Renders the 8-agent pipeline as a vertical /
 *   branching timeline (intake_safety → extraction → validator → state_builder →
 *   [electrophysiology ∥ hemodynamics] → recovery → evaluator) and the live SSE
 *   span log, driven by the store's trace stream.
 * READS from store: traceEvents, stream (source/connected/error), status.
 * Folds the raw SSE events (stream_setup, run_start, agent_stage, tool_call,
 *   run_finish, eval_scores) into per-agent span state — status, tools called,
 *   duration, confidence, warnings — then renders each agent as it runs.
 * The useTraceStream hook (mounted in AppShell) feeds traceEvents; this panel
 *   never opens its own EventSource.
 */

import { useEffect, useMemo } from "react";
import {
  Activity,
  CaretRight,
  CheckCircle,
  CircleNotch,
  Heartbeat,
  Lightning,
  ListChecks,
  Pulse,
  ShieldCheck,
  SpinnerGap,
  Stack,
  TrendUp,
  TreeStructure,
  WarningCircle,
  XCircle,
  type Icon,
} from "@phosphor-icons/react";
import { motion, useReducedMotion, AnimatePresence } from "motion/react";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/Panel";
import { AGENT_STAGES, type AgentName } from "@/types/agents";
import { useHeartTwinStore, type TraceEvent, type PipelineStatus } from "@/lib/store";

// ---------------------------------------------------------------------------
// Span model — what one agent looks like at any moment during a live run.
// ---------------------------------------------------------------------------

type SpanStatus = "pending" | "running" | "success" | "warning" | "failed";

interface AgentSpan {
  name: AgentName;
  status: SpanStatus;
  /** Distinct tools this agent reported calling, in first-seen order. */
  tools: string[];
  /** Summed tool-call duration (ms) observed for this agent. */
  durationMs: number;
  /** Latest confidence [0,1] reported on an agent_stage event. */
  confidence: number | null;
  /** De-duplicated warnings reported across this agent's stage events. */
  warnings: string[];
}

/** Per-stage grouping used to draw the timeline (stage 5 is the parallel fork). */
interface TimelineStage {
  stage: number;
  parallel: boolean;
  spans: AgentSpan[];
  status: SpanStatus;
}

// Phosphor icon per agent (the `icon` string in AGENT_STAGES maps here so we
// never hand-roll SVG and keep a single icon family).
const AGENT_ICON: Record<AgentName, Icon> = {
  intake_safety_agent: ShieldCheck,
  extraction_agent: Stack,
  validator_agent: CheckCircle,
  state_builder_agent: ListChecks,
  electrophysiology_agent: Activity,
  hemodynamics_agent: Heartbeat,
  recovery_agent: TrendUp,
  evaluator_agent: Lightning,
};

const STATUS_ICON: Record<SpanStatus, Icon> = {
  pending: CircleNotch,
  running: SpinnerGap,
  success: CheckCircle,
  warning: WarningCircle,
  failed: XCircle,
};

const STATUS_CHIP: Record<SpanStatus, string> = {
  pending: "idle",
  running: "running",
  success: "success",
  warning: "warning",
  failed: "failed",
};

const STATUS_LABEL: Record<SpanStatus, string> = {
  pending: "Queued",
  running: "Running",
  success: "Done",
  warning: "Warn",
  failed: "Failed",
};

/** Token color for a status — drives the rail node + accent. */
const STATUS_COLOR: Record<SpanStatus, string> = {
  pending: "var(--ht-faint)",
  running: "var(--ht-signal-bright)",
  success: "var(--ht-ecg)",
  warning: "var(--ht-warn)",
  failed: "var(--ht-accent-bright)",
};

const AGENT_NAMES = AGENT_STAGES.map((s) => s.name);
const STAGE_NUMS = [...new Set(AGENT_STAGES.map((s) => s.stage))].sort(
  (a, b) => a - b,
);

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

/**
 * Flatten one SSE event into the fields the UI reads.
 *
 * The backend wraps the original trace dict under a nested `payload` key on BOTH
 * transports: local sends `{ kind, source, payload: <trace> }` and redis sends
 * `{ kind, agent, status, tool, payload: <trace> }`. Rich fields (tools_called,
 * confidence, warnings, metrics, tool_name) live ONLY in that nested dict, so we
 * read the nested object first and fall back to the flattened top level.
 */
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

/** Normalize any server status spelling onto the five span states. */
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

/** A status only ever moves forward toward a terminal state. */
const TERMINAL: SpanStatus[] = ["success", "warning", "failed"];
function mergeStatus(prev: SpanStatus, next: SpanStatus): SpanStatus {
  if (TERMINAL.includes(prev) && next === "running") return prev;
  // failed dominates a same-stage warning/success when both arrive.
  if (prev === "failed" || next === "failed") return "failed";
  return next;
}

/** Resolve a string to a known agent name, or null. */
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
  return {
    name,
    status: "pending",
    tools: [],
    durationMs: 0,
    confidence: null,
    warnings: [],
  };
}

function readDuration(p: Record<string, unknown>): number | null {
  const metrics =
    p.metrics && typeof p.metrics === "object" && !Array.isArray(p.metrics)
      ? (p.metrics as Record<string, unknown>)
      : null;
  return asNumber(metrics?.duration_ms) ?? asNumber(p.duration_ms);
}

/*
 * Two passes over the trace.
 *
 * Pass 1 reads `agent_stage` events, which carry each agent's authoritative,
 *   correctly-attributed list (`tools_called`), status, confidence, warnings.
 *   From those lists we build a `tool -> owner` index for tools owned by a
 *   single agent.
 * Pass 2 reads `tool_call` events for durations. The live backend shares one
 *   run_id across every agent in a pipeline phase and usually omits the owning
 *   `agent` on a tool_call, so we attribute a duration by its tool name via the
 *   index (and by an explicit `agent` when present). Ambiguous tools are skipped
 *   rather than charged to the wrong agent.
 */
function foldTrace(events: TraceEvent[]): FoldResult {
  const spans = {} as Record<AgentName, AgentSpan>;
  for (const name of AGENT_NAMES) spans[name] = freshSpan(name);

  let runFinished = false;
  let runFailed = false;

  // tool name -> single owning agent (dropped to null once a tool is shared).
  const toolOwner = new Map<string, AgentName | null>();

  // Pass 1: authoritative per-agent state from agent_stage events.
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

  // Pass 2: durations from tool_call events, attributed unambiguously.
  for (const evt of events) {
    if (eventKind(evt) !== "tool_call") continue;
    const p = fieldsOf(evt);
    const tool = asString(p.tool_name) ?? asString(p.tool);
    const owner =
      pickAgent(p.agent) ?? (tool ? toolOwner.get(tool) ?? null : null);
    if (!owner) continue;
    const span = spans[owner];
    if (tool && !span.tools.includes(tool)) span.tools.push(tool);
    const duration = readDuration(p);
    if (duration !== null) span.durationMs += duration;
    if (span.status === "pending") span.status = "running";
  }

  return { spans, runFinished, runFailed };
}

/** Roll an array of spans up to one stage-level status for the rail node. */
function rollupStatus(spans: AgentSpan[]): SpanStatus {
  const statuses = spans.map((s) => s.status);
  if (statuses.every((s) => s === "pending")) return "pending";
  if (statuses.includes("failed")) return "failed";
  if (statuses.some((s) => s === "running")) return "running";
  if (statuses.includes("warning")) return "warning";
  if (statuses.every((s) => s === "success")) return "success";
  return "running";
}

function buildTimeline(spans: Record<AgentName, AgentSpan>): TimelineStage[] {
  return STAGE_NUMS.map((stage) => {
    const meta = AGENT_STAGES.filter((s) => s.stage === stage);
    const stageSpans = meta.map((m) => spans[m.name]);
    return {
      stage,
      parallel: meta.length > 1,
      spans: stageSpans,
      status: rollupStatus(stageSpans),
    };
  });
}

const META_BY_NAME = Object.fromEntries(
  AGENT_STAGES.map((s) => [s.name, s]),
) as Record<AgentName, (typeof AGENT_STAGES)[number]>;

function formatDuration(ms: number): string {
  if (ms <= 0) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
}

function formatConfidence(value: number | null): string | null {
  if (value === null) return null;
  const pct = value <= 1 ? value * 100 : value;
  return `${Math.round(pct)}%`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const STREAM_HINT: Record<PipelineStatus, string> = {
  idle: "Run a case to stream the eight-agent orchestration here.",
  creating: "Opening the case and the trace stream.",
  created: "Case open. Agents start as extraction runs.",
  extracting: "Intake, extraction and validation are reporting in.",
  extracted: "Evidence validated. Building the cardiac twin next.",
  operating: "State builder and the parallel simulators are working.",
  operated: "Twin operating. Recovery scenarios queued.",
  simulating: "Recovery and the evaluator are closing the run.",
  complete: "Run complete across all eight agents.",
  improving: "Self-improvement rerun in progress.",
  error: "The run failed. Inspect the spans below for the failing stage.",
};

export function AgentTraceTimeline() {
  const traceEvents = useHeartTwinStore((s) => s.traceEvents);
  const stream = useHeartTwinStore((s) => s.stream);
  const status = useHeartTwinStore((s) => s.status);
  const reduce = useReducedMotion();

  // Expose the live trace store on `window.hearttwin` so the observability panel
  // is inspectable and scriptable from the browser console (and from external
  // tooling): read `traceEvents`, drive a run with `runPipeline(...)`, or attach
  // the stream to an existing case via `setCaseId(...)`. Read-through to the same
  // singleton the panel renders; no private copy of state.
  useEffect(() => {
    if (typeof window === "undefined") return;
    (window as unknown as { hearttwin?: typeof useHeartTwinStore }).hearttwin =
      useHeartTwinStore;
  }, []);

  const { spans, runFinished, runFailed } = useMemo(
    () => foldTrace(traceEvents),
    [traceEvents],
  );
  const timeline = useMemo(() => buildTimeline(spans), [spans]);

  const activeCount = useMemo(
    () => Object.values(spans).filter((s) => s.status !== "pending").length,
    [spans],
  );
  const doneCount = useMemo(
    () =>
      Object.values(spans).filter((s) => TERMINAL.includes(s.status)).length,
    [spans],
  );

  const hasRun = activeCount > 0;
  const toolCalls = useMemo(
    () => traceEvents.filter((e) => eventKind(e) === "tool_call"),
    [traceEvents],
  );

  const streamChip = stream.connected
    ? { status: "running", label: `Live · ${stream.source}` }
    : stream.error
      ? { status: "warning", label: "Reconnecting" }
      : runFinished
        ? { status: runFailed ? "failed" : "success", label: "Stream closed" }
        : { status: "idle", label: "Standby" };

  return (
    <Panel className="h-full">
      <PanelHeader
        icon={TreeStructure}
        accent="signal"
        eyebrow="Orchestration"
        title="Agent trace"
        actions={
          <span className="ht-chip" data-status={streamChip.status}>
            <span
              className={`ht-chip-dot ${stream.connected ? "ht-pulse" : ""}`}
            />
            {streamChip.label}
          </span>
        }
      />
      <div className="ht-hairline" />

      <PanelBody className="flex flex-col gap-4 pt-4">
        {/* Run progress meter — honest count of agents that have reported. */}
        <div className="flex items-center justify-between gap-3">
          <span className="ht-eyebrow">Eight-agent pipeline</span>
          <span className="ht-mono text-[0.7rem] text-muted">
            {doneCount}/{AGENT_NAMES.length} settled
          </span>
        </div>
        <div
          className="relative h-1 w-full overflow-hidden rounded-full bg-surface-2"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={AGENT_NAMES.length}
          aria-valuenow={doneCount}
          aria-label="Agents settled"
        >
          <motion.span
            className="absolute inset-y-0 left-0 rounded-full"
            style={{
              background: runFailed
                ? "var(--ht-accent-bright)"
                : "linear-gradient(90deg, var(--ht-signal-dim), var(--ht-signal-bright))",
            }}
            initial={false}
            animate={{ width: `${(doneCount / AGENT_NAMES.length) * 100}%` }}
            transition={{ duration: reduce ? 0 : 0.5, ease: [0.16, 1, 0.3, 1] }}
          />
        </div>

        {/* The branching timeline. */}
        <ol className="relative flex flex-col">
          {timeline.map((stage, i) => (
            <StageRow
              key={stage.stage}
              stage={stage}
              index={i}
              isLast={i === timeline.length - 1}
              reduce={Boolean(reduce)}
            />
          ))}
        </ol>

        <div className="ht-hairline" />

        {/* Live span log: the raw Redis-stream events as they land. */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="ht-eyebrow">Span log</span>
            <span className="ht-mono text-[0.7rem] text-muted">
              {traceEvents.length} events · {toolCalls.length} tool calls
            </span>
          </div>

          {!hasRun ? (
            <div className="flex items-center gap-2.5 rounded-[var(--ht-r-md)] border border-dashed border-[var(--ht-line)] px-3 py-3">
              <Pulse className="size-4 flex-none text-signal-dim" weight="duotone" />
              <span className="text-xs leading-relaxed text-muted">
                {STREAM_HINT[status]}
              </span>
              <span className="ht-ecg-sweep ml-auto h-px w-14 flex-none rounded-full" />
            </div>
          ) : (
            <ul className="flex max-h-44 flex-col gap-px overflow-y-auto pr-1">
              <AnimatePresence initial={false}>
                {traceEvents
                  .slice(-14)
                  .reverse()
                  .map((evt) => (
                    <SpanLogRow key={evt.id} evt={evt} reduce={Boolean(reduce)} />
                  ))}
              </AnimatePresence>
            </ul>
          )}
        </div>
      </PanelBody>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Stage row — one node on the rail, with its agent span(s) beside it.
// ---------------------------------------------------------------------------

function StageRow({
  stage,
  index,
  isLast,
  reduce,
}: {
  stage: TimelineStage;
  index: number;
  isLast: boolean;
  reduce: boolean;
}) {
  const StatusGlyph = STATUS_ICON[stage.status];
  const color = STATUS_COLOR[stage.status];
  const live = stage.status === "running";

  return (
    <motion.li
      className="grid grid-cols-[1.75rem_1fr] gap-3"
      initial={reduce ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.45,
        delay: reduce ? 0 : index * 0.05,
        ease: [0.16, 1, 0.3, 1],
      }}
    >
      {/* Rail: node + connector down to the next stage. */}
      <div className="relative flex flex-col items-center">
        <span
          className="relative z-[1] grid size-7 flex-none place-items-center rounded-full border bg-surface-1"
          style={{
            color,
            borderColor:
              stage.status === "pending"
                ? "var(--ht-line)"
                : `color-mix(in oklab, ${color} 50%, var(--ht-line))`,
          }}
        >
          <motion.span
            className="grid place-items-center"
            animate={
              live && !reduce ? { rotate: 360 } : { rotate: 0 }
            }
            transition={
              live && !reduce
                ? { duration: 1.1, ease: "linear", repeat: Infinity }
                : { duration: 0 }
            }
          >
            <StatusGlyph
              weight={stage.status === "pending" ? "regular" : "fill"}
              className="size-[0.95rem]"
            />
          </motion.span>
          {live && !reduce ? (
            <motion.span
              aria-hidden
              className="absolute inset-0 rounded-full border"
              style={{ borderColor: color }}
              initial={{ opacity: 0.5, scale: 0.85 }}
              animate={{ opacity: 0, scale: 1.7 }}
              transition={{
                duration: 1.8,
                ease: [0.16, 1, 0.3, 1],
                repeat: Infinity,
              }}
            />
          ) : null}
        </span>

        {!isLast ? (
          <span
            aria-hidden
            className="mt-1 w-px flex-1"
            style={{
              minHeight: "1.25rem",
              background:
                stage.status === "pending"
                  ? "var(--ht-line)"
                  : `linear-gradient(var(--ht-line-strong), ${color})`,
            }}
          />
        ) : null}
      </div>

      {/* Stage content: one card, or a parallel fork of two. */}
      <div className="pb-3">
        {stage.parallel ? (
          <ParallelFork spans={stage.spans} reduce={reduce} />
        ) : (
          <SpanCard span={stage.spans[0]} reduce={reduce} />
        )}
      </div>
    </motion.li>
  );
}

// ---------------------------------------------------------------------------
// Parallel fork — the EP ∥ Hemodynamics branch, shown as two columns.
// ---------------------------------------------------------------------------

function ParallelFork({ spans, reduce }: { spans: AgentSpan[]; reduce: boolean }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5">
        <span className="ht-eyebrow text-signal-dim">Parallel fork</span>
        <span
          aria-hidden
          className="h-px flex-1"
          style={{
            background:
              "linear-gradient(90deg, var(--ht-signal-line), transparent)",
          }}
        />
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {spans.map((span) => (
          <SpanCard key={span.name} span={span} reduce={reduce} compact />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Span card — a single agent's live state.
// ---------------------------------------------------------------------------

function SpanCard({
  span,
  reduce,
  compact = false,
}: {
  span: AgentSpan;
  reduce: boolean;
  compact?: boolean;
}) {
  const meta = META_BY_NAME[span.name];
  const AgentGlyph = AGENT_ICON[span.name];
  const color = STATUS_COLOR[span.status];
  const pending = span.status === "pending";
  const confidence = formatConfidence(span.confidence);

  return (
    <motion.div
      layout={!reduce}
      className="rounded-[var(--ht-r-md)] border px-3 py-2.5"
      style={{
        borderColor: pending
          ? "var(--ht-line)"
          : "color-mix(in oklab, " + color + " 32%, var(--ht-line))",
        background: pending
          ? "color-mix(in oklab, var(--ht-surface-2) 50%, transparent)"
          : "color-mix(in oklab, " + color + " 8%, var(--ht-surface-2))",
      }}
      animate={
        reduce
          ? undefined
          : { opacity: pending ? 0.62 : 1 }
      }
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
    >
      <div className="flex items-start gap-2.5">
        <span
          aria-hidden
          className="mt-px grid size-6 flex-none place-items-center rounded-[var(--ht-r-sm)] border border-[var(--ht-line)] bg-surface-1"
          style={{ color: pending ? "var(--ht-faint)" : color }}
        >
          <AgentGlyph weight="duotone" className="size-[0.9rem]" />
        </span>

        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-[0.82rem] font-medium text-ink-2">
              {meta.displayName}
            </span>
            <span
              className="ht-chip flex-none"
              data-status={STATUS_CHIP[span.status]}
              style={{ height: "1.25rem" }}
            >
              {STATUS_LABEL[span.status]}
            </span>
          </div>

          {!compact ? (
            <span className="truncate text-[0.7rem] leading-snug text-muted">
              {meta.description}
            </span>
          ) : null}

          {/* Metrics row: duration + confidence, mono telemetry. */}
          {!pending && (span.durationMs > 0 || confidence) ? (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[0.68rem] text-muted">
              {span.durationMs > 0 ? (
                <span className="ht-mono">
                  <span className="text-faint">tool</span>{" "}
                  {formatDuration(span.durationMs)}
                </span>
              ) : null}
              {confidence ? (
                <span className="ht-mono">
                  <span className="text-faint">conf</span>{" "}
                  <span style={{ color }}>{confidence}</span>
                </span>
              ) : null}
            </div>
          ) : null}

          {/* Tools called — phosphor chips, de-duplicated. */}
          {span.tools.length > 0 ? (
            <div className="flex flex-wrap gap-1 pt-0.5">
              {span.tools.slice(0, 5).map((tool) => (
                <span
                  key={tool}
                  className="ht-mono inline-flex items-center gap-1 rounded-[var(--ht-r-xs)] border border-[var(--ht-line)] bg-surface-1 px-1.5 py-0.5 text-[0.64rem] text-ink-2"
                >
                  <CaretRight className="size-2.5 text-signal-dim" weight="bold" />
                  {tool}
                </span>
              ))}
              {span.tools.length > 5 ? (
                <span className="ht-mono inline-flex items-center px-1 py-0.5 text-[0.64rem] text-faint">
                  +{span.tools.length - 5}
                </span>
              ) : null}
            </div>
          ) : null}

          {/* Warnings — amber, never hidden. */}
          {span.warnings.length > 0 ? (
            <ul className="flex flex-col gap-0.5 pt-0.5">
              {span.warnings.slice(0, 2).map((warning) => (
                <li
                  key={warning}
                  className="flex items-start gap-1 text-[0.66rem] leading-snug text-warn"
                >
                  <WarningCircle
                    weight="fill"
                    className="mt-px size-3 flex-none"
                  />
                  <span className="min-w-0">{warning}</span>
                </li>
              ))}
              {span.warnings.length > 2 ? (
                <li className="pl-4 text-[0.64rem] text-faint">
                  +{span.warnings.length - 2} more warnings
                </li>
              ) : null}
            </ul>
          ) : null}
        </div>
      </div>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Span log row — one raw SSE event in the live feed.
// ---------------------------------------------------------------------------

const LOG_KIND_COLOR: Record<string, string> = {
  agent_stage: "var(--ht-signal-bright)",
  tool_call: "var(--ht-ecg)",
  run_start: "var(--ht-ink-2)",
  start_run: "var(--ht-ink-2)",
  run_finish: "var(--ht-ink-2)",
  finish_run: "var(--ht-ink-2)",
  eval_scores: "var(--ht-warn)",
  stream_setup: "var(--ht-faint)",
  redis_error: "var(--ht-accent-bright)",
};

function logDetail(evt: TraceEvent): string {
  const p = fieldsOf(evt);
  const kind = eventKind(evt);
  if (kind === "agent_stage") {
    const agent = asString(p.agent);
    return agent ? agent.replace(/_agent$/, "") : "stage";
  }
  if (kind === "tool_call") {
    return asString(p.tool_name) ?? asString(p.tool) ?? "tool";
  }
  if (kind === "run_finish" || kind === "finish_run") {
    return asString(p.status) ?? "finished";
  }
  if (kind === "stream_setup") {
    return asString(p.source) ?? "setup";
  }
  if (kind === "redis_error") {
    return "redis";
  }
  return asString(p.event) ?? "event";
}

function SpanLogRow({ evt, reduce }: { evt: TraceEvent; reduce: boolean }) {
  const kind = eventKind(evt);
  const color = LOG_KIND_COLOR[kind] ?? "var(--ht-muted)";
  return (
    <motion.li
      layout={!reduce}
      initial={reduce ? false : { opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      exit={reduce ? undefined : { opacity: 0 }}
      transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
      className="ht-mono flex items-center gap-2 rounded-[var(--ht-r-xs)] px-1 py-1 text-[0.68rem] hover:bg-surface-2"
    >
      <span
        aria-hidden
        className="size-1.5 flex-none rounded-full"
        style={{ background: color }}
      />
      <span className="flex-none" style={{ color }}>
        {kind}
      </span>
      <span className="truncate text-ink-2">{logDetail(evt)}</span>
      <span className="ml-auto flex-none text-faint">{evt.id}</span>
    </motion.li>
  );
}
