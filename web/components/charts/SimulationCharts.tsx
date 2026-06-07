"use client";

/*
 * CONTRACT: owns the quantitative simulation views — the pressure-volume loop,
 *   the cardiac-cycle waveform, and the multi-day recovery trajectories with
 *   uncertainty bands.
 * READS from store: visualization (SimulationVisualization), scenarios
 *   (RecoveryScenario[]), status.
 * Charts render through the shared Plot wrapper (./Plot, client-only, binds
 *   plotly.js-dist-min) using basePlotLayout/basePlotConfig so they inherit the
 *   console palette. Colors are resolved from the OKLCH design tokens at runtime
 *   (getComputedStyle on :root) — never hardcoded — because Plotly draws to its
 *   own SVG/canvas and needs concrete color strings.
 *
 * Data notes (verified against the live backend):
 *   - visualization.pv_loop: closed loop, volume_ml × pressure_mmhg (≈200 pts).
 *     EDV/ESV/EDP are derived from the loop (max/min volume + pressure there).
 *   - visualization.cardiac_cycle: time_ms with pressure_mmhg + volume_ml over
 *     one beat (≈50 samples). Pressure and volume live on two y-axes.
 *   - scenarios[].trajectory[].uncertainty_low/high bound CARDIAC OUTPUT
 *     (cardiac_output_l_min), not EF — the band wraps the CO line.
 */

import { useEffect, useMemo, useSyncExternalStore } from "react";
import { motion, useReducedMotion } from "motion/react";
import {
  ChartLineUp,
  Heartbeat,
  Pulse,
  Waveform,
} from "@phosphor-icons/react";
import type { PlotParams } from "react-plotly.js";
import Plot, { basePlotConfig, basePlotLayout } from "@/components/charts/Plot";
import {
  Panel,
  PanelBody,
  PanelEmpty,
  PanelHeader,
} from "@/components/ui/Panel";
import { useHeartTwinStore } from "@/lib/store";
import type {
  RecoveryScenario,
  SimulationVisualization,
} from "@/types/heart";

// Derive Plotly types from the react-plotly.js public API so we never depend on
// @types/plotly.js being resolvable on its own (the foundation does the same).
type PlotLayout = PlotParams["layout"];
type PlotTrace = PlotParams["data"][number];

// ---------------------------------------------------------------------------
// Token resolution — read concrete colors from the OKLCH design tokens so the
// charts stay on-brand without re-specifying any palette here.
// ---------------------------------------------------------------------------

interface ChartPalette {
  accent: string; // systolic crimson — primary / pressure / PV loop
  signal: string; // signal cyan — data / volume
  ecg: string; // recovery green
  warn: string; // amber
  ink2: string;
  muted: string;
  surface2: string;
}

const FALLBACK_PALETTE: ChartPalette = {
  accent: "#e8556a",
  signal: "#5fd4d8",
  ecg: "#52d6a0",
  warn: "#e8b84a",
  ink2: "#cfd6e2",
  muted: "#9aa6ba",
  surface2: "#262b38",
};

function readToken(style: CSSStyleDeclaration, name: string, fallback: string) {
  const v = style.getPropertyValue(name).trim();
  return v.length > 0 ? v : fallback;
}

/** Resolve the brand tokens to concrete strings once the document is available. */
function resolvePalette(): ChartPalette {
  if (typeof window === "undefined") return FALLBACK_PALETTE;
  const s = getComputedStyle(document.documentElement);
  return {
    accent: readToken(s, "--ht-accent-bright", FALLBACK_PALETTE.accent),
    signal: readToken(s, "--ht-signal-bright", FALLBACK_PALETTE.signal),
    ecg: readToken(s, "--ht-ecg", FALLBACK_PALETTE.ecg),
    warn: readToken(s, "--ht-warn", FALLBACK_PALETTE.warn),
    ink2: readToken(s, "--ht-ink-2", FALLBACK_PALETTE.ink2),
    muted: readToken(s, "--ht-muted", FALLBACK_PALETTE.muted),
    surface2: readToken(s, "--ht-surface-2", FALLBACK_PALETTE.surface2),
  };
}

