"use client";

/*
 * CONTRACT: compact evaluator scorecard — the evaluator/critic agent's quality
 *   scores as one-line rows (label + value colored by band), a verdict chip, and
 *   a single summary line for failed checks / warnings. No bars, no animation:
 *   everything visible at once. READS from store: evaluation (EvaluationReport).
 */

import { useMemo } from "react";
import { Gauge, SealCheck } from "@phosphor-icons/react";
import { Panel, PanelBody, PanelEmpty, PanelHeader } from "@/components/ui/Panel";
import { useHeartTwinStore } from "@/lib/store";
import type { EvaluationReport } from "@/types/api";

type Band = "good" | "watch" | "poor";

interface MetricSpec {
  key: string;
  label: string;
  invert?: boolean;
}

const METRICS: MetricSpec[] = [
  { key: "extraction_completeness", label: "Extraction" },
  { key: "physiological_plausibility", label: "Plausibility" },
  { key: "safety_compliance", label: "Safety" },
  { key: "hallucination_risk", label: "Hallucination risk", invert: true },
  { key: "visualization_readiness", label: "Visualization" },
  { key: "recovery_scenario_stability", label: "Recovery stability" },
];

const BAND_COLOR: Record<Band, string> = {
  good: "var(--ht-ecg)",
  watch: "var(--ht-warn)",
  poor: "var(--ht-accent-bright)",
};

function bandFor(value: number, invert?: boolean): Band {
  const goodness = invert ? 1 - value : value;
  if (goodness >= 0.85) return "good";
  if (goodness >= 0.6) return "watch";
  return "poor";
}

function readScore(evaluation: EvaluationReport, key: string): number | null {
  const fromEval = evaluation.eval_scores as Record<string, unknown> | undefined;
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

function pct(value: number | null): string {
  return value === null ? "n/a" : `${Math.round(Math.max(0, Math.min(1, value)) * 100)}`;
}

export function EvalScorecard() {
  const evaluation = useHeartTwinStore((s) => s.evaluation);

  const overall = evaluation ? readOverall(evaluation) : null;
  const passed = evaluation?.passed ?? false;

  const warnings = useMemo(() => {
    if (!evaluation) return [] as string[];
    return Array.from(
      new Set([...(evaluation.eval_scores?.warnings ?? []), ...(evaluation.warnings ?? [])]),
    );
  }, [evaluation]);
  const failedChecks = useMemo(() => {
    if (!evaluation) return [] as string[];
    return Array.from(
      new Set([
        ...(evaluation.eval_scores?.failed_checks ?? []),
        ...(evaluation.failed_checks ?? []),
      ]),
    );
  }, [evaluation]);

  return (
    <Panel className="h-full">
      <PanelHeader
        icon={Gauge}
        accent="ecg"
        eyebrow="Quality"
        title="Evaluation"
        actions={
          evaluation ? (
            <span className="ht-chip" data-status={passed ? "success" : "warning"}>
              <SealCheck weight="fill" className="size-3.5" />
              {passed ? "Passed" : "Review"}
              {overall !== null ? ` · ${pct(overall)}` : ""}
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
      <PanelBody className="pt-2">
        {!evaluation ? (
          <PanelEmpty
            icon={Gauge}
            accent="ecg"
            title="No scores yet"
            hint="Scores appear after the simulation runs."
          />
        ) : (
          <ol className="flex flex-col">
            {METRICS.map((spec) => {
              const v = readScore(evaluation, spec.key);
              const band = v === null ? "watch" : bandFor(v, spec.invert);
              return (
                <li
                  key={spec.key}
                  className="flex items-center gap-2 border-b border-[var(--ht-line)] py-1.5 last:border-0"
                >
                  <span className="truncate text-[0.78rem] text-ink-2">{spec.label}</span>
                  <span
                    className="ht-mono ml-auto flex-none text-[0.74rem] tabular-nums"
                    style={{ color: v === null ? "var(--ht-muted)" : BAND_COLOR[band] }}
                  >
                    {pct(v)}
                  </span>
                </li>
              );
            })}
            {/* Failed checks / warnings always list their reasons, never a
                bare count or icon. */}
            {failedChecks.length > 0 ? (
              <li className="pt-2.5">
                <p className="ht-eyebrow text-accent-bright">
                  Failed checks · {failedChecks.length}
                </p>
                <ul className="mt-1 flex flex-col gap-1">
                  {failedChecks.map((c) => (
                    <li key={c} className="text-[0.64rem] leading-snug text-ink-2">
                      · {c}
                    </li>
                  ))}
                </ul>
              </li>
            ) : null}
            {warnings.length > 0 ? (
              <li className="pt-2.5">
                <p className="ht-eyebrow text-warn">Warnings · {warnings.length}</p>
                <ul className="mt-1 flex flex-col gap-1">
                  {warnings.map((w) => (
                    <li key={w} className="text-[0.64rem] leading-snug text-ink-2">
                      · {w}
                    </li>
                  ))}
                </ul>
              </li>
            ) : null}
          </ol>
        )}
      </PanelBody>
    </Panel>
  );
}
