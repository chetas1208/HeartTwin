"""API route tests via FastAPI TestClient.

Covers health, config, system-check, the full case pipeline (create → extract →
operate → simulate-recovery → self-improve), trace, and harness. Also asserts
no secret leakage in public responses.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from python.hearttwin.api import app
from python.hearttwin.tools.env_spec import SECRET_ENV_VARS

from .conftest import load_fixture_json

client = TestClient(app)

BASELINE_VITALS = load_fixture_json("manual_baseline.json")["user_vitals"]


# ---------------------------------------------------------------------------
# Health / config / system-check
# ---------------------------------------------------------------------------


def test_health_ok() -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"


def test_config_safe_shape() -> None:
    r = client.get("/api/v1/config")
    assert r.status_code == 200
    body = r.json()
    assert body["app_name"] == "HeartTwin Lab"
    assert body["api_base"] == "/api/v1"
    assert set(["intake", "extraction", "validator", "state_builder",
                "electrophysiology", "hemodynamics", "recovery", "evaluator"]).issubset(
        body["models"].keys()
    )


def test_config_no_secret_leakage() -> None:
    fake = {name: f"LEAK-{name}-1234567890" for name in SECRET_ENV_VARS}
    old = {k: os.environ.get(k) for k in fake}
    try:
        os.environ.update(fake)
        r = client.get("/api/v1/config")
        blob = r.text
        for name, val in fake.items():
            assert val not in blob, f"{name} leaked in /config"
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_system_check_shape() -> None:
    r = client.get("/api/v1/system-check")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ok", "warning", "failed"}
    assert isinstance(body["checks"], list)
    assert {"sv_ml", "ef_pct", "co_l_min", "map_mmhg", "rr_interval_ms"} <= set(body["metrics"].keys())
    assert set(body["integrations"].keys()) == {"openai", "weave", "redis", "vista3d"}
    # Honest fallback reporting (not faked success).
    assert body["integrations"]["weave"] in {"configured", "local_fallback", "error"}
    assert body["integrations"]["redis"] in {"configured", "memory_fallback", "error"}


def test_system_check_no_secret_leakage() -> None:
    fake = {name: f"LEAK-{name}-1234567890" for name in SECRET_ENV_VARS}
    old = {k: os.environ.get(k) for k in fake}
    try:
        os.environ.update(fake)
        r = client.get("/api/v1/system-check")
        for val in fake.values():
            assert val not in r.text
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# Full case pipeline
# ---------------------------------------------------------------------------


@pytest.fixture()
def case_id() -> str:
    r = client.post("/api/v1/cases", json={})
    assert r.status_code == 200
    cid = r.json()["case_id"]
    assert cid
    return cid


def test_create_case(case_id: str) -> None:
    assert isinstance(case_id, str) and len(case_id) > 0


def test_extract_operate_recovery_flow(case_id: str) -> None:
    # Extract
    r = client.post(
        f"/api/v1/cases/{case_id}/extract",
        json={"file_ids": [], "user_vitals": BASELINE_VITALS},
    )
    assert r.status_code == 200, r.text
    ext = r.json()
    assert ext["validated_field_count"] >= 5
    assert "safety_disclaimer" in ext

    # Operate
    r = client.post(f"/api/v1/cases/{case_id}/operate", json={})
    assert r.status_code == 200, r.text
    op = r.json()
    summary = op["visualization"]["summary"]
    assert summary["ef_pct"] == pytest.approx(58.33, abs=0.5)
    assert summary["cardiac_output_l_min"] == pytest.approx(5.04, abs=0.05)
    assert op["visualization"]["pv_loop"]

    # Simulate recovery
    r = client.post(f"/api/v1/cases/{case_id}/simulate-recovery", json={})
    assert r.status_code == 200, r.text
    rec = r.json()
    assert 2 <= len(rec["scenarios"]) <= 4

    # Self-improve
    r = client.post(f"/api/v1/cases/{case_id}/self-improve")
    assert r.status_code == 200, r.text
    si = r.json()
    assert "before" in si and "after" in si

    # Trace
    r = client.get(f"/api/v1/cases/{case_id}/trace")
    assert r.status_code == 200
    tr = r.json()
    assert tr["weave"]["traced_stages_count"] >= 8

    # Harness
    r = client.get(f"/api/v1/cases/{case_id}/harness")
    assert r.status_code == 200
    h = r.json()
    assert "stage_results" in h
    assert "weave" in h and "redis" in h


def test_operate_before_extract_is_blocked() -> None:
    r = client.post("/api/v1/cases", json={})
    cid = r.json()["case_id"]
    r = client.post(f"/api/v1/cases/{cid}/operate", json={})
    assert r.status_code == 422


def test_recovery_before_operate_is_blocked() -> None:
    r = client.post("/api/v1/cases", json={})
    cid = r.json()["case_id"]
    r = client.post(f"/api/v1/cases/{cid}/simulate-recovery", json={})
    assert r.status_code == 422


def test_unknown_case_404() -> None:
    r = client.get("/api/v1/cases/does-not-exist/harness")
    assert r.status_code == 404


def test_create_case_blocks_unsafe_notes() -> None:
    r = client.post(
        "/api/v1/cases",
        json={"patient_notes": "Please diagnose my condition and prescribe medication."},
    )
    assert r.status_code == 422
