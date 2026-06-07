"use client";

/*
 * CONTRACT: owns the evaluator scorecard — the evaluator/critic agent's quality
 *   scores (extraction completeness, physiological plausibility, safety
 *   compliance, hallucination risk, visualization readiness, recovery scenario
 *   stability, overall) and the pass/fail verdict, plus warnings + failed checks.
 * READS from store: evaluation (EvaluationReport), status.
 *
 * Design: not the hero-metric cliché. The overall verdict is a slim ledger strip
 *   (verdict chip + tabular overall, with a fine progress meter), and each metric
 *   is an animated track that fills from its score. Hallucination risk reads
 *   lower-is-better: its track is inverted and its hue flips on the risk band.
 *   Bars animate via motion, values count up, reveals stagger. Warnings and
 *   failed checks are surfaced as their own typed lists below the tracks.
 */

import { useEffect, useMemo } from "react";
import {
  Gauge,
  SealCheck,
  Warning,
  WarningOctagon,
  ShieldCheck,
  ArrowDown,
} from "@phosphor-icons/react";
import {
  animate,
  motion,
  useMotionValue,
  useReducedMotion,
  useTransform,
  type MotionValue,
} from "motion/react";
import { Panel, PanelBody, PanelEmpty, PanelHeader } from "@/components/ui/Panel";
import { useHeartTwinStore } from "@/lib/store";
import type { EvaluationReport } from "@/types/api";

/** Visual band for a 0-1 score. `invert` = lower is better (hallucination). */
type Band = "good" | "watch" | "poor";

interface MetricSpec {
  key: string;
  label: string;
  /** lower-is-better metric (hallucination risk). */
  invert?: boolean;
}

const METRICS: MetricSpec[] = [
  { key: "extraction_completeness", label: "Extraction completeness" },
  { key: "physiological_plausibility", label: "Physiological plausibility" },
  { key: "safety_compliance", label: "Safety compliance" },
  { key: "hallucination_risk", label: "Hallucination risk", invert: true },
  { key: "visualization_readiness", label: "Visualization readiness" },
  { key: "recovery_scenario_stability", label: "Recovery stability" },
];

const BAND_COLOR: Record<Band, string> = {
  good: "var(--ht-ecg)",
  watch: "var(--ht-warn)",
  poor: "var(--ht-accent-bright)",
};

/** Classify a 0-1 value into a band. For invert metrics, low value is good. */
function bandFor(value: number, invert?: boolean): Band {
  const goodness = invert ? 1 - value : value;
  if (goodness >= 0.85) return "good";
  if (goodness >= 0.6) return "watch";
  return "poor";
}

/**
 * Pull the 0-1 score for a metric, preferring eval_scores then scores. Returns
 * null when the field is genuinely absent so a track renders "not scored"
 * instead of a fake zero.
 */
function readScore(
  evaluation: EvaluationReport,
  key: string,
): number | null {
  const fromEval = evaluation.eval_scores as
    | Record<string, unknown>
    | undefined;
  const fromScores = evaluation.scores as Record<string, unknown> | undefined;
  const raw = fromEval?.[key] ?? fromScores?.[key];
  return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
}

function readOverall(evaluation: EvaluationReport): number | null {
  const e = evaluation.eval_scores?.overall_score;
  if (typeof e === "number" && Number.isFinite(e)) return e;
  const s = evaluation.scores.overall_score ?? evaluation.scores.overall;
  return typeof s === "number" && Number.isFinite(s) ? s : null;
}

/** Tabular numeric that counts up to `value` (0-100 scale) on change. */
function CountUp({
  mv,
  suffix = "",
  decimals = 0,
}: {
  mv: MotionValue<number>;
  suffix?: string;
  decimals?: number;
}) {
  const text = useTransform(mv, (v) => `${v.toFixed(decimals)}${suffix}`);
  return <motion.span>{text}</motion.span>;
}

