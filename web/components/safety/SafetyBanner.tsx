"use client";

/*
 * CONTRACT: owns the mandatory educational-simulation safety disclaimer. This is
 *   a hard requirement of HeartTwin Lab — it must be visible at all times and is
 *   rendered by AppShell in the header chrome so it survives every layout state.
 * READS from store: safetyDisclaimer (falls back to the canonical text before
 *   any API response arrives, so it is never empty).
 * This component renders the full disclaimer line with a caution glyph.
 * Siblings: do not remove or hide this. If you need the text, import
 *   SAFETY_DISCLAIMER from this file.
 */

import { Warning } from "@phosphor-icons/react";
import { useHeartTwinStore } from "@/lib/store";

export const SAFETY_DISCLAIMER =
  "Educational simulation only. HeartTwin Lab is not a medical device, does not " +
  "diagnose, and does not recommend treatment. All outputs are simulated " +
  "estimates. Consult a qualified clinician for any health decisions.";

export function SafetyBanner() {
  const fromApi = useHeartTwinStore((s) => s.safetyDisclaimer);
  const text = fromApi ?? SAFETY_DISCLAIMER;

  return (
    <div
      role="note"
      aria-label="Safety disclaimer"
      className="flex items-start gap-2.5 border-b border-[var(--ht-warn-line)] bg-[var(--ht-warn-soft)] px-4 py-2 sm:px-6"
    >
      <Warning
        weight="fill"
        aria-hidden
        className="mt-px size-4 flex-none text-warn"
      />
      <p className="text-[0.78rem] leading-snug text-ink-2">
        <span className="font-semibold text-warn">Educational simulation only.</span>{" "}
        {text.replace(/^Educational simulation only\.\s*/i, "")}
      </p>
    </div>
  );
}
