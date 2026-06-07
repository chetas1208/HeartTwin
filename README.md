# HeartTwin Lab

Agentic cardiac digital twin simulator. Educational simulation only — not for clinical use, diagnosis, or treatment decisions.

## What it does

HeartTwin Lab accepts cardiac-related files (PDF reports, ECG images/CSV, echo/MRI-style images, structured vitals) and builds an explainable cardiac simulation. It produces:

- Extracted cardiac observations with full provenance (source, confidence, extraction method)
- A canonical `CardiacTwinState` with deterministic SV, EF, CO, MAP, QTc calculations
- A simulated cardiac cycle with pressure-volume loop visualization
- 2-4 bounded simulated recovery trajectories with uncertainty bands
- A full 8-agent orchestration trace

**Every value shows its source.** Extracted values cite the file and method. Derived values cite the formula. Default values are labeled `default_model_prior`.

## Quick start

The frontend is a Next.js + CopilotKit app under `web/`; the backend is the
FastAPI app under `python/hearttwin`. Run them as two processes:

```bash
cp .env.example .env        # add your API keys (never commit .env)

# 1. Backend (FastAPI) on :8000
python -m uvicorn python.hearttwin.api:app --reload --port 8000

# 2. Frontend (Next.js) on :3000
cd web && pnpm install --ignore-workspace && pnpm dev   # http://localhost:3000
```

Point the frontend at the backend with `NEXT_PUBLIC_API_BASE` (copy
`web/.env.example` to `web/.env.local`; defaults to `http://localhost:8000/api/v1`).
The CopilotKit chat route proxies to the backend's `/copilotkit` AG-UI endpoint.

## Environment variables

```dotenv
# OpenAI
OPENAI_API_KEY=

# OpenAI model routing
OPENAI_MODEL_INTAKE=gpt-5.4-mini
OPENAI_MODEL_EXTRACTION=gpt-5.4-mini
OPENAI_MODEL_VALIDATOR=gpt-5.4-mini
OPENAI_MODEL_STATE_BUILDER=gpt-5.5
OPENAI_MODEL_ELECTROPHYSIOLOGY=gpt-5.4-mini
OPENAI_MODEL_HEMODYNAMICS=gpt-5.4-mini
OPENAI_MODEL_RECOVERY=gpt-5.5
OPENAI_MODEL_EVALUATOR=gpt-5.5
OPENAI_MODEL_FAST=gpt-5.4-nano
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# W&B / Weave
WANDB_API_KEY=
WANDB_ENTITY=
WANDB_PROJECT=hearttwin-weavehacks
NEXT_PUBLIC_WEAVE_PROJECT_URL=

# Storage
BLOB_READ_WRITE_TOKEN=

# Redis / Upstash
UPSTASH_REDIS_REST_URL=
UPSTASH_REDIS_REST_TOKEN=

# API base
# Public base used by the Next.js frontend (web/). Full origin for local dev,
# deployed API URL in production.
NEXT_PUBLIC_API_BASE=http://localhost:8000/api/v1
# Server-side API base.
API_BASE=/api/v1

# VISTA-3D local/tunneled model endpoint
VISTA3D_API_BASE=
VISTA3D_API_KEY=
VISTA3D_TIMEOUT_SECONDS=120
VISTA3D_ENABLED=false

# App
NEXT_PUBLIC_APP_NAME=HeartTwin Lab
HEARTTWIN_SAFETY_MODE=strict
HEARTTWIN_TRACE_MODE=weave_with_local_fallback
HEARTTWIN_REDIS_MEMORY_ENABLED=true
```

The Next.js frontend reads `NEXT_PUBLIC_API_BASE` for REST + the SSE trace stream. `API_BASE` is the server-side base used inside the backend.

Without any API keys, the app runs on local in-memory fallbacks and deterministic algorithms where possible. Weave, Redis, OpenAI, and VISTA-3D integrations all fail safely when disabled or unconfigured.

## API endpoints

```
GET  /api/v1/health                          health check
POST /api/v1/cases                           create a case
POST /api/v1/cases/{id}/files                upload PDF/image/CSV
POST /api/v1/cases/{id}/extract              stages 1-3: intake + extraction + validation
POST /api/v1/cases/{id}/operate              stages 4-5-7: state builder + EP + hemodynamics + evaluator
POST /api/v1/cases/{id}/simulate-recovery    stages 6-7: recovery orchestration + evaluator
POST /api/v1/cases/{id}/self-improve         bounded harness improvement rerun
GET  /api/v1/cases/{id}                      get full case state
GET  /api/v1/cases/{id}/trace                get agent trace
GET  /api/v1/cases/{id}/trace/stream         live agent trace (SSE)
```

