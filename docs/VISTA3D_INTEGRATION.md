# VISTA-3D Integration Guide

> Audience: future programming agents wiring the VISTA-3D CT segmentation service into HeartTwin Lab.
> This is a field guide derived from **live probing of the running service on 2026-06-06**, not from the
> upstream docs alone. Everything marked **[verified]** was observed directly against the deployment.

---

## 1. What it is

A **self-hosted MONAI / NVIDIA VISTA-3D CT segmentation API** (FastAPI, service version `0.3.0`).
VISTA-3D is a 3D foundation model that segments ~100+ anatomical structures from a CT volume, either
automatically or guided by class prompts.

**[verified]** Live `/health` snapshot of the deployment:

| Property | Value |
|----------|-------|
| Model | MONAI VISTA-3D `0.5.8` |
| Frameworks | MONAI `1.5.2`, torch `2.7.1+cu118`, CUDA `11.8`, cuDNN `91900` |
| GPUs | 2× NVIDIA GeForce RTX 3090 (24 GB each) |
| Workers | 6 (3 per GPU), model preloaded, async job queue |
| Auth | **None** — security is a secret capability URL only |
| Storage/DB | server-side job store + output/preview files on disk |

---

## 2. Access model — the secret capability URL ⚠️

The base URL has the shape:

```
{ORIGIN}/x/{ENDPOINT_SECRET}/...
```

- `ORIGIN` is **ephemeral and rotates.** During testing it moved through
  `http://vista3d-api:8000` (Docker-internal, only resolves inside the container network) →
  `http://130.212.4.96:8000` (raw IP on a CENIC research network, firewalled to specific clients) →
  `https://<random-words>.trycloudflare.com` (a Cloudflare quick-tunnel, the only form reachable from
  an arbitrary host). **Assume the public URL changes every session.**
- `ENDPOINT_SECRET` (e.g. `v3d_…`) is the *only* credential. Anyone with the full URL has full access.

**Integration rules that follow from this:**
1. **Never hardcode** the origin or secret. Drive them from env vars (see §8).
2. **Treat the secret like an API key** — do not commit it, log it, or echo it into traces/UI.
3. **[verified]** A wrong/missing secret returns `404 {"detail":"Not Found"}` — indistinguishable from a
   missing route. Don't try to "detect auth failures"; a 404 on `/health` means *either* bad secret *or*
   bad origin. Probe `/health` at startup to validate both at once.

---

## 3. Endpoints

All paths are **relative to `{ORIGIN}/x/{ENDPOINT_SECRET}`** unless noted. Source: `/openapi.json` (also
browsable at `{ORIGIN}/docs`). **[verified]** all of the following respond as described.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Service + GPU + worker + queue status |
| POST | `/api/v1/segment` | Submit a CT → returns a job (HTTP **202**, async) |
| GET | `/api/v1/jobs/{job_id}` | Poll job status |
| DELETE | `/api/v1/jobs/{job_id}` | Delete a job + its files |
| GET | `/api/v1/jobs/{job_id}/result` | Download segmentation mask (`.nii.gz`, `application/gzip`) |
| GET | `/api/v1/jobs/{job_id}/metadata` | Rich metadata: labels found, spacing, timing, pre/post-proc |
| GET | `/api/v1/jobs/{job_id}/preview` | List of preview PNG URLs |
| GET | `/api/v1/jobs/{job_id}/preview/{filename}` | A single rendered overlay PNG |

Not under the secret prefix: `{ORIGIN}/docs` (Swagger UI) and `{ORIGIN}/openapi.json`.
**[verified]** `{ORIGIN}/` itself is `404` — there is no root route.

---

## 4. Submitting a segmentation (`POST /api/v1/segment`)

