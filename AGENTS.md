# AGENTS.md — HeartTwin Lab swarm operating rules

> Operating rules for any agent (or human) working this repo during **WeaveHacks 4
> (Jun 6–7, 2026)**. Read this **before** picking up work. The actionable backlog
> is **[`docs/TASKS.md`](./docs/TASKS.md)** — claim a task there, follow the rules
> here. Strategic context is in [`docs/PLANNING.md`](./docs/PLANNING.md).

---

## 0. Mission & north star

**Win all three sponsor prizes — Best Use of Weave, CopilotKit, and Redis — with a
bulletproof 3-minute demo.** Theme is **Multi-Agent Orchestration**, which our
8-agent cardiac digital twin already embodies. Everything is built backwards from
the demo in `docs/TASKS.md §1`.

One-liner: *"HeartTwin Lab — a multi-agent cardiac digital twin you talk to: a
CopilotKit agent orchestrates 8 specialist agents over a deterministic physics
core, every step traced live in Weave and streamed through Redis, rendering a
beating 3D heart and bounded recovery scenarios."*

**Hard judging facts (verified Jun 6):**
- **Weave is MANDATORY for prize eligibility.** You must open a **public** Weave
  project and show live traces to judges. No Weave = no prize.
- Demo is **~3 minutes, strictly enforced, demo-first, 1–2 slides, public GitHub.**
- Judges reward *genuine* multi-agent orchestration + *meaningful* (load-bearing,
  shown-on-screen) sponsor usage — not a single LLM call in a wrapper.

---

## 1. Golden rules (non-negotiable)

1. **Protect the demo spine.** Tasks tagged `[DC]` (demo-critical) come first and
   must always be in a working state. `[W]` (wow) tasks are pure upside and are the
   first things cut under time pressure (cut order: `TC.6 → TB.6 → TD.6`).
2. **Verify before you mark done.** Every task in `docs/TASKS.md` has a **Verify**
   gate. "It compiles" is not done. Run the gate; paste the result in your PR.
3. **The deterministic physics core is sacred.** LLMs never do math. Do not touch
   the formulas in `python/hearttwin/tools/cardiac_state.py` /
   `hemodynamics.py` / `recovery_sim.py` or their results. The LLM only
   *reasons, orchestrates, and narrates*.
4. **Safety stays on.** Every API response keeps the `safety_disclaimer`. The
   intake agent's diagnosis/treatment/emergency blocking must keep working. Never
   add diagnostic or treatment language anywhere.
5. **Never break the test suite.** 153 Python tests are green. Run `pnpm test:py`
   (and `pnpm check` for the backend) before pushing. New behavior needs new tests.
6. **Secrets are never committed.** Use env vars only (see §4). Never log PII or raw
   uploaded content — the sanitizer in `weave_trace.py` exists for this; keep using it.
7. **Stay in your lane (file ownership).** Backend work lives under `python/` +
   `api/`; new frontend lives under `web/`. Don't edit files another task owns —
   each task lists the files it touches. If two tasks need the same file, coordinate
   on the status board first.
8. **Branch & PR discipline** — see §3.

---

## 2. Coordination protocol (multiple humans + swarms in parallel)

- **Claim before you build.** In `docs/TASKS.md`, set the task's status to
  `WIP @your-handle` (status board at the top of that file) so two swarms don't
  collide. Set it back to `DONE` (with the PR link) when the Verify gate passes, or
  `BLOCKED` with a one-line reason.
- **Workstreams are designed to be independent.** A (Weave), B (Redis),
  C (CopilotKit), D (Frontend), E (Deploy) can run concurrently after the WS-0 gate.
- **WS-0 is a gate.** Nobody's `[DC]` work is truly verifiable until WS-0 (creds +
  Next.js skeleton) lands. Do WS-0 first, together.
- **Integration seams are explicit** (so parallel work converges cleanly):
  - The single instrumentation seam is `trace_sink` in
    `python/hearttwin/tools/weave_trace.py` — Weave (WS-A) *and* the Redis live
    stream (WS-B) both hook here. Coordinate edits to this one file.
  - The frontend talks to the backend only through `web/lib/api.ts` +
    `web/hooks/useTraceStream.ts` (WS-D). Keep the API contract in `web/types/*`
    matching `python/hearttwin/schemas.py`.
