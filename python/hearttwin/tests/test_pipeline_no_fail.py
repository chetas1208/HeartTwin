"""Adversarial no-fail review: on VALID input with the default policy, no agent
stage should ever come back 'failed'/'error'. Agents must degrade with an
explained warning (population priors), never hard-fail.

Intentional gates are out of scope here and covered elsewhere: the intake
safety block on unsafe *requests* (test_api_routes / test_safety_language) and
the opt-in `missing_value_policy="refuse"` strict mode.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from python.hearttwin.api import app

from .conftest import load_fixture_json

client = TestClient(app)

BASELINE = load_fixture_json("manual_baseline.json")["user_vitals"]
PARTIAL = load_fixture_json("manual_partial_data.json")["user_vitals"]
REDUCED = load_fixture_json("manual_reduced_function.json")["user_vitals"]

# Valid but stressful inputs (extreme-yet-physiological, sparse, and empty).
SEVERE_LOW_EF = {
    "heart_rate_bpm": 110.0,
    "systolic_bp_mmhg": 95.0,
    "diastolic_bp_mmhg": 70.0,
    "edv_ml": 240.0,
    "esv_ml": 200.0,  # EF ~17%
}
SPARSE = {"heart_rate_bpm": 80.0}
EMPTY: dict = {}

CASES = {
    "baseline": BASELINE,
    "partial": PARTIAL,
    "reduced": REDUCED,
    "severe_low_ef": SEVERE_LOW_EF,
    "sparse": SPARSE,
    "empty": EMPTY,
}

FAIL_STATUSES = {"failed", "error", "blocked"}


def _stage_statuses(stage_results: list[dict]) -> list[tuple[str, str]]:
    out = []
    for r in stage_results:
        name = r.get("agent_name") or r.get("agent_id") or r.get("stage") or "?"
        out.append((str(name), str(r.get("status", "")).lower()))
    return out


@pytest.mark.parametrize("label", list(CASES))
def test_operate_has_no_failed_stage(label: str) -> None:
    vitals = CASES[label]
    cid = client.post("/api/v1/cases", json={}).json()["case_id"]

    ext = client.post(
        f"/api/v1/cases/{cid}/extract",
        json={"file_ids": [], "user_vitals": vitals},
    )
    assert ext.status_code == 200, f"[{label}] extract failed: {ext.text}"

    op = client.post(f"/api/v1/cases/{cid}/operate", json={})
    assert op.status_code == 200, f"[{label}] operate failed: {op.text}"
    body = op.json()

    statuses = _stage_statuses(body.get("stage_results", []))
    failed = [(n, s) for n, s in statuses if s in FAIL_STATUSES]
    assert not failed, f"[{label}] operate produced failed stages: {failed}"

    # Recovery should also complete without a failed stage.
    rec = client.post(f"/api/v1/cases/{cid}/simulate-recovery", json={})
    assert rec.status_code == 200, f"[{label}] recovery failed: {rec.text}"
    rec_failed = [
        (n, s) for n, s in _stage_statuses(rec.json().get("stage_results", []))
        if s in FAIL_STATUSES
    ]
    assert not rec_failed, f"[{label}] recovery produced failed stages: {rec_failed}"


@pytest.mark.parametrize("label", list(CASES))
def test_operate_findings_present_and_safe(label: str) -> None:
    """Every operate run carries the cardiac_findings payload (even if empty)."""
    cid = client.post("/api/v1/cases", json={}).json()["case_id"]
    client.post(
        f"/api/v1/cases/{cid}/extract",
        json={"file_ids": [], "user_vitals": CASES[label]},
    )
    op = client.post(f"/api/v1/cases/{cid}/operate", json={}).json()
    findings = op["visualization"]["cardiac_findings"]
    assert "findings" in findings
    assert findings["segment_model"] == "AHA 17-segment"
