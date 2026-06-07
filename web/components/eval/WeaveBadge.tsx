"use client";

/*
 * CONTRACT: owns the Weave linkage indicator — the live W&B Weave connection and
 *   a prominent deep link to the run trace. This is the sponsor-eligibility proof,
 *   so the link is an obvious, clickable button, not a passive chip. Lives in the
 *   AppShell header "Weave link slot".
 * READS from store: weave (WeaveInfo).
 *
 * States:
 *   connected + run_url  -> live pulse dot + "View live trace in Weave" button
 *                           that opens the run trace in a new tab; traced stage /
 *                           tool counts shown when the backend reports them.
 *   connected, no run yet -> button deep-links the project workspace instead.
 *   error / standby       -> compact status chip, no dead link.
 */

import { ArrowSquareOut, Graph } from "@phosphor-icons/react";
import { motion, useReducedMotion } from "motion/react";
import { useHeartTwinStore } from "@/lib/store";

export function WeaveBadge() {
  const weave = useHeartTwinStore((s) => s.weave);
  const reduce = useReducedMotion() ?? false;

  const status = weave?.status ?? "not_configured";
  const connected = status === "connected";

  // Prefer a concrete run trace; fall back to the project workspace.
  const runUrl = weave?.run_url ?? null;
  const url = runUrl ?? weave?.project_url ?? null;
  const linksToRun = Boolean(runUrl);

  const stages = weave?.traced_stages_count;
  const tools = weave?.traced_tool_calls_count;
  const hasCounts =
    typeof stages === "number" || typeof tools === "number";

  // No live link yet: compact status chip (error / connecting / standby).
  if (!connected || !url) {
    const chipStatus =
      status === "error" ? "error" : weave?.enabled ? "running" : "idle";
    const label =
      status === "error"
        ? "Weave error"
        : weave?.enabled
          ? "Weave connecting"
          : "Weave standby";
    return (
      <span className="ht-chip" data-status={chipStatus} title="W&B Weave tracing">
        <Graph weight="duotone" className="size-3.5" />
        {label}
      </span>
    );
  }

  // Live: a prominent, obviously-clickable deep link to the trace.
  return (
    <motion.a
      href={url}
      target="_blank"
      rel="noreferrer noopener"
      title={
        linksToRun
          ? "Open this run's live trace in W&B Weave"
          : "Open the W&B Weave project workspace"
      }
      initial={reduce ? false : { opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      whileHover={reduce ? undefined : { y: -1 }}
      whileTap={reduce ? undefined : { scale: 0.98 }}
      className="group inline-flex items-center gap-2 rounded-[var(--ht-r-md)] border border-[var(--ht-signal-line)] bg-[var(--ht-signal-soft)] px-2.5 py-1.5 text-signal-bright transition-colors hover:bg-[color-mix(in_oklab,var(--ht-signal-soft)_60%,var(--ht-surface-3))]"
    >
      {/* Live pulse dot — conveys an active tracing connection. */}
      <span className="ht-pulse relative grid place-items-center text-ecg">
        <span className="ht-chip-dot" />
      </span>

      <span className="flex flex-col leading-none">
        <span className="text-[0.78rem] font-semibold">
          {linksToRun ? "View live trace in Weave" : "View Weave project"}
        </span>
        <span className="ht-mono text-[0.62rem] text-signal-dim">
          {weave?.project ?? "weave"}
          {hasCounts ? (
            <>
              {" · "}
              {typeof stages === "number" ? `${stages} stages` : null}
              {typeof stages === "number" && typeof tools === "number"
                ? " · "
                : null}
              {typeof tools === "number" ? `${tools} tools` : null}
            </>
          ) : null}
        </span>
      </span>

      <ArrowSquareOut
        weight="bold"
        className="size-3.5 opacity-70 transition-opacity group-hover:opacity-100"
      />
    </motion.a>
  );
}
