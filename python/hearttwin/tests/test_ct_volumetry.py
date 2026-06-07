"""Tests for deterministic CT segmentation volumetry + abnormality flags."""
from __future__ import annotations

import numpy as np

from python.hearttwin.tools.ct_volumetry import (
    AORTA_LABEL,
    HEART_LABEL,
    analyze_mask_bytes,
    derive_ct_abnormalities,
    label_volumes_ml,
    read_nifti_labelmap,
)
from python.hearttwin.tools.nifti_write import write_nifti_labelmap


def _mask_with_heart(voxels: int, spacing=(1.5, 1.5, 1.5), aorta_voxels: int = 0) -> np.ndarray:
    """Build a tiny label-map with a known heart voxel count."""
    grid = int(round((voxels + aorta_voxels) ** (1 / 3))) + 6
    m = np.zeros((grid, grid, grid), dtype=np.uint16)
    flat = m.reshape(-1)
    flat[:voxels] = HEART_LABEL
    flat[voxels:voxels + aorta_voxels] = AORTA_LABEL
    return flat.reshape(m.shape)


def test_volume_formula_is_exact():
    spacing = (2.0, 2.0, 2.0)  # 8 mm^3 per voxel -> 0.008 mL
    mask = _mask_with_heart(1000, spacing=spacing)  # 1000 * 0.008 = 8.0 mL
    vols = label_volumes_ml(mask, spacing)
    assert vols["heart"]["voxel_count"] == 1000
    assert vols["heart"]["volume_ml"] == 8.0
    assert vols["heart"]["label_id"] == HEART_LABEL


def test_nifti_roundtrip_preserves_labels_and_spacing():
    spacing = (1.5, 1.5, 1.5)
    mask = _mask_with_heart(500, spacing=spacing, aorta_voxels=120)
    blob = write_nifti_labelmap(mask, spacing_mm=spacing)
    vol = read_nifti_labelmap(blob)
    assert vol.shape == mask.shape
    assert vol.spacing_mm == spacing
    # label set preserved
    assert set(np.unique(vol.data).tolist()) == {0, AORTA_LABEL, HEART_LABEL}
    assert int((vol.data == HEART_LABEL).sum()) == 500
    assert int((vol.data == AORTA_LABEL).sum()) == 120


def test_cardiomegaly_proxy_flags_enlarged_heart():
    # voxel volume 3.375 mm^3 (1.5^3). Want ~1400 mL (severe) -> ~414815 voxels.
    spacing = (1.5, 1.5, 1.5)
    vox = int(1400 * 1000 / (1.5 ** 3))
    vols = label_volumes_ml(_mask_with_heart(vox, spacing=spacing), spacing)
    abn = derive_ct_abnormalities(vols, output_labels=[HEART_LABEL])
    ids = {a["id"]: a for a in abn}
    assert "ct_cardiomegaly_proxy" in ids
    assert ids["ct_cardiomegaly_proxy"]["severity"] == "severe"
    assert ids["ct_cardiomegaly_proxy"]["educational"] is True
    # safety framing: explicitly labels itself a non-diagnostic simulation proxy
    summary = ids["ct_cardiomegaly_proxy"]["summary"].lower()
    assert "not a diagnosis" in summary and "proxy" in summary


def test_normal_heart_within_reference():
    spacing = (1.5, 1.5, 1.5)
    vox = int(700 * 1000 / (1.5 ** 3))  # 700 mL, within reference
    vols = label_volumes_ml(_mask_with_heart(vox, spacing=spacing), spacing)
    abn = derive_ct_abnormalities(vols, output_labels=[HEART_LABEL])
    ids = {a["id"] for a in abn}
    assert "ct_heart_within_reference" in ids
    assert "ct_cardiomegaly_proxy" not in ids


def test_heart_absent_when_out_of_fov():
    abn = derive_ct_abnormalities({}, output_labels=[])
    ids = {a["id"] for a in abn}
    assert "ct_heart_absent" in ids


def test_analyze_mask_bytes_end_to_end_and_failsafe():
    spacing = (1.5, 1.5, 1.5)
    vox = int(1200 * 1000 / (1.5 ** 3))  # moderate
    blob = write_nifti_labelmap(_mask_with_heart(vox, spacing=spacing), spacing_mm=spacing)
    res = analyze_mask_bytes(blob, metadata={"output_labels": [HEART_LABEL],
                                             "model_name": "MONAI VISTA-3D", "model_version": "0.5.8"})
    assert res.status == "analyzed"
    assert res.volumes["heart"]["volume_ml"] > 1000
    assert any(a["id"] == "ct_cardiomegaly_proxy" for a in res.abnormalities)
    assert res.provenance["source"] == "vista3d"

    # fail-safe on garbage
    bad = analyze_mask_bytes(b"not a nifti at all")
    assert bad.status == "unreadable_mask"
    assert bad.warnings
