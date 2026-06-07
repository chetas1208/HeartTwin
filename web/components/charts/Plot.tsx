"use client";

/*
 * Thin Plotly wrapper for the foundation. react-plotly.js expects a `plotly.js`
 * build; the full build is heavy, so we bind the factory to `plotly.js-dist-min`
 * and load it client-only via next/dynamic (Plotly touches `window`/`document`).
 *
 * NOT sibling-owned. SimulationCharts and any other chart consumer import this
 * `Plot` and pass Plotly `data`/`layout`/`config`. A dark, on-brand base layout
 * is exported so charts inherit the console palette without re-specifying it.
 */

import dynamic from "next/dynamic";
import type { ComponentType } from "react";
import type { PlotParams } from "react-plotly.js";

// react-plotly.js default export is a factory: createPlotlyComponent(Plotly).
// Resolve both modules client-side, then build the component once.
const Plot = dynamic(
  async () => {
    const [{ default: createPlotlyComponent }, Plotly] = await Promise.all([
      import("react-plotly.js/factory"),
      import("plotly.js-dist-min"),
    ]);
    return createPlotlyComponent(
      Plotly as unknown as Parameters<typeof createPlotlyComponent>[0],
    ) as ComponentType<PlotParams>;
  },
  {
    ssr: false,
    loading: () => (
      <div className="ht-skeleton h-full min-h-[180px] w-full rounded-[var(--ht-r-md)]" />
    ),
  },
);

/** Base Plotly layout themed to the HeartTwin console (dark, hairline grids). */
export const basePlotLayout: Partial<PlotParams["layout"]> = {
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "rgba(0,0,0,0)",
  font: {
    family:
      "var(--font-geist-mono, ui-monospace, monospace)",
    color: "#aeb9cc",
    size: 11,
  },
  margin: { l: 48, r: 16, t: 16, b: 40 },
  xaxis: {
    gridcolor: "rgba(150,165,190,0.14)",
    zerolinecolor: "rgba(150,165,190,0.24)",
    linecolor: "rgba(150,165,190,0.24)",
  },
  yaxis: {
    gridcolor: "rgba(150,165,190,0.14)",
    zerolinecolor: "rgba(150,165,190,0.24)",
    linecolor: "rgba(150,165,190,0.24)",
  },
  showlegend: false,
};

export const basePlotConfig: Partial<PlotParams["config"]> = {
  displayModeBar: false,
  responsive: true,
};

export default Plot;
