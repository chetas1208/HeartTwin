# HeartTwin Lab — Vercel Root Deployment

> **Educational cardiac simulation only. Not for diagnosis or treatment decisions.**

HeartTwin Lab deploys from the **repository root** to Vercel: the Nuxt 4 frontend
(via Nitro) and the FastAPI Python backend (as a serverless function) live in one
monorepo. No subdirectory selection is required.

## Root deploy structure

```txt
package.json        # Nuxt app + scripts
pnpm-lock.yaml      # Node lockfile (Vercel uses --frozen-lockfile)
nuxt.config.ts      # Nuxt + runtimeConfig (env → public config)
vercel.json         # framework + rewrites /api → Python function
api/index.py        # serverless entrypoint: `from python.hearttwin.api import app`
python/hearttwin/   # FastAPI app, 8 agents, deterministic tools
pyproject.toml      # Python dependencies
.env.example        # documented env vars (no secrets)
```

`api/index.py` is intentionally tiny:

```python
from python.hearttwin.api import app as hearttwin_app
app = hearttwin_app
```

## vercel.json

```json
{
  "framework": "nuxtjs",
  "buildCommand": "pnpm build",
  "installCommand": "pnpm install --frozen-lockfile",
  "devCommand": "pnpm dev:nuxt",
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

## Steps

1. Push the repo to GitHub (public for WeaveHacks judging).
2. In Vercel, **New Project → import the repo → Root Directory = `/` (root)**.
   Framework preset: **Nuxt.js**.
3. Set environment variables (below).
4. Deploy. Confirm `GET /api/v1/health` returns `{"status":"ok"}`.
5. Run the production smoke test (below).

## Required / optional Vercel env vars

Set these on the **Vercel project** (backend host). Secrets live server-side only.

### Required for full functionality (app still runs without them via fallbacks)

| Var | Purpose |
|---|---|
| `OPENAI_API_KEY` | LLM reasoning. Missing → deterministic fallbacks. |
| `WANDB_API_KEY` | Weave tracing. Missing → local trace fallback. |
| `WANDB_PROJECT` | Should be `hearttwin-weavehacks`. |
| `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | Redis memory. Missing → in-memory fallback. |

### Public (safe to expose to the browser)

| Var | Value |
|---|---|
| `NUXT_PUBLIC_API_BASE` | `/api/v1` (primary — preferred by Nuxt) |
| `API_BASE` | `/api/v1` |
| `NUXT_PUBLIC_APP_NAME` | `HeartTwin Lab` |
| `NUXT_PUBLIC_WEAVE_PROJECT_URL` | public Weave project URL |

> `NEXT_PUBLIC_API_BASE` is a **backward-compat fallback only**. Nuxt code prefers
> `NUXT_PUBLIC_API_BASE`. No production code requires `http://localhost:8000`.

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

## Nuxt / Nitro notes

- `ssr: true`; build via `pnpm build`. Vercel auto-detects the Nuxt preset.
- `runtimeConfig.public` exposes only non-secret values (app name, API base,
  Weave project URL). Server-only secrets stay in `runtimeConfig` (not `public`).

## Confirm the deployment

```bash
curl https://your-app.vercel.app/api/v1/health         # {"status":"ok"}
curl https://your-app.vercel.app/api/v1/config          # no secrets
curl https://your-app.vercel.app/api/v1/system-check    # honest integration status
E2E_BASE_URL=https://your-app.vercel.app pnpm smoke:prod
```

## What not to commit

- `.env` (gitignored), any real API keys/tokens.
- `node_modules/`, `.nuxt/`, `.output/`, `.vercel/`.
- Large/real datasets or media. Fixtures are tiny and synthetic only.

## Troubleshooting

- **Python dependency too large / build fails**: trim `pyproject.toml`; ensure no
  heavy ML libs sneaked in. Weave is optional.
- **API route not found (404 on `/api/...`)**: check `vercel.json` rewrite and
  that `api/index.py` imports the app. Run `pnpm verify:vercel`.
- **Env vars missing**: app still runs via fallbacks; `/api/v1/system-check`
  `integrations` block will show `fallback`/`local_fallback`/`memory_fallback`.
- **VISTA tunnel down**: set `VISTA3D_ENABLED=false`; extraction/operation continue.
- **Weave not configured**: traces use the local fallback; harness shows
  `not_configured`. Add `WANDB_API_KEY` for live traces (required for the prize).
- **Redis not configured**: in-memory fallback; harness shows in-memory. Add
  Upstash REST URL + token for persistence.
