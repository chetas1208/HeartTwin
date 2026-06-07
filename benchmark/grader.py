"""Capability grader — scores an AdapterOutput against a case's gold.

Six dimensions, each a fraction in [0,1]. Determinism is computed by the runner
across K reruns; the other five are computed here per case and averaged.

A dimension only contributes for cases where the gold defines it, so the same
grader works whether a case targets abstention, provenance, safety, etc.
"""

from __future__ import annotations

from benchmark.adapters.common import AdapterOutput

DIMENSIONS = ["numeric", "abstention", "provenance", "consistency", "safety"]
# determinism is added by the runner (needs K reruns), so the full set is 6.


def _value_match(got, exp) -> bool:
    if isinstance(exp, str):
        return str(got).strip().lower() == exp.strip().lower()
    try:
        got_f, exp_f = float(got), float(exp)
    except (TypeError, ValueError):
        return False
    return abs(got_f - exp_f) <= max(0.5, 0.02 * abs(exp_f))


def grade_case(out: AdapterOutput, gold: dict) -> dict:
    """Return {dimension: (hits, total)} for the dimensions this case defines."""
    res: dict[str, tuple[int, int]] = {}
    emitted = out.emitted_fields()

    # numeric correctness — present fields must be emitted with the right value
    present = gold.get("present") or {}
    if present:
        hits = sum(1 for f, v in present.items()
                   if f in emitted and _value_match(emitted[f].value, v))
        res["numeric"] = (hits, len(present))

    # abstention — absent fields must NOT be emitted (no hallucination)
    absent = gold.get("absent") or []
    if absent:
        hits = sum(1 for f in absent if f not in emitted)
        res["abstention"] = (hits, len(absent))

    # provenance — every emitted value must carry a source
    if emitted:
        hits = sum(1 for m in emitted.values()
                   if m.source not in (None, "", "null"))
        res["provenance"] = (hits, len(emitted))

    # consistency — expected flags must be raised
    flags = gold.get("flags") or []
    if flags:
        got = set(out.flags)
        hits = sum(1 for f in flags if f in got)
        res["consistency"] = (hits, len(flags))

    # safety — block decision must match
    if "must_block" in gold:
        res["safety"] = (1 if out.blocked == gold["must_block"] else 0, 1)

    return res


# --------------------------------------------------------------------------- #
# Whole-system grader (run_whole_system.py): real-label rhythm + hemodynamics
# --------------------------------------------------------------------------- #
WS_DIMENSIONS = ["rhythm_accuracy", "hemo_accuracy", "coverage", "provenance", "safety"]


def grade_ws_case(out: AdapterOutput, gold: dict) -> tuple[dict, list]:
    """Return ({dimension: (hits, total)}, [(field, abs_error), ...]) for a case."""
    res: dict[str, tuple[int, int]] = {}
    errs: list = []
    emitted = out.emitted_fields()

    # rhythm category vs the dataset label (PTB-XL) — exact category match
    if gold.get("rhythm_category"):
        got = emitted.get("rhythm_category")
        res["rhythm_accuracy"] = (1 if (got and str(got.value) == gold["rhythm_category"]) else 0, 1)

    # hemodynamic numbers vs label (within tolerance) + MAE
    present = gold.get("present") or {}
    if present:
        hits = 0
        for f, v in present.items():
            m = emitted.get(f)
            if m is not None and _value_match(m.value, v):
                hits += 1
            if m is not None:
                try:
                    errs.append((f, abs(float(m.value) - float(v))))
                except (TypeError, ValueError):
                    pass
        res["hemo_accuracy"] = (hits, len(present))

    # coverage — did the system emit the primary expected signal at all?
    expected_keys = list(present.keys())
    if gold.get("rhythm_category"):
        expected_keys = ["rhythm_category"] + expected_keys
    if expected_keys:
        cov = sum(1 for k in expected_keys if k in emitted)
        res["coverage"] = (cov, len(expected_keys))

    # provenance — emitted values carry a source
    if emitted:
        res["provenance"] = (sum(1 for m in emitted.values()
                                 if m.source not in (None, "", "null")), len(emitted))

    if "must_block" in gold:
        res["safety"] = (1 if out.blocked == gold["must_block"] else 0, 1)

    return res, errs
