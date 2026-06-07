"""Deterministic CT segmentation volumetry + abnormality flags.

Turns a VISTA-3D **label-map mask** (NIfTI) into structure volumes and a small
set of *educational, simulation-only* abnormality observations. Mirrors the
HeartTwin invariant: **the model never does the math** — every number here is
computed in pure Python from voxel counts × spacing.

Honest scope (per docs/VISTA3D_INTEGRATION.md §7a):
  * VISTA-3D emits the heart as a **single label (115)** — no chamber split.
    So we can produce a **global** volumetric cardiomegaly proxy, but NOT
    chamber EF, regional wall motion, or scar from CT here.
  * Findings are framed as educational reference observations, never diagnoses.

No third-party deps: a minimal NIfTI-1/2 reader is implemented on numpy only,
so the serverless bundle stays small.
"""
from __future__ import annotations

import gzip
import json
import math
import pathlib
import struct
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

# Cardiac / great-vessel label IDs we care about (verified, doc §7a).
HEART_LABEL = 115
AORTA_LABEL = 6
CARDIAC_LABELS: dict[int, str] = {
    115: "heart",
    6: "aorta",
    7: "inferior vena cava",
    108: "left atrial appendage",
    119: "pulmonary vein",
    125: "superior vena cava",
}

_REF_PATH = pathlib.Path(__file__).parent.parent / "data" / "ct_reference_ranges.json"


def _load_reference_ranges() -> dict[str, Any]:
    try:
        return json.loads(_REF_PATH.read_text())
    except Exception:
        # Conservative fallback so volumetry never hard-fails on a missing file.
        return {
            "heart_total_volume_ml": {
                "normal_max": 900.0, "mild": 1000.0, "moderate": 1150.0, "severe": 1350.0,
                "note": "Approximate adult whole-heart CT segmentation volume; educational proxy only.",
            }
        }


# ---------------------------------------------------------------------------
# Minimal NIfTI reader (label-map masks). numpy only.
# ---------------------------------------------------------------------------
_NIFTI_DATATYPES = {
    2: np.uint8, 4: np.int16, 8: np.int32, 16: np.float32,
    64: np.float64, 256: np.int8, 512: np.uint16, 768: np.uint32, 1024: np.int64,
}


@dataclass
class NiftiVolume:
    data: np.ndarray            # integer label-map (we round/cast)
    spacing_mm: tuple[float, float, float]
    shape: tuple[int, ...]


def read_nifti_labelmap(file_bytes: bytes) -> NiftiVolume:
    """Parse a NIfTI-1 (single-file `n+1`) volume into an integer label-map.

    Handles gzip (`.nii.gz`) transparently and both byte orders. Raises
    ValueError on anything that isn't a usable NIfTI-1 volume — callers wrap
    this in a fail-safe.
    """
    if file_bytes[:2] == b"\x1f\x8b":  # gzip magic
        file_bytes = gzip.decompress(file_bytes)
    if len(file_bytes) < 352:
        raise ValueError("buffer too small to be a NIfTI-1 volume")

    # Determine endianness from sizeof_hdr (must be 348).
    for endian in ("<", ">"):
        sizeof_hdr = struct.unpack(endian + "i", file_bytes[0:4])[0]
        if sizeof_hdr == 348:
            break
    else:
        raise ValueError("not a NIfTI-1 header (sizeof_hdr != 348)")

    magic = file_bytes[344:348]
    if magic not in (b"n+1\x00", b"ni1\x00"):
        raise ValueError(f"unexpected NIfTI magic {magic!r}")
    if magic == b"ni1\x00":
        raise ValueError("two-file NIfTI (ni1) not supported; provide single-file n+1 .nii/.nii.gz")

    dim = struct.unpack(endian + "8h", file_bytes[40:56])
    ndim = dim[0]
    if not (1 <= ndim <= 7):
        raise ValueError(f"implausible NIfTI ndim={ndim}")
    shape = tuple(int(d) for d in dim[1:1 + ndim])

    datatype = struct.unpack(endian + "h", file_bytes[70:72])[0]
    pixdim = struct.unpack(endian + "8f", file_bytes[76:108])
    spacing = tuple(abs(float(p)) for p in pixdim[1:4])
    if len(spacing) < 3:
        spacing = tuple(list(spacing) + [1.0] * (3 - len(spacing)))
    spacing = (spacing[0] or 1.0, spacing[1] or 1.0, spacing[2] or 1.0)

    vox_offset = int(struct.unpack(endian + "f", file_bytes[108:112])[0]) or 352
    np_dtype = _NIFTI_DATATYPES.get(datatype)
    if np_dtype is None:
        raise ValueError(f"unsupported NIfTI datatype code {datatype}")

    count = 1
    for s in shape:
        count *= s
    raw = np.frombuffer(file_bytes, dtype=np.dtype(np_dtype).newbyteorder(endian),
                        count=count, offset=vox_offset)
    arr = raw.reshape(shape, order="F")  # NIfTI is column-major (dim[1] fastest)
    # Round float label-maps to nearest int; cast to a signed int label array.
    labels = np.rint(arr).astype(np.int32)
    return NiftiVolume(data=labels, spacing_mm=spacing, shape=shape)