function MetricTrack({
  spec,
  value,
  index,
  reduce,
}: {
  spec: MetricSpec;
  value: number | null;
  index: number;
  reduce: boolean;
}) {
  const pct = value === null ? 0 : Math.max(0, Math.min(1, value)) * 100;
  const band = value === null ? "watch" : bandFor(value, spec.invert);
  const color = BAND_COLOR[band];

  const counter = useMotionValue(0);
  useEffect(() => {
    if (value === null) {
      counter.set(0);
      return;
    }
    if (reduce) {
      counter.set(pct);
      return;
    }
    const controls = animate(counter, pct, {
      duration: 0.9,
      delay: 0.06 + index * 0.05,
      ease: [0.16, 1, 0.3, 1],
    });
    return () => controls.stop();
  }, [counter, pct, value, reduce, index]);

  return (
    <li className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1.5">
      <div className="flex items-center gap-1.5">
        {spec.invert ? (
          <ArrowDown
            weight="bold"
            aria-label="lower is better"
            className="size-3 text-faint"
          />
        ) : null}
        <span className="text-[0.78rem] leading-tight text-ink-2">
          {spec.label}
        </span>
      </div>

      <span
        className="ht-mono text-right text-[0.74rem] tabular-nums"
        style={{ color: value === null ? "var(--ht-muted)" : color }}
      >
        {value === null ? "n/a" : <CountUp mv={counter} />}
      </span>

      <div
        className="col-span-2 h-[5px] overflow-hidden rounded-full"
        style={{ background: "var(--ht-surface-3)" }}
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value === null ? undefined : Math.round(pct)}
        aria-label={spec.label}
      >
        <motion.div
          className="h-full rounded-full"
          style={{ background: color, transformOrigin: "left center" }}
          initial={reduce ? false : { scaleX: 0 }}
          animate={{ scaleX: pct / 100 }}
          transition={{
            duration: reduce ? 0 : 0.9,
            delay: reduce ? 0 : 0.06 + index * 0.05,
            ease: [0.16, 1, 0.3, 1],
          }}
        />
      </div>
    </li>
  );
}

