#!/usr/bin/env python3
"""HeartTwinBench — system vs. baseline head-to-head.

Runs the HeartTwin deterministic harness AND a baseline LLM through the SAME
adapter interface, grades both with the SAME grader across six capability
dimensions, and prints a two-column scorecard with the delta.

The point is the reliability GAP, not absolute accuracy:
  numeric · abstention · provenance · consistency · safety · determinism

Usage:
  python benchmark/run_compare.py                         # mock baseline (offline plumbing demo)
  python benchmark/run_compare.py --baseline openai --model gpt-4o-mini --k 5 --temperature 0.7
  python benchmark/run_compare.py --json

Flags:
  --baseline {openai,mock}  baseline source (default: openai if OPENAI_API_KEY set, else mock)
  --model NAME              baseline model id (openai mode)
  --temperature FLOAT       baseline sampling temperature (default 0.4)
  --k INT                   reruns per case for determinism (default: 3, system always deterministic)
  --json                    machine-readable output only

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
# system adapter imports python.hearttwin.* (needs repo root);
# grader/adapters import benchmark.* (needs repo root too, as the package parent)
sys.path.insert(0, str(REPO_ROOT))

from benchmark.adapters import system_adapter, baseline_adapter  # noqa: E402
from benchmark.grader import grade_case, DIMENSIONS  # noqa: E402

ALL_DIMENSIONS = DIMENSIONS + ["determinism"]
CASES = HERE / "cases" / "compare.jsonl"


def load_cases() -> list[dict]:
    with CASES.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _accumulate(totals: dict, per_case: dict) -> None:
    for dim, (hits, total) in per_case.items():
        h, t = totals.get(dim, (0, 0))
        totals[dim] = (h + hits, t + total)


def run_adapter(name: str, infer_once, cases: list[dict], k: int) -> dict:
    """Run an adapter over all cases k times; grade dimension 1 (the first run)
    and compute determinism across the k runs."""
    totals: dict[str, tuple[int, int]] = {}
    det_stable = 0
    errors = 0
    rows = []
    for case in cases:
        runs = [infer_once(case) for _ in range(k)]
        first = runs[0]
        if first.error:
            errors += 1
        graded = grade_case(first, case["gold"])
        _accumulate(totals, graded)
        fingerprints = {r.fingerprint() for r in runs}
        stable = len(fingerprints) == 1
        det_stable += stable
        rows.append({
            "id": case["id"], "dimension": case["dimension"],
            "graded": {d: list(v) for d, v in graded.items()},
            "stable": stable,
            "blocked": first.blocked, "flags": first.flags,
            "emitted": sorted(first.emitted_fields().keys()),
            "error": first.error,
        })

    scores = {d: round(h / t, 4) if t else None for d, (h, t) in totals.items()}
    scores["determinism"] = round(det_stable / len(cases), 4) if cases else None
    counts = {d: t for d, (h, t) in totals.items()}
    counts["determinism"] = len(cases)
    present = [scores[d] for d in ALL_DIMENSIONS if scores.get(d) is not None]
    scores["overall"] = round(sum(present) / len(present), 4) if present else 0.0
    return {"adapter": name, "k": k, "scores": scores, "counts": counts,
            "errors": errors, "n": len(cases), "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", choices=["openai", "mock"], default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--temperature", type=float, default=0.4)
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--sample-per-dim", type=int, default=None,
                    help="smoke test: take the first N cases of each dimension")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    baseline_mode = args.baseline or ("openai" if os.environ.get("OPENAI_API_KEY") else "mock")
    if baseline_mode == "openai" and not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: --baseline openai needs OPENAI_API_KEY. "
              "Set it, or use --baseline mock for an offline plumbing demo.", file=sys.stderr)
        return 2
    cases = load_cases()
    if args.sample_per_dim:
        seen: dict[str, int] = {}
        subset = []
        for c in cases:
            d = c["dimension"]
            if seen.get(d, 0) < args.sample_per_dim:
                subset.append(c)
                seen[d] = seen.get(d, 0) + 1
        cases = subset

    # system: deterministic, so k=1 suffices but we run k to PROVE 0 variance
    sys_result = run_adapter(system_adapter.NAME, system_adapter.infer, cases, args.k)

    def baseline_once(case):
        return baseline_adapter.infer(case, mode=baseline_mode,
                                      model=args.model, temperature=args.temperature)

    base_name = baseline_adapter.NAME + (f" ({args.model})" if (baseline_mode == "openai" and args.model)
                                         else " [MOCK]" if baseline_mode == "mock" else "")
    base_result = run_adapter(base_name, baseline_once, cases, args.k)

    summary = {
        "benchmark": "HeartTwinBench (compare)",
        "n_cases": len(cases),
        "k": args.k,
        "baseline_mode": baseline_mode,
        "baseline_model": args.model,
        "baseline_temperature": args.temperature,
        "dimensions": ALL_DIMENSIONS,
        "system": sys_result,
        "baseline": base_result,
        "delta": {d: _delta(sys_result["scores"].get(d), base_result["scores"].get(d))
                  for d in ALL_DIMENSIONS + ["overall"]},
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        _print(summary)
    (HERE / "compare_results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0


def _delta(a, b):
    if a is None or b is None:
        return None
    return round(a - b, 4)


def _fmt(v):
    return f"{v:.2f}" if isinstance(v, float) else " -- "


def _print(s: dict) -> None:
    sysc = s["system"]["scores"]
    basec = s["baseline"]["scores"]
    counts = s["system"]["counts"]
    # a fully-errored baseline produces meaningless 0/1 artifacts — blank it out
    baseline_invalid = s["baseline"].get("errors", 0) == s["baseline"].get("n", 0) > 0
    if baseline_invalid:
        basec = {}
    print("=" * 72)
    print(" HeartTwinBench - System vs Baseline  (higher = better; Delta = system - baseline)")
    print(f" cases={s['n_cases']}  k={s['k']}  baseline={s['baseline']['adapter']}"
          f"  temp={s['baseline_temperature']}")
    print(" Educational cardiac simulation only. Not for clinical use.")
    print("=" * 72)
    print(f"  {'dimension':14s} {'n':>4s}   {'HeartTwin':>9s}  {'baseline':>9s}   {'Delta':>6s}")
    print("  " + "-" * 56)
    for d in ALL_DIMENSIONS:
        a, b = sysc.get(d), basec.get(d)
        dl = _delta(a, b)
        n = counts.get(d, 0)
        flag = ""
        if dl is not None and dl >= 0.15:
            flag = "  <-- system wins"
        elif dl is not None and dl <= -0.15:
            flag = "  <-- baseline wins"
        print(f"  {d:14s} {n:>4d}   {_fmt(a):>9s}  {_fmt(b):>9s}   "
              f"{(f'{dl:+.2f}' if dl is not None else ' -- '):>6s}{flag}")
    print("  " + "-" * 56)
    a, b = sysc.get("overall"), basec.get("overall")
    dl = _delta(a, b)
    print(f"  {'OVERALL':14s} {'':>4s}   {_fmt(a):>9s}  {_fmt(b):>9s}   "
          f"{(f'{dl:+.2f}' if dl is not None else ' -- '):>6s}")
    print("=" * 72)
    berr = s["baseline"].get("errors", 0)
    bn = s["baseline"].get("n", 0)
    if berr:
        sample = next((r.get("error") for r in s["baseline"]["rows"] if r.get("error")), "")
        print(f"  WARNING: baseline errored on {berr}/{bn} cases - its column is NOT a valid")
        print(f"           comparison. First error: {sample}")
        if berr == bn:
            print("           The baseline produced no usable output (check key quota/billing).")
    if s["baseline_mode"] == "mock":
        print("  NOTE: baseline=mock is an OFFLINE stand-in for harness plumbing only -")
        print("        NOT a real model. Run with --baseline openai for headline numbers.")
    print("  Wrote compare_results.json")


if __name__ == "__main__":
    raise SystemExit(main())
