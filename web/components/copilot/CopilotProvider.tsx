"use client";

/*
 * CONTRACT: owns the CopilotKit runtime context for the whole app + the themed
 *   CSS variables CopilotKit reads. Mounts at the root so any descendant can use
 *   CopilotKit hooks (useCopilotChat, useCopilotAction, useCoAgent, ...).
 * READS from store: nothing (it is the provider boundary itself).
 * This file: wires <CopilotKit runtimeUrl="/api/copilotkit">, imports the
 *   CopilotKit stylesheet, and maps our OKLCH palette onto CopilotKit's CSS vars
 *   via CopilotKitCSSProperties so the dock matches the console.
 * Siblings: the visible chat surface lives in components/copilot/CopilotDock.tsx;
 *   do not add UI here.
 */

import { CopilotKit } from "@copilotkit/react-core";
import "@copilotkit/react-ui/styles.css";
import type { CSSProperties, ReactNode } from "react";

const RUNTIME_URL = "/api/copilotkit";

// CopilotKit theming is done by setting its documented CSS custom properties on
// an ancestor. This version does not export CopilotKitCSSProperties, so we type
// the override as CSSProperties extended with the known --copilot-kit-* vars.
type CopilotKitCSSProperties = CSSProperties &
  Record<`--copilot-kit-${string}`, string>;

// HeartTwin palette mapped onto CopilotKit's CSS custom properties. Hex mirrors
// of the OKLCH tokens in globals.css (CopilotKit reads literal CSS vars).
const copilotTheme: CopilotKitCSSProperties = {
  "--copilot-kit-primary-color": "#e0506b",
  "--copilot-kit-contrast-color": "#fdeef0",
  "--copilot-kit-background-color": "#171d29",
  "--copilot-kit-secondary-color": "#1f2633",
  "--copilot-kit-secondary-contrast-color": "#f4f6fa",
  "--copilot-kit-separator-color": "rgba(150, 165, 190, 0.22)",
  "--copilot-kit-muted-color": "#9aa7bd",
};

export function CopilotProvider({ children }: { children: ReactNode }) {
  return (
    <CopilotKit runtimeUrl={RUNTIME_URL}>
      <div style={copilotTheme} className="contents">
        {children}
      </div>
    </CopilotKit>
  );
}
