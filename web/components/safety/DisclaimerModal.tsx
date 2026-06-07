"use client";

/*
 * One-time educational-use disclaimer. Shown on first open and dismissed for
 * good once acknowledged (localStorage). Replaces the persistent safety banner
 * so the working surface stays calm and clinical. This component owns the
 * mandatory boundary language (not a medical device / no diagnosis / no
 * treatment / consult a physician).
 */

import { useEffect, useState } from "react";

const ACK_KEY = "hearttwin:disclaimer-ack:v1";

export function DisclaimerModal() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    try {
      if (!localStorage.getItem(ACK_KEY)) setOpen(true);
    } catch {
      setOpen(true);
    }
  }, []);

  if (!open) return null;

  const acknowledge = () => {
    try {
      localStorage.setItem(ACK_KEY, "1");
    } catch {
      /* private mode — modal simply reappears next session */
    }
    setOpen(false);
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="ht-disclaimer-title"
      className="fixed inset-0 grid place-items-center bg-[color-mix(in_oklab,var(--ht-bg)_70%,black)] p-4 backdrop-blur-sm"
      style={{ zIndex: 100 }}
    >
      <div className="w-full max-w-md rounded-[var(--ht-r-lg,14px)] border border-[var(--ht-line)] bg-[var(--ht-surface)] p-6 shadow-xl">
        <h2
          id="ht-disclaimer-title"
          className="text-[1.05rem] font-semibold tracking-tight text-ink"
        >
          Before you begin
        </h2>
        <p className="mt-3 text-[0.86rem] leading-relaxed text-ink-2">
          HeartTwin Lab is an educational simulation. It is{" "}
          <span className="font-medium text-ink">not a medical device</span>, does
          not diagnose conditions, and does not recommend treatment.
        </p>
        <p className="mt-2 text-[0.86rem] leading-relaxed text-ink-2">
          All outputs are simulated estimates. Always consult a licensed
          physician for medical advice, diagnosis, or treatment decisions.
        </p>
        <button
          type="button"
          onClick={acknowledge}
          className="mt-5 w-full rounded-[var(--ht-r-sm)] border border-[var(--ht-accent-line)] bg-[var(--ht-accent-soft)] px-4 py-2.5 text-[0.85rem] font-medium text-accent-bright transition-colors hover:bg-[color-mix(in_oklab,var(--ht-accent-soft)_70%,transparent)]"
        >
          I understand
        </button>
      </div>
    </div>
  );
}
