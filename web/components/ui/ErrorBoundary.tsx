"use client";

/*
 * Panel-level error boundary. Contains a render/runtime failure to its own
 * panel with an honest error state, so one component (e.g. a WebGL context
 * failure in the 3D viewport, or a transient backend error) can never blank
 * the whole console. This is explicit failure surfacing, not a silent
 * fallback: the panel says what failed.
 */

import { Component, type ReactNode } from "react";
import { Warning } from "@phosphor-icons/react";

interface Props {
  name: string;
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error): void {
    // Surface to the console for debugging; the UI shows an honest error state.
    console.error(`[${this.props.name}] panel error:`, error);
  }

  reset = (): void => this.setState({ error: null });

  render(): ReactNode {
    if (this.state.error) {
      return (
        <section
          className="flex min-h-[140px] flex-col items-center justify-center gap-2 rounded-[var(--ht-r-sm)] border border-[var(--ht-line)] bg-[var(--ht-surface,transparent)] p-6 text-center"
          role="alert"
        >
          <Warning weight="fill" className="size-5 text-muted" />
          <p className="text-sm font-medium text-ink">{this.props.name} unavailable</p>
          <p className="ht-mono text-[0.64rem] leading-relaxed text-faint">
            {this.state.error.message.slice(0, 160)}
          </p>
          <button
            type="button"
            onClick={this.reset}
            className="ht-mono mt-1 rounded-[var(--ht-r-xs,4px)] border border-[var(--ht-line)] px-2.5 py-1 text-[0.64rem] text-muted transition-colors hover:text-ink"
          >
            Retry
          </button>
        </section>
      );
    }
    return this.props.children;
  }
}
