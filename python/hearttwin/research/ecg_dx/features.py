"""Deterministic feature extraction for the research ECG diagnostic classifier.

Turns a 12-lead ECG (n_samples, 12) into a fixed feature vector: per-lead
amplitude/morphology statistics plus rhythm features (HR, RR variability) derived
from lead II. Pure numpy/scipy — no LLM, deterministic.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, filtfilt, find_peaks

_LEAD_II = 1  # standard PTB-XL lead order: I, II, III, aVR, aVL, aVF, V1..V6


def _bandpass(sig: np.ndarray, fs: float, lo: float = 0.5, hi: float = 40.0) -> np.ndarray:
    nyq = 0.5 * fs
    hi = min(hi, nyq * 0.99)
    try:
        b, a = butter(3, [lo / nyq, hi / nyq], btype="band")
        return filtfilt(b, a, sig)
    except Exception:
        return sig


def _rpeaks(lead2: np.ndarray, fs: float) -> np.ndarray:
    x = _bandpass(np.nan_to_num(lead2), fs)
    if x.std() == 0:
        return np.array([], dtype=int)
    dist = int(0.25 * fs)  # >=250 ms refractory
    peaks, _ = find_peaks(x, distance=dist, height=np.percentile(x, 90))
    return peaks


def _rhythm_features(lead2: np.ndarray, fs: float) -> list[float]:
    peaks = _rpeaks(lead2, fs)
    if len(peaks) < 3:
        return [0.0] * 7
    rr = np.diff(peaks) / fs * 1000.0  # ms
    hr = 60000.0 / np.mean(rr)
    rmssd = float(np.sqrt(np.mean(np.diff(rr) ** 2))) if len(rr) > 1 else 0.0
    pnn50 = float(np.mean(np.abs(np.diff(rr)) > 50)) if len(rr) > 1 else 0.0
    cv = float(np.std(rr) / np.mean(rr)) if np.mean(rr) else 0.0
    return [float(hr), float(np.mean(rr)), float(np.std(rr)), rmssd, pnn50, cv, float(len(peaks))]


def extract_features(sig: np.ndarray, fs: float = 100.0) -> np.ndarray:
    """sig: (n_samples, n_leads) -> 1-D feature vector."""
    sig = np.nan_to_num(np.asarray(sig, dtype=np.float32))
    if sig.ndim == 1:
        sig = sig[:, None]
    feats: list[float] = []
    # per-lead morphology stats
    for j in range(sig.shape[1]):
        x = sig[:, j]
        feats += [float(x.mean()), float(x.std()), float(x.min()), float(x.max()),
                  float(np.percentile(x, 25)), float(np.percentile(x, 75)),
                  float(np.mean(np.abs(np.diff(x)))), float(np.sqrt(np.mean(x ** 2)))]
    # rhythm features from lead II (fallback to lead 0)
    lead2 = sig[:, _LEAD_II] if sig.shape[1] > _LEAD_II else sig[:, 0]
    feats += _rhythm_features(lead2, fs)
    return np.asarray(feats, dtype=np.float32)


def feature_names(n_leads: int = 12) -> list[str]:
    stat = ["mean", "std", "min", "max", "q25", "q75", "absdiff", "rms"]
    names = [f"lead{j}_{s}" for j in range(n_leads) for s in stat]
    names += ["hr_bpm", "rr_mean_ms", "rr_std_ms", "rmssd", "pnn50", "rr_cv", "n_peaks"]
    return names
