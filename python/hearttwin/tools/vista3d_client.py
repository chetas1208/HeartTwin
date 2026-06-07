"""VISTA-3D (MONAI) cardiac CT segmentation client.

Thin, fail-safe wrapper around the VISTA-3D segmentation API described in
``docs/VISTA3D_INTEGRATION.md``. Used by the Multimodal Extraction Agent to
*orchestrate* segmentation of CT-volume uploads — never to compute clinical
values itself (volumes must be derived deterministically from the returned
mask in a later stage, never guessed by an LLM).

Design constraints (serverless-safe):
  * env-gated (``VISTA3D_ENABLED`` + ``VISTA3D_API_BASE``) — fully optional;
  * health-checked before submission;
  * **submit-and-return** — never blocks on polling a long-running GPU job;
  * never raises — any failure degrades to a labelled, warning-carrying result.

Verified facts baked in here (see the integration guide for sourcing):
  * VISTA-3D emits the heart as a **single label (115)** — it does not split
    into chambers, so "left ventricle" / "right ventricle" / "myocardium"
    all resolve to 115 with an explanatory warning.
  * "pulmonary artery" has no verified label; the closest verified class is
    "pulmonary vein" (119), used as a labelled proxy.
"""

from __future__ import annotations

import json
import os
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from python.hearttwin.tools.env_config import env_bool

_DEFAULT_TIMEOUT_SECONDS = 120.0

# Verified cardiac & great-vessel label IDs (docs/VISTA3D_INTEGRATION.md §7a).
_LABEL_IDS: dict[str, int] = {
    "heart": 115,
    "left ventricle": 115,
    "right ventricle": 115,
    "myocardium": 115,
    "aorta": 6,
    "pulmonary artery": 119,  # proxy: closest verified class is "pulmonary vein"
}

# Classes VISTA-3D cannot resolve as distinct masks on this deployment — the
# single "heart" label (115) covers all of them.
_NOT_SEPARABLE_PROXY_NOTES: dict[str, str] = {
    "left ventricle": "VISTA-3D emits the heart as a single label (115); chamber-level masks are not available.",
    "right ventricle": "VISTA-3D emits the heart as a single label (115); chamber-level masks are not available.",
    "myocardium": "VISTA-3D emits the heart as a single label (115); a separate myocardium mask is not available.",
    "pulmonary artery": "No verified 'pulmonary artery' class; using 'pulmonary vein' (119) as the closest verified proxy.",
}


class Vista3DSegmentationResult(BaseModel):
    """Outcome of a (possibly skipped/failed) VISTA-3D segmentation orchestration."""

    status: Literal["disabled", "unavailable", "queued", "failed", "skipped"] = "skipped"
    file_id: Optional[str] = None
    filename: Optional[str] = None
    job_id: Optional[str] = None
    status_url: Optional[str] = None
    result_url: Optional[str] = None
    metadata_url: Optional[str] = None
    mode: str = "automatic"
    requested_classes: list[str] = Field(default_factory=list)
    label_ids: dict[str, int] = Field(default_factory=dict)
    label_prompt: list[int] = Field(default_factory=list)
    note: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


def is_configured() -> bool:
    """True only when VISTA-3D is explicitly enabled and an API base is set."""
    if not env_bool("VISTA3D_ENABLED", False):
        return False
    return bool(_base_url())


def _base_url() -> str:
    return (os.environ.get("VISTA3D_API_BASE") or os.environ.get("VISTA3D_BASE_URL") or "").rstrip("/")


def _api_key() -> str:
    return os.environ.get("VISTA3D_API_KEY") or os.environ.get("VISTA3D_ENDPOINT_SECRET") or ""


def _timeout() -> float:
    raw = os.environ.get("VISTA3D_TIMEOUT_SECONDS") or os.environ.get("VISTA3D_TIMEOUT_S")
    try:
        return float(raw) if raw else _DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        return _DEFAULT_TIMEOUT_SECONDS