`multipart/form-data`. Fields (from the OpenAPI schema; defaults noted):

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `image` | file (octet-stream) | **yes** | **[verified]** Allowed: `.nii`, `.nii.gz`, or `.zip` (a DICOM series). Other types → `422`. |
| `mode` | string | no | `automatic` (default) \| `interactive` \| `segment_everything`. **[verified]** any other value → `422`. |
| `label_prompt` | string (JSON array) | no | e.g. `[6,7,17]` — restrict output to these class IDs. **[verified]** works. |
| `points` | string (JSON) | no | `[[x,y,z], …]` for `interactive` mode. |
| `point_labels` | string (JSON) | no | `[1,0, …]` — 1 = foreground click, 0 = background. |
| `resample_spacing` | string | no | Override preprocessing spacing (default `1.5,1.5,1.5` mm). |
| `roi_size` | string | no | Sliding-window ROI (default `128,128,128`). |
| `sw_batch_size` | int | no | Sliding-window batch (default `1`). |
| `overlap` | number | no | Sliding-window overlap (default `0.5`). |
| `amp_enabled` | string | no | Mixed precision (default on). |
| `priority` | int | no | Queue priority, default `0` (higher = sooner). |
| `generate_preview` | string | no | Truthy → render preview PNGs. |
| `return_format` | string | no | Default `nii.gz`. |
| `callback_url` | string | no | **Webhook** — server POSTs job completion here (avoids polling). |
| `callback_upload_result` | string | no | Include result payload in the callback. |
| `callback_include_metadata` | string | no | Include metadata in the callback. |

**Response (202)** — a `SubmitResponse`:

```json
{
  "job_id": "…",
  "status": "queued",
  "status_url":   "{ORIGIN}/x/{secret}/api/v1/jobs/{job_id}",
  "result_url":   "…/result",
  "metadata_url": "…/metadata",
  "preview_url":  "…/preview"
}
```

The server hands back ready-to-use absolute URLs — prefer following those over re-building paths.

---

## 5. Modes — measured behavior **[verified]**

Tested against a 472 KB lower-thorax→abdomen CT (`122×101×30` @ 3 mm).

| Mode / prompt | Result | Runtime | Notes |
|---------------|--------|---------|-------|
| `automatic` (no prompt) | **43 structures** segmented | ~6.7 s **cold**, <1 s warm | Peak ~5.8 GB VRAM. First call includes model warmup; warm calls on the same tiny volume are sub-second. |
| `automatic` + `label_prompt=[6,7,17]` | exactly aorta, IVC, portal/splenic vein | ~7.3 s | Output mask contains *only* the requested classes → ideal for targeted vessel extraction. |
| `segment_everything` | full label set (same 43 here) | <1 s warm | Behaves like full automatic on this volume. |
| `label_prompt=[115]` (heart, on an **abdomen-only** CT) | **empty** `output_labels: []` | ~0.8 s | A class not present in the field of view yields a *valid, completed* job with an empty mask. The same prompt on a **cardiothoracic** CT returns the heart correctly (§7a). **Always check `output_labels` is non-empty before trusting a result.** |
| `interactive` (+ `points`/`point_labels`) | ❌ **FAILS** | — | **[verified]** Job reaches `failed` with `error_message: "TypeError: expected np.ndarray (got Tensor)"`, regardless of point format or presence of `label_prompt`. **Interactive mode is broken on this deployment — do not use it.** Use `automatic` + `label_prompt` instead. |

**Takeaway:** for HeartTwin, use **`automatic` with `label_prompt`** for targeted structures, or bare
`automatic` for a full organ map. Avoid `interactive`.

---

## 6. Job lifecycle & outputs

1. `POST /segment` → `202` with `job_id`, status `queued`.
2. Poll `GET /jobs/{job_id}` → status transitions `queued → running → completed | failed`.
   **[verified]** small volumes complete in seconds; poll every 2–4 s with a timeout, or use `callback_url`.
3. On `completed`:
   - `GET /jobs/{job_id}/result` → the **segmentation mask** as `.nii.gz`.
   - `GET /jobs/{job_id}/metadata` → see below.
   - `GET /jobs/{job_id}/preview` → preview PNG URLs (if `generate_preview` was set).

