"""End-to-end CT path: extraction artifact -> state -> findings.

Mocks only the VISTA-3D *network* submit/poll/fetch; the deterministic mask
volumetry + abnormality derivation run for real against a synthetic NIfTI mask.
"""
from __future__ import annotations

import numpy as np
import pytest

from python.hearttwin.agents import extraction_agent
from python.hearttwin.agents.state_builder_agent import run_state_builder_agent
from python.hearttwin.tools.ct_volumetry import HEART_LABEL, analyze_mask_bytes
from python.hearttwin.tools.cardiac_findings import derive_findings
from python.hearttwin.tools.nifti_write import write_nifti_labelmap


def _enlarged_heart_mask_bytes(volume_ml: float = 1400.0, spacing=(1.5, 1.5, 1.5)) -> bytes:
    vox = int(volume_ml * 1000 / (spacing[0] * spacing[1] * spacing[2]))
    grid = int(round(vox ** (1 / 3))) + 4
    m = np.zeros((grid, grid, grid), dtype=np.uint16)
    m.reshape(-1)[:vox] = HEART_LABEL
    return write_nifti_labelmap(m, spacing_mm=spacing)


@pytest.mark.asyncio
async def test_ct_flows_from_extraction_to_findings(monkeypatch):
    mask_bytes = _enlarged_heart_mask_bytes()

    async def fake_segment(file_bytes, filename, *, file_id=None, **kw):
        # Bypass the network; run the real deterministic analysis on the mask.
        analysis = analyze_mask_bytes(
            file_bytes, metadata={"output_labels": [HEART_LABEL],
                                  "model_name": "MONAI VISTA-3D", "model_version": "0.5.8"})
        return {
            "source": "vista3d", "method": "ct_segmentation", "filename": filename,
            "file_id": file_id, "job_id": "test-job", "status": analysis.status,
            "volumes": analysis.volumes, "abnormalities": analysis.abnormalities,
            "output_labels": analysis.output_labels, "provenance": analysis.provenance,
            "warnings": analysis.warnings,
        }

    monkeypatch.setattr(extraction_agent, "segment_ct_and_analyze", fake_segment)

    # 1. Extraction routes the CT and emits the artifact.
    resp = await extraction_agent.run_extraction_agent(
        files=[{"file_id": "ct1", "filename": "scan.nii.gz",
                "content_type": "application/octet-stream", "bytes": mask_bytes}],
        user_vitals=None, case_id="caseX",
    )
    fields = resp.outputs["extracted_fields"]
    assert "__ct_segmentation__" in fields
    assert fields["__ct_segmentation__"]["value"]["status"] == "analyzed"

    # 2. State builder attaches it + records provenance.
    _, state = await run_state_builder_agent(validated_fields=fields, case_id="caseX")
    assert state.ct_segmentation is not None
    assert any(e.method == "ct_segmentation" for e in state.source_map)

    # 3. Findings layer surfaces the CT abnormality + honest imaging_source.
    out = derive_findings(state.model_dump(mode="json"), {"summary": {}})
    assert out["imaging_source"] == "vista3d_segmentation"
    ct_finding = next(f for f in out["findings"] if f["id"] == "ct_cardiomegaly_proxy")
    assert ct_finding["severity"] == "severe"
    assert "not a diagnosis" in ct_finding["summary"].lower()


@pytest.mark.asyncio
async def test_ct_disabled_degrades_without_crash(monkeypatch):
    async def fake_segment(file_bytes, filename, *, file_id=None, **kw):
        return {"source": "vista3d", "method": "ct_segmentation", "status": "disabled",
                "note": "VISTA-3D segmentation is disabled.", "warnings": [], "job_id": None}

    monkeypatch.setattr(extraction_agent, "segment_ct_and_analyze", fake_segment)
    resp = await extraction_agent.run_extraction_agent(
        files=[{"file_id": "ct1", "filename": "scan.nii.gz",
                "content_type": "application/octet-stream", "bytes": b"x"}],
        user_vitals=None, case_id="caseX",
    )
    # Still a successful agent run; artifact carries the disabled status, no crash.
    assert "__ct_segmentation__" in resp.outputs["extracted_fields"]
    assert resp.outputs["extracted_fields"]["__ct_segmentation__"]["value"]["status"] == "disabled"
