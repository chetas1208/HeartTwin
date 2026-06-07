# HeartTwin Lab — WeaveHacks 4 Submission

> **Educational cardiac simulation only. Not for diagnosis or treatment decisions.**

---

## Summary

**HeartTwin Lab** is a multi-agent cardiac digital twin you talk to: a CopilotKit
agent orchestrates 8 specialist agents over a deterministic physics core, every
step traced live in Weave and streamed through Redis, rendering a beating 3D heart
and bounded recovery scenarios. It is built for education and research, not clinical use.

---

## What It Does

HeartTwin accepts cardiac clinical files (PDF reports, ECG images/CSV, echo/MRI
images, structured vitals) and builds an explainable cardiac simulation:

1. **Intake & Safety Agent** — classifies intent, blocks unsafe medical requests, redacts PII.
2. **Multimodal Extraction Agent** — extracts structured cardiac observations (SV, EF, CO, MAP, QTc, ECG labels) from any uploaded file type with full provenance.
3. **Evidence Validator Agent** — cross-validates extracted values, detects physiological impossibilities, flags conflicts.
4. **Cardiac State Builder Agent** — assembles the canonical `CardiacTwinState` from validated evidence; derives SV, EF, CO, MAP deterministically; labels all population priors.
5. **Electrophysiology Agent** — builds the electrical state; runs Pan-Tompkins QRS detection on waveform data; normalizes reported rhythm labels.
6. **Hemodynamics Simulation Agent** — computes cardiac operation metrics, pressure-volume loops, and 3D visualization payloads using deterministic Python tools.
7. **Recovery Orchestration Agent** — generates 2–4 bounded simulated recovery trajectories with uncertainty bands; uses Redis agentic memory to select scenario templates.
8. **Evaluator & Critic Agent** — scores the run (extraction completeness, physiological plausibility, safety compliance, hallucination risk, visualization readiness, recovery stability); proposes harness improvements.

**Safety boundary:** The LLM only reasons, orchestrates, and narrates. All numeric
cardiac quantities are computed exclusively by deterministic Python tools.

---

## Why It's Useful

Cardiac digital twins have real research and educational value: they help
researchers, educators, and trainees understand how hemodynamic parameters
interact, how recovery scenarios differ, and how simulation quality is measured.
HeartTwin makes this accessible through natural language with a clear multi-agent
pipeline that is fully observable via Weave traces and Redis memory.

The harness's self-improvement loop demonstrates how AI systems can critique
their own outputs and improve simulation configuration — without inventing
clinical values or providing medical advice.

---

## How It's Built

- **Backend:** FastAPI (Python) on Hugging Face Spaces (Docker). 8 agents, each
  schema-bound and Weave-traced. Deterministic physics core in `tools/`.
- **Frontend:** Nuxt 3 (Vue) at `app/`. CopilotKit integration in `web/` (Next.js).
  Harness panel shows Agent Pipeline, Weave Trace, Eval Scores, Redis Memory,
  Self-Improvement Run, and Research Basis.
- **Multi-agent orchestration:** CopilotKit AG-UI protocol connects the frontend
  copilot to the backend pipeline. The Cardiology Copilot agent drives
  `create_case → extract → operate → simulate_recovery` with generative UI cards
  and a human-in-the-loop confirmation step before simulation.

---

## Sponsor Tools

### W&B Weave (Best Use of Weave)

- `weave.init("entity/hearttwin-weavehacks")` at module load.
- Every agent stage, deterministic tool call, OpenAI metadata, and eval score is
  traced as a nested call tree: `pipeline → agent → tool`.
- `hearttwin.evaluate_run` traces the Evaluator's 6-dimensional scoring.
- `hearttwin.self_improve_run` records before/after eval score comparison.
- Public project link is surfaced in the API `/config` endpoint and in the
  Harness UI Weave card.
- Local JSON trace fallback works with zero configuration.

### Redis / Upstash (Best Use of Redis)

Four load-bearing uses, all shown on screen in the Harness panel:

1. **Streams** — `XADD` from `trace_sink`; FastAPI SSE endpoint polls `XRANGE`
   for live trace streaming to the browser.
2. **RedisJSON / Hashes** — case state persisted at `hearttwin:case:{id}:{stage}`.
3. **Brute-force cosine KNN** — cardiac profile vectors stored as base64 float32
   in Redis Hashes; NumPy cosine similarity retrieves similar prior cases.
4. **Agentic memory** — `hearttwin:memory:*` keys store critic patterns,
   instability patterns, safe scenario templates, and harness fix history.

### CopilotKit (Best Use of CopilotKit)

- `CopilotSidebar` drives the full pipeline via `useCopilotAction` with
  `render` for generative UI cards (agent status, eval scores, recovery charts).
- `renderAndWaitForResponse` provides a human-in-the-loop confirmation before
  running the simulation.
- `useCopilotReadable` exposes case state so the copilot reasons over real data.
- Node runtime on Vercel (`app/api/copilotkit/route.ts`) proxies to the Python
  backend via `remoteEndpoints`.

---

## Agent Orchestration

The 8-agent pipeline runs sequentially with explicit hand-offs:

```
Intake & Safety
  → Multimodal Extraction
    → Evidence Validator
      → Cardiac State Builder
        → [Electrophysiology ‖ Hemodynamics Simulation]
          → Recovery Orchestration
            → Evaluator & Critic
              → (optional) Self-Improvement → Evaluator & Critic (rerun)
```

Each agent publishes an `AgentStageResult` (schema in `schemas.py`) and records
a Weave trace. The orchestrator assembles results and routes between stages.

---

## Safety Boundary

- No output contains diagnosis, treatment, or medication language.
- Every output carries: *"Educational cardiac simulation only. Not for diagnosis or treatment decisions."*
- The Evaluator scans all generated text for unsafe phrases at every run.
- `check_request_safety()` in `safety.py` blocks unsafe user requests before any agent runs.
- LLMs never compute SV, EF, CO, MAP, QTc, RR interval, PV loop arrays, or ECG features.

---

## Repository

Public GitHub: https://github.com/your-org/hearttwin-lab (replace with actual URL)

Live demo backend: https://your-hf-space.hf.space (replace with actual URL)

Live demo frontend: https://hearttwin-lab.vercel.app (replace with actual URL)
