"use client";

/*
 * CONTRACT: owns the CopilotKit chat surface — the embedded "Cardiology Copilot"
 *   that reads the live case context and drives the pipeline through the backend
 *   CopilotKit actions (create_case / extract / operate / simulate_recovery /
 *   answer_case_question, served at /copilotkit and proxied by the Next route).
 * READS from store: caseId, status, validatedFields, validatedFieldCount, state,
 *   evaluation, scenarios (exposed to the agent via useCopilotReadable).
 * BUILDS:
 *   - useCopilotReadable: streams the current case state into the agent context.
 *   - useCopilotAction (render-only): GENERATIVE UI — when the agent runs a
 *     pipeline stage the matching on-brand card renders inline in the chat with
 *     streaming status (inProgress -> complete). AgentTrace card for the staged
 *     actions, a Metrics card for operate.
 *   - useCopilotAction (renderAndWaitForResponse): HUMAN-IN-THE-LOOP confirm
 *     before any recovery simulation runs.
 * The CopilotKit provider already wraps the app (CopilotProvider) and themes the
 *   chat onto our palette. This is a "use client" leaf; do not add app chrome.
 */

import { useMemo, useState, type ReactNode } from "react";
import type { Icon } from "@phosphor-icons/react";
import {
  Activity,
  ArrowsClockwise,
  ChatCircleDots,
  CheckCircle,
  Gauge,
  Heartbeat,
  Pulse,
  ShieldCheck,
  Sparkle,
  TreeStructure,
  Warning,
  X,
} from "@phosphor-icons/react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { CopilotChat } from "@copilotkit/react-ui";
import { useCopilotAction, useCopilotReadable } from "@copilotkit/react-core";
import { useHeartTwinStore } from "@/lib/store";
import { formatNumber, formatPercent } from "@/lib/formatters";

// ---------------------------------------------------------------------------
// Small typed helpers for reading the backend action results (shape mirrors
// python/hearttwin/copilot.py). Results arrive untyped from the runtime, so we
// read defensively without inventing data.
// ---------------------------------------------------------------------------

type ActionStatus = "inProgress" | "executing" | "complete";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function numberAt(source: Record<string, unknown>, key: string): number | null {
  const raw = source[key];
  return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
}

function stringAt(source: Record<string, unknown>, key: string): string | null {
  const raw = source[key];
  return typeof raw === "string" && raw.length > 0 ? raw : null;
}

/** Read the operate/simulation summary metrics from a stored CardiacTwinState-shaped result. */
interface TwinMetrics {
  efPct: number | null;
  cardiacOutput: number | null;
  strokeVolume: number | null;
  heartRate: number | null;
  edv: number | null;
  esv: number | null;
  dataQuality: number | null;
}

function readTwinMetrics(result: unknown): TwinMetrics {
  const root = asRecord(result);
  const viz = asRecord(root.visualization);
  const summary = asRecord(viz.summary);
  const state = asRecord(root.state);
  const measurements = asRecord(state.measurements);

  // measurements hold MeasuredValue objects ({ value, unit, ... }); summary holds plain numbers.
  const measured = (key: string): number | null =>
    numberAt(asRecord(measurements[key]), "value");

  return {
    efPct: numberAt(summary, "ef_pct") ?? measured("ejection_fraction_pct"),
    cardiacOutput:
      numberAt(summary, "cardiac_output_l_min") ?? measured("cardiac_output_l_min"),
    strokeVolume: numberAt(summary, "stroke_volume_ml") ?? measured("stroke_volume_ml"),
    heartRate: numberAt(summary, "heart_rate_bpm") ?? measured("heart_rate_bpm"),
    edv: numberAt(summary, "edv_ml") ?? measured("edv_ml"),
    esv: numberAt(summary, "esv_ml") ?? measured("esv_ml"),
    dataQuality: numberAt(root, "data_quality_score"),
  };
}

function isFailedResult(result: unknown): string | null {
  const root = asRecord(result);
  if (root.status === "failed") {
    return stringAt(root, "detail") ?? stringAt(root, "error") ?? "Action failed";
  }
  return null;
}

// ---------------------------------------------------------------------------
// Generative-UI card shell. On-brand, streaming-aware (inProgress -> complete).
// ---------------------------------------------------------------------------

type CardTone = "signal" | "accent" | "ecg" | "warn";