/** Add an alpha channel to an oklch(...) / hex / rgb color string for fills. */
function withAlpha(color: string, alpha: number): string {
  const c = color.trim();
  if (c.startsWith("oklch(")) {
    const inner = c.slice(6, -1).trim();
    if (inner.includes("/")) {
      return `oklch(${inner.split("/")[0].trim()} / ${alpha})`;
    }
    return `oklch(${inner} / ${alpha})`;
  }
  if (c.startsWith("rgb(")) {
    return c.replace("rgb(", "rgba(").replace(")", `, ${alpha})`);
  }
  if (c.startsWith("rgba(")) {
    return c.replace(/,[^,]*\)$/, `, ${alpha})`);
  }
  if (c.startsWith("#")) {
    const a = Math.round(alpha * 255)
      .toString(16)
      .padStart(2, "0");
    const hex = c.length === 4 ? c.slice(1).replace(/(.)/g, "$1$1") : c.slice(1);
    return `#${hex}${a}`;
  }
  return c;
}

// Token values are static for the session and exist only client-side. Read them
// once via useSyncExternalStore: the SSR/first-paint snapshot is the fallback,
// the client snapshot resolves the real OKLCH tokens. The subscribe is a no-op
// because the tokens never change after hydration (no theme switching here).
let cachedPalette: ChartPalette | null = null;

function getClientPalette(): ChartPalette {
  if (!cachedPalette) cachedPalette = resolvePalette();
  return cachedPalette;
}

function subscribe(): () => void {
  return () => {};
}

function usePalette(): ChartPalette {
  return useSyncExternalStore(
    subscribe,
    getClientPalette,
    () => FALLBACK_PALETTE,
  );
}

// ---------------------------------------------------------------------------
// Shared layout helpers
// ---------------------------------------------------------------------------

const CHART_HEIGHT = 196;
const RECOVERY_HEIGHT = 224;

function axisTheme(p: ChartPalette): NonNullable<PlotLayout["xaxis"]> {
  return {
    gridcolor: withAlpha(p.muted, 0.14),
    zerolinecolor: withAlpha(p.muted, 0.22),
    linecolor: withAlpha(p.muted, 0.24),
    tickfont: { size: 9.5, color: p.muted },
    title: { font: { size: 10, color: p.muted } },
    automargin: true,
  };
}

function mergeLayout(extra: PlotLayout): PlotLayout {
  const base = basePlotLayout as PlotLayout;
  return {
    ...base,
    ...extra,
    margin: { l: 46, r: 16, t: 10, b: 36, ...(extra.margin ?? {}) },
    font: { ...base.font, ...(extra.font ?? {}) },
  };
}

// ---------------------------------------------------------------------------
// Chart builders
// ---------------------------------------------------------------------------

function pvLoopFigure(viz: SimulationVisualization, p: ChartPalette) {
  const { volume_ml, pressure_mmhg } = viz.pv_loop;
  // Close the loop so the fill reads as one continuous cycle.
  const vx = [...volume_ml, volume_ml[0]];
  const py = [...pressure_mmhg, pressure_mmhg[0]];
  // End-diastolic / end-systolic points derived from the loop itself: EDV is the
  // maximum ventricular volume (end of filling), ESV the minimum (end of
  // ejection), and EDP the filling pressure at that end-diastolic sample.
  const edvIdx = volume_ml.indexOf(Math.max(...volume_ml));
  const edv_ml = volume_ml[edvIdx];
  const esv_ml = Math.min(...volume_ml);
  const edp_mmhg = pressure_mmhg[edvIdx];

  const data: PlotTrace[] = [
    {
      x: vx,
      y: py,
      type: "scatter",
      mode: "lines",
      fill: "toself",
      fillcolor: withAlpha(p.accent, 0.1),
      line: { color: p.accent, width: 2, shape: "spline", smoothing: 0.6 },
      hovertemplate:
        "%{x:.0f} mL · %{y:.0f} mmHg<extra></extra>",
      name: "PV loop",
    },
    {
      x: [esv_ml, edv_ml],
      y: [edp_mmhg, edp_mmhg],
      type: "scatter",
      mode: "markers",
      marker: {
        color: [p.signal, p.accent],
        size: 7,
        line: { color: p.surface2, width: 1.5 },
      },
      hovertemplate: "%{text}: %{x:.0f} mL<extra></extra>",
      text: ["ESV", "EDV"],
      name: "volumes",
    },
  ];

  const layout = mergeLayout({
    height: CHART_HEIGHT,
    showlegend: false,
    xaxis: { ...axisTheme(p), title: { text: "Volume (mL)" } },
    yaxis: { ...axisTheme(p), title: { text: "Pressure (mmHg)" } },
    annotations: [
      {
        x: 0.5,
        y: 1.02,
        xref: "paper",
        yref: "paper",
        text: `stroke work ${viz.pv_loop.stroke_work_j.toFixed(2)} J`,
        showarrow: false,
        font: { size: 9.5, color: p.muted },
        xanchor: "center",
        yanchor: "bottom",
      },
    ],
  });

  return { data, layout };
}

