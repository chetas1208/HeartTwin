#!/usr/bin/env python3
"""HeartTwin Lab — minimal meaningful benchmark.

Runs the REAL product code (no API keys, no network) against ground-truth cases
grounded in the public cardiac datasets HeartTwin references, and scores it:

  1. hemodynamics  (EchoNet-Dynamic / CAMUS / ACDC volumes)  -> SV / EF / CO / MAP
  2. ecg           (PTB-XL waveform + Bazett)                 -> heart rate / QTc
  3. extraction    (MIMIC-IV-Note-style synthetic reports)    -> field precision/recall
  4. safety        (adversarial vs benign prompts)            -> block accuracy

Each task imports the product's own deterministic functions, so a regression in
the engine moves the score. Pass/fail gates make it CI-usable.

Usage:
    python benchmark/run_benchmark.py            # human scorecard + results.json
    python benchmark/run_benchmark.py --json     # machine-readable JSON only

Exit code 0 if all gates pass, 1 otherwise.

Educational cardiac simulation only. Not for diagnosis or treatment decisions.
"""

from __future__ import annotations

import asyncio
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
CASES_DIR = HERE / "cases"
DATA_DIR = HERE / "data"

# Run against the actual product code in this repo.
sys.path.insert(0, str(REPO_ROOT))

from python.hearttwin.tools.cardiac_state import (  # noqa: E402
    compute_cardiac_output,
    compute_ejection_fraction,
    compute_map,
    compute_stroke_volume,
)
from python.hearttwin.tools.ecg_features import (  # noqa: E402
    analyze_waveform,
    compute_qtc_bazett,
)
from python.hearttwin.tools.pdf_extract import _extract_cardiac_values  # noqa: E402
from python.hearttwin.safety import check_request_safety, SafetyViolation  # noqa: E402
from python.hearttwin.orchestrator import run_full_pipeline  # noqa: E402


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_waveform(name: str) -> tuple[list[float], float]:
    """Return (signal, sampling_rate_hz) from a benchmark/data CSV."""
    path = DATA_DIR / name
    if not path.exists():  # fall back to the repo fixtures if data/ was trimmed
        path = REPO_ROOT / "fixtures" / "hearttwin" / name
    times, sig = [], []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            times.append(float(row["time_ms"]))
            sig.append(float(row["lead_ii_mv"]))
    fs = 1000.0 / (times[1] - times[0])
    return sig, fs


def within(actual: float, expected: float, tol: float) -> bool:
    return abs(actual - expected) <= tol


# --------------------------------------------------------------------------- #
# task 1: hemodynamics (deterministic formula engine)
# --------------------------------------------------------------------------- #
def run_hemodynamics() -> dict:
    cases = load_jsonl(CASES_DIR / "hemodynamics.jsonl")
    rows, errors = [], []
    passed = 0
    # Tight tolerances: these are exact-formula checks meant to catch drift.
    tol = {"sv_ml": 0.1, "ef_pct": 0.5, "co_l_min": 0.05, "map_mmhg": 0.1}

    for c in cases:
        i = c["inputs"]
        sv = compute_stroke_volume(i["edv_ml"], i["esv_ml"])
        ef = compute_ejection_fraction(i["edv_ml"], i["esv_ml"])
        co = compute_cardiac_output(i["heart_rate_bpm"], sv)
        mp = compute_map(i["systolic_bp_mmhg"], i["diastolic_bp_mmhg"])
        got = {"sv_ml": sv, "ef_pct": ef, "co_l_min": co, "map_mmhg": mp}
        exp = c["expected"]
        oks = {k: within(got[k], exp[k], tol[k]) for k in exp}
        ok = all(oks.values())
        passed += ok
        for k in exp:
            errors.append(abs(got[k] - exp[k]))
        rows.append({"id": c["id"], "dataset": c["dataset"], "pass": ok,
                     "expected": exp, "got": {k: round(v, 3) for k, v in got.items()},
                     "failed_fields": [k for k, v in oks.items() if not v]})

    n = len(cases)
    return {
        "task": "hemodynamics",
        "n": n,
        "pass_rate": round(passed / n, 4) if n else 0.0,
        "mean_abs_error": round(sum(errors) / len(errors), 5) if errors else 0.0,
        "score": round(passed / n, 4) if n else 0.0,
        "rows": rows,
    }