export function EvalScorecard() {
  const evaluation = useHeartTwinStore((s) => s.evaluation);
  const reduce = useReducedMotion() ?? false;

  const overall = evaluation ? readOverall(evaluation) : null;
  const passed = evaluation?.passed ?? false;

  const overallPct = overall === null ? 0 : Math.max(0, Math.min(1, overall)) * 100;
  const overallBand: Band = overall === null ? "watch" : bandFor(overall);
  const overallColor = BAND_COLOR[overallBand];

  const overallCounter = useMotionValue(0);
  useEffect(() => {
    if (overall === null) {
      overallCounter.set(0);
      return;
    }
    if (reduce) {
      overallCounter.set(overallPct);
      return;
    }
    const controls = animate(overallCounter, overallPct, {
      duration: 1.1,
      ease: [0.16, 1, 0.3, 1],
    });
    return () => controls.stop();
  }, [overallCounter, overallPct, overall, reduce]);

  const warnings = useMemo(() => {
    if (!evaluation) return [] as string[];
    const fromEval = evaluation.eval_scores?.warnings ?? [];
    const top = evaluation.warnings ?? [];
    // De-duplicate while preserving order; eval_scores warnings first.
    return Array.from(new Set([...fromEval, ...top]));
  }, [evaluation]);

  const failedChecks = useMemo(() => {
    if (!evaluation) return [] as string[];
    const a = evaluation.eval_scores?.failed_checks ?? [];
    const b = evaluation.failed_checks ?? [];
    return Array.from(new Set([...a, ...b]));
  }, [evaluation]);

  const hasEval = Boolean(evaluation);

  return (
    <Panel className="h-full">
      <PanelHeader
        icon={Gauge}
        accent="ecg"
        eyebrow="Quality"
        title="Evaluation"
        actions={
          hasEval ? (
            <span
              className="ht-chip"
              data-status={passed ? "success" : "warning"}
            >
              <SealCheck weight="fill" className="size-3.5" />
              {passed ? "Passed" : "Needs review"}
            </span>
          ) : (
            <span className="ht-chip" data-status="idle">
              <span className="ht-chip-dot" />
              Standby
            </span>
          )
        }
      />
      <div className="ht-hairline" />
      <PanelBody className="pt-4">
        {!hasEval || !evaluation ? (
          <PanelEmpty
            icon={Gauge}
            accent="ecg"
            title="No scores yet"
            hint="The evaluator scores extraction, plausibility, safety, hallucination risk, and recovery stability after the simulation runs."
          />
        ) : (
          <div className="flex flex-col gap-4">
            {/* Overall verdict ledger — a slim strip, not a hero number. */}
            <div className="flex flex-col gap-2 rounded-[var(--ht-r-md)] border border-[var(--ht-line)] bg-surface-2/50 px-3.5 py-3">
              <div className="flex items-baseline justify-between">
                <span className="ht-eyebrow">Overall score</span>
                <span
                  className="ht-mono text-[1.35rem] font-medium leading-none tabular-nums"
                  style={{ color: overallColor }}
                >
                  {overall === null ? (
                    "n/a"
                  ) : (
                    <CountUp mv={overallCounter} decimals={0} />
                  )}
                  {overall === null ? null : (
                    <span className="ml-0.5 text-[0.7rem] text-muted">/100</span>
                  )}
                </span>
              </div>
              <div
                className="h-1.5 overflow-hidden rounded-full"
                style={{ background: "var(--ht-surface-3)" }}
                role="meter"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={overall === null ? undefined : Math.round(overallPct)}
                aria-label="Overall evaluation score"
              >
                <motion.div
                  className="h-full rounded-full"
                  style={{
                    background: overallColor,
                    transformOrigin: "left center",
                  }}
                  initial={reduce ? false : { scaleX: 0 }}
                  animate={{ scaleX: overallPct / 100 }}
                  transition={{
                    duration: reduce ? 0 : 1.1,
                    ease: [0.16, 1, 0.3, 1],
                  }}
                />
              </div>
            </div>

            {/* Per-metric animated tracks. */}
            <ul className="grid gap-3">
              {METRICS.map((spec, i) => (
                <MetricTrack
                  key={spec.key}
                  spec={spec}
                  value={readScore(evaluation, spec.key)}
                  index={i}
                  reduce={reduce}
                />
              ))}
            </ul>

            {/* Failed checks: hard gates the evaluator tripped. */}
            {failedChecks.length > 0 ? (
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-1.5">
                  <WarningOctagon
                    weight="fill"
                    className="size-3.5 text-accent-bright"
                  />
                  <span className="ht-eyebrow text-accent-bright">
                    Failed checks
                  </span>
                  <span className="ht-mono ml-auto text-[0.68rem] text-muted">
                    {failedChecks.length}
                  </span>
                </div>
                <ul className="flex flex-col gap-1.5">
                  {failedChecks.map((check, i) => (
                    <motion.li
                      key={check}
                      initial={reduce ? false : { opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{
                        duration: 0.35,
                        delay: 0.04 * i,
                        ease: [0.16, 1, 0.3, 1],
                      }}
                      className="ht-mono flex items-start gap-2 rounded-[var(--ht-r-sm)] border border-[var(--ht-accent-line)] bg-[var(--ht-accent-soft)] px-2.5 py-1.5 text-[0.72rem] leading-snug text-ink-2"
                    >
                      <span className="mt-px text-accent-bright">·</span>
                      <span className="min-w-0 break-words">{check}</span>
                    </motion.li>
                  ))}
                </ul>
              </div>
            ) : null}

            {/* Soft warnings from the evaluator + critic. */}
            {warnings.length > 0 ? (
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-1.5">
                  <Warning weight="fill" className="size-3.5 text-warn" />
                  <span className="ht-eyebrow text-warn">Warnings</span>
                  <span className="ht-mono ml-auto text-[0.68rem] text-muted">
                    {warnings.length}
                  </span>
                </div>
                <ul className="flex flex-col gap-1.5">
                  {warnings.map((warning, i) => (
                    <motion.li
                      key={warning}
                      initial={reduce ? false : { opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{
                        duration: 0.35,
                        delay: 0.04 * i,
                        ease: [0.16, 1, 0.3, 1],
                      }}
                      className="flex items-start gap-2 rounded-[var(--ht-r-sm)] border border-[var(--ht-warn-line)] bg-[var(--ht-warn-soft)] px-2.5 py-1.5 text-[0.74rem] leading-snug text-ink-2"
                    >
                      <span className="mt-px text-warn">·</span>
                      <span className="min-w-0">{warning}</span>
                    </motion.li>
                  ))}
                </ul>
              </div>
            ) : null}

            {/* Clean-run affirmation when the evaluator found nothing to flag. */}
            {warnings.length === 0 && failedChecks.length === 0 ? (
              <div className="flex items-center gap-2 rounded-[var(--ht-r-sm)] border border-[var(--ht-ecg-line)] bg-[var(--ht-ecg-soft)] px-2.5 py-2">
                <ShieldCheck weight="fill" className="size-4 text-ecg" />
                <span className="text-[0.74rem] text-ink-2">
                  No warnings or failed checks on this run.
                </span>
              </div>
            ) : null}
          </div>
        )}
      </PanelBody>
    </Panel>
  );
}
