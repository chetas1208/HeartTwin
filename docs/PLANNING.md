# HeartTwin Lab — WeaveHacks 4 Planning

> **⚠️ Read [`../AGENTS.md`](../AGENTS.md) + [`TASKS.md`](./TASKS.md) first — they are
> the authoritative, research-verified plan (Jun 6).** This file is strategic
> context. Three facts below are now **corrected**; where they conflict, AGENTS.md
> §4 wins:
> - **Weave is NOT actually wired.** `weave_trace.py`'s `publish()` is a no-op
>   (calls a non-existent `client.publish()`) — it only writes local JSON. Real
>   `weave.init()` + `@weave.op` instrumentation is a build task (WS-A), and Weave
>   is **mandatory for prize eligibility**.
> - **No native Redis vector search.** Upstash Redis has **no `FT.SEARCH`/KNN** and
>   Upstash Vector is unavailable to us — use **brute-force cosine KNN** over
>   base64-float32 vectors in a Hash (§4 of this file is right; ignore the
>   "Upstash Vector / RediSearch `FT.SEARCH`" suggestion).
> - **CopilotKit path is decided:** migrate the frontend to **Next.js/React under
>   `web/`** (the §5 A/B question is resolved — full React migration, not a Vue
>   island). Backend deploys to **HF Spaces**, frontend to **Vercel**.