const toneColor: Record<CardTone, string> = {
  signal: "var(--ht-signal-bright)",
  accent: "var(--ht-accent-bright)",
  ecg: "var(--ht-ecg)",
  warn: "var(--ht-warn)",
};

const toneSoft: Record<CardTone, string> = {
  signal: "var(--ht-signal-soft)",
  accent: "var(--ht-accent-soft)",
  ecg: "var(--ht-ecg-soft)",
  warn: "var(--ht-warn-soft)",
};

function GenCard({
  icon: IconCmp,
  eyebrow,
  title,
  tone,
  status,
  children,
}: {
  icon: Icon;
  eyebrow: string;
  title: string;
  tone: CardTone;
  status: ActionStatus;
  children: ReactNode;
}) {
  const reduce = useReducedMotion();
  const running = status !== "complete";

  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 8, scale: 0.99 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
      className="ht-panel my-1.5 w-full overflow-hidden"
    >
      <header className="flex items-center gap-2.5 px-3 py-2.5">
        <span
          aria-hidden
          className="grid size-7 flex-none place-items-center rounded-[var(--ht-r-sm)] border border-[var(--ht-line)]"
          style={{ color: toneColor[tone], background: toneSoft[tone] }}
        >
          <IconCmp weight="duotone" className="size-4" />
        </span>
        <div className="flex min-w-0 flex-col">
          <span className="ht-eyebrow leading-tight">{eyebrow}</span>
          <span className="truncate text-[0.84rem] font-semibold text-ink">
            {title}
          </span>
        </div>
        <span
          className="ht-chip ml-auto"
          data-status={running ? "running" : "success"}
        >
          <span className={`ht-chip-dot ${running ? "ht-pulse" : ""}`} />
          {running ? "Running" : "Done"}
        </span>
      </header>
      <div className="ht-hairline" />
      <div className="px-3 py-2.5">{children}</div>
    </motion.div>
  );
}

/** A failed-action card: honest error surface, no fake success. */
function GenFailCard({ title, detail }: { title: string; detail: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
      className="ht-panel my-1.5 w-full overflow-hidden"
    >
      <div className="flex items-start gap-2.5 px-3 py-2.5">
        <Warning weight="fill" className="mt-0.5 size-4 flex-none text-accent-bright" />
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="text-[0.84rem] font-semibold text-ink">{title}</span>
          <span className="text-[0.74rem] leading-relaxed text-muted">{detail}</span>
        </div>
      </div>
    </motion.div>
  );
}

/** One labelled telemetry value in a generative card. */
function Stat({
  label,
  value,
  unit,
  tone = "ink",
}: {
  label: string;
  value: string;
  unit?: string;
  tone?: "ink" | "signal" | "ecg" | "accent";
}) {
  const valueColor =
    tone === "signal"
      ? "text-signal-bright"
      : tone === "ecg"
        ? "text-ecg"
        : tone === "accent"
          ? "text-accent-bright"
          : "text-ink";
  // Suppress the unit on the missing-value placeholder so a null metric reads
  // "-" rather than "- mL".
  const showUnit = Boolean(unit) && value !== "-";
  return (
    <div className="flex flex-col gap-0.5 rounded-[var(--ht-r-sm)] border border-[var(--ht-line)] bg-surface-2/50 px-2.5 py-2">
      <span className="ht-eyebrow text-[0.6rem] leading-none">{label}</span>
      <span className={`ht-mono text-[0.95rem] font-semibold leading-tight ${valueColor}`}>
        {value}
        {showUnit ? <span className="ml-0.5 text-[0.62rem] text-muted">{unit}</span> : null}
      </span>
    </div>
  );
}

/** Streaming progress shimmer used while an action is inProgress/executing. */
function RunningRows({ rows }: { rows: number }) {
  return (
    <div className="grid gap-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="ht-ecg-sweep h-px flex-1 rounded-full" />
        </div>
      ))}
      <div className="flex items-center gap-1.5 text-[0.72rem] text-muted">
        <Pulse className="size-3.5 text-signal-dim" />
        Streaming agent telemetry
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The dock.
// ---------------------------------------------------------------------------

