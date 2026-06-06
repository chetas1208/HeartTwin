# TASKS.md — HeartTwin Lab → WeaveHacks 4 execution backlog

> The actionable, swarm-ready backlog. **Read [`../AGENTS.md`](../AGENTS.md) first.**
> Claim a task by setting its status in the **Status board** below to
> `WIP @handle`; mark `DONE (PR #n)` when its **Verify** gate passes.
>
> Tags: **`[DC]`** = demo-critical (build first, keep working) · **`[W]`** = wow /
> cuttable (cut order under time pressure: `TC.6 → TB.6 → TD.6`).

---

## 1. The 3-minute demo (build everything backwards from this)

| Time | On screen | Prize proof |
|---|---|---|
| 0:00–0:20 | Type to the embedded Copilot: *"Here are my labs + ECG, build my cardiac twin"* + drop files | CopilotKit |
| 0:20–1:10 | Live trace panel lights up: 8 agents (intake→extraction→validator→state→**[EP ∥ hemodynamics]**→evaluator) streamed from Redis; Copilot renders a generative-UI card per agent | Multi-agent theme · CopilotKit gen-UI · Redis Stream |
| 1:10–1:50 | 3D beating heart + PV loop + ECG; ask *"what if we reduce afterload?"* → recovery scenarios (human-in-the-loop) | CopilotKit HITL |
| 1:50–2:30 | Cut to **Weave dashboard**: nested trace tree of the run just done — per-agent spans, the OpenAI call, latency/tokens + an **Evaluation scorecard** | **Weave (eligibility)** |
| 2:30–3:00 | Redis load-bearing: KNN found a similar prior case · semantic-cache hit cuts latency · token-cost counter; close on safety disclaimer + GitHub link | Redis |

**Critical path:** `WS-0` → (`WS-A` ∥ `WS-B` ∥ `WS-C-backend` ∥ `WS-D`) → integrate
→ `WS-E` deploy → rehearse. **Demo spine = every `[DC]` task.**

---

## 2. Status board

| Task | Tag | Title | Owns (files) | Deps | Status |
|---|---|---|---|---|---|
| T0.1 | [DC] | Wire creds & connectivity smoke | `.env`, HF/Vercel secrets | — | TODO |
| T0.2 | [DC] | Pin Weave + CopilotKit docs/versions | `docs/INTEGRATION_NOTES.md` | — | TODO |
| T0.3 | [DC] | Scaffold `web/` Next.js app | `web/**` | — | TODO |
| TA.1 | [DC] | Real `weave.init` + keep fallback | `tools/weave_trace.py` | T0.1 | TODO |
| TA.2 | [DC] | `@weave.op` nested across agents | `orchestrator.py`, `agents/*` | TA.1 | TODO |
| TA.3 | [DC] | Capture + surface call URL | `weave_trace.py`, `api.py` | TA.1 | TODO |
| TA.4 | [DC] | Flush traces before response | `api.py` / middleware | TA.1 | TODO |
| TA.5 | [DC] | `weave.Evaluation` over golden cases | `evals/`, `tools/scoring.py` | TA.2 | TODO |
| TB.1 | [DC] | Upstash async REST client | `tools/redis_client.py` | T0.1 | TODO |
| TB.2 | [DC] | RedisJSON persistent case store | `tools/storage.py` | TB.1 | TODO |
| TB.3 | [DC] | `XADD` trace stream from sink | `tools/weave_trace.py` | TB.1 | TODO |
| TB.4 | [DC] | SSE endpoint (XRANGE by last-id) | `api.py` | TB.3 | TODO |
| TB.5 | [W] | Case-memory KNN (embeddings) | `tools/case_memory.py` | TB.1 | TODO |
| TB.6 | [W] | Semantic cache + token counters | `tools/redis_client.py`, `api.py` | TB.1 | TODO |
| TC.1 | [DC] | Backend CopilotKit `/copilotkit` agent | `python/hearttwin/copilot.py` | T0.1 | TODO |
| TC.2 | [DC] | Vercel CopilotKit Node route | `web/app/api/copilotkit/route.ts` | T0.3, TC.1 | TODO |
| TC.3 | [DC] | Provider + sidebar + readable state | `web/app/**`, `web/components/copilot/**` | TC.2 | TODO |
| TC.4 | [DC] | Generative-UI action cards | `web/components/copilot/**` | TC.3 | TODO |
| TC.5 | [DC] | Human-in-the-loop recovery confirm | `web/components/copilot/**` | TC.3 | TODO |
| TC.6 | [W] | `useCoAgent` shared-state mirror | `web/components/copilot/**` | TC.3 | TODO |
| TD.1 | [DC] | Port types + utils verbatim | `web/types/**`, `web/lib/**` | T0.3 | TODO |
| TD.2 | [DC] | API client + `useTraceStream` SSE hook | `web/lib/api.ts`, `web/hooks/**` | TD.1, TB.4 | TODO |
| TD.3 | [DC] | Upload + vitals + system-check views | `web/app/**`, `web/components/upload/**` | TD.2 | TODO |
| TD.4 | [DC] | Live AgentTraceTimeline | `web/components/orchestration/**` | TD.2 | TODO |
| TD.5 | [DC] | Charts (PV loop, ECG, recovery) | `web/components/charts/**` | TD.2 | TODO |
| TD.6 | [W] | 3D beating heart (react-three-fiber) | `web/components/heart/**` | TD.2 | TODO |
| TD.7 | — | Shell, safety banners, Weave badge | `web/components/layout/**` | TD.2 | TODO |
| TE.1 | [DC] | Backend → HF Spaces (Docker) | `Dockerfile`, `requirements.txt` | WS-A/B/C | TODO |
| TE.2 | [DC] | Frontend → Vercel (Root=web) | Vercel project settings | T0.3 | TODO |
| TE.3 | [DC] | CORS + end-to-end prod smoke | `api.py` | TE.1, TE.2 | TODO |
| TE.4 | — | Local `make demo` fallback | `Makefile`/`docker-compose.yml` | — | TODO |

