"use client";

/*
 * Shared panel chrome for the console. NOT a sibling-owned file — it is part of
 * the foundation's component vocabulary so every panel has the same header,
 * hairline, and body rhythm. Import and compose; do not fork per panel.
 */

import type { Icon } from "@phosphor-icons/react";
import type { ReactNode } from "react";

type Accent = "accent" | "signal" | "ecg" | "warn" | "neutral";

const accentColor: Record<Accent, string> = {
  accent: "var(--ht-accent-bright)",
  signal: "var(--ht-signal-bright)",
  ecg: "var(--ht-ecg)",
  warn: "var(--ht-warn)",
  neutral: "var(--ht-muted)",
};

export function Panel({
  children,
  className = "",
  raised = false,
}: {
  children: ReactNode;
  className?: string;
  raised?: boolean;
}) {
  return (
    <section
      className={`flex min-h-0 flex-col overflow-hidden ${raised ? "ht-panel-raised" : "ht-panel"} ${className}`}
    >
      {children}
    </section>
  );
}

export function PanelHeader({
  icon: IconCmp,
  eyebrow,
  title,
  accent = "neutral",
  actions,
}: {
  icon?: Icon;
  eyebrow: string;
  title: string;
  accent?: Accent;
  actions?: ReactNode;
}) {
  return (
    <header className="flex items-start justify-between gap-3 px-4 pt-4 pb-3">
      <div className="flex items-start gap-3">
        {IconCmp ? (
          <span
            aria-hidden
            className="grid size-8 flex-none place-items-center rounded-[var(--ht-r-sm)] border border-[var(--ht-line)] bg-surface-2"
            style={{ color: accentColor[accent] }}
          >
            <IconCmp weight="duotone" className="size-[1.05rem]" />
          </span>
        ) : null}
        <div className="flex flex-col gap-0.5">
          <span className="ht-eyebrow">{eyebrow}</span>
          <h2 className="ht-panel-title">{title}</h2>
        </div>
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </header>
  );
}

export function PanelBody({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`min-h-0 flex-1 overflow-y-auto px-4 pb-4 ${className}`}>
      {children}
    </div>
  );
}

/** Composed, on-brand empty state for a panel awaiting data. */
export function PanelEmpty({
  icon: IconCmp,
  title,
  hint,
  accent = "signal",
  children,
}: {
  icon: Icon;
  title: string;
  hint: string;
  accent?: Accent;
  children?: ReactNode;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 rounded-[var(--ht-r-md)] border border-dashed border-[var(--ht-line)] bg-[color-mix(in_oklab,var(--ht-surface-2)_40%,transparent)] px-6 py-10 text-center">
      <span
        aria-hidden
        className="grid size-11 place-items-center rounded-full border border-[var(--ht-line)] bg-surface-2"
        style={{ color: accentColor[accent] }}
      >
        <IconCmp weight="duotone" className="size-5" />
      </span>
      <p className="text-sm font-medium text-ink-2">{title}</p>
      <p className="max-w-[42ch] text-xs leading-relaxed text-muted">{hint}</p>
      {children}
    </div>
  );
}
