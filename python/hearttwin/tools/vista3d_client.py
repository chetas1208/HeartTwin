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
