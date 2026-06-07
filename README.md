# HeartTwin Lab

**An auditable, multi-agent cardiac digital twin.** Upload the cardiac evidence you already have — a discharge PDF, an ECG image or CSV, an echo/MRI still, or just structured vitals — and HeartTwin builds an explainable physiological model of the heart: a canonical cardiac state, a beating 3D twin with anatomically-localized findings, a pressure–volume simulation, and bounded recovery forecasts. Every number shows where it came from.

> **Educational simulation only.** HeartTwin Lab is **not a medical device**. It does not diagnose, prescribe, triage, or recommend treatment. Every output is a simulated, educational estimate.

---

## Why this matters

Clinicians and trainees are surrounded by numbers (EF, QTc, CO, MAP) and by tools that produce more numbers — but almost none of those tools let you see *where a number came from*, *what it implies physiologically*, or *what happens next under a different load*. Two failure modes dominate:

1. **Static calculators** give you one formula in isolation. They can't relate EF to afterload, localize a regional change to a coronary territory, or project a recovery trajectory.
2. **Black-box medical LLMs** will happily *invent* an ejection fraction, hide their reasoning, and drift into diagnostic language. Nothing about the output is auditable, and that is exactly what makes it unusable in a clinical setting.

HeartTwin Lab is built around the conviction that **a model is only useful to a clinician if its every value is traceable, its math is deterministic, and its limits are stated out loud.** It turns scattered cardiac evidence into a single, inspectable physiological state — and then makes that state *do something*: localize to anatomy, beat in 3D, simulate a cardiac cycle, and forecast bounded recovery scenarios. It is a teaching and exploration instrument with the rigor that makes its output worth reading.

---

## How it's different — in depth

### 1. Provenance on every single value
Extracted values cite the **source file, extraction method, and a confidence score**. Derived values cite the **exact formula**. Anything filled from population data is explicitly labeled a **`default_model_prior`**. You can audit the entire state field-by-field. No other "AI cardiac" tool hands you a fully sourced state object.

### 2. LLMs never do the math
All numeric outputs (SV, EF, CO, MAP, RR, QTc, BSA) come from **pure, tested Python functions** — never from a language model. LLMs are used only where they're appropriate: reading documents, classifying intent, and writing prose. Results are **reproducible**, not sampled. This is the single biggest reason the output can be trusted.

### 3. Anatomically-localized, code-tagged findings (for radiologists & cardiologists)
HeartTwin doesn't stop at scalars. A deterministic **findings layer** localizes the simulated state to anatomy using the standard **AHA 17-segment left-ventricle model** and **coronary artery territories (LAD / RCA / LCx)**, and renders them as **numbered callouts on the 3D twin** with a matching clinical readout: region, a brief observation, the driving metric, and **reference codes**. Reduced EF → global LV; a regional wall change + scar fraction → the right segments and territory; widened QRS / prolonged QTc → conduction and repolarization observations. Every finding is framed as an **educational simulation observation with reference terminology — never a diagnosis** — so it is legible to a clinician without crossing the safety line.

### 4. An observable multi-agent harness — not one opaque prompt
Eight staged agents (intake & safety → extraction → validation → state builder → electrophysiology ∥ hemodynamics → recovery → evaluator) run as a transparent pipeline with a **live trace** and structured **evaluation scores** (extraction completeness, physiological plausibility, safety compliance, hallucination risk, visualization readiness, recovery stability). You can watch each agent settle and read *why* any warning was raised. Warnings never appear without their reason.

### 5. A twin you can run scenarios on
Beyond a static snapshot, HeartTwin produces **2–4 bounded recovery trajectories** with uncertainty bands, constrained by safe per-day parameter shifts. It's a digital twin you can interrogate ("what if afterload falls?"), not a report you read once.

### 6. Degrades, never bluffs
Missing data is filled from conservative population priors **and flagged**, with elevated uncertainty — never silently guessed. On valid input, no agent hard-fails: the pipeline degrades with explained warnings (covered by an adversarial no-fail test). The only blocking paths are intentional safety gates, and each states its reason.

### 7. Safe by construction
Diagnostic / treatment / emergency language is blocked at **both** the request (intake) and the model-output boundary. Every API response carries a mandatory disclaimer. The product is honest about being a simulation.

---

## Who it's for

- **Cardiology / radiology trainees & educators** — see how measurements drive function, how a regional change maps to a coronary territory and AHA segments, and how recovery bounds behave.
- **Clinician-facing tool builders** — a reference implementation of an *auditable* clinical AI pipeline: sourced state, deterministic math, visible evals, hard safety boundaries.
- **Researchers** — a sandbox for cardiac physiology and bounded what-if simulation with reproducible numerics.

It is **not** for clinical decision-making, and it does not try to be.

## What it produces