def _headers() -> dict[str, str]:
    key = _api_key()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _resolve_label_prompt(target_classes: list[str]) -> tuple[dict[str, int], list[int], list[str]]:
    """Map requested class names to verified VISTA-3D label IDs.

    Returns (name -> id mapping for resolved classes, deduped ordered id list,
    warnings for classes that have no verified mapping or are merged proxies).
    """
    label_ids: dict[str, int] = {}
    warnings: list[str] = []
    for raw_name in target_classes:
        name = raw_name.strip().lower()
        label_id = _LABEL_IDS.get(name)
        if label_id is None:
            warnings.append(f"No verified VISTA-3D label for target class '{raw_name}' — skipped")
            continue
        label_ids[raw_name] = label_id
        proxy_note = _NOT_SEPARABLE_PROXY_NOTES.get(name)
        if proxy_note:
            warnings.append(f"'{raw_name}': {proxy_note}")

    label_prompt: list[int] = []
    for label_id in label_ids.values():
        if label_id not in label_prompt:
            label_prompt.append(label_id)
    return label_ids, label_prompt, warnings


async def health_check() -> tuple[bool, list[str]]:
    """Best-effort probe of ``/health``. Never raises; returns (ok, warnings)."""
    if not is_configured():
        return False, ["VISTA3D_ENABLED is not set or VISTA3D_API_BASE is missing"]

    try:
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{_base_url()}/health", headers=_headers(), timeout=_timeout())
        if resp.status_code != 200:
            return False, [f"VISTA-3D /health returned HTTP {resp.status_code}"]
        body = resp.json()
        if body.get("status") not in ("ok", "healthy", True) and not body.get("model_loaded"):
            return False, [f"VISTA-3D health check reported degraded status: {body}"]
        return True, []
    except Exception as exc:
        return False, [f"VISTA-3D health check failed: {type(exc).__name__}: {exc}"]


async def run_segmentation(
    file_bytes: bytes,
    filename: str,
    target_classes: list[str],
    *,
    file_id: Optional[str] = None,
    mode: str = "automatic",
) -> Vista3DSegmentationResult:
    """Submit a CT volume for segmentation and return immediately with a job id.

    Deliberately does **not** poll for completion (GPU segmentation jobs can run
    for minutes; blocking here would be unsafe in a serverless request path).
    Any failure — disabled config, unreachable service, bad upload, API error —
    degrades to a labelled result carrying warnings; this function never raises.
    """
    label_ids, label_prompt, label_warnings = _resolve_label_prompt(target_classes)

    if not is_configured():
        return Vista3DSegmentationResult(
            status="disabled",
            file_id=file_id,
            filename=filename,
            mode=mode,
            requested_classes=list(target_classes),
            label_ids=label_ids,
            label_prompt=label_prompt,
            note="VISTA-3D segmentation is disabled (set VISTA3D_ENABLED=true and VISTA3D_API_BASE to enable).",
            warnings=label_warnings,
        )

    healthy, health_warnings = await health_check()
    if not healthy:
        return Vista3DSegmentationResult(
            status="unavailable",
            file_id=file_id,
            filename=filename,
            mode=mode,
            requested_classes=list(target_classes),
            label_ids=label_ids,
            label_prompt=label_prompt,
            note="VISTA-3D service is unavailable — segmentation skipped, no values invented.",
            warnings=label_warnings + health_warnings,
        )

    try:
        import httpx

        data: dict[str, Any] = {"mode": mode}
        if label_prompt:
            data["label_prompt"] = json.dumps(label_prompt)

        files = {"image": (filename, file_bytes, "application/octet-stream")}
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{_base_url()}/api/v1/segment",
                headers=_headers(),
                data=data,
                files=files,
                timeout=_timeout(),
            )

        if resp.status_code != 202:
            return Vista3DSegmentationResult(
                status="failed",
                file_id=file_id,
                filename=filename,
                mode=mode,
                requested_classes=list(target_classes),
                label_ids=label_ids,
                label_prompt=label_prompt,
                note=f"VISTA-3D submission failed with HTTP {resp.status_code}",
                warnings=label_warnings + [f"submit response: {resp.text[:300]}"],
            )

        body = resp.json()
        job_id = body.get("job_id")
        return Vista3DSegmentationResult(
            status="queued",
            file_id=file_id,
            filename=filename,
            job_id=job_id,
            status_url=body.get("status_url"),
            result_url=body.get("result_url"),
            metadata_url=body.get("metadata_url"),
            mode=mode,
            requested_classes=list(target_classes),
            label_ids=label_ids,
            label_prompt=label_prompt,
            note=(
                "Segmentation job submitted and queued — result is asynchronous; "
                "no chamber volumes are computed here. Poll the job status separately "
                "and derive any volumes deterministically from the returned mask."
            ),
            warnings=label_warnings,
        )
    except Exception as exc:
        return Vista3DSegmentationResult(
            status="failed",
            file_id=file_id,
            filename=filename,
            mode=mode,
            requested_classes=list(target_classes),
            label_ids=label_ids,
            label_prompt=label_prompt,
            note="VISTA-3D submission raised an exception — segmentation skipped, no values invented.",
            warnings=label_warnings + [f"{type(exc).__name__}: {exc}"],
        )