- **Don't duplicate research.** The verified facts in §4 are the answer — don't
  re-litigate them. If a doc contradicts §4, §4 wins (it's newer).

---

## 3. Git / branch / PR rules

- **Develop on `claude/fervent-mccarthy-NrLAO`** (create locally if missing). You
  may branch short-lived feature branches off it (e.g. `ws-a-weave-ops`) and PR back
  into it — one workstream per PR is ideal.
- **Never push to `main`/`master`/default** without explicit human permission.
- `git push -u origin <branch>`; retry transient network failures up to 4× with
  exponential backoff (2s/4s/8s/16s).
- **Open PRs as ready for review (not draft).** Title references the workstream;
  body lists the task IDs done and pastes the Verify output. Keep commits small and
  descriptive.
- **Do not commit** secrets, `.env`, `node_modules/`, build output, or large binaries.

---

## 4. Verified technical constraints (use these — already researched)

> These supersede any older guidance in `docs/PLANNING.md` or `README.md`.

### Weave (WS-A)
- **The current `weave_trace.py` does NOT emit real traces** — `_publish()` calls a
  non-existent `client.publish()`. It's a local-JSON fallback only. **This is a real
  build task, not polish.** Replace with proper `weave.init()` + `@weave.op`.
- `weave.init("<entity>/<project>")` once at module load, **env-guarded** (no key →
  skip, keep local fallback). Decorate orchestrator stages + each `run_*` agent so
  the call tree **nests** (pipeline → agent → tool). Works on sync & async fns.
- **Flush before the HTTP response returns** (`client.flush()` or equivalent) so
  traces appear within seconds — confirm the exact call in docs (T0.2).
- Capture the call's public URL (`weave.get_current_call().ui_url` — verify) and
  surface it in the API `weave` block + UI. Set `WANDB_ENTITY` + `WANDB_PROJECT` so
  the project link is public and shareable with judges.
- The existing OpenAI call in `tools/image_extract.py` auto-traces once
  `weave.init()` runs.

### Redis / Upstash (WS-B)
- Use the **`upstash-redis` async REST client** (`from upstash_redis.asyncio import
  Redis`, `Redis.from_env()`), instantiated **at module scope**. REST beats TCP on
  serverless (no socket exhaustion). Env: `UPSTASH_REDIS_REST_URL` +
  `UPSTASH_REDIS_REST_TOKEN`.
- **NO native vector search / KNN on Upstash Redis** (no `FT.SEARCH`, Upstash Vector
  is NOT available to us). Do **brute-force cosine KNN in NumPy** over vectors stored
  as **base64 float32 in a Hash** (`HGETALL` once, ~hundreds of vectors = sub-ms).
  The scaffold in `tools/case_memory.py` already does brute-force — persist its
  vectors in Redis, do **not** try RediSearch.
- **Streams work over REST** (`XADD`/`XRANGE`/`XLEN`) but **`XREAD BLOCK` does
  NOT.** Live trace = `XADD` from `trace_sink` → FastAPI **SSE** endpoint that polls
  `XRANGE` by last-id → browser `EventSource` (use `Last-Event-ID` for lossless
  reconnect).
- **RedisJSON** (`JSON.SET`/`JSON.GET`), pipelines, and `MULTI/EXEC` are supported;
  blocking list ops are not.
- **Free-tier limits that bite:** **500K commands/month** (a 0.5s SSE poll ≈
  7.2K/hr/tab → poll every **1–2s** and cap demo tabs), 10MB max request, 32KB max
  hash field (1536-dim float32 b64 ≈ 8KB, fine), 256MB DB, 1 DB.
- **"Best use of Redis" = breadth, shown live:** Streams (trace) + RedisJSON/Hashes
  (case state) + base64-Hash KNN (case memory) + `INCR`/`SETEX` (token/cost counters,
  prompt/extraction cache, rate limit).

### CopilotKit (WS-C)
- **CopilotKit is React-first.** Decision already made by the team: **migrate the
  frontend to Next.js (App Router) under `web/`** — do not bolt React into Nuxt.
- Runtime: a **Node route `app/api/copilotkit/route.ts` on Vercel** (default Node
  runtime — do **not** set `runtime = "edge"`), created with
  `copilotRuntimeNextJSAppRouterEndpoint`, proxying to the Python backend via
  `remoteEndpoints: [copilotKitEndpoint({ url: \`${process.env.API_BASE}/copilotkit\` })]`.
- Backend exposes the agent with the **CopilotKit Python SDK**:
  `add_fastapi_endpoint(app, sdk, "/copilotkit")` (AG-UI). The "Cardiology Copilot"
  agent's actions = pipeline stages (`create_case`/`extract`/`operate`/
  `simulate_recovery`) + Q&A over case state.
