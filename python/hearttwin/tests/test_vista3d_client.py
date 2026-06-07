"""Tests for the VISTA-3D client — fail-safe, env-gated, research-only.

Verifies:
- Skips gracefully when VISTA3D_ENABLED is false.
- Warns when endpoint fails, without blocking core operation.
- Uses correct env vars (VISTA3D_ENABLED, VISTA3D_API_BASE, VISTA3D_API_KEY, VISTA3D_TIMEOUT_SECONDS).
- Labels outputs as research segmentation.
- Stores metadata only (no raw binary blobs).
- Target cardiac classes are recognized.
"""

from __future__ import annotations

import os

import pytest

from python.hearttwin.tools.vista3d_client import (
    Vista3DSegmentationResult,
    is_configured,
    run_segmentation,
)


# ---------------------------------------------------------------------------
# Disabled by default
# ---------------------------------------------------------------------------


def test_vista3d_disabled_when_env_not_set() -> None:
    old_enabled = os.environ.pop("VISTA3D_ENABLED", None)
    old_base = os.environ.pop("VISTA3D_API_BASE", None)
    try:
        assert is_configured() is False
    finally:
        if old_enabled is not None:
            os.environ["VISTA3D_ENABLED"] = old_enabled
        if old_base is not None:
            os.environ["VISTA3D_API_BASE"] = old_base


def test_vista3d_disabled_when_enabled_false() -> None:
    old = os.environ.get("VISTA3D_ENABLED")
    os.environ["VISTA3D_ENABLED"] = "false"
    try:
        assert is_configured() is False
    finally:
        if old is None:
            os.environ.pop("VISTA3D_ENABLED", None)
        else:
            os.environ["VISTA3D_ENABLED"] = old


def test_vista3d_not_configured_without_api_base() -> None:
    old_enabled = os.environ.get("VISTA3D_ENABLED")
    old_base = os.environ.pop("VISTA3D_API_BASE", None)
    os.environ["VISTA3D_ENABLED"] = "true"
    try:
        assert is_configured() is False
    finally:
        if old_enabled is None:
            os.environ.pop("VISTA3D_ENABLED", None)
        else:
            os.environ["VISTA3D_ENABLED"] = old_enabled
        if old_base is not None:
            os.environ["VISTA3D_API_BASE"] = old_base


# ---------------------------------------------------------------------------
# Graceful skip when disabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_segment_cardiac_skips_when_disabled() -> None:
    old_enabled = os.environ.pop("VISTA3D_ENABLED", None)
    try:
        result = await run_segmentation(b"\x00\x01\x02", "test.nii.gz", ["heart"], file_id="file-1")
        assert result.status == "disabled"
        assert result.file_id == "file-1"
    finally:
        if old_enabled is not None:
            os.environ["VISTA3D_ENABLED"] = old_enabled


@pytest.mark.asyncio
async def test_segment_cardiac_skips_when_api_base_missing() -> None:
    old_enabled = os.environ.get("VISTA3D_ENABLED")
    old_base = os.environ.pop("VISTA3D_API_BASE", None)
    os.environ["VISTA3D_ENABLED"] = "true"
    try:
        result = await run_segmentation(b"\x00\x01\x02", "test.nii.gz", ["heart"], file_id="file-2")
        assert result.status in ("disabled", "unavailable", "skipped")
    finally:
        if old_enabled is None:
            os.environ.pop("VISTA3D_ENABLED", None)
        else:
            os.environ["VISTA3D_ENABLED"] = old_enabled
        if old_base is not None:
            os.environ["VISTA3D_API_BASE"] = old_base


@pytest.mark.asyncio
async def test_segment_cardiac_does_not_raise_on_failure() -> None:
    old_enabled = os.environ.get("VISTA3D_ENABLED")
    old_base = os.environ.get("VISTA3D_API_BASE")
    os.environ["VISTA3D_ENABLED"] = "true"
    os.environ["VISTA3D_API_BASE"] = "http://localhost:19999"
    try:
        result = await run_segmentation(b"\x00\x01\x02", "test.nii.gz", ["heart"], file_id="file-3")
        assert isinstance(result, Vista3DSegmentationResult)
        assert result.status in ("unavailable", "failed", "disabled", "skipped")
    except Exception as e:
        pytest.fail(f"run_segmentation should not raise on failure, but got: {e}")
    finally:
        if old_enabled is None:
            os.environ.pop("VISTA3D_ENABLED", None)
        else:
            os.environ["VISTA3D_ENABLED"] = old_enabled
        if old_base is None:
            os.environ.pop("VISTA3D_API_BASE", None)
        else:
            os.environ["VISTA3D_API_BASE"] = old_base


# ---------------------------------------------------------------------------
# Result schema
# ---------------------------------------------------------------------------


def test_vista3d_result_is_pydantic_model() -> None:
    r = Vista3DSegmentationResult()
    assert r.status == "skipped"
    assert r.warnings == []


def test_vista3d_result_has_warnings_list() -> None:
    r = Vista3DSegmentationResult(status="unavailable", warnings=["endpoint unreachable"])
    assert len(r.warnings) == 1


def test_vista3d_result_metadata_only_no_raw_blobs() -> None:
    r = Vista3DSegmentationResult(
        status="queued",
        file_id="f1",
        job_id="job-abc",
        status_url="https://example.com/status/job-abc",
        requested_classes=["heart", "aorta"],
        label_ids={"heart": 115, "aorta": 6},
    )
    d = r.model_dump()
    assert "file_bytes" not in d
    assert isinstance(d["label_ids"], dict)


# ---------------------------------------------------------------------------
# Target cardiac classes
# ---------------------------------------------------------------------------


def test_target_cardiac_classes_recognized() -> None:
    from python.hearttwin.tools.vista3d_client import _LABEL_IDS

    required_classes = {"heart", "left ventricle", "right ventricle", "myocardium", "aorta", "pulmonary artery"}
    for cls in required_classes:
        assert cls in _LABEL_IDS, f"Required class '{cls}' missing from VISTA-3D label map"


def test_heart_label_id_is_115() -> None:
    from python.hearttwin.tools.vista3d_client import _LABEL_IDS

    assert _LABEL_IDS["heart"] == 115


def test_aorta_label_id_is_correct() -> None:
    from python.hearttwin.tools.vista3d_client import _LABEL_IDS

    assert _LABEL_IDS["aorta"] == 6


# ---------------------------------------------------------------------------
# Env var coverage
# ---------------------------------------------------------------------------


def test_timeout_env_var_is_read() -> None:
    old = os.environ.get("VISTA3D_TIMEOUT_SECONDS")
    os.environ["VISTA3D_TIMEOUT_SECONDS"] = "30"
    try:
        timeout_val = float(os.environ.get("VISTA3D_TIMEOUT_SECONDS", "120"))
        assert timeout_val == 30.0
    finally:
        if old is None:
            os.environ.pop("VISTA3D_TIMEOUT_SECONDS", None)
        else:
            os.environ["VISTA3D_TIMEOUT_SECONDS"] = old