function cardiacCycleFigure(viz: SimulationVisualization, p: ChartPalette) {
  const { time_ms, pressure_mmhg, volume_ml } = viz.cardiac_cycle;
  const t = time_ms.map((ms) => ms / 1000); // seconds reads cleaner

  const data: PlotTrace[] = [
    {
      x: t,
      y: pressure_mmhg,
      type: "scatter",
      mode: "lines",
      line: { color: p.accent, width: 1.9 },
      yaxis: "y",
      name: "LV pressure",
      hovertemplate: "%{x:.2f}s · %{y:.0f} mmHg<extra>pressure</extra>",
    },
    {
      x: t,
      y: volume_ml,
      type: "scatter",
      mode: "lines",
      line: { color: p.signal, width: 1.9, dash: "dot" },
      yaxis: "y2",
      name: "LV volume",
      hovertemplate: "%{x:.2f}s · %{y:.0f} mL<extra>volume</extra>",
    },
  ];

  const layout = mergeLayout({
    height: CHART_HEIGHT,
    showlegend: false,
    margin: { l: 44, r: 42, t: 10, b: 36 },
    xaxis: { ...axisTheme(p), title: { text: "Time (s)" } },
    yaxis: {
      ...axisTheme(p),
      title: { text: "Pressure (mmHg)", font: { size: 10, color: p.accent } },
      tickfont: { size: 9.5, color: p.accent },
    },
    yaxis2: {
      ...axisTheme(p),
      title: { text: "Volume (mL)", font: { size: 10, color: p.signal } },
      tickfont: { size: 9.5, color: p.signal },
      overlaying: "y",
      side: "right",
      showgrid: false,
    },
  });

  return { data, layout };
}

function recoveryFigure(scenarios: RecoveryScenario[], p: ChartPalette) {
  // Cycle the four brand hues; the uncertainty band wraps cardiac output.
  const hues = [p.ecg, p.signal, p.accent, p.warn];
  const data: PlotTrace[] = [];

  scenarios.forEach((sc, i) => {
    const color = hues[i % hues.length];
    const days = sc.trajectory.map((d) => d.day);
    const co = sc.trajectory.map((d) => d.cardiac_output_l_min);
    const low = sc.trajectory.map((d) => d.uncertainty_low);
    const high = sc.trajectory.map((d) => d.uncertainty_high);

    // Uncertainty band: high outline then low (reversed) filled to previous.
    data.push({
      x: days,
      y: high,
      type: "scatter",
      mode: "lines",
      line: { color: "transparent", width: 0 },
      hoverinfo: "skip",
      showlegend: false,
      name: `${sc.scenario_label} high`,
    });
    data.push({
      x: days,
      y: low,
      type: "scatter",
      mode: "lines",
      fill: "tonexty",
      fillcolor: withAlpha(color, 0.12),
      line: { color: "transparent", width: 0 },
      hoverinfo: "skip",
      showlegend: false,
      name: `${sc.scenario_label} low`,
    });
    // Central cardiac-output trajectory.
    data.push({
      x: days,
      y: co,
      type: "scatter",
      mode: "lines",
      line: { color, width: 2, shape: "spline", smoothing: 0.5 },
      name: scenarioShortLabel(sc),
      hovertemplate: `day %{x} · %{y:.2f} L/min<extra>${scenarioShortLabel(
        sc,
      )}</extra>`,
    });
  });

  const layout = mergeLayout({
    height: RECOVERY_HEIGHT,
    showlegend: true,
    legend: {
      orientation: "h",
      x: 0,
      y: 1.18,
      font: { size: 9.5, color: p.ink2 },
      bgcolor: "rgba(0,0,0,0)",
      itemsizing: "constant",
    },
    margin: { l: 46, r: 16, t: 34, b: 36 },
    xaxis: { ...axisTheme(p), title: { text: "Day" } },
    yaxis: { ...axisTheme(p), title: { text: "Cardiac output (L/min)" } },
  });

  return { data, layout };
}

