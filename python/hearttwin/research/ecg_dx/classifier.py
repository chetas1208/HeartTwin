"""Research ECG diagnostic classifier — load a trained model and predict.

User-reachable, with a mandatory disclaimer on every result. HeartTwin Lab is not
a medical tool; this is an experimental research screening output, not a diagnosis.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .features import extract_features

SUPERCLASSES = ["NORM", "MI", "STTC", "CD", "HYP"]
_SUPERCLASS_NAMES = {
    "NORM": "Normal ECG",
    "MI": "Myocardial infarction pattern",
    "STTC": "ST/T change pattern",
    "CD": "Conduction disturbance pattern",
    "HYP": "Hypertrophy pattern",
}

DISCLAIMER = (
    "RESEARCH SCREENING OUTPUT — NOT A DIAGNOSIS. HeartTwin Lab is not a medical "
    "tool or medical device. These are experimental model probabilities for an ECG "
    "superclass screening task, not medical advice. Do not use for clinical "
    "decisions; consult a qualified clinician."
)

_MODEL_PATH = Path(__file__).resolve().parent / "model.joblib"


class EcgDxClassifier:
    """Thin wrapper around a trained multi-label scikit-learn model."""

    def __init__(self, model: Any | None = None, threshold: float = 0.5) -> None:
        self._model = model
        self.threshold = threshold

    @classmethod
    def load(cls, path: Path | None = None) -> "EcgDxClassifier":
        import joblib
        p = path or _MODEL_PATH
        if not p.exists():
            raise FileNotFoundError(
                f"No trained model at {p}. Train one with "
                f"`python -m python.hearttwin.research.ecg_dx.train`."
            )
        bundle = joblib.load(p)
        clf = cls(model=bundle["model"], threshold=bundle.get("threshold", 0.5))
        clf.feature_dim = bundle.get("feature_dim")
        return clf

    @property
    def available(self) -> bool:
        return self._model is not None

    def predict_proba(self, sig: np.ndarray, fs: float = 100.0) -> dict[str, float]:
        feats = extract_features(sig, fs).reshape(1, -1)
        probs = _multilabel_proba(self._model, feats)[0]
        return {c: round(float(p), 4) for c, p in zip(SUPERCLASSES, probs)}

    def classify(self, sig: np.ndarray, fs: float = 100.0) -> dict[str, Any]:
        """Return per-superclass probabilities + flagged classes + DISCLAIMER."""
        proba = self.predict_proba(sig, fs)
        flagged = sorted([c for c, p in proba.items() if p >= self.threshold],
                         key=lambda c: -proba[c])
        return {
            "task": "ecg_superclass_screening",
            "probabilities": proba,
            "class_names": _SUPERCLASS_NAMES,
            "flagged": flagged,
            "threshold": self.threshold,
            "model": "research_ecg_dx_v0",
            "disclaimer": DISCLAIMER,
        }


def _multilabel_proba(model: Any, X: np.ndarray) -> np.ndarray:
    """Return (n_samples, n_classes) positive-class probabilities for a
    OneVsRest / multi-output sklearn model."""
    out = model.predict_proba(X)
    # OneVsRestClassifier -> ndarray (n, n_classes); MultiOutput -> list of (n,2)
    if isinstance(out, list):
        return np.column_stack([col[:, 1] for col in out])
    return np.asarray(out)