---

## 3. WS-0 — Foundations (gate; do these first, together)

### T0.1 `[DC]` Wire creds & connectivity smoke
- **Do:** Populate `.env` (and HF Space + Vercel secrets) with `WANDB_API_KEY`,
  `WANDB_ENTITY`, `WANDB_PROJECT` (use a clear public name, e.g.
  `hearttwin-weavehacks`), `OPENAI_API_KEY`, `UPSTASH_REDIS_REST_URL`,
  `UPSTASH_REDIS_REST_TOKEN`. Update `.env.example`.
- **Verify:** a throwaway script connects to all three: `weave.init(...)` returns a
  client, OpenAI lists models, Redis `set`/`get` round-trips. Delete the script after.

### T0.2 `[DC]` Pin Weave + CopilotKit docs/versions
- **Do:** Fetch current docs; record exact pip/npm package names, versions, and the
  canonical snippets (`@weave.op`, `weave.get_current_call().ui_url`,
  `client.flush()`, `weave.Evaluation`; CopilotKit packages,
  `copilotRuntimeNextJSAppRouterEndpoint`, `copilotKitEndpoint`,
  `add_fastapi_endpoint`, the hooks) into `docs/INTEGRATION_NOTES.md`.
- **Verify:** `docs/INTEGRATION_NOTES.md` exists with version-pinned, copy-pasteable
  snippets for both libraries.

### T0.3 `[DC]` Scaffold `web/` Next.js app
- **Do:** `create-next-app` in `web/` (App Router, TypeScript, Tailwind, ESLint).
  Add a placeholder home page.
- **Verify:** `cd web && pnpm dev` renders at `localhost:3000`; `pnpm build` passes.

---

## 4. WS-A — Weave (Best Use of Weave + eligibility) `[DC]`

> Seam: `python/hearttwin/tools/weave_trace.py` + `orchestrator.py`. The current
> `publish()` is a no-op — replace it with real Weave. Keep the local-JSON fallback.

- **TA.1** Real `weave.init("<entity>/<project>")` at module load, env-guarded (no
  key → local fallback path unchanged). **Verify:** a `/operate` run creates a call
  visible in the Weave UI.