# Default cardiac / great-vessel classes to request (heart + aorta resolve to
# verified labels; chamber names collapse to the single heart label 115).
DEFAULT_CARDIAC_CLASSES = ["heart", "aorta"]


async def _get(url: str) -> Any:
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers(), timeout=_timeout())
    resp.raise_for_status()
    return resp


async def poll_until_done(
    status_url: str, *, interval_s: float = 3.0, max_wait_s: float = 90.0
) -> dict[str, Any]:
    """Poll a job's status URL until completed/failed or timeout. Never raises."""
    import asyncio

    waited = 0.0
    last: dict[str, Any] = {"status": "unknown"}
    while waited <= max_wait_s:
        try:
            resp = await _get(status_url)
            last = resp.json()
        except Exception as exc:
            return {"status": "poll_error", "error": f"{type(exc).__name__}: {exc}"}
        if str(last.get("status", "")).lower() in ("completed", "failed", "error"):
            return last
        await asyncio.sleep(interval_s)
        waited += interval_s
    return {"status": "timeout", "last": last, "waited_s": waited}


async def segment_ct_and_analyze(
    file_bytes: bytes,
    filename: str,
    *,
    file_id: Optional[str] = None,
    target_classes: Optional[list[str]] = None,
    max_wait_s: float = 90.0,
) -> dict[str, Any]:
    """Full CT path: submit -> poll -> metadata -> mask -> deterministic volumetry.

    Returns a JSON-able dict suitable to embed as the ``__ct_segmentation__``
    extraction artifact. Fail-safe: any disabled/unavailable/failed/timeout state
    degrades to a labelled result with warnings and **no invented values**.
    """
    from python.hearttwin.tools.ct_volumetry import analyze_mask_bytes

    classes = target_classes or DEFAULT_CARDIAC_CLASSES
    submit = await run_segmentation(file_bytes, filename, classes, file_id=file_id)

    base = {
        "source": "vista3d",
        "method": "ct_segmentation",
        "filename": filename,
        "file_id": file_id,
        "job_id": submit.job_id,
        "requested_classes": classes,
        "submit_status": submit.status,
        "warnings": list(submit.warnings),
    }

    if submit.status != "queued":
        # disabled / unavailable / failed — honest passthrough, no crash.
        base["status"] = submit.status
        base["note"] = submit.note
        return base

    status = await poll_until_done(submit.status_url or "", max_wait_s=max_wait_s)
    job_state = str(status.get("status", "")).lower()
    if job_state != "completed":
        base["status"] = job_state or "unknown"
        base["note"] = "CT segmentation did not complete in time — no values invented."
        if status.get("error_message"):
            base["warnings"].append(str(status["error_message"]))
        return base

    # Fetch metadata + mask using server-provided absolute URLs.
    metadata: dict[str, Any] = {}
    try:
        if submit.metadata_url:
            metadata = (await _get(submit.metadata_url)).json()
    except Exception as exc:
        base["warnings"].append(f"metadata fetch failed: {type(exc).__name__}: {exc}")

    output_labels = metadata.get("output_labels")
    if isinstance(output_labels, list) and not output_labels:
        base["status"] = "empty_mask"
        base["note"] = ("Segmentation completed but no requested structures were in the CT field "
                        "of view (empty mask) — no values invented.")
        base["metadata"] = metadata
        return base

    try:
        mask_bytes = (await _get(submit.result_url)).content if submit.result_url else b""
    except Exception as exc:
        base["status"] = "result_fetch_error"
        base["warnings"].append(f"result fetch failed: {type(exc).__name__}: {exc}")
        return base

    analysis = analyze_mask_bytes(mask_bytes, metadata=metadata, provenance={"job_id": submit.job_id})
    base["status"] = analysis.status  # "analyzed" | "unreadable_mask"
    base["volumes"] = analysis.volumes
    base["abnormalities"] = analysis.abnormalities
    base["output_labels"] = analysis.output_labels
    base["provenance"] = analysis.provenance
    base["metadata"] = {k: metadata.get(k) for k in
                        ("model_name", "model_version", "input_spacing", "input_shape",
                         "output_labels", "runtime_seconds") if k in metadata}
    base["warnings"].extend(analysis.warnings)
    return base
