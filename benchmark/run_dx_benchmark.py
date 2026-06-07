#!/usr/bin/env python3
"""HeartTwinBench (diagnosis) — the research ECG classifier vs PTB-XL labels.

Scores the trained research classifier on the held-out PTB-XL test split against
real DIAGNOSTIC SUPERCLASS labels (NORM/MI/STTC/CD/HYP): macro-AUROC + macro-F1,
plus per-class. Optionally compares an LLM baseline (gpt-4o reading the ECG strip).

Run:
  python benchmark/run_dx_benchmark.py
  python benchmark/run_dx_benchmark.py --llm-baseline --model gpt-4o --limit 20

Prereq: prep_ptbxl_dx.py + python -m python.hearttwin.research.ecg_dx.train

RESEARCH/benchmark use only. HeartTwin Lab is not a medical device.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT))

from python.hearttwin.research.ecg_dx.classifier import EcgDxClassifier, SUPERCLASSES  # noqa: E402
from python.hearttwin.research.ecg_dx.features import extract_features  # noqa: E402

_NPZ = HERE / "datasets" / "ptbxl" / "dx_dataset.npz"
_SPLIT = REPO_ROOT / "python" / "hearttwin" / "research" / "ecg_dx" / "test_split.npz"


def _metrics(Y: np.ndarray, P: np.ndarray) -> dict:
    from sklearn.metrics import roc_auc_score, f1_score
    per_auc = {}
    aucs = []
    for j, c in enumerate(SUPERCLASSES):
        if Y[:, j].sum() and Y[:, j].sum() < len(Y):
            a = float(roc_auc_score(Y[:, j], P[:, j]))
            per_auc[c] = round(a, 3)
            aucs.append(a)
        else:
            per_auc[c] = None
    preds = (P >= 0.5).astype(int)
    return {
        "macro_auroc": round(float(np.mean(aucs)), 4) if aucs else None,
        "macro_f1": round(float(f1_score(Y, preds, average="macro", zero_division=0)), 4),
        "per_class_auroc": per_auc,
        "n": int(len(Y)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm-baseline", action="store_true")
    ap.add_argument("--model", default="gpt-4o")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not _NPZ.exists() or not _SPLIT.exists():
        print("ERROR: missing dataset/split. Run prep_ptbxl_dx.py then ecg_dx.train.", file=sys.stderr)
        return 2

    data = np.load(_NPZ, allow_pickle=True)
    X, Y, fs = data["X"], data["Y"], float(data["fs"])
    test_idx = np.load(_SPLIT)["test_idx"]
    Xte, Yte = X[test_idx], Y[test_idx]

    clf = EcgDxClassifier.load()
    P = np.stack([np.array([clf.predict_proba(Xte[i], fs)[c] for c in SUPERCLASSES])
                  for i in range(len(Xte))])
    system = _metrics(Yte, P)

    summary = {"benchmark": "HeartTwinBench (diagnosis)", "labels": "PTB-XL superclass",
               "classes": SUPERCLASSES, "system": system, "baseline": None}

    if args.llm_baseline:
        summary["baseline"] = _run_llm_baseline(Xte, Yte, fs, test_idx, data, args)

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        _print(summary)
    (HERE / "dx_results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0


def _run_llm_baseline(Xte, Yte, fs, test_idx, data, args) -> dict:
    """gpt-4o reads a rendered ECG strip and returns superclass probabilities."""
    import base64, io, os
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import openai

    if not os.environ.get("OPENAI_API_KEY"):
        return {"error": "no OPENAI_API_KEY"}
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    prompt = ("You are an EDUCATIONAL research ECG screening assistant (NOT a medical "
              "device, not a diagnosis). Given a lead-II ECG strip, return JSON with a "
              f"probability in [0,1] for each superclass {SUPERCLASSES}: "
              '{"NORM":..,"MI":..,"STTC":..,"CD":..,"HYP":..}.')
    n = min(args.limit or len(Xte), len(Xte))
    P, Y = [], []
    for i in range(n):
        sig = Xte[i][:, 1]
        fig, ax = plt.subplots(figsize=(12, 2.6), dpi=100)
        ax.plot(np.arange(len(sig)) / fs, sig, lw=0.7, color="black")
        ax.set_xlabel("s"); ax.grid(True, color="#f0a0a0", lw=0.4)
        buf = io.BytesIO(); fig.tight_layout(); fig.savefig(buf, format="png"); plt.close(fig)
        b64 = base64.b64encode(buf.getvalue()).decode()
        try:
            r = client.chat.completions.create(
                model=args.model, temperature=0, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": prompt},
                          {"role": "user", "content": [
                              {"type": "text", "text": "Classify this ECG strip."},
                              {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]}],
                max_tokens=200)
            d = json.loads(r.choices[0].message.content or "{}")
            P.append([float(d.get(c, 0.0) or 0.0) for c in SUPERCLASSES])
            Y.append(Yte[i])
        except Exception as exc:
            print(f"  baseline skip {i}: {type(exc).__name__}")
    if not P:
        return {"error": "no baseline predictions"}
    return _metrics(np.asarray(Y), np.asarray(P)) | {"model": args.model}


def _print(s: dict) -> None:
    sy = s["system"]
    print("=" * 64)
    print(" HeartTwinBench - DIAGNOSIS (research classifier vs PTB-XL labels)")
    print(" RESEARCH SCREENING ONLY - not a medical device, not a diagnosis.")
    print("=" * 64)
    print(f"  research classifier:  macro-AUROC={sy['macro_auroc']}  "
          f"macro-F1={sy['macro_f1']}  (n={sy['n']})")
    print(f"  per-class AUROC: {sy['per_class_auroc']}")
    b = s.get("baseline")
    if b and "error" not in b:
        print(f"  {b.get('model','LLM')} baseline:  macro-AUROC={b['macro_auroc']}  "
              f"macro-F1={b['macro_f1']}  (n={b['n']})")
        if sy['macro_auroc'] and b['macro_auroc']:
            print(f"  Delta macro-AUROC: {sy['macro_auroc'] - b['macro_auroc']:+.3f}")
    elif b:
        print(f"  baseline: {b['error']}")
    print("=" * 64)
    print("  Wrote dx_results.json")


if __name__ == "__main__":
    raise SystemExit(main())