- **TA.2** Decorate orchestrator stage fns + each `run_*` agent with `@weave.op`
  (async-aware) so the call tree nests pipeline → agent → tool. **Verify:** Weave
  shows a nested span tree for one `/operate` run (8 agents, EP∥hemo visible).
- **TA.3** Capture `weave.get_current_call().ui_url` (verify exact API in T0.2);
  return it in the API `weave` block and store on the case. **Verify:** API returns a
  real `run_url` that opens the trace.
- **TA.4** Flush traces before the HTTP response returns. **Verify:** trace is
  visible in the UI within a few seconds of the request completing.
- **TA.5** Wrap `scoring.evaluate_run` scorers as `@weave.op` scorers and define a
  `weave.Evaluation` over the existing golden cases (`tests/test_golden_cases.py`).
  **Verify:** the Evaluation + scores render in the Weave UI.

---

## 5. WS-B — Redis (Best Use of Redis) `[DC]` for trace; `[W]` for rest

- **TB.1** `tools/redis_client.py`: `upstash-redis` async client via `Redis.from_env()`
  at module scope; tiny helpers. **Verify:** connects; `set/get` round-trips.
- **TB.2** Move `tools/storage.py` case state to **RedisJSON** (`JSON.SET`/`GET`)
  keyed by `case_id` with TTL; keep in-memory fallback when unconfigured. **Verify:**
  a case persists across two separate processes.
- **TB.3** `trace_sink` emits `XADD trace:{case_id}` for every event
  (`start_run`/`log_agent_stage`/`log_tool_call`/`log_eval_scores`/`finish_run`).
  **Verify:** `XRANGE trace:{id} - +` shows the events of a run.
- **TB.4** `GET /api/v1/cases/{id}/trace/stream` — SSE (sse-starlette) polling
  `XRANGE` by last-id every ~1–2s; supports `Last-Event-ID`. **Verify:** `curl -N`
  streams events live as a pipeline runs.
- **TB.5** `[W]` Case-memory KNN: embed case summary (OpenAI embeddings), store
  base64 float32 in a Hash, brute-force cosine top-k on new cases → "similar prior
  case." Build on existing `tools/case_memory.py`. **Verify:** returns sensible
  neighbors for a seeded case.
- **TB.6** `[W]` Semantic cache for OpenAI calls (`SETEX` keyed by content hash) +
  `INCR` token/cost counters; expose `GET /api/v1/redis-stats`. **Verify:** a
  repeated identical extraction is a cache hit; counters increment.

---

## 6. WS-C — CopilotKit (Best Use of CopilotKit) `[DC]`

