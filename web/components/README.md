# HeartTwin Lab — frontend conventions (read before editing)

This is the shared foundation. ~11 sibling agents build on top of it in parallel.
Follow these rules so the merges are clean and the console stays coherent.

## Ownership

- **One component owns one file.** Edit only the file you were assigned. Do not
  touch another panel's file or the shared foundation files below.
- **Foundation files (do not edit unless you are the foundation agent):**
  - `app/globals.css` — design tokens + primitives
  - `app/layout.tsx`, `app/page.tsx`
  - `lib/api.ts` — typed HTTP client (add a method only if a new endpoint exists)
  - `lib/store.ts` — Zustand store (shared state)
  - `hooks/useTraceStream.ts` — SSE trace stream
  - `components/layout/AppShell.tsx` — the grid + chrome
  - `components/ui/Panel.tsx`, `components/charts/Plot.tsx` — shared primitives
  - `components/copilot/CopilotProvider.tsx`
  - `components/safety/SafetyBanner.tsx` — mandatory, never remove/hide

## State + data flow

- **Shared state flows through `lib/store.ts`** (`useHeartTwinStore`). Read slices
  with selectors; call actions to mutate. Do not stash component-local UI state
  in the store.
- **Shared API through `lib/api.ts`.** It throws `ApiRequestError` on failure —
  no silent fallbacks, no mock data. Surface the error in your panel.
- **Pipeline orchestration is `store.runPipeline()`** (create → extract → operate
  → simulate-recovery). The intake panel triggers it; other panels read results.
- **Trace events** are appended by `useTraceStream` (already mounted in AppShell).
  Read them from `store.traceEvents`; do not open your own EventSource.

## Styling

- **Never hardcode colors.** Use the Tailwind utilities mapped from tokens
  (`bg-surface-1/2/3`, `text-ink / ink-2 / muted / faint`, `text-accent /
  accent-bright`, `text-signal / signal-bright`, `text-ecg`, `text-warn`,
  `border-line`) or the CSS vars (`var(--ht-...)`). Palette is OKLCH.
- **Use the primitives:** `.ht-panel`, `.ht-panel-raised`, `.ht-hairline`,
  `.ht-btn`/`.ht-btn-primary`/`-secondary`/`-ghost`, `.ht-chip[data-status]`,
  `.ht-skeleton`, `.ht-eyebrow`, `.ht-mono`. Compose `Panel`/`PanelHeader`/
  `PanelBody`/`PanelEmpty` from `components/ui/Panel.tsx`.
- One radius scale (cards ≤ 14px). One button shape. Skeletons for loading,
  composed empty states (not "TODO" / "nothing here").

## Components + interactivity

- **All interactive components are `"use client"`** and isolated leaves.
- **Motion via `motion/react`.** Respect `useReducedMotion()`. Use
  `useMotionValue`/`useFrame` for continuous values, never `useState`.
- **Icons via `@phosphor-icons/react` only.** No hand-rolled SVG icons.
- **Charts:** import the shared `Plot` (default) + `basePlotLayout`/
  `basePlotConfig` from `components/charts/Plot.tsx`. It is client-only and binds
  `plotly.js-dist-min`.
- **3D:** keep all react-three-fiber work inside a single `"use client"` leaf
  (see `components/heart/HeartScene.tsx`).
- Layout with CSS Grid, `min-h-[100dvh]`, no flexbox percentage math.

## Copy

- No em dashes, no marketing buzzwords. Button labels are verb + object. The
  safety disclaimer is mandatory and always visible.

## Types

- Everything is typed against `web/types/*` (mirrors `python/hearttwin/schemas.py`)
  and `web/lib/*` (formatters, units, validators). Reuse them; do not redefine.