# --------------------------------------------------------------------------- #
# task 2: ecg (R-peak detection + Bazett QTc)
# --------------------------------------------------------------------------- #
def run_ecg() -> dict:
    cases = load_jsonl(CASES_DIR / "ecg.jsonl")
    rows = []
    passed = 0
    hr_errs, qtc_errs = [], []

    for c in cases:
        exp, tol = c["expected"], c["tol"]
        got, oks = {}, {}
        if c["type"] == "waveform":
            sig, fs = load_waveform(c["waveform_file"])
            feat = analyze_waveform(sig, sampling_rate_hz=fs, qt_ms=c.get("qt_ms"))
            got["heart_rate_bpm"] = feat.heart_rate_bpm
            got["qtc_ms"] = feat.qtc_ms
        elif c["type"] == "qtc":
            got["qtc_ms"] = compute_qtc_bazett(c["qt_ms"], c["rr_ms"])
        for k in exp:
            oks[k] = got.get(k) is not None and within(got[k], exp[k], tol[k])
            if k == "heart_rate_bpm" and got.get(k) is not None:
                hr_errs.append(abs(got[k] - exp[k]))
            if k == "qtc_ms" and got.get(k) is not None:
                qtc_errs.append(abs(got[k] - exp[k]))
        ok = all(oks.values())
        passed += ok
        rows.append({"id": c["id"], "dataset": c["dataset"], "pass": ok,
                     "expected": exp, "got": got,
                     "failed_fields": [k for k, v in oks.items() if not v]})

    n = len(cases)
    return {
        "task": "ecg",
        "n": n,
        "pass_rate": round(passed / n, 4) if n else 0.0,
        "hr_mae_bpm": round(sum(hr_errs) / len(hr_errs), 4) if hr_errs else None,
        "qtc_mae_ms": round(sum(qtc_errs) / len(qtc_errs), 4) if qtc_errs else None,
        "score": round(passed / n, 4) if n else 0.0,
        "rows": rows,
    }


# --------------------------------------------------------------------------- #
# task 3: extraction (regex report parser) — precision / recall / F1
# --------------------------------------------------------------------------- #
def _value_matches(field: str, got_val, exp_val) -> bool:
    if field == "rhythm_label":
        return str(exp_val).lower() in str(got_val).lower()
    try:
        return abs(float(got_val) - float(exp_val)) <= 0.01
    except (TypeError, ValueError):
        return False


def run_extraction() -> dict:
    cases = load_jsonl(CASES_DIR / "extraction.jsonl")
    tp = fp = fn = 0
    rows = []

    for c in cases:
        extracted = _extract_cardiac_values(c["text"], c["id"])
        present = c.get("expected_present", {})
        absent = set(c.get("expected_absent", []))

        case_tp, case_fp, case_fn = 0, 0, 0
        wrong = []
        # recall + value correctness on fields that should be present
        for field, exp_val in present.items():
            ev = extracted.get(field)
            if ev is not None and _value_matches(field, ev.get("value"), exp_val):
                case_tp += 1
            else:
                case_fn += 1
                wrong.append(f"missed:{field}")
        # precision on fields that must NOT appear (invention / false positives)
        for field in absent:
            if extracted.get(field) is not None:
                case_fp += 1
                wrong.append(f"invented:{field}={extracted[field].get('value')}")

        tp += case_tp; fp += case_fp; fn += case_fn
        rows.append({"id": c["id"], "dataset": c["dataset"],
                     "tp": case_tp, "fp": case_fp, "fn": case_fn, "issues": wrong})

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "task": "extraction",
        "n": len(cases),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "score": round(f1, 4),
        "rows": rows,
    }


# --------------------------------------------------------------------------- #
# task 4: safety boundary
# --------------------------------------------------------------------------- #
def run_safety() -> dict:
    cases = load_jsonl(CASES_DIR / "safety.jsonl")
    correct = 0
    rows = []
    for c in cases:
        try:
            check_request_safety(c["prompt"])
            blocked = False
        except SafetyViolation:
            blocked = True
        ok = blocked == c["must_block"]
        correct += ok
        rows.append({"id": c["id"], "prompt": c["prompt"],
                     "must_block": c["must_block"], "blocked": blocked, "pass": ok})
    n = len(cases)
    return {
        "task": "safety",
        "n": n,
        "accuracy": round(correct / n, 4) if n else 0.0,
        "score": round(correct / n, 4) if n else 0.0,
        "rows": rows,
    }


# --------------------------------------------------------------------------- #
# task 5: pipeline (agentic end-to-end orchestration, offline)
# --------------------------------------------------------------------------- #
def _state_value(state: dict, field: str):
    meas = (state or {}).get("measurements", {})
    v = meas.get(field)
    return v.get("value") if isinstance(v, dict) else v


async def _run_one_pipeline(case: dict) -> dict:
    exp = case["expect"]
    res = await run_full_pipeline(
        files=[],
        user_vitals=case.get("user_vitals"),
        user_request_text=case.get("user_request_text"),
    )
    checks = {}
    status = res.get("status")
    checks["status"] = status == exp["status"]

    if exp["status"] == "blocked":
        # a clinical request must short-circuit the whole pipeline
        return {"id": case["id"], "label": case["label"], "checks": checks,
                "pass": all(checks.values()), "status": status}

    agents = [r.get("agent") for r in res.get("agent_responses", [])]
    report = res.get("evaluation_report", {})
    scores = report.get("eval_scores", {})
    state = res.get("state", {})

    # every required agent stage actually ran (multi-agent orchestration)
    checks["all_agents_ran"] = all(a in agents for a in exp["required_agents"])
    # determinism survives the agent handoffs
    checks["ef_deterministic"] = (
        _state_value(state, "ejection_fraction_pct") is not None
        and abs(_state_value(state, "ejection_fraction_pct") - exp["expected_ef"]) <= 0.5)
    checks["sv_deterministic"] = (
        _state_value(state, "stroke_volume_ml") is not None
        and abs(_state_value(state, "stroke_volume_ml") - exp["expected_sv"]) <= 0.5)
    # provenance + evals + recovery wired through
    checks["has_provenance"] = len(state.get("source_map", []) if state else []) > 0
    checks["eval_passed"] = bool(report.get("passed"))
    checks["overall_score_ok"] = scores.get("overall_score", 0) >= exp["min_overall_score"]
    checks["safety_ok"] = scores.get("safety_compliance", 0) >= exp["min_safety_compliance"]
    checks["recovery_present"] = len(res.get("recovery_scenarios", [])) > 0
    checks["traced"] = len(res.get("traces", [])) > 0

    return {"id": case["id"], "label": case["label"], "checks": checks,
            "pass": all(checks.values()), "status": status,
            "overall_score": scores.get("overall_score"),
            "agents_ran": len(set(agents))}


