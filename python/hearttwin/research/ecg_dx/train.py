"""Train the research ECG diagnostic classifier on the PTB-XL dx slice.

Multi-label (5 diagnostic superclasses) OneVsRest random forest on deterministic
features. Saves model.joblib + a held-out test split for run_dx_benchmark.py.

Run:  python -m python.hearttwin.research.ecg_dx.train
Prereq: python benchmark/datasets/prep_ptbxl_dx.py

Not a medical device. Research/benchmark use only.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .classifier import SUPERCLASSES
from .features import extract_features

_REPO = Path(__file__).resolve().parents[4]
_NPZ = _REPO / "benchmark" / "datasets" / "ptbxl" / "dx_dataset.npz"
_MODEL = Path(__file__).resolve().parent / "model.joblib"
_SPLIT = Path(__file__).resolve().parent / "test_split.npz"


def _featurize(X: np.ndarray, fs: float) -> np.ndarray:
    return np.stack([extract_features(X[i], fs) for i in range(X.shape[0])])


def main() -> None:
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.multiclass import OneVsRestClassifier
    from sklearn.metrics import roc_auc_score, f1_score

    if not _NPZ.exists():
        raise SystemExit(f"missing {_NPZ}; run benchmark/datasets/prep_ptbxl_dx.py first")

    data = np.load(_NPZ, allow_pickle=True)
    X, Y, ids = data["X"], data["Y"], data["ids"]
    fs = float(data["fs"])
    print(f"dataset X={X.shape} Y={Y.shape} fs={fs}")

    # deterministic patient-agnostic split (by index; fixed seed)
    rng = np.random.RandomState(42)
    idx = rng.permutation(len(X))
    n_test = max(1, int(0.25 * len(X)))
    test_idx, train_idx = idx[:n_test], idx[n_test:]

    print("extracting features ...")
    Xtr = _featurize(X[train_idx], fs)
    Xte = _featurize(X[test_idx], fs)
    Ytr, Yte = Y[train_idx], Y[test_idx]

    # kept deliberately small (max_depth + tree count) so the trained model is
    # lightweight enough to ship with the repo and the API endpoint works as-is.
    clf = OneVsRestClassifier(
        RandomForestClassifier(n_estimators=120, max_depth=12,
                               class_weight="balanced", random_state=42, n_jobs=-1)
    )
    clf.fit(Xtr, Ytr)

    proba = clf.predict_proba(Xte)
    preds = (proba >= 0.5).astype(int)
    aucs = []
    for j, c in enumerate(SUPERCLASSES):
        if Yte[:, j].sum() and Yte[:, j].sum() < len(Yte):
            aucs.append(roc_auc_score(Yte[:, j], proba[:, j]))
    macro_auc = float(np.mean(aucs)) if aucs else float("nan")
    macro_f1 = f1_score(Yte, preds, average="macro", zero_division=0)
    print(f"held-out  macro-AUROC={macro_auc:.3f}  macro-F1={macro_f1:.3f}  (n_test={len(test_idx)})")

    joblib.dump({"model": clf, "threshold": 0.5, "feature_dim": Xtr.shape[1]}, _MODEL)
    np.savez_compressed(_SPLIT, test_idx=test_idx, fs=fs)
    print(f"saved {_MODEL.name} + {_SPLIT.name}")


if __name__ == "__main__":
    main()