- **TC.1** `python/hearttwin/copilot.py`: CopilotKit Python SDK agent ("Cardiology
  Copilot") exposed via `add_fastapi_endpoint(app, sdk, "/copilotkit")`. Actions =
  `create_case`/`extract`/`operate`/`simulate_recovery` + Q&A over case state;
  reasoning via OpenAI (auto-traced by Weave). **Verify:** the AG-UI endpoint
  responds to a CopilotKit handshake.
- **TC.2** `web/app/api/copilotkit/route.ts` via
  `copilotRuntimeNextJSAppRouterEndpoint` + `remoteEndpoints → copilotKitEndpoint({
  url: ${API_BASE}/copilotkit })` (Node runtime, not edge). **Verify:** a chat
  message from the app reaches the backend agent.
- **TC.3** `<CopilotKit>` provider + `<CopilotSidebar>`; `useCopilotReadable`
  exposes current case state. **Verify:** the copilot answers "what's my EF?" from
  live state.
- **TC.4** `useCopilotAction` with `render` → custom **generative-UI** cards
  (AgentTrace / Metrics / Heart), streamed (`status: inProgress→complete`).
  **Verify:** an action renders a custom React component inside the chat.
- **TC.5** `renderAndWaitForResponse` **human-in-the-loop** confirm for "run recovery
  scenarios?". **Verify:** the agent pauses for a user click before proceeding.
- **TC.6** `[W]` `useCoAgent` shared state mirroring live agent progress in the chat.
- **Fallback (if AG-UI is slow):** client-side `useCopilotAction` handlers calling
  the existing REST endpoints directly — keep the demo unblocked.

---

## 7. WS-D — Frontend port (Nuxt → React under `web/`)

> The legacy Nuxt app in `app/` is the reference. Port what the demo needs into
> `web/`, then remove `app/` + Nuxt config at the end (TE/cleanup). `types/*` and
> `utils/*` port nearly verbatim.

- **TD.1** `[DC]` Port `app/types/{api,heart,agents}.ts` + `app/utils/*` →
  `web/types/`, `web/lib/`. **Verify:** `tsc` passes in `web/`.
- **TD.2** `[DC]` `web/lib/api.ts` (the ~9 methods from
  `app/composables/useHeartTwinApi.ts`) + `web/hooks/useTraceStream.ts` (EventSource
  → TB.4). **Verify:** create-case + a live trace event render against a local backend.
- **TD.3** `[DC]` Upload + manual vitals + system-check views. **Verify:** can upload
  a file and run `/system-check` from the UI.
- **TD.4** `[DC]` Live `AgentTraceTimeline` consuming `useTraceStream`. **Verify:**
  the 8 agents animate in as a run executes.
- **TD.5** `[DC]` Charts via `react-plotly.js`: PV loop, ECG, recovery timeline (port
  from `app/components/charts/*`). **Verify:** PV loop + ECG render from a real
  `/operate` payload.
- **TD.6** `[W]` 3D beating heart via `react-three-fiber` + `drei` (port
  `app/components/heart/*` from TresJS). **Verify:** heart renders and beats; degrade
  gracefully if WebGL unavailable.
- **TD.7** Layout shell, glass cards, **safety banner** (mandatory), Weave deep-link
  badge. **Verify:** disclaimer is visible on every screen.

---

## 8. WS-E — Deploy `[DC]`

- **TE.1** `Dockerfile` + `requirements.txt` for FastAPI; deploy to **Hugging Face
  Spaces (Docker, CPU-basic)**; set backend secrets. **Verify:** public URL serves
  `/api/v1/health` and `/api/v1/system-check` returns `ok`.
- **TE.2** Vercel project, **Root Directory = `web`**; set `NEXT_PUBLIC_API_BASE`
  (HF URL) + CopilotKit runtime envs; deploy. **Verify:** the app loads and talks to
  the backend.
- **TE.3** FastAPI CORS allows the Vercel domain (incl. preview); run the full demo
  path on prod (create→extract→operate→simulate-recovery→trace stream + Weave link).
  **Verify:** the whole demo works on the deployed URLs.
- **TE.4** Local fallback: `make demo` / `docker-compose` runs backend + frontend
  offline. **Verify:** full path works with no internet beyond the LLM key.

---

## 9. Risk register & fallbacks

| Risk | Mitigation / fallback |
|---|---|
| Weave traces don't flush on a short-lived process | Backend on always-on HF Spaces + explicit `client.flush()`; local trace panel already works |
| CopilotKit AG-UI Python wiring eats time | Client-side `useCopilotAction` → existing REST endpoints (still strong CopilotKit usage) |
| 3D heart port (TD.6) slow | Ship 2D/static heart; demo unaffected — it's `[W]` |
| Redis 500K cmd/mo budget (SSE polling) | 1–2s poll interval; cap open demo tabs; raise interval if needed |
| Time crunch | Protect the spine; cut `TC.6 → TB.6 → TD.6` in that order |
| Vercel kills long SSE | Short-lived SSE + `EventSource` auto-reconnect via `Last-Event-ID` |

---

## 10. Definition of Done (per prize)

- **Weave** — public project link works; nested live-run trace tree visible; one
  `weave.Evaluation` with scorers in the UI. *(Eligibility gate.)*
- **CopilotKit** — embedded copilot drives the pipeline; ≥1 generative-UI component;
  ≥1 human-in-the-loop step.
- **Redis** — ≥3 load-bearing uses shown live: Stream trace + JSON state + (KNN
  memory and/or cache + counter).
- **Demo** — < 3 min, demo-first, repo public, works on deployed URLs **and** local
  fallback; `pnpm test:py` green.