- A sourced `CardiacTwinState` (deterministic SV, EF, CO, MAP, QTc).
- A beating **3D digital twin** with severity-coded, anatomically-anchored finding callouts (AHA 17-segment + coronary territory + reference codes) and an honest "no findings / no CT provided" state.
- A simulated cardiac cycle with a pressure–volume loop.
- 2–4 bounded recovery trajectories with uncertainty bands.
- A full 8-agent orchestration trace + structured eval scores, every warning explained.

---

## Quick start

Frontend is a Next.js + CopilotKit app under `web/`; backend is FastAPI under `python/hearttwin`. Run them as two processes:

```bash
cp .env.example .env        # add your API keys (never commit .env)

# 1. Backend (FastAPI) on :8000
python -m uvicorn python.hearttwin.api:app --reload --port 8000

# 2. Frontend (Next.js) on :3000
cd web && pnpm install --ignore-workspace && pnpm dev   # http://localhost:3000
```

Point the frontend at the backend with `NEXT_PUBLIC_API_BASE` (copy `web/.env.example` to `web/.env.local`; defaults to `http://localhost:8000/api/v1`). The CopilotKit chat route proxies to the backend's `/copilotkit` AG-UI endpoint.

Without any API keys the app still runs: LLM-backed steps fall back to deterministic behavior, and Weave / Redis / OpenAI / VISTA-3D all degrade safely when unconfigured.

## API endpoints

```
GET  /api/v1/health                          health check
POST /api/v1/cases                           create a case
POST /api/v1/cases/{id}/files                upload PDF/image/CSV
POST /api/v1/cases/{id}/extract              stages 1-3: intake + extraction + validation
POST /api/v1/cases/{id}/operate              stages 4-5-7: state builder + EP + hemodynamics + evaluator
                                             (returns visualization.cardiac_findings)
POST /api/v1/cases/{id}/simulate-recovery    stages 6-7: bounded recovery + evaluator
POST /api/v1/cases/{id}/self-improve         bounded harness improvement rerun
GET  /api/v1/cases/{id}                      full case state
GET  /api/v1/cases/{id}/trace                agent trace (snapshot)
GET  /api/v1/cases/{id}/trace/stream         live agent trace (SSE)
```

## Pipeline stages

| Stage | Agent | Endpoint |
|-------|-------|----------|
| 1 | Intake & Safety | `/extract` |
| 2 | Multimodal Extraction | `/extract` |
| 3 | Evidence Validator | `/extract` |
| 4 | Cardiac State Builder | `/operate` |
| 5a | Electrophysiology (parallel) | `/operate` |
| 5b | Hemodynamics Simulation (parallel) | `/operate` |
| 6 | Recovery Orchestration | `/simulate-recovery` |
| 7 | Evaluator & Critic | `/operate` + `/simulate-recovery` |

## Deterministic formulas

All numeric outputs come from pure Python in `python/hearttwin/tools/`. LLMs never perform math.

```
SV  = EDV - ESV
EF  = (SV / EDV) × 100
CO  = (HR × SV) / 1000
MAP = DBP + (SBP - DBP) / 3
RR  = 60000 / HR
QTc = QT / sqrt(RR [seconds])   [Bazett]
BSA = sqrt(H × W / 3600)         [Mosteller]
```

## Findings & anatomy

The findings layer (`python/hearttwin/tools/cardiac_findings.py`) maps the simulated state onto the **AHA 17-segment model** and **coronary territories**, attaching a 3D anchor, severity, observation, and reference codes. It reports `imaging_source` honestly (`none` / `image_extraction` / `vista3d_segmentation`). VISTA-3D segmentation is **optional** and, in its current contract, returns segmentation label IDs + a job handle (not a CT-derived mesh); the 3D twin is an anatomically-faithful stylized model driven by the real state, not a rendered scan.

## Environment variables

See `.env.example`. Highlights: `OPENAI_API_KEY` (+ per-agent `OPENAI_MODEL_*`), `WANDB_*` for Weave tracing, `UPSTASH_REDIS_REST_*` for case memory, `VISTA3D_*` for optional segmentation, and `NEXT_PUBLIC_API_BASE` for the frontend.

## Tests

```bash
pnpm test:py          # Python backend tests (incl. adversarial no-fail + findings)
pnpm build            # build the Next.js frontend (web/)
pnpm verify:all       # env + repo + vercel checks, tests, and build
```

## Deploy (Vercel)

Two pieces: the **frontend** as a Vercel project with **Root Directory = `web`** (framework: Next.js; set `NEXT_PUBLIC_API_BASE` to the backend URL), and the **backend** as a Python serverless function from the repo root (`vercel.json` routes `/api/:path*` → `api/index.py`).

## Safety boundary

HeartTwin Lab is an educational simulation. It does **not** diagnose, recommend medication or treatment, or provide emergency guidance. It blocks diagnostic/treatment language at the intake and output boundaries, labels every output `SIMULATION ONLY`, flags every value filled from priors, and frames all anatomic findings as educational observations with reference terminology — never a clinical diagnosis. Use it for education, research, and exploring cardiac physiology — not for clinical decisions.
