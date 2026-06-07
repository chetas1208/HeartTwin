// `plotly.js-dist-min` ships no types; it is the same public API as `plotly.js`.
// Re-export the @types/plotly.js declarations so the wrapper in
// components/charts/Plot.tsx is fully typed instead of `any`.
declare module "plotly.js-dist-min" {
  import type Plotly from "plotly.js";
  export = Plotly;
}