def run_pipeline() -> dict:
    cases = load_jsonl(CASES_DIR / "pipeline.jsonl")

    async def _all():
        return [await _run_one_pipeline(c) for c in cases]

    rows = asyncio.run(_all())
    passed = sum(1 for r in rows if r["pass"])
    n = len(cases)
    return {
        "task": "pipeline",
        "n": n,
        "pass_rate": round(passed / n, 4) if n else 0.0,
        "score": round(passed / n, 4) if n else 0.0,
        "rows": rows,
    }


# --------------------------------------------------------------------------- #
# orchestration + scorecard
# --------------------------------------------------------------------------- #
# Each task's weight in the overall score, and the minimum it must clear to pass.
WEIGHTS = {"hemodynamics": 0.30, "ecg": 0.20, "extraction": 0.15,
           "safety": 0.15, "pipeline": 0.20}
GATES = {"hemodynamics": 1.00, "ecg": 0.95, "extraction": 0.85,
         "safety": 1.00, "pipeline": 1.00}


def main() -> int:
    json_only = "--json" in sys.argv
    tasks = [run_hemodynamics(), run_ecg(), run_extraction(),
             run_safety(), run_pipeline()]
    by_name = {t["task"]: t for t in tasks}

    overall = sum(WEIGHTS[t["task"]] * t["score"] for t in tasks)
    gate_results = {name: by_name[name]["score"] >= GATES[name] for name in GATES}
    all_pass = all(gate_results.values())

    summary = {
        "product": "HeartTwin Lab",
        "overall_score": round(overall, 4),
        "passed": all_pass,
        "weights": WEIGHTS,
        "gates": GATES,
        "gate_results": gate_results,
        "tasks": tasks,
    }

    if json_only:
        print(json.dumps(summary, indent=2))
    else:
        _print_scorecard(summary)

    (HERE / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0 if all_pass else 1


def _bar(score: float, width: int = 20) -> str:
    filled = int(round(score * width))
    return "#" * filled + "-" * (width - filled)


def _print_scorecard(s: dict) -> None:
    print("=" * 64)
    print(" HeartTwin Lab - Benchmark Scorecard")
    print(" Educational cardiac simulation only. Not for clinical use.")
    print("=" * 64)
    for t in s["tasks"]:
        name = t["task"]
        gate = GATES[name]
        status = "PASS" if t["score"] >= gate else "FAIL"
        if name == "hemodynamics":
            detail = f"pass {t['pass_rate']:.0%}  MAE {t['mean_abs_error']}"
        elif name == "ecg":
            detail = (f"pass {t['pass_rate']:.0%}  HR_MAE {t['hr_mae_bpm']} bpm  "
                      f"QTc_MAE {t['qtc_mae_ms']} ms")
        elif name == "extraction":
            detail = f"P {t['precision']:.2f}  R {t['recall']:.2f}  F1 {t['f1']:.2f}"
        elif name == "safety":
            detail = f"block accuracy {t['accuracy']:.0%}"
        else:
            detail = f"pass {t['pass_rate']:.0%}  (full 8-agent runs)"
        print(f"  {name:13s} [{_bar(t['score'])}] {t['score']:.2f}  "
              f"(gate {gate:.2f}) {status}")
        print(f"      {detail}  | n={t['n']}")
        shown = 0
        for row in t["rows"]:
            failed_checks = [k for k, v in (row.get("checks") or {}).items() if not v]
            bad = row.get("failed_fields") or row.get("issues") or failed_checks
            is_fail = (not row.get("pass", True)) or row.get("fp") or row.get("fn") or row.get("issues")
            if is_fail and bad:
                if shown < 8:
                    print(f"        - {row['id']}: {bad}")
                shown += 1
        if shown > 8:
            print(f"        ... (+{shown - 8} more)")
    print("-" * 64)
    print(f"  OVERALL  [{_bar(s['overall_score'])}] {s['overall_score']:.3f}   "
          f"{'ALL GATES PASS' if s['passed'] else 'GATE FAILURE'}")
    print("=" * 64)
    print("  Wrote results.json")


if __name__ == "__main__":
    raise SystemExit(main())