- Hooks to use: `useCopilotReadable` (expose case state), `useCopilotAction` with
  `render` (**generative UI** — stream custom React cards, `status:
  inProgress→complete`), `renderAndWaitForResponse` (**human-in-the-loop**),
  optionally `useCoAgent` (shared state). Components: `<CopilotKit>` provider +
  `<CopilotSidebar>`/`<CopilotChat>`. Import the required CSS.
- **Pin exact package names + versions in `T0.2`** before building (the API moves
  fast). **Fallback if AG-UI wiring is slow:** client-side `useCopilotAction`
  handlers calling the existing REST endpoints directly — still strong CopilotKit
  usage, unblocks the demo.

### Deploy (WS-E)
- **Backend → Hugging Face Spaces (Docker, CPU-basic): free and won't sleep during
  the 48h event.** Do **NOT** run this backend on Vercel Python functions — the
  500ms SIGTERM shutdown kills Weave trace flushes, there are no WebSockets, and
  weave/wandb is fragile against the 500MB bundle. (Render free web service is the
  keep-warm backup.)
- **Frontend Next.js → Vercel**, **Root Directory = `web`** (no `vercel.json`
  needed). The CopilotKit Node route stays on Vercel.
- **Secrets placement:** `OPENAI_API_KEY`, `WANDB_*`, `UPSTASH_*` live on the
  **backend host**. On Vercel set `NEXT_PUBLIC_API_BASE` (backend URL) — note the
  rename from the old `NUXT_PUBLIC_*`. FastAPI **CORS** must allow the Vercel domain
  (incl. `*.vercel.app` preview) — `api.py` already uses permissive CORS; tighten if
  needed.

---

## 5. Definition of Done

**Global:** demo runs end-to-end on the **deployed URLs** *and* via a **local
fallback**; `pnpm test:py` green; repo public with a clean README; the demo fits in
**< 3 minutes**.

**Per prize:**
- **Weave** — public project link works; a **nested trace tree** of a live run is
  visible; **one `weave.Evaluation`** with scorers shows in the UI. (Eligibility.)
- **CopilotKit** — an embedded copilot **drives the pipeline**; ≥1 **generative-UI**
  custom component renders in chat; ≥1 **human-in-the-loop** step.
- **Redis** — **≥3 load-bearing uses shown on screen**: Stream trace + JSON state +
  (KNN memory and/or semantic cache + counter).

---

## 6. Run / verify locally (quick reference)

```bash
# Backend (Python)
pnpm test:py            # 153 tests — keep green
pnpm check              # typecheck + lint + tests

# Backend dev server (FastAPI)
uvicorn api.index:app --reload --port 8000   # /api/v1/health, /api/v1/system-check

# Smoke the full pipeline (deterministic golden case)
curl localhost:8000/api/v1/system-check

# New frontend (once scaffolded under web/)
cd web && pnpm dev      # http://localhost:3000
```

- `GET /api/v1/system-check` runs the full pipeline on a golden case and validates
  outputs — use it as your fastest "is the backend healthy?" check and as a
  judge-friendly determinism demo.
- Keep `web/types/*` in sync with `python/hearttwin/schemas.py`. The API client is
  ~9 thin methods — see the legacy `app/composables/useHeartTwinApi.ts` for the
  contract to port.

---

## 7. Quality bar

Match the surrounding code's style, naming, and comment density. No over-
engineering — this is a 2-day hackathon, demo-first. Prefer the smallest change that
passes the Verify gate and protects the spine. When in doubt, ask on the status
board rather than guessing on a shared file.
