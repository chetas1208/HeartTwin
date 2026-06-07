#!/usr/bin/env python3
"""Local smoke test for HeartTwin Lab.

Runs the real pipeline in-process (no HTTP server required) against the
baseline fixture: health/config snapshot, create case, extract, operate,
simulate recovery. Prints a summary and exits non-zero on failure.

If an HTTP base URL is provided via E2E_BASE_URL, it instead hits the live API.

Usage:
  python scripts/run_local_smoke.py
  E2E_BASE_URL=http://localhost:3001 python scripts/run_local_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / "fixtures" / "hearttwin" / "manual_baseline.json"


def _load_baseline_vitals() -> dict:
    data = json.loads(FIXTURE.read_text())
    return data["user_vitals"]


async def _run_in_process() -> int:
    from python.hearttwin.orchestrator import (
        run_extraction_pipeline,
        run_operation_pipeline,
        run_recovery_pipeline,
    )
    from python.hearttwin.schemas import CaseRecord
    from python.hearttwin.tools.env_config import validate_environment

    failures: list[str] = []
    vitals = _load_baseline_vitals()

    env = validate_environment()
    print(f"[config] openai_configured={env['openai']['configured']} "
          f"weave={env['weave']['configured']} redis={env['redis']['configured']} "
          f"vista3d_enabled={env['vista3d']['enabled']}")

    case = CaseRecord(status="created")
    print(f"[case] created {case.case_id}")

    _, case = await run_extraction_pipeline(case=case, files=[], user_vitals=vitals)
    if not case.validated_fields:
        failures.append("extraction produced no validated fields")
    print(f"[extract] validated_fields={len(case.validated_fields)}")

    _, viz, report = await run_operation_pipeline(case=case)
    summary = (viz or {}).get("summary", {})
    ef = summary.get("ef_pct")
    co = summary.get("cardiac_output_l_min")
    print(f"[operate] EF={ef} CO={co} has_pv_loop={bool(viz.get('pv_loop'))}")
    if not viz.get("pv_loop"):
        failures.append("operation produced no PV loop")
    if ef is None:
        failures.append("operation produced no EF")

    _, scenarios, _ = await run_recovery_pipeline(case=case)
    print(f"[recovery] scenarios={len(scenarios)}")
    if not (2 <= len(scenarios) <= 4):
        failures.append(f"recovery produced {len(scenarios)} scenarios (expected 2-4)")

    eval_scores = report.get("eval_scores", {})
    print(f"[evaluator] overall_score={eval_scores.get('overall_score')}")
    if "overall_score" not in eval_scores:
        failures.append("evaluator produced no overall_score")

    if failures:
        print("\nSMOKE FAILURES:")
        for f in failures:
            print(f"  - {f}")
        print("\nRESULT: FAILED")
        return 1
    print("\nRESULT: OK")
    return 0


def _run_http(base_url: str) -> int:
    import httpx

    api = base_url.rstrip("/")
    if not api.endswith("/api/v1"):
        api = api + "/api/v1"
    vitals = _load_baseline_vitals()
    failures: list[str] = []

    with httpx.Client(timeout=60.0) as client:
        h = client.get(f"{api}/health")
        print(f"[health] {h.status_code}")
        if h.status_code != 200:
            failures.append("health not 200")

        cfg = client.get(f"{api}/config")
        print(f"[config] {cfg.status_code}")
        if cfg.status_code != 200:
            failures.append("config not 200")

        case_resp = client.post(f"{api}/cases", json={})
        case_id = case_resp.json().get("case_id")
        print(f"[case] {case_id}")
        if not case_id:
            print("\nRESULT: FAILED (no case id)")
            return 1

        ext = client.post(f"{api}/cases/{case_id}/extract", json={"file_ids": [], "user_vitals": vitals})
        print(f"[extract] {ext.status_code}")
        op = client.post(f"{api}/cases/{case_id}/operate", json={})
        print(f"[operate] {op.status_code}")
        rec = client.post(f"{api}/cases/{case_id}/simulate-recovery", json={})
        print(f"[recovery] {rec.status_code}")
        for label, resp in (("extract", ext), ("operate", op), ("recovery", rec)):
            if resp.status_code != 200:
                failures.append(f"{label} returned {resp.status_code}")

    if failures:
        print("\nSMOKE FAILURES:")
        for f in failures:
            print(f"  - {f}")
        print("\nRESULT: FAILED")
        return 1
    print("\nRESULT: OK")
    return 0


def main() -> int:
    base_url = os.environ.get("E2E_BASE_URL")
    if base_url:
        print(f"== HeartTwin smoke (HTTP {base_url}) ==")
        return _run_http(base_url)
    print("== HeartTwin smoke (in-process) ==")
    return asyncio.run(_run_in_process())


if __name__ == "__main__":
    raise SystemExit(main())
