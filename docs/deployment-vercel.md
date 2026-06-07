# HeartTwin Lab — Vercel Deployment

> **Educational cardiac simulation only. Not for diagnosis or treatment decisions.**

HeartTwin Lab deploys as **two pieces**:

- **Frontend** — the Next.js + CopilotKit app under `web/`, deployed as a Vercel
  project with **Root Directory = `web`** (framework preset: Next.js).
- **Backend** — the FastAPI Python app, deployed from the **repository root** as a
  Vercel serverless function (`api/index.py`). The root `vercel.json` routes
  `/api/:path*` to it.

The frontend reaches the backend over `NEXT_PUBLIC_API_BASE`, so the two can live
in separate Vercel projects (or the backend can be hosted elsewhere — e.g. a
container host — as long as CORS allows the frontend origin).

## Backend: root deploy structure

```txt
vercel.json         # rewrites /api → Python function
api/index.py        # serverless entrypoint: `from python.hearttwin.api import app`
python/hearttwin/   # FastAPI app, 8 agents, deterministic tools
pyproject.toml      # Python dependencies
requirements.txt    # mirror of runtime deps
.env.example        # documented env vars (no secrets)
```

`api/index.py` is intentionally tiny:

```python
from python.hearttwin.api import app as hearttwin_app
app = hearttwin_app
```

### Backend vercel.json

```json
{
  "rewrites": [{ "source": "/api/:path*", "destination": "/api/index.py" }],
  "functions": { "api/index.py": { "maxDuration": 60, "memory": 1024 } }
}
```

- All `/api/*` requests route to the Python function.
- `maxDuration: 60` gives the pipeline (and Weave trace flush) time to complete.
  Do **not** run this backend on a 10s/500ms-shutdown runtime.

Verify locally before pushing:

```bash
pnpm verify:vercel
```

### Backend steps

1. Push the repo to GitHub (public for WeaveHacks judging).
2. In Vercel, **New Project → import the repo → Root Directory = `/` (root)**.
3. Set environment variables (below).
4. Deploy. Confirm `GET /api/v1/health` returns `{"status":"ok"}`.

## Frontend: web/ deploy

1. In Vercel, **New Project → import the same repo → Root Directory = `web`**.
   Framework preset: **Next.js** (auto-detected; `web/vercel.json` pins it).
2. Set `NEXT_PUBLIC_API_BASE` to the backend URL (e.g.
   `https://your-backend.vercel.app/api/v1`) and `OPENAI_API_KEY` (the CopilotKit
   chat brain). The CopilotKit route proxies to `${origin}/copilotkit`.
3. Deploy. Open the app and confirm the case pipeline + live trace render.

## Required / optional backend env vars

Set these on the **backend** Vercel project. Secrets live server-side only.

### Required for full functionality (app still runs without them via fallbacks)

| Var | Purpose |
|---|---|
| `OPENAI_API_KEY` | LLM reasoning. Missing → deterministic fallbacks. |
| `WANDB_API_KEY` | Weave tracing. Missing → local trace fallback. |
| `WANDB_PROJECT` | Should be `hearttwin-weavehacks`. |
| `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | Redis memory. Missing → in-memory fallback. |

### Public / API base

| Var | Where | Value |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | frontend (`web`) | backend URL, e.g. `https://your-backend.vercel.app/api/v1` |
| `API_BASE` | backend | `/api/v1` |
| `NEXT_PUBLIC_APP_NAME` | frontend | `HeartTwin Lab` |
| `NEXT_PUBLIC_WEAVE_PROJECT_URL` | frontend | public Weave project URL |

> No production code requires `http://localhost:8000`; it is only a named dev
> default in the CopilotKit route.

### Optional

| Var | Default | Purpose |
|---|---|---|
| `WANDB_ENTITY` | — | W&B entity |
| `BLOB_READ_WRITE_TOKEN` | — | Vercel Blob storage; missing → local metadata fallback |
| `VISTA3D_ENABLED` | `false` | Enable 3D segmentation |
| `VISTA3D_API_BASE`, `VISTA3D_API_KEY` | — | VISTA-3D endpoint (only if enabled) |
| `VISTA3D_TIMEOUT_SECONDS` | `120` | VISTA-3D timeout |
| `HEARTTWIN_SAFETY_MODE` | `strict` | Safety mode |
| `HEARTTWIN_TRACE_MODE` | `weave_with_local_fallback` | Trace mode |
| `HEARTTWIN_REDIS_MEMORY_ENABLED` | `true` | Redis memory toggle |
| `OPENAI_MODEL_*`, `OPENAI_EMBEDDING_MODEL` | see `.env.example` | Per-agent model routing |

## Python serverless notes

- Entry: `api/index.py` exports `app` from `python.hearttwin.api`.
- Dependencies come from `pyproject.toml`. Keep the bundle lean — avoid torch,
  tensorflow, monai, opencv. `weave`/`wandb` are optional (`tracing` extra).
- The function uses the default Node/Python runtime, not edge.

## Confirm the deployment

```bash
curl https://your-backend.vercel.app/api/v1/health         # {"status":"ok"}
curl https://your-backend.vercel.app/api/v1/config          # no secrets
curl https://your-backend.vercel.app/api/v1/system-check    # honest integration status
```

## What not to commit

- `.env` / `web/.env.local` (gitignored), any real API keys/tokens.
- `node_modules/`, `web/.next/`, `.vercel/`.
- Large/real datasets or media. Fixtures are tiny and synthetic only.

## Troubleshooting

- **Python dependency too large / build fails**: trim `pyproject.toml`; ensure no
  heavy ML libs sneaked in. Weave is optional.
- **API route not found (404 on `/api/...`)**: check `vercel.json` rewrite and
  that `api/index.py` imports the app. Run `pnpm verify:vercel`.
- **Frontend can't reach backend / CORS error**: set `NEXT_PUBLIC_API_BASE` to the
  backend URL and ensure FastAPI CORS allows the frontend origin (`api.py` uses
  permissive CORS by default).
- **Env vars missing**: app still runs via fallbacks; `/api/v1/system-check`
  `integrations` block will show `fallback`/`local_fallback`/`memory_fallback`.
- **VISTA tunnel down**: set `VISTA3D_ENABLED=false`; extraction/operation continue.
- **Weave not configured**: traces use the local fallback; harness shows
  `not_configured`. Add `WANDB_API_KEY` for live traces (required for the prize).
- **Redis not configured**: in-memory fallback; harness shows in-memory. Add
  Upstash REST URL + token for persistence.