function scenarioShortLabel(sc: RecoveryScenario): string {
  // "Simulated Load Reduction Scenario" -> "Load Reduction"
  const cleaned = sc.scenario_label
    .replace(/^simulated\s+/i, "")
    .replace(/\s+scenario$/i, "")
    .trim();
  return cleaned.length > 0 ? cleaned : sc.scenario_type.replace(/_/g, " ");
}

// ---------------------------------------------------------------------------
// Readouts (elegant, not the banned hero-metric template)
// ---------------------------------------------------------------------------

interface Readout {
  label: string;
  value: string;
  unit: string;
}

function buildReadouts(viz: SimulationVisualization): Readout[] {
  const s = viz.summary;
  return [
    { label: "Ejection fraction", value: s.ef_pct.toFixed(1), unit: "%" },
    {
      label: "Cardiac output",
      value: s.cardiac_output_l_min.toFixed(2),
      unit: "L/min",
    },
    { label: "Mean arterial", value: s.map_mmhg.toFixed(0), unit: "mmHg" },
    { label: "Stroke volume", value: s.stroke_volume_ml.toFixed(0), unit: "mL" },
  ];
}

function ReadoutStrip({ readouts }: { readouts: Readout[] }) {
  const reduce = useReducedMotion();
  return (
    <div className="grid grid-cols-2 divide-y divide-[var(--ht-line)] overflow-hidden rounded-[var(--ht-r-md)] border border-[var(--ht-line)] bg-[color-mix(in_oklab,var(--ht-surface-2)_45%,transparent)] sm:grid-cols-4 sm:divide-y-0 sm:divide-x">
      {readouts.map((r, i) => (
        <motion.div
          key={r.label}
          className="flex flex-col gap-1 px-3.5 py-3"
          initial={reduce ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            duration: 0.42,
            delay: reduce ? 0 : i * 0.05,
            ease: [0.16, 1, 0.3, 1],
          }}
        >
          <span className="text-[0.66rem] font-medium uppercase tracking-[0.08em] text-muted">
            {r.label}
          </span>
          <span className="flex items-baseline gap-1">
            <span className="ht-mono text-[1.35rem] font-semibold leading-none text-ink">
              {r.value}
            </span>
            <span className="ht-mono text-[0.7rem] text-ink-2">{r.unit}</span>
          </span>
        </motion.div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chart bay shell (header + framed plot), with enter animation
// ---------------------------------------------------------------------------

function ChartBay({
  label,
  meta,
  icon: Icon,
  index,
  className = "",
  children,
}: {
  label: string;
  meta?: string;
  icon: typeof Heartbeat;
  index: number;
  className?: string;
  children: React.ReactNode;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.figure
      className={`flex flex-col gap-2 rounded-[var(--ht-r-md)] border border-[var(--ht-line)] bg-[color-mix(in_oklab,var(--ht-surface-2)_38%,transparent)] p-3 ${className}`}
      initial={reduce ? false : { opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.5,
        delay: reduce ? 0 : 0.08 + index * 0.07,
        ease: [0.16, 1, 0.3, 1],
      }}
    >
      <figcaption className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2">
          <Icon weight="duotone" className="size-4 text-signal" />
          <span className="text-[0.8rem] font-medium text-ink-2">{label}</span>
        </span>
        {meta ? (
          <span className="ht-mono text-[0.66rem] text-muted">{meta}</span>
        ) : null}
      </figcaption>
      {children}
    </motion.figure>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * Opt-in E2E seam: when the page is loaded with `?e2e=1`, expose the store's
 * visualization/scenario setters on `window.__hearttwinSeed` so an automated
 * screenshot run can inject a real backend payload (the intake "run" trigger is
 * owned by another panel). Completely inert without the query flag — no global
 * is attached, no behavior changes in normal use.
 */
function useE2ESeed(): void {
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!new URLSearchParams(window.location.search).has("e2e")) return;
    const seedKey = "__hearttwinSeed";
    (window as unknown as Record<string, unknown>)[seedKey] = (payload: {
      visualization?: SimulationVisualization;
      scenarios?: RecoveryScenario[];
    }) => {
      const store = useHeartTwinStore.getState();
      if (payload.visualization) store.setVisualization(payload.visualization);
      if (payload.scenarios) store.setScenarios(payload.scenarios);
    };
    return () => {
      delete (window as unknown as Record<string, unknown>)[seedKey];
    };
  }, []);
}

export function SimulationCharts() {
  const visualization = useHeartTwinStore((s) => s.visualization);
  const scenarios = useHeartTwinStore((s) => s.scenarios);
  const palette = usePalette();
  useE2ESeed();

  const hasViz = Boolean(visualization);
  const hasScenarios = scenarios.length > 0;

  // react-plotly.js re-renders via Plotly.react when data/layout identity
  // changes, so resolving the palette (new figure objects) repaints colors in
  // place — no remount keying needed.
  const pv = useMemo(
    () => (visualization ? pvLoopFigure(visualization, palette) : null),
    [visualization, palette],
  );
  const cycle = useMemo(
    () => (visualization ? cardiacCycleFigure(visualization, palette) : null),
    [visualization, palette],
  );
  const recovery = useMemo(
    () => (hasScenarios ? recoveryFigure(scenarios, palette) : null),
    [scenarios, hasScenarios, palette],
  );
  const readouts = useMemo(
    () => (visualization ? buildReadouts(visualization) : []),
    [visualization],
  );

  return (
    <Panel className="h-full">
      <PanelHeader
        icon={ChartLineUp}
        accent="signal"
        eyebrow="Physiology"
        title="Simulation"
        actions={
          <span className="ht-chip" data-status={hasViz ? "success" : "idle"}>
            <span className="ht-chip-dot" />
            {hasViz ? "Simulated" : "Standby"}
          </span>
        }
      />
      <div className="ht-hairline" />
      <PanelBody className="pt-4">
        {!hasViz && !hasScenarios ? (
          <PanelEmpty
            icon={Heartbeat}
            accent="signal"
            title="No simulation yet"
            hint="Run the pipeline to generate the pressure-volume loop, the cardiac-cycle waveform, and bounded recovery trajectories."
          />
        ) : (
          <div className="flex flex-col gap-3.5">
            {readouts.length > 0 ? <ReadoutStrip readouts={readouts} /> : null}

            <div className="grid gap-3 sm:grid-cols-2">
              {pv && visualization ? (
                <ChartBay
                  icon={Heartbeat}
                  label="Pressure-volume loop"
                  meta={`area ${Math.round(
                    visualization.pv_loop.pv_loop_area_mmhg_ml,
                  ).toLocaleString()} mmHg·mL`}
                  index={0}
                >
                  <Plot
                    data={pv.data}
                    layout={pv.layout}
                    config={basePlotConfig}
                    useResizeHandler
                    style={{ width: "100%", height: CHART_HEIGHT }}
                  />
                </ChartBay>
              ) : null}

              {cycle && visualization ? (
                <ChartBay
                  icon={Waveform}
                  label="Cardiac cycle"
                  meta={`${visualization.summary.heart_rate_bpm.toFixed(0)} bpm`}
                  index={1}
                >
                  <Plot
                    data={cycle.data}
                    layout={cycle.layout}
                    config={basePlotConfig}
                    useResizeHandler
                    style={{ width: "100%", height: CHART_HEIGHT }}
                  />
                </ChartBay>
              ) : null}
            </div>

            {recovery ? (
              <ChartBay
                icon={Pulse}
                label="Recovery trajectories"
                meta={`${scenarios.length} scenarios · ${
                  scenarios[0]?.summary_metrics.horizon_days ?? 0
                }d horizon`}
                index={2}
              >
                <Plot
                  data={recovery.data}
                  layout={recovery.layout}
                  config={basePlotConfig}
                  useResizeHandler
                  style={{ width: "100%", height: RECOVERY_HEIGHT }}
                />
                <p className="text-[0.68rem] leading-relaxed text-muted">
                  Cardiac output per scenario over the recovery horizon. Shaded
                  bands show the simulated uncertainty range. Educational
                  estimates only.
                </p>
              </ChartBay>
            ) : null}
          </div>
        )}
      </PanelBody>
    </Panel>
  );
}
