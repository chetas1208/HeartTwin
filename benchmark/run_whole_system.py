#!/usr/bin/env python3
"""HeartTwinBench (whole-system) — the ENTIRE pipeline vs. a single LLM.

Feeds the same clinical evidence to:
  - the full 8-agent HeartTwin pipeline (run_full_pipeline; VISTA-3D off), and
  - one multimodal LLM (config option, default gpt-4o) given the same evidence
    rendered for a model (ECG strip PNG / vitals text) plus a strong fair prompt,
scores both with one shared grader against REAL dataset labels where available
(PTB-XL rhythm), and reports the delta.

Cases:
  cases/ptbxl_cases.jsonl         real PTB-XL ECG (rhythm label)  [run datasets/prep_ptbxl.py]
  cases/whole_system_cases.jsonl  vitals (derived label) + safety [run generate_cases.py]

Usage:
  python benchmark/run_whole_system.py                          # mock baseline if no key
  python benchmark/run_whole_system.py --model gpt-4o --temperature 0 --k 1
  python benchmark/run_whole_system.py --baseline mock
  python benchmark/run_whole_system.py --limit 6 --json

Educational cardiac simulation only. Not for diagnosis or treatment decisions.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT))

from benchmark.adapters import pipeline_system_adapter as sysad  # noqa: E402
from benchmark.adapters import multimodal_baseline_adapter as basead  # noqa: E402
from benchmark.grader import grade_ws_case, WS_DIMENSIONS  # noqa: E402

ALL_DIMENSIONS = WS_DIMENSIONS + ["determinism"]
CASE_FILES = ["ptbxl_cases.jsonl", "whole_system_cases.jsonl"]


def load_cases(limit: int | None) -> list[dict]:
    cases = []
    for name in CASE_FILES:
        p = HERE / "cases" / name
        if p.exists():
            cases += [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    if limit:
        # keep a spread of modalities
        seen: dict[str, int] = {}
        out = []
        for c in cases:
            m = c.get("modality", "?")
            if seen.get(m, 0) < limit:
                out.append(c); seen[m] = seen.get(m, 0) + 1
        return out
    return cases


def _acc(totals, per):
    for d, (h, t) in per.items():
        a, b = totals.get(d, (0, 0))
        totals[d] = (a + h, b + t)


def run_adapter(name, infer_once, cases, k):
    totals: dict[str, tuple[int, int]] = {}
    abs_errs: list[float] = []
    det_stable = 0
    errors = 0
    rows = []
    for case in cases:
        runs = [infer_once(case) for _ in range(k)]
        first = runs[0]
        if first.error:
            errors += 1
        graded, errs = grade_ws_case(first, case["gold"])
        _acc(totals, graded)
        abs_errs += [e for _, e in errs]
        stable = len({r.fingerprint() for r in runs}) == 1
        det_stable += stable
        rows.append({"id": case["id"], "dataset": case.get("dataset"),
                     "modality": case.get("modality"),
                     "graded": {d: list(v) for d, v in graded.items()},
                     "abs_errs": errs, "stable": stable, "blocked": first.blocked,
                     "emitted": {k2: [m.value, m.source] for k2, m in first.emitted_fields().items()},
                     "error": first.error})
    scores = {d: round(h / t, 4) if t else None for d, (h, t) in totals.items()}
    scores["determinism"] = round(det_stable / len(cases), 4) if cases else None
    counts = {d: t for d, (h, t) in totals.items()}
    counts["determinism"] = len(cases)
    present = [scores[d] for d in ALL_DIMENSIONS if scores.get(d) is not None]
    scores["overall"] = round(sum(present) / len(present), 4) if present else 0.0
    mae = round(sum(abs_errs) / len(abs_errs), 3) if abs_errs else None
    return {"adapter": name, "scores": scores, "counts": counts, "mae": mae,
            "errors": errors, "n": len(cases), "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", choices=["openai", "mock"], default=None)
    ap.add_argument("--model", default="gpt-4o")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--k", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    mode = args.baseline or ("openai" if os.environ.get("OPENAI_API_KEY") else "mock")
    if mode == "openai" and not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: needs OPENAI_API_KEY (or use --baseline mock).", file=sys.stderr)
        return 2

    cases = load_cases(args.limit)
    if not cases:
        print("ERROR: no cases. Run datasets/prep_ptbxl.py and generate_cases.py first.", file=sys.stderr)
        return 2

    sys_res = run_adapter(sysad.NAME, sysad.infer, cases, args.k)

    def baseline_once(c):
        return basead.infer(c, mode=mode, model=args.model, temperature=args.temperature)
    bname = basead.NAME + (f" ({args.model})" if mode == "openai" else " [MOCK]")
    base_res = run_adapter(bname, baseline_once, cases, args.k)

    summary = {"benchmark": "HeartTwinBench (whole-system)", "n_cases": len(cases),
               "k": args.k, "baseline_mode": mode, "baseline_model": args.model,
               "baseline_temperature": args.temperature, "dimensions": ALL_DIMENSIONS,
               "system": sys_res, "baseline": base_res,
               "delta": {d: _delta(sys_res["scores"].get(d), base_res["scores"].get(d))
                         for d in ALL_DIMENSIONS + ["overall"]}}
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        _print(summary)
    (HERE / "whole_system_results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0


def _delta(a, b):
    return None if (a is None or b is None) else round(a - b, 4)


def _fmt(v):
    return f"{v:.2f}" if isinstance(v, float) else " -- "


def _print(s):
    sysc, basec = s["system"]["scores"], s["baseline"]["scores"]
    counts = s["system"]["counts"]
    binvalid = s["baseline"].get("errors", 0) == s["baseline"].get("n", 0) > 0
    if binvalid:
        basec = {}
    print("=" * 74)
    print(" HeartTwinBench - WHOLE PIPELINE vs LLM  (Delta = system - baseline)")
    print(f" cases={s['n_cases']}  k={s['k']}  baseline={s['baseline']['adapter']}"
          f"  temp={s['baseline_temperature']}  (VISTA-3D off)")
    print(" Educational cardiac simulation only. Not for clinical use.")
    print("=" * 74)
    print(f"  {'dimension':16s} {'n':>4s}   {'pipeline':>9s}  {'baseline':>9s}   {'Delta':>6s}")
    print("  " + "-" * 58)
    for d in ALL_DIMENSIONS:
        a, b = sysc.get(d), basec.get(d)
        dl = _delta(a, b)
        flag = "  <-- system wins" if (dl is not None and dl >= 0.15) else (
               "  <-- baseline wins" if (dl is not None and dl <= -0.15) else "")
        print(f"  {d:16s} {counts.get(d,0):>4d}   {_fmt(a):>9s}  {_fmt(b):>9s}   "
              f"{(f'{dl:+.2f}' if dl is not None else ' -- '):>6s}{flag}")
    print("  " + "-" * 58)
    a, b = sysc.get("overall"), basec.get("overall")
    dl = _delta(a, b)
    print(f"  {'OVERALL':16s} {'':>4s}   {_fmt(a):>9s}  {_fmt(b):>9s}   "
          f"{(f'{dl:+.2f}' if dl is not None else ' -- '):>6s}")
    print(f"  hemodynamic MAE: pipeline={s['system']['mae']}  baseline="
          f"{s['baseline']['mae'] if not binvalid else '--'}")
    print("=" * 74)
    if binvalid:
        sample = next((r.get("error") for r in s["baseline"]["rows"] if r.get("error")), "")
        print(f"  WARNING: baseline errored on all {s['baseline']['n']} cases - column omitted.")
        print(f"           First error: {sample}")
    if s["baseline_mode"] == "mock":
        print("  NOTE: baseline=mock is an OFFLINE stand-in (no real model). Use --model for real numbers.")
    print("  Wrote whole_system_results.json")


if __name__ == "__main__":
    raise SystemExit(main())