# ---------------------------------------------------------------------------
# Volumetry
# ---------------------------------------------------------------------------
def label_volumes_ml(
    mask: np.ndarray,
    spacing_mm: tuple[float, float, float],
    label_names: Optional[dict[int, str]] = None,
) -> dict[str, dict[str, Any]]:
    """Deterministic per-label volume: voxel_count × ∏ spacing / 1000 (mL)."""
    voxel_volume_mm3 = float(spacing_mm[0]) * float(spacing_mm[1]) * float(spacing_mm[2])
    names = label_names or CARDIAC_LABELS
    ids, counts = np.unique(mask, return_counts=True)
    out: dict[str, dict[str, Any]] = {}
    for label_id, voxel_count in zip(ids.tolist(), counts.tolist()):
        if label_id == 0:  # background
            continue
        name = names.get(int(label_id), f"label_{int(label_id)}")
        out[name] = {
            "label_id": int(label_id),
            "voxel_count": int(voxel_count),
            "volume_ml": round(voxel_count * voxel_volume_mm3 / 1000.0, 2),
            "formula": "voxel_count × ∏ spacing / 1000",
        }
    return out


# ---------------------------------------------------------------------------
# Abnormality observations (educational, simulation-only)
# ---------------------------------------------------------------------------
def _severity_for(volume_ml: float, ref: dict[str, Any]) -> Optional[str]:
    if volume_ml >= ref.get("severe", math.inf):
        return "severe"
    if volume_ml >= ref.get("moderate", math.inf):
        return "moderate"
    if volume_ml >= ref.get("mild", math.inf):
        return "mild"
    if volume_ml > ref.get("normal_max", math.inf):
        return "mild"
    return None