const COPILOT_INSTRUCTIONS = [
  "You are the Cardiology Copilot embedded in HeartTwin Lab, a multi-agent",
  "cardiac digital-twin console. You coordinate an educational SIMULATION; you",
  "never diagnose, prescribe, triage, or give medical advice.",
  "",
  "Always build the twin by CALLING THE ACTIONS. Do not compute cardiac metrics",
  "yourself and do not write formulas or LaTeX: the deterministic pipeline owns",
  "the numbers. When the user gives vitals or asks to build/simulate a twin, run",
  "this sequence and report the values the actions return:",
  "1. create_case -> returns a case_id (carry it through every later call).",
  "2. extract -> pass the measurements as user_vitals using these keys:",
  "   heart_rate_bpm, systolic_bp_mmhg, diastolic_bp_mmhg, edv_ml, esv_ml,",
  "   ejection_fraction_pct, stroke_volume_ml, cardiac_output_l_min.",
  "3. operate -> builds the twin state and runs the cardiac-cycle simulation;",
  "   read the ejection fraction and other metrics from its result.",
  "4. simulate_recovery -> bounded recovery scenarios.",
  "5. answer_case_question -> answer follow-up questions from stored case state.",
  "",
  "So for a request like 'build a twin from these vitals ... then tell me the",
  "ejection fraction', call create_case, then extract with the vitals, then",
  "operate, then state the ejection fraction from the operate result.",
  "",
  "HUMAN-IN-THE-LOOP: before calling simulate_recovery you MUST call the",
  "confirm_recovery_simulation action and only proceed if the user confirms.",
  "If the live case context already holds the answer (e.g. ejection fraction",
  "after operate), state it directly with its units instead of recomputing.",
].join("\n");

const SUGGESTIONS = [
  {
    title: "Build a twin from vitals",
    message:
      "Build a cardiac twin from these vitals: HR 88, BP 135/85, EDV 130, ESV 70, then tell me the ejection fraction.",
  },
  {
    title: "Explain the ejection fraction",
    message: "What is the ejection fraction for the current case, and how is it derived?",
  },
  {
    title: "Run recovery scenarios",
    message: "Simulate a recovery trajectory for this case.",
  },
];