## WeaveHacks 4 Alignment

HeartTwin Lab is designed as a multi-agent simulation harness.

Judging criteria mapping:
- Creativity: cardiac digital twin + multi-agent scientific simulator
- Harness sophistication: 8-agent staged orchestration with deterministic tools
- Utility: educational/research simulation of cardiac operation and recovery scenarios
- Technical execution: Next.js + CopilotKit + Python serverless + 3D visualization + tested simulation engine
- Sponsor usage: W&B Weave traces/evals, optional OpenAI extraction, optional Redis memory

Required W&B Weave setup:
1. Create a W&B account.
2. Set `WANDB_API_KEY`.
3. Set `WANDB_PROJECT=hearttwin-weavehacks`.
4. Optionally set `WANDB_ENTITY` or `NEXT_PUBLIC_WEAVE_PROJECT_URL`.
5. Run a case and click View Weave Project.

If Weave is not configured, HeartTwin still records local JSON traces and eval scores.

## Harness Evals

Every operation, recovery, and self-improvement rerun returns structured eval scores:

- Extraction completeness
- Physiological plausibility
- Safety compliance
- Hallucination risk, where lower is better
- Visualization readiness
- Recovery scenario stability
- Overall score

Overall score is a weighted combination of the positive scores with a penalty for hallucination risk. The evaluator also records warnings and failed checks for unsafe medical language, unsupported values, impossible physiology, unstable recovery curves, and visualization gaps.

## Self-Improvement Rerun

`POST /api/v1/cases/{id}/self-improve` runs one bounded harness improvement pass after a recovery simulation exists. It compares before/after eval scores, preserves warnings, and may only adjust recovery harness settings such as max parameter shift, uncertainty penalty, target metric, or recovery horizon. It never changes uploaded evidence, user-provided values, or deterministic cardiac formulas.

## Pipeline stages

| Stage | Agent | Endpoint |
|-------|-------|----------|
| 1 | Intake & Safety Agent | `/extract` |
| 2 | Multimodal Extraction Agent | `/extract` |
| 3 | Evidence Validator Agent | `/extract` |
| 4 | Cardiac State Builder Agent | `/operate` |
| 5a | Electrophysiology Agent (parallel) | `/operate` |
| 5b | Hemodynamics Simulation Agent (parallel) | `/operate` |
| 6 | Recovery Orchestration Agent | `/simulate-recovery` |
| 7 | Evaluator & Critic Agent | `/operate` + `/simulate-recovery` |

## Deterministic formulas

All numeric outputs are produced by pure Python functions in `python/hearttwin/tools/cardiac_state.py` and `hemodynamics.py`. LLMs never perform math.

```
SV  = EDV - ESV
EF  = (SV / EDV) × 100
CO  = (HR × SV) / 1000
MAP = DBP + (SBP - DBP) / 3
RR  = 60000 / HR
QTc = QT / sqrt(RR [seconds])   [Bazett]
BSA = sqrt(H × W / 3600)         [Mosteller]
```

## Tests

```bash
pnpm test:py          # Python backend tests
pnpm build            # build the Next.js frontend (web/)
pnpm verify:all       # env + repo + vercel checks, tests, and build
```

## Deploy to Vercel

Frontend and backend deploy as two pieces:

- **Frontend** — a Vercel project rooted at `web/` (framework: Next.js).
  Set `NEXT_PUBLIC_API_BASE` to the deployed backend URL.
- **Backend** — the Python FastAPI app, deployed from the repo root. The root
  `vercel.json` routes `/api/:path*` to the `api/index.py` serverless function.

## Safety Boundary

HeartTwin Lab is not a medical device. It does not diagnose, prescribe, triage, or recommend treatment. All recovery paths are bounded educational simulations.

HeartTwin Lab is an educational simulation tool. It:

- Does **not** diagnose any condition
- Does **not** recommend medication, treatment, or dosing
- Does **not** provide emergency triage or clinical guidance
- Labels every output with `SIMULATION ONLY`
- Adds a mandatory safety disclaimer to every API response
- Blocks requests containing diagnosis/treatment/emergency language at the intake agent

Use it for education, research, and exploring cardiac physiology concepts — not for clinical decision-making.