### The result mask **[verified]**
- A **label-map NIfTI** in the **original input space** (`metadata.postprocessing.invert_to_original_space = true`;
  `output_shape == input_shape`, e.g. `122×101×30`).
- Each voxel value is an **integer class ID**; map IDs → names via `metadata.output_label_names`.
- To compute a structure's volume deterministically: `voxel_count(label) × prod(input_spacing)` mm³.
  (Keeps HeartTwin's invariant: **the model never does the math** — derive metrics in Python from voxels.)

### Metadata highlights **[verified]** (`JobMetadataResponse`)
```
model_name, model_version            → provenance (e.g. "MONAI VISTA-3D", "0.5.8")
input_shape, input_spacing           → geometry
output_shape, output_labels[]        → which class IDs are present
output_label_names{id: name}         → human labels
mode, label_prompt, points           → how it was asked
gpu, runtime_seconds, peak_memory_mb → performance/provenance
preprocessing  {resample_spacing, orientation:"RAS", intensity_range:[HU_min,HU_max]}
postprocessing {roi_size, sw_batch_size, overlap, amp_enabled, invert_to_original_space}
versions {torch, cuda, cudnn, monai}
created_at, completed_at
```

---

## 7. Label reference

VISTA-3D uses a fixed integer label dictionary (~130 classes). The IDs below are **[verified]** — observed
in real `output_label_names` across two test scans (an abdominal CT and a cardiothoracic CT). The mask is a
label-map where each voxel = one of these IDs.

### 7a. Cardiac & great-vessel labels (the ones that matter for HeartTwin) — all **[verified]**

| ID | Name | ID | Name |
|----|------|----|------|
| **115** | **heart** ✅ | 119 | pulmonary vein |
| 6 | aorta | 125 | superior vena cava |
| 7 | inferior vena cava | 11 | esophagus |
| 108 | left atrial appendage | 57 | trachea |
| 17 | portal vein and splenic vein | 112 / 113 | left / right common carotid artery |

> **Heart = 115 is confirmed.** A targeted `label_prompt=[115,108,119,125,6,7]` on a cardiothoracic CT
> (`255×178×256` @ 1.49 mm) returned exactly those classes *with voxels* (`output_labels:[6,7,108,115,119,125]`,
> ~2.7 s). Automatic mode on the same scan also labeled `115→"heart"`, `108→"left atrial appendage"`,
> `119→"pulmonary vein"`, `125→"superior vena cava"`. Note: VISTA-3D emits the **heart as a single label
> (115)** — it does **not** split into the four chambers. For chamber-level volumes you'd need a different
> model or a downstream split. The heart only appears when it's in the scan's FOV (an abdomen-only CT yields
> an empty mask for 115 — see §5).

### 7b. Other verified labels (abdomen + trunk)

| ID | Name | ID | Name | ID | Name |
|----|------|----|------|----|------|
| 1 | liver | 19 | small bowel | 63–74 | left ribs 1–12 |
| 3 | spleen | 22 | brain | 75–86 | right ribs 1–12 |
| 4 | pancreas | 28 | left lung upper lobe | 87/88 | left/right humerus |
| 5 | right kidney | 29 | left lung lower lobe | 89/90 | left/right scapula |
| 8 | right adrenal gland | 30 | right lung upper lobe | 91/92 | left/right clavicula |
| 9 | left adrenal gland | 31 | right lung middle lobe | 93/94 | left/right femur |
| 10 | gallbladder | 32 | right lung lower lobe | 104/105 | left/right autochthon |
| 12 | stomach | 33–50 | vertebrae L5→C7 | 106/107 | left/right iliopsoas |
| 13 | duodenum | 51–56 | vertebrae C6→C1 | 114 | costal cartilages |
| 14 | left kidney | 61 | right iliac vena | 117 | right kidney cyst |
| 15 | bladder | 62 | colon | 120 | skull |
| 16 | (pelvic organ) | 100 | left gluteus medius | 121 | spinal cord |
| 126 | thyroid gland | 127 | vertebrae S1 | | |

This is not the complete dictionary — only IDs we saw emitted. To enumerate the rest, run `automatic` on a
whole-body CT and read `output_label_names`, or check the upstream VISTA-3D bundle `label_dict`.

---

## 8. Recommended integration into HeartTwin

### Configuration (env-driven — see `.env.example`, README §Environment variables)
Add, **without committing real values**:
```
VISTA3D_API_BASE=            # full origin, e.g. https://<tunnel>.trycloudflare.com
VISTA3D_API_KEY=             # endpoint capability token or API key
VISTA3D_TIMEOUT_SECONDS=120  # per-request timeout
VISTA3D_ENABLED=false        # disabled by default; app must still run
```
Use `VISTA3D_API_BASE` at runtime and pass `VISTA3D_API_KEY` as the endpoint credential. Because local/tunnel
origins can rotate, make it reconfigurable and **probe `/health` on startup**; degrade gracefully (HeartTwin already
runs on deterministic fallbacks when an optional service is absent — keep that contract).

### Where it fits the pipeline
- This is a **multimodal extraction tool** (Stage 2 territory): it turns an uploaded CT into anatomical
  masks → which feed deterministic geometry into the Cardiac State Builder (Stage 4).
- Put the client in `python/hearttwin/tools/vista3d_client.py` (pure tool, no LLM), mirroring the
  deterministic-tools pattern in `python/hearttwin/tools/`. Add tests under `python/hearttwin/tests/`.

### Provenance (HeartTwin's core invariant)
Every value derived from a segmentation must cite its source. Suggested provenance record per derived metric:
```
source: "vista3d"
method: "ct_segmentation"
model:  "MONAI VISTA-3D 0.5.8"        # from metadata.model_name/version
job_id: "<uuid>"                       # reproducibility
label:  "aorta (6)"                    # which mask
formula: "voxel_count × ∏ spacing"     # how the number was computed (in Python, not the model)
```
This slots into the existing `extracted` / `derived` / `default_model_prior` provenance taxonomy.

### Async & serverless
The Python backend is **Vercel serverless** (`api/index.py`, mangum). Long polls can exceed function
timeouts. Two safe patterns:
1. **Submit + return job_id immediately**, then have the frontend poll `status_url` (the API already returns
   absolute poll URLs). Best fit for serverless.
2. Use **`callback_url`** so VISTA-3D webhooks the result back to a HeartTwin endpoint — no polling at all.
Avoid blocking a single serverless invocation on the full segmentation when volumes are large.

### Robustness checklist (all **[verified]** failure modes)
- ✅ Validate `/health` (`status:"ok"`, `model_loaded:true`, `cuda_available:true`) before submitting.
- ✅ After completion, **assert `output_labels` is non-empty** (empty = class out of FOV / nothing found).
- ✅ Handle `status:"failed"` + `error_message` (e.g. interactive-mode crash) without throwing the UI off.
- ✅ Map HTTP errors: `422` = your request is malformed (bad file type, missing `image`, bad `mode`);
  `404` = bad secret/origin *or* unknown job id.
- ✅ Respect concurrency: ~6 workers / 2 GPUs. Use `priority` and don't flood the queue.
- ✅ Keep the **safety boundary**: segmentation output is still `SIMULATION ONLY` — no diagnosis, no triage.

---

## 9. Copy-paste recipes

### curl — full automatic run
```bash
BASE="$VISTA3D_API_BASE"
# 1) health
curl -sS -H "Authorization: Bearer $VISTA3D_API_KEY" "$BASE/health"
# 2) submit (targeted great vessels) → capture job_id
curl -sS -X POST "$BASE/api/v1/segment" \
  -H "Authorization: Bearer $VISTA3D_API_KEY" \
  -F "image=@scan.nii.gz" -F "mode=automatic" \
  -F 'label_prompt=[6,7]' -F "generate_preview=true"
# 3) poll
curl -sS -H "Authorization: Bearer $VISTA3D_API_KEY" "$BASE/api/v1/jobs/$JOB_ID"
# 4) fetch mask + metadata
curl -sS -L -H "Authorization: Bearer $VISTA3D_API_KEY" -o seg.nii.gz "$BASE/api/v1/jobs/$JOB_ID/result"
curl -sS -H "Authorization: Bearer $VISTA3D_API_KEY" "$BASE/api/v1/jobs/$JOB_ID/metadata"
```
> Note: pass the file as `-F "image=@scan.nii.gz"`. Adding `;type=…` breaks curl's file read (observed).

### Python client sketch (`python/hearttwin/tools/vista3d_client.py`)
```python
import os, time, json, httpx

class Vista3DClient:
    def __init__(self):
        self.prefix = os.environ["VISTA3D_API_BASE"].rstrip("/")
        self.headers = {"Authorization": f"Bearer {os.environ['VISTA3D_API_KEY']}"}
        self.timeout = float(os.environ.get("VISTA3D_TIMEOUT_SECONDS", "120"))

    def health(self) -> dict:
        return httpx.get(f"{self.prefix}/health", headers=self.headers, timeout=self.timeout).json()

    def segment(self, image_path: str, *, mode="automatic", label_prompt=None,
                generate_preview=False) -> dict:
        files = {"image": open(image_path, "rb")}
        data = {"mode": mode}
        if label_prompt is not None:
            data["label_prompt"] = json.dumps(label_prompt)   # JSON array string
        if generate_preview:
            data["generate_preview"] = "true"
        r = httpx.post(f"{self.prefix}/api/v1/segment", headers=self.headers, data=data, files=files,
                       timeout=self.timeout)
        r.raise_for_status()                                   # 202 expected
        return r.json()

    def wait(self, job_id: str, *, interval=3.0, max_wait=600) -> dict:
        deadline = max_wait
        while deadline > 0:
            s = httpx.get(f"{self.prefix}/api/v1/jobs/{job_id}", headers=self.headers, timeout=self.timeout).json()
            if s["status"] in ("completed", "failed"):
                return s
            time.sleep(interval); deadline -= interval
        raise TimeoutError(job_id)

    def metadata(self, job_id: str) -> dict:
        return httpx.get(f"{self.prefix}/api/v1/jobs/{job_id}/metadata", headers=self.headers,
                         timeout=self.timeout).json()

    def result_bytes(self, job_id: str) -> bytes:
        return httpx.get(f"{self.prefix}/api/v1/jobs/{job_id}/result", headers=self.headers,
                         timeout=self.timeout).content
```
Then derive volumes deterministically from the mask (e.g. with `nibabel` + `numpy`):
`voxel_count(label) * float(np.prod(meta["input_spacing"]))` mm³ — **never** let an LLM produce the number.

---

## 10. Quick reference — status codes **[verified]**

| Situation | HTTP | Body |
|-----------|------|------|
| Bad secret / bad origin / unknown route | 404 | `{"detail":"Not Found"}` |
| Unknown `job_id` | 404 | `{"detail":"Job not found."}` |
| Missing `image` | 422 | pydantic `missing` for `body.image` |
| Bad file type | 422 | `Unsupported file type '.txt'. Allowed: .nii, .nii.gz, .zip (DICOM series).` |
| Bad `mode` | 422 | `mode must be 'automatic', 'interactive', or 'segment_everything'.` |
| Submit OK | 202 | `SubmitResponse` |
| Interactive inference | job `failed` | `error_message: "TypeError: expected np.ndarray (got Tensor)"` |

---

*Findings recorded from live testing on 2026-06-06 against MONAI VISTA-3D 0.5.8, using an abdominal CT
(`122×101×30`) and a cardiothoracic CT (`255×178×256`, niivue-images `CT_Abdo.nii.gz`). Heart label (115)
and great-vessel labels are verified. Remember the public origin rotates.*