export function CopilotDock() {
  const [open, setOpen] = useState(false);
  const reduce = useReducedMotion();

  const caseId = useHeartTwinStore((s) => s.caseId);
  const status = useHeartTwinStore((s) => s.status);
  const validatedFields = useHeartTwinStore((s) => s.validatedFields);
  const validatedFieldCount = useHeartTwinStore((s) => s.validatedFieldCount);
  const state = useHeartTwinStore((s) => s.state);
  const evaluation = useHeartTwinStore((s) => s.evaluation);
  const scenarios = useHeartTwinStore((s) => s.scenarios);

  // A compact, simulation-safe snapshot of the live case for the agent. Stable
  // identity per dependency so the readable updates only when the case changes.
  const caseContext = useMemo(() => {
    const measurements = state?.measurements ?? null;
    const value = (mv: { value: number } | null | undefined) =>
      mv && typeof mv.value === "number" ? mv.value : null;

    return {
      case_id: caseId,
      pipeline_status: status,
      validated_field_count: validatedFieldCount,
      validated_field_names: Object.keys(validatedFields ?? {}),
      data_quality_score: state?.data_quality_score ?? null,
      safety_level: state?.safety_level ?? null,
      metrics: measurements
        ? {
            heart_rate_bpm: value(measurements.heart_rate_bpm),
            ejection_fraction_pct: value(measurements.ejection_fraction_pct),
            stroke_volume_ml: value(measurements.stroke_volume_ml),
            cardiac_output_l_min: value(measurements.cardiac_output_l_min),
            edv_ml: value(measurements.edv_ml),
            esv_ml: value(measurements.esv_ml),
          }
        : null,
      rhythm_label: state?.electrophysiology?.rhythm_label ?? null,
      evaluation: evaluation
        ? {
            passed: evaluation.passed,
            overall: evaluation.scores?.overall ?? evaluation.scores?.overall_score ?? null,
            safety_compliance: evaluation.scores?.safety_compliance ?? null,
          }
        : null,
      recovery_scenarios: scenarios.map((scenario) => ({
        label: scenario.scenario_label,
        final_ef_pct: scenario.summary_metrics?.final_ef_pct ?? null,
        horizon_days: scenario.summary_metrics?.horizon_days ?? null,
      })),
    };
  }, [
    caseId,
    status,
    validatedFields,
    validatedFieldCount,
    state,
    evaluation,
    scenarios,
  ]);

  useCopilotReadable({
    description:
      "The live HeartTwin Lab case state shown in the console: case id, pipeline " +
      "status, validated evidence, current cardiac metrics, evaluator scores, and " +
      "simulated recovery scenarios. Answer questions from this context first.",
    value: caseContext,
  });

  // ---- GENERATIVE UI: render-only mirrors of the backend pipeline actions. ----
  // available "disabled" => the frontend never executes them, it only renders a
  // card when the agent invokes the backend action of the same name.

  useCopilotAction({
    name: "create_case",
    available: "disabled",
    render: ({ status: s, result }) => {
      const fail = isFailedResult(result);
      if (fail) return <GenFailCard title="Could not create case" detail={fail} />;
      const newCaseId = stringAt(asRecord(result), "case_id");
      return (
        <GenCard
          icon={Heartbeat}
          eyebrow="Stage 1 · Intake & Safety"
          title="Case created"
          tone="accent"
          status={s}
        >
          {s !== "complete" ? (
            <RunningRows rows={1} />
          ) : (
            <div className="flex items-center gap-2 text-[0.78rem] text-ink-2">
              <ShieldCheck weight="duotone" className="size-4 text-accent-bright" />
              <span>Simulation boundaries enforced.</span>
              {newCaseId ? (
                <span className="ht-mono ml-auto text-[0.68rem] text-muted">
                  {newCaseId.slice(0, 8)}
                </span>
              ) : null}
            </div>
          )}
        </GenCard>
      );
    },
  });

  useCopilotAction({
    name: "extract",
    available: "disabled",
    render: ({ status: s, result }) => {
      const fail = isFailedResult(result);
      if (fail) return <GenFailCard title="Extraction blocked" detail={fail} />;
      const root = asRecord(result);
      const count = numberAt(root, "validated_field_count");
      return (
        <GenCard
          icon={TreeStructure}
          eyebrow="Stages 2-3 · Extract & Validate"
          title="Evidence validated"
          tone="signal"
          status={s}
        >
          {s !== "complete" ? (
            <RunningRows rows={2} />
          ) : (
            <div className="flex items-center gap-2 text-[0.78rem] text-ink-2">
              <CheckCircle weight="duotone" className="size-4 text-signal-bright" />
              <span>Validated cardiac evidence assembled.</span>
              <span className="ht-mono ml-auto text-[0.72rem] text-signal-bright">
                {count ?? 0} fields
              </span>
            </div>
          )}
        </GenCard>
      );
    },
  });

  useCopilotAction({
    name: "operate",
    available: "disabled",
    render: ({ status: s, result }) => {
      const fail = isFailedResult(result);
      if (fail) return <GenFailCard title="Operate failed" detail={fail} />;
      const metrics = readTwinMetrics(result);
      return (
        <GenCard
          icon={Gauge}
          eyebrow="Stages 4-5-7 · Operate"
          title="Twin metrics"
          tone="ecg"
          status={s}
        >
          {s !== "complete" ? (
            <RunningRows rows={3} />
          ) : (
            <div className="grid grid-cols-2 gap-2">
              <Stat
                label="Ejection fraction"
                value={formatPercent(metrics.efPct, 1).replace("%", "")}
                unit="%"
                tone="ecg"
              />
              <Stat
                label="Cardiac output"
                value={formatNumber(metrics.cardiacOutput, 2)}
                unit="L/min"
                tone="signal"
              />
              <Stat
                label="Stroke volume"
                value={formatNumber(metrics.strokeVolume, 0)}
                unit="mL"
              />
              <Stat
                label="Heart rate"
                value={formatNumber(metrics.heartRate, 0)}
                unit="bpm"
              />
            </div>
          )}
        </GenCard>
      );
    },
  });

  useCopilotAction({
    name: "simulate_recovery",
    available: "disabled",
    render: ({ status: s, result }) => {
      const fail = isFailedResult(result);
      if (fail) return <GenFailCard title="Recovery simulation failed" detail={fail} />;
      const root = asRecord(result);
      const list = Array.isArray(root.scenarios) ? root.scenarios : [];
      return (
        <GenCard
          icon={Activity}
          eyebrow="Stage 6 · Recovery"
          title="Simulated trajectories"
          tone="ecg"
          status={s}
        >
          {s !== "complete" ? (
            <RunningRows rows={2} />
          ) : list.length === 0 ? (
            <span className="text-[0.78rem] text-muted">
              No recovery scenarios returned for this case.
            </span>
          ) : (
            <ul className="grid gap-1.5">
              {list.slice(0, 4).map((item, i) => {
                const scenario = asRecord(item);
                const summary = asRecord(scenario.summary_metrics);
                const label =
                  stringAt(scenario, "scenario_label") ?? `Scenario ${i + 1}`;
                const finalEf = numberAt(summary, "final_ef_pct");
                return (
                  <li
                    key={`${label}-${i}`}
                    className="flex items-center gap-2 rounded-[var(--ht-r-sm)] border border-[var(--ht-line)] bg-surface-2/50 px-2.5 py-1.5"
                  >
                    <span className="truncate text-[0.76rem] text-ink-2">{label}</span>
                    <span className="ht-mono ml-auto text-[0.74rem] text-ecg">
                      EF {formatPercent(finalEf, 0)}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </GenCard>
      );
    },
  });

  // ---- HUMAN-IN-THE-LOOP: confirm before running recovery simulation. ----
  useCopilotAction({
    name: "confirm_recovery_simulation",
    description:
      "Ask the user to confirm before running bounded simulated recovery " +
      "scenarios. Call this and wait for the user's answer before simulate_recovery.",
    parameters: [
      {
        name: "summary",
        type: "string",
        required: false,
        description: "A one-line description of the recovery run to confirm.",
      },
    ],
    renderAndWaitForResponse: ({ status: s, args, respond }) => (
      <RecoveryConfirmCard
        status={s}
        summary={typeof args?.summary === "string" ? args.summary : undefined}
        respond={respond}
      />
    ),
  });

  return (
    <div
      className="fixed bottom-4 right-4 flex flex-col items-end gap-3"
      style={{ zIndex: "var(--ht-z-dock)" }}
    >
      <AnimatePresence>
        {open ? (
          <motion.div
            initial={reduce ? false : { opacity: 0, y: 14, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, y: 14, scale: 0.98 }}
            transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
            className="ht-panel-raised flex h-[min(34rem,calc(100dvh-7rem))] w-[min(24rem,calc(100vw-2rem))] flex-col overflow-hidden"
            role="dialog"
            aria-label="Cardiology Copilot"
          >
            <header className="flex items-center gap-2 px-4 py-3">
              <span
                aria-hidden
                className="grid size-7 place-items-center rounded-[var(--ht-r-sm)] border border-[var(--ht-accent-line)] bg-[var(--ht-accent-soft)] text-accent-bright"
              >
                <Sparkle weight="fill" className="size-4" />
              </span>
              <div className="flex flex-col leading-none">
                <span className="ht-panel-title text-[0.9rem]">Cardiology Copilot</span>
                <span className="ht-mono text-[0.62rem] text-muted">
                  {caseId ? `case ${caseId.slice(0, 8)}` : "no active case"}
                </span>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="ht-btn ht-btn-ghost ml-auto size-8 rounded-[var(--ht-r-sm)] p-0"
                aria-label="Close Cardiology Copilot"
              >
                <X weight="bold" className="size-4" />
              </button>
            </header>
            <div className="ht-hairline" />

            <div className="ht-copilot-surface min-h-0 flex-1">
              <CopilotChat
                className="h-full"
                instructions={COPILOT_INSTRUCTIONS}
                suggestions={SUGGESTIONS}
                labels={{
                  title: "Cardiology Copilot",
                  initial:
                    "I can build a cardiac twin from vitals, run the simulation, and " +
                    "answer questions about this case. All outputs are simulated " +
                    "educational estimates, not medical advice.",
                  placeholder: "Ask about this case or build a twin",
                }}
              />
            </div>
            <CopilotSurfaceStyle />
          </motion.div>
        ) : null}
      </AnimatePresence>

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="ht-btn ht-btn-primary size-12 rounded-full p-0 shadow-[var(--ht-shadow-raised)]"
        aria-expanded={open}
        aria-label={open ? "Close Cardiology Copilot" : "Open Cardiology Copilot"}
      >
        {open ? (
          <X weight="bold" className="size-5" />
        ) : (
          <ChatCircleDots weight="fill" className="size-5" />
        )}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scoped styling so the embedded CopilotChat sits flush inside the dock panel
// and adopts the console's type rhythm. Namespaced under .ht-copilot-surface so
// it never leaks into the rest of the app; globals.css stays untouched.
// ---------------------------------------------------------------------------

function CopilotSurfaceStyle() {
  return (
    <style>{`
      .ht-copilot-surface { display: flex; min-height: 0; }
      .ht-copilot-surface .copilotKitChat {
        flex: 1;
        min-height: 0;
        height: 100%;
        border: 0;
        border-radius: 0;
        box-shadow: none;
        background: transparent;
        font-family: var(--font-sans);
      }
      .ht-copilot-surface .copilotKitMessages { padding: 0.75rem 0.875rem; }
      .ht-copilot-surface .copilotKitMessage {
        font-size: 0.84rem;
        line-height: 1.5;
        border-radius: var(--ht-r-md);
      }
      .ht-copilot-surface .copilotKitMessage.copilotKitUserMessage {
        background: var(--ht-accent);
        color: var(--ht-accent-ink);
      }
      .ht-copilot-surface .copilotKitMessage.copilotKitAssistantMessage {
        background: var(--ht-surface-3);
        color: var(--ht-ink);
        border: 1px solid var(--ht-line);
      }
      .ht-copilot-surface .copilotKitInputContainer { padding: 0.625rem 0.75rem 0.75rem; }
      .ht-copilot-surface .copilotKitInput {
        border: 1px solid var(--ht-line-strong);
        border-radius: var(--ht-r-md);
        background: var(--ht-surface-1);
      }
      .ht-copilot-surface .copilotKitInput:focus-within {
        border-color: var(--ht-signal-line);
      }
      .ht-copilot-surface textarea::placeholder { color: var(--ht-muted); }
      .ht-copilot-surface .copilotKitCodeBlock,
      .ht-copilot-surface code { font-family: var(--font-mono); }
    `}</style>
  );
}

// ---------------------------------------------------------------------------
// HITL confirm card (rendered by renderAndWaitForResponse).
// ---------------------------------------------------------------------------

function RecoveryConfirmCard({
  status,
  summary,
  respond,
}: {
  status: ActionStatus;
  summary?: string;
  respond?: (result: string) => void;
}) {
  const reduce = useReducedMotion();
  const [choice, setChoice] = useState<"confirmed" | "declined" | null>(null);
  const answered = status === "complete" || choice !== null;

  const decide = (value: "confirmed" | "declined") => {
    if (answered || !respond) return;
    setChoice(value);
    respond(
      value === "confirmed"
        ? "The user confirmed. Proceed to run simulate_recovery now."
        : "The user declined. Do not run simulate_recovery; ask what they would like instead.",
    );
  };

  const resolved = choice ?? (status === "complete" ? "confirmed" : null);

  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 8, scale: 0.99 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.26, ease: [0.16, 1, 0.3, 1] }}
      className="ht-panel my-1.5 w-full overflow-hidden"
    >
      <header className="flex items-center gap-2.5 px-3 py-2.5">
        <span
          aria-hidden
          className="grid size-7 flex-none place-items-center rounded-[var(--ht-r-sm)] border border-[var(--ht-ecg-line)]"
          style={{ color: "var(--ht-ecg)", background: "var(--ht-ecg-soft)" }}
        >
          <Activity weight="duotone" className="size-4" />
        </span>
        <div className="flex min-w-0 flex-col">
          <span className="ht-eyebrow leading-tight">Confirm · Recovery</span>
          <span className="text-[0.84rem] font-semibold text-ink">
            Run recovery simulation?
          </span>
        </div>
      </header>
      <div className="ht-hairline" />
      <div className="flex flex-col gap-2.5 px-3 py-2.5">
        <p className="text-[0.76rem] leading-relaxed text-muted">
          {summary ??
            "This runs bounded, simulated recovery trajectories over the current twin state. Results are educational estimates, not a treatment plan."}
        </p>

        {!answered ? (
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => decide("declined")}
              className="ht-btn ht-btn-secondary h-9"
            >
              Not now
            </button>
            <button
              type="button"
              onClick={() => decide("confirmed")}
              className="ht-btn ht-btn-primary h-9"
            >
              <ArrowsClockwise weight="bold" className="size-4" />
              Run simulation
            </button>
          </div>
        ) : (
          <div
            className="ht-chip self-start"
            data-status={resolved === "confirmed" ? "success" : "idle"}
          >
            {resolved === "confirmed" ? (
              <>
                <CheckCircle weight="fill" className="size-3.5" />
                Confirmed
              </>
            ) : (
              <>
                <X weight="bold" className="size-3.5" />
                Declined
              </>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
}
