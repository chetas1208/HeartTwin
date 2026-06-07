"use client";

/*
 * CONTRACT: owns the console chrome and the viewport-fit layout: a left rail
 *   (case intake), a dominant center work surface that tabs between the Digital
 *   Twin (3D) and Physiology Simulation (charts), and a right rail of compressed
 *   observability (agent trace, evaluation, case memory). Also renders the
 *   header, CopilotDock, footer, and the first-open DisclaimerModal (the safety
 *   boundary lives there, not a persistent banner), and bootstraps the SSE trace
 *   stream + initial Redis snapshot.
 * READS from store: caseId, status, redisStats (and wires the trace stream).
 * This is the foundation's layout. Sibling agents edit the individual panel
 *   files, NOT this grid. If a panel needs more or less space, coordinate here.
 */

import { useEffect, useState } from "react";
import { Heartbeat } from "@phosphor-icons/react";
import { useHeartTwinStore, type PipelineStatus } from "@/lib/store";
import { redisStats } from "@/lib/api";
import { useTraceStream } from "@/hooks/useTraceStream";
import { DisclaimerModal } from "@/components/safety/DisclaimerModal";
import { WeaveBadge } from "@/components/eval/WeaveBadge";
import { CaseIntakePanel } from "@/components/intake/CaseIntakePanel";
import { AgentTraceTimeline } from "@/components/trace/AgentTraceTimeline";
import { SimulationCharts } from "@/components/charts/SimulationCharts";
import { HeartScene } from "@/components/heart/HeartScene";
import { EvalScorecard } from "@/components/eval/EvalScorecard";
import { RedisStatsRail } from "@/components/redis/RedisStatsRail";
import { CopilotDock } from "@/components/copilot/CopilotDock";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

const STATUS_LABEL: Record<PipelineStatus, string> = {
  idle: "Ready",
  creating: "Creating case",
  created: "Case created",
  extracting: "Extracting evidence",
  extracted: "Evidence validated",
  operating: "Building twin",
  operated: "Twin operating",
  simulating: "Simulating recovery",
  complete: "Run complete",
  improving: "Self-improving",
  error: "Run failed",
};

function statusKind(status: PipelineStatus): string {
  if (status === "error") return "failed";
  if (status === "complete") return "success";
  if (status === "idle") return "idle";
  return "running";
}

type CenterTab = "twin" | "sim";

const CENTER_TABS: { id: CenterTab; label: string }[] = [
  { id: "twin", label: "Digital Twin" },
  { id: "sim", label: "Physiology Simulation" },
];

export function AppShell() {
  const status = useHeartTwinStore((s) => s.status);
  const caseId = useHeartTwinStore((s) => s.caseId);
  const setRedisStats = useHeartTwinStore((s) => s.setRedisStats);
  const [tab, setTab] = useState<CenterTab>("twin");

  // Live trace stream for the active case (no polling fallback).
  useTraceStream(caseId, { enabled: Boolean(caseId) });

  // One initial Redis/system snapshot so the rail is honest on first paint.
  useEffect(() => {
    let cancelled = false;
    redisStats()
      .then((stats) => {
        if (!cancelled) setRedisStats(stats);
      })
      .catch(() => {
        /* backend offline at boot — rail shows standby, no fake data */
      });
    return () => {
      cancelled = true;
    };
  }, [setRedisStats]);

  return (
    <div className="flex min-h-[100dvh] flex-col lg:h-[100dvh] lg:min-h-0 lg:overflow-hidden">
      <header
        className="sticky top-0 border-b border-[var(--ht-line)] bg-[color-mix(in_oklab,var(--ht-bg)_82%,transparent)] backdrop-blur-md"
        style={{ zIndex: "var(--ht-z-sticky)" }}
      >
        <div className="mx-auto flex w-full max-w-[1480px] items-center gap-4 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2.5">
            <span
              aria-hidden
              className="grid size-9 place-items-center rounded-[var(--ht-r-sm)] border border-[var(--ht-accent-line)] bg-[var(--ht-accent-soft)] text-accent-bright"
            >
              <Heartbeat weight="fill" className="size-5" />
            </span>
            <span className="text-[0.95rem] font-semibold tracking-tight text-ink">
              HeartTwin Lab
            </span>
          </div>

          <div className="ml-auto flex items-center gap-2.5">
            <span className="ht-chip" data-status={statusKind(status)}>
              <span
                className={`ht-chip-dot ${statusKind(status) === "running" ? "ht-pulse" : ""}`}
              />
              {STATUS_LABEL[status]}
            </span>
            {/* Weave link slot */}
            <WeaveBadge />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1600px] flex-1 px-3 py-3 sm:px-4 lg:min-h-0 lg:overflow-hidden">
        <div className="grid grid-cols-12 gap-3 lg:h-full lg:min-h-0">
          {/* Left rail: case intake */}
          <div className="col-span-12 flex flex-col lg:col-span-3 lg:min-h-0 lg:[&>*]:h-full">
            <ErrorBoundary name="Case intake"><CaseIntakePanel /></ErrorBoundary>
          </div>

          {/* Center: the cardiac work surface — tabbed twin / simulation */}
          <div className="col-span-12 flex flex-col border border-[var(--ht-line)] bg-[var(--ht-surface-1)] lg:col-span-6 lg:min-h-0">
            <div
              role="tablist"
              aria-label="Cardiac view"
              className="flex flex-none border-b border-[var(--ht-line)]"
            >
              {CENTER_TABS.map((t) => (
                <button
                  key={t.id}
                  role="tab"
                  aria-selected={tab === t.id}
                  onClick={() => setTab(t.id)}
                  className={`-mb-px border-b-2 px-4 py-2.5 text-[0.82rem] font-medium transition-colors ${
                    tab === t.id
                      ? "border-accent-bright text-ink"
                      : "border-transparent text-muted hover:text-ink-2"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div className="min-h-0 flex-1 [&>*]:h-full [&_.ht-panel]:border-0">
              {tab === "twin" ? (
                <ErrorBoundary name="Cardiac viewport"><HeartScene /></ErrorBoundary>
              ) : (
                <ErrorBoundary name="Simulation charts"><SimulationCharts /></ErrorBoundary>
              )}
            </div>
          </div>

          {/* Right rail: compressed observability — trace, evaluation, memory */}
          <div className="col-span-12 grid gap-3 lg:col-span-3 lg:min-h-0 lg:grid-rows-3 lg:[&>*]:min-h-0 lg:[&>*]:h-full">
            <ErrorBoundary name="Agent trace"><AgentTraceTimeline /></ErrorBoundary>
            <ErrorBoundary name="Evaluation"><EvalScorecard /></ErrorBoundary>
            <ErrorBoundary name="Redis case memory"><RedisStatsRail /></ErrorBoundary>
          </div>
        </div>
      </main>

      <footer className="border-t border-[var(--ht-line)]">
        <div className="mx-auto w-full max-w-[1480px] px-4 py-3 sm:px-6">
          <p className="text-[0.68rem] text-faint">
            Simulated educational estimates. Not a medical device.
          </p>
        </div>
      </footer>

      <DisclaimerModal />
      <ErrorBoundary name="Cardiology Copilot"><CopilotDock /></ErrorBoundary>
    </div>
  );
}