def derive_ct_abnormalities(
    volumes: dict[str, dict[str, Any]],
    *,
    output_labels: Optional[list[int]] = None,
    provenance: Optional[dict[str, Any]] = None,
    reference_ranges: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Map structure volumes to a small set of educational observations.

    Honest and bounded: only a **global cardiomegaly proxy** from the single
    heart label, plus presence/absence notes. Never claims chamber EF, regional
    wall motion, or a diagnosis.
    """
    ref = reference_ranges or _load_reference_ranges()
    prov = dict(provenance or {})
    prov.setdefault("source", "vista3d")
    prov.setdefault("method", "ct_segmentation")
    findings: list[dict[str, Any]] = []

    heart = volumes.get("heart")
    heart_present = heart is not None and (output_labels is None or HEART_LABEL in output_labels)

    if not heart_present:
        findings.append({
            "id": "ct_heart_absent",
            "title": "Heart not segmented from CT",
            "region": "Heart",
            "severity": "info",
            "summary": ("CT segmentation returned no heart label (115) — the heart was likely "
                        "outside the scan field of view. No CT-derived cardiac volume is available; "
                        "no value invented."),
            "metric": None,
            "codes": [{"system": "VISTA-3D label", "code": "115", "label": "heart (absent)"}],
            "educational": True,
            "provenance": prov,
        })
    else:
        hv = float(heart["volume_ml"])
        hr_ref = ref.get("heart_total_volume_ml", {})
        sev = _severity_for(hv, hr_ref)
        if sev:
            findings.append({
                "id": "ct_cardiomegaly_proxy",
                "title": f"Enlarged whole-heart CT volume ({hv:.0f} mL)",
                "region": "Heart (global)",
                "severity": sev,
                "summary": (
                    f"Simulation: segmented whole-heart CT volume ({hv:.0f} mL) exceeds the "
                    f"educational reference (normal ≤ {hr_ref.get('normal_max', '?')} mL), a coarse "
                    f"volumetric cardiomegaly proxy. VISTA-3D emits the heart as one label, so this "
                    f"is a global proxy only — not a chamber EF, wall-motion, or scar assessment, and "
                    f"not a diagnosis."
                ),
                "metric": f"whole-heart CT volume {hv:.0f} mL",
                "codes": [
                    {"system": "VISTA-3D label", "code": "115", "label": "heart"},
                    {"system": "observation", "code": "cardiomegaly_proxy", "label": "volumetric proxy"},
                ],
                "educational": True,
                "provenance": {**prov, "label": "heart (115)",
                               "formula": "voxel_count × ∏ spacing / 1000"},
            })
        else:
            findings.append({
                "id": "ct_heart_within_reference",
                "title": f"Whole-heart CT volume within educational reference ({hv:.0f} mL)",
                "region": "Heart (global)",
                "severity": "info",
                "summary": (f"Simulation: segmented whole-heart CT volume ({hv:.0f} mL) is within the "
                            f"educational reference range (≤ {hr_ref.get('normal_max', '?')} mL)."),
                "metric": f"whole-heart CT volume {hv:.0f} mL",
                "codes": [{"system": "VISTA-3D label", "code": "115", "label": "heart"}],
                "educational": True,
                "provenance": {**prov, "label": "heart (115)"},
            })

    aorta = volumes.get("aorta")
    if aorta is not None:
        findings.append({
            "id": "ct_aorta_present",
            "title": f"Aorta segmented ({float(aorta['volume_ml']):.0f} mL in FOV)",
            "region": "Aorta",
            "severity": "info",
            "summary": ("Simulation: aorta segmented from CT. Volume depends on how much of the aorta "
                        "is in the scan field of view, so it is reported for context, not used as an "
                        "abnormality threshold."),
            "metric": f"aorta CT volume {float(aorta['volume_ml']):.0f} mL (FOV-dependent)",
            "codes": [{"system": "VISTA-3D label", "code": "6", "label": "aorta"}],
            "educational": True,
            "provenance": {**prov, "label": "aorta (6)"},
        })

    return findings


@dataclass
class CtAnalysis:
    status: str
    volumes: dict[str, dict[str, Any]] = field(default_factory=dict)
    abnormalities: list[dict[str, Any]] = field(default_factory=list)
    output_labels: list[int] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def analyze_mask_bytes(
    mask_bytes: bytes,
    *,
    metadata: Optional[dict[str, Any]] = None,
    provenance: Optional[dict[str, Any]] = None,
) -> CtAnalysis:
    """Full deterministic mask -> volumes -> abnormalities. Never raises."""
    warnings: list[str] = []
    try:
        vol = read_nifti_labelmap(mask_bytes)
    except Exception as exc:
        return CtAnalysis(status="unreadable_mask",
                          warnings=[f"CT mask not readable: {type(exc).__name__}: {exc}"])

    meta = metadata or {}
    # Prefer metadata's label-name map + spacing when present (richer than NIfTI header).
    label_names = {int(k): str(v) for k, v in (meta.get("output_label_names") or {}).items()} or CARDIAC_LABELS
    spacing = vol.spacing_mm
    meta_spacing = meta.get("input_spacing")
    if isinstance(meta_spacing, (list, tuple)) and len(meta_spacing) >= 3:
        try:
            spacing = (float(meta_spacing[0]), float(meta_spacing[1]), float(meta_spacing[2]))
        except (TypeError, ValueError):
            warnings.append("metadata input_spacing malformed — using NIfTI header spacing")

    volumes = label_volumes_ml(vol.data, spacing, label_names)
    output_labels = meta.get("output_labels")
    if not isinstance(output_labels, list):
        output_labels = [v["label_id"] for v in volumes.values()]

    prov = {
        "source": "vista3d",
        "method": "ct_segmentation",
        "model": f"{meta.get('model_name', 'MONAI VISTA-3D')} {meta.get('model_version', '')}".strip(),
        "spacing_mm": list(spacing),
        "shape": list(vol.shape),
    }
    if provenance:
        prov.update(provenance)

    abn = derive_ct_abnormalities(volumes, output_labels=output_labels, provenance=prov)
    return CtAnalysis(status="analyzed", volumes=volumes, abnormalities=abn,
                      output_labels=list(output_labels), provenance=prov, warnings=warnings)
