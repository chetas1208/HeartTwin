declare module 'plotly.js-dist-min' {
  const Plotly: {
    newPlot(el: HTMLElement, data: unknown[], layout?: unknown, config?: unknown): Promise<unknown>
    react(el: HTMLElement, data: unknown[], layout?: unknown, config?: unknown): Promise<unknown>
    purge(el: HTMLElement): void
    relayout(el: HTMLElement, update: unknown): Promise<unknown>
  }
  export = Plotly
}