Two shared mental models for the team: **(1)** where the project is today, and
**(2)** what to build with the provided hackathon tools. Both are also captured
as Excalidraw diagrams under [`docs/diagrams/`](./diagrams) — open the
`.excalidraw` files directly on [excalidraw.com](https://excalidraw.com) or with
the VS Code Excalidraw extension.

| Diagram | Source (re-renderable) | Export (openable) |
|---|---|---|
| Current state | [`diagrams/source/01-current-state.json`](./diagrams/source/01-current-state.json) | [`diagrams/01-current-state.excalidraw`](./diagrams/01-current-state.excalidraw) |
| Tool brainstorm | [`diagrams/source/02-brainstorm-tools.json`](./diagrams/source/02-brainstorm-tools.json) | [`diagrams/02-brainstorm-tools.excalidraw`](./diagrams/02-brainstorm-tools.excalidraw) |

Regenerate the exports after editing a source with:

```bash
python docs/diagrams/build_excalidraw.py
```

---

## 1. Current state

HeartTwin Lab is an **8-agent cardiac digital-twin simulator** (educational
only — not a medical device). Stack: **Nuxt 4 / Vue 3 / Tailwind / Pinia**
frontend, **Python serverless** backend, deterministic physiology tools, and a
staged agent orchestrator. Every numeric output carries provenance, and LLMs
never do math.

**Layers**

- **Frontend (`app/`)** — 3D beating heart (TresJS/Three.js), Plotly charts
  (ECG, PV-loop, recovery), Pinia stores (`case` / `simulation` / `ui`), upload
  + orchestration UI, pages `index` / `lab` / `case` / `about`.
- **API (`api/index.py` → `python/hearttwin/api.py`, `/api/v1`)** —
  `/extract` (stages 1-3), `/operate` (4·5·7), `/simulate-recovery` (6·7),
  `/self-improve`, plus `/cases`, `/trace`, `/health`.
- **Orchestration (`python/hearttwin/orchestrator.py`)** — staged pipeline,
  EP + Hemodynamics run in parallel, evaluator runs after operate and recovery.
- **Deterministic tools (`python/hearttwin/tools/`)** — pure Python, unit-tested.
- **Sponsor / external** — W&B Weave (wired: traces + evals), OpenAI Vision
  (optional), Upstash Redis (optional), Vercel Blob (optional).
- **Safety** — `SIMULATION ONLY`; intake blocks diagnosis/treatment language.

### Agent → file map

| Stage | Agent | File (`python/hearttwin/agents/`) | Endpoint |
|---|---|---|---|
| 1 | Intake & Safety | `intake_agent.py` | `/extract` |
| 2 | Multimodal Extraction | `extraction_agent.py` | `/extract` |
| 3 | Evidence Validator | `validator_agent.py` | `/extract` |
| 4 | Cardiac State Builder | `state_builder_agent.py` | `/operate` |
| 5a | Electrophysiology (parallel) | `electrophysiology_agent.py` | `/operate` |
| 5b | Hemodynamics (parallel) | `hemodynamics_agent.py` | `/operate` |
| 6 | Recovery Orchestration | `recovery_agent.py` | `/simulate-recovery` |
| 7 | Evaluator & Critic | `evaluator_agent.py` | `/operate` + `/simulate-recovery` |

### Tool → file map (`python/hearttwin/tools/`)

`cardiac_state.py` · `hemodynamics.py` · `recovery_sim.py` · `ecg_features.py` ·
`pdf_extract.py` · `image_extract.py` · `scoring.py` · `storage.py` ·
`weave_trace.py` · **`case_memory.py` (new — see §4)**

---

## 2. WeaveHacks 4 tools & prizes

Theme: **Multi-Agent Orchestration** — "orchestrate pipelines, wrangle swarms."

| Tool | Status in repo | Opportunity |
|---|---|---|
| **W&B Weave** | Wired (required host) | Go deeper: evals, leaderboard, online guardrails, run comparison |
| **Redis** | Shallow `SET`/`GET` in `storage.py` | **Prize.** Vector priors, semantic cache, Streams, RedisJSON |
| **CopilotKit** | Absent | **Prize.** In-app copilot driving the pipeline + generative UI |
| **Cursor** | Dev tool | Velocity on the above integrations |

> **Key insight:** Weave is already integrated; the two *prize* tools
> (**Redis** and **CopilotKit**) are the biggest gaps and the highest-leverage
> work. The brainstorm diagram is organised around this.

Sources: [WeaveHacks 4 · Luma](https://luma.com/weavehacks),
[WeaveHacks · Devpost](https://weavehacks-1.devpost.com/). The participant
logistics Notion page is JS-rendered and could not be fetched directly — if it
lists additional sponsors, fold them into `02-brainstorm-tools.json` and rebuild.

---

## 3. Idea backlog (by tool)

**W&B Weave** — trace the full 8-agent swarm (one `@weave.op` per agent) ·
Weave Evaluations + public leaderboard over the golden cases · online guardrail
evals on live traces (safety + hallucination) · before/after self-improvement
run comparison.

**Redis (prize)** — *vector search for similar-case priors* (scaffolded, §4) ·
semantic cache for OpenAI vision extractions keyed by file hash · Redis Streams
for a live agent-trace event log to the UI · RedisJSON / TimeSeries for state +
recovery trajectories (replacing shallow `SET`/`GET`).

**CopilotKit (prize)** — in-app "Cardiology Copilot" that drives the pipeline by
chat · CoAgents rendering the live 8-agent run as generative UI · human-in-the-
loop approval of the self-improve rerun · generative UI rendering PV-loop +
recovery charts inline.

**Cursor** — scaffold agents + tests fast (153 Python tests already green) ·
pair-program the CopilotKit + Redis work · keep deterministic tools pure.

---

## 4. Scaffolded in this PR — `tools/case_memory.py`

A stack-native start on the **Redis** track: a case-memory + similar-case
retrieval layer.

- `build_profile_vector(state)` — deterministic, normalized cardiac feature
  vector (pure). Missing fields map to the population typical (0.0).
- `cosine_similarity(a, b)` — pure.
- `index_case(...)` / `retrieve_similar(...)` — brute-force cosine KNN over an
  in-memory index, with best-effort Upstash Redis persistence. Mirrors
  `storage.py`: env-gated, `try/except`, fully offline for dev/tests.
- `suggest_priors_from_neighbors(...)` — derives **labelled prior suggestions**
  (`source: "similar_case_prior"`, low confidence). Advisory only; never
  fabricates absent fields, never overwrites extracted/user evidence.

Tested in `tests/test_case_memory.py` (17 tests, offline). Full suite: **153
passing**.

**Wiring (next step, not yet done to keep behaviour unchanged):**

1. After `state_builder_agent` builds a state, call `index_case()` with its
   profile vector + summary.
2. When a field would fall back to `default_model_prior`, call
   `retrieve_similar()` + `suggest_priors_from_neighbors()` and surface the
   suggestion in the UI as a *prior* the user can accept — keeping provenance.
3. Swap the brute-force KNN for **Upstash Vector / RediSearch `FT.SEARCH`** and
   add **Redis Streams** for the live trace. The pure functions stay the seam.

---

## 5. CopilotKit — decision needed before scaffolding

CopilotKit's UI components are **React-first**; this app is **Vue/Nuxt**. Pick a
path before building so we don't ship a broken integration:

- **A. React island** — mount a React + CopilotKit widget inside the Nuxt page;
  fastest route to the official copilot UX + CoAgents.
- **B. Custom Vue copilot** — use only the framework-agnostic CopilotKit runtime
  (Node) behind a hand-built Vue chat panel; more work, no React dependency.

Recommendation: **A** for the hackathon (speed + judges see the real CopilotKit
UX). Confirm before implementation.

---

## 6. Build sequence

- **NOW** — Redis case-memory (scaffolded here) + Weave swarm tracing.
- **NEXT** — CopilotKit copilot (after the A/B decision above).
- **LATER** — Redis Streams live trace · Weave leaderboard · CoAgents.
