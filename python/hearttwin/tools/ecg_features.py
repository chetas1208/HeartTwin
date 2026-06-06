"""ECG signal feature extraction.

Implements a lightweight Pan-Tompkins-style R-peak detector for CSV waveform data.
Falls back to report-extracted values when waveform is unavailable.
Never infers rhythm from images alone without high confidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EcgFeatures:
    rr_intervals_ms: list[float]
    mean_rr_ms: float
    heart_rate_bpm: float
    qrs_duration_ms: Optional[float]
    qt_interval_ms: Optional[float]
    qtc_ms: Optional[float]
    r_peak_indices: list[int]
    r_peak_count: int
    rhythm_descriptor: str
    r_peak_confidence: float
    arrhythmia_instability_score: float
    conduction_delay_score: float
    warnings: list[str] = field(default_factory=list)
    method: str = "waveform_analysis"


def _bandpass_filter_simple(signal: list[float], low_cutoff: float = 5.0, high_cutoff: float = 15.0, fs: float = 500.0) -> list[float]:
    """Very lightweight moving-average bandpass approximation.
    Not a clinical-grade filter. For educational simulation only.
    """
    window_low = max(1, int(fs / high_cutoff))
    window_high = max(1, int(fs / low_cutoff))

    def moving_avg(s: list[float], w: int) -> list[float]:
        out = []
        for i in range(len(s)):
            start = max(0, i - w // 2)
            end = min(len(s), i + w // 2 + 1)
            out.append(sum(s[start:end]) / (end - start))
        return out

    low_freq = moving_avg(signal, window_high)
    high_freq = moving_avg(signal, window_low)
    return [h - l for h, l in zip(high_freq, low_freq)]


def _derivative(signal: list[float]) -> list[float]:
    """First-order finite difference derivative."""
    out = [0.0] * len(signal)
    for i in range(1, len(signal) - 1):
        out[i] = (signal[i + 1] - signal[i - 1]) / 2.0
    return out


def _squared(signal: list[float]) -> list[float]:
    return [x * x for x in signal]


def _moving_window_integration(signal: list[float], window: int) -> list[float]:
    out = []
    cumsum = [0.0] * (len(signal) + 1)
    for i, v in enumerate(signal):
        cumsum[i + 1] = cumsum[i] + v
    for i in range(len(signal)):
        start = max(0, i - window + 1)
        out.append((cumsum[i + 1] - cumsum[start]) / (i - start + 1))
    return out


def detect_r_peaks(
    signal: list[float],
    sampling_rate_hz: float = 500.0,
    refractory_ms: float = 200.0,
) -> tuple[list[int], float]:
    """Lightweight Pan-Tompkins-inspired R-peak detector.

    Returns (peak_indices, confidence_score).
    Confidence is approximate — do not use for clinical interpretation.
    """
    if len(signal) < 10:
        return [], 0.0

    filtered = _bandpass_filter_simple(signal, fs=sampling_rate_hz)
    deriv = _derivative(filtered)
    sq = _squared(deriv)
    window_samples = max(1, int(0.15 * sampling_rate_hz))
    integrated = _moving_window_integration(sq, window_samples)

    if not integrated or max(integrated) == 0:
        return [], 0.0

    threshold = max(integrated) * 0.35

    refractory_samples = int((refractory_ms / 1000.0) * sampling_rate_hz)
    peaks: list[int] = []
    last_peak = -refractory_samples

    for i in range(1, len(integrated) - 1):
        if (
            integrated[i] > threshold
            and integrated[i] > integrated[i - 1]
            and integrated[i] > integrated[i + 1]
            and (i - last_peak) >= refractory_samples
        ):
            search_start = max(0, i - window_samples // 2)
            search_end = min(len(signal), i + window_samples // 2)
            local_max_idx = search_start + signal[search_start:search_end].index(
                max(signal[search_start:search_end])
            )
            peaks.append(local_max_idx)
            last_peak = i

    duration_s = len(signal) / sampling_rate_hz
    expected_beats = duration_s * 1.5
    confidence = min(1.0, len(peaks) / max(1, expected_beats)) if expected_beats > 0 else 0.0
    confidence = max(0.1, confidence) if peaks else 0.0

    return peaks, round(confidence, 3)


def compute_rr_intervals(peak_indices: list[int], sampling_rate_hz: float) -> list[float]:
    """Compute RR intervals in milliseconds from peak indices."""
    if len(peak_indices) < 2:
        return []
    rr = []
    for i in range(1, len(peak_indices)):
        interval_ms = (peak_indices[i] - peak_indices[i - 1]) / sampling_rate_hz * 1000.0
        rr.append(round(interval_ms, 1))
    return rr


def compute_qtc_bazett(qt_ms: float, mean_rr_ms: float) -> float:
    """QTc = QT / sqrt(RR in seconds)."""
    if mean_rr_ms <= 0:
        raise ValueError("RR must be positive")
    rr_s = mean_rr_ms / 1000.0
    return round(qt_ms / math.sqrt(rr_s), 1)


def classify_rhythm(mean_rr_ms: float, rr_variability_ms: float) -> str:
    """Return a simulation-safe rhythm descriptor based on computed intervals.
    Never claims clinical diagnosis.
    """
    hr = 60000.0 / max(mean_rr_ms, 100.0)
    variability_ratio = rr_variability_ms / max(mean_rr_ms, 1.0)

    if variability_ratio > 0.25:
        return "simulated irregular rhythm pattern"
    elif hr < 50:
        return "simulated bradycardic rhythm pattern"
    elif hr > 100:
        return "simulated tachycardic rhythm pattern"
    else:
        return "simulated regular sinus-like rhythm pattern"


def compute_arrhythmia_instability(rr_intervals_ms: list[float]) -> float:
    """Compute arrhythmia instability score from RR variability.
    Returns value in [0, 1]. Higher = more irregular.
    """
    if len(rr_intervals_ms) < 2:
        return 0.0
    mean_rr = sum(rr_intervals_ms) / len(rr_intervals_ms)
    rmssd = math.sqrt(
        sum((rr_intervals_ms[i] - rr_intervals_ms[i - 1]) ** 2 for i in range(1, len(rr_intervals_ms)))
        / (len(rr_intervals_ms) - 1)
    )
    score = min(1.0, rmssd / mean_rr)
    return round(score, 4)


def analyze_waveform(
    signal: list[float],
    sampling_rate_hz: float = 500.0,
    qrs_duration_ms: Optional[float] = None,
    qt_ms: Optional[float] = None,
) -> EcgFeatures:
    """Full ECG waveform analysis pipeline.
    Returns EcgFeatures with simulation-safe descriptors.
    """
    warnings: list[str] = []

    peaks, confidence = detect_r_peaks(signal, sampling_rate_hz)

    if len(peaks) < 2:
        warnings.append("Insufficient R peaks detected — ECG metrics unavailable from waveform")
        return EcgFeatures(
            rr_intervals_ms=[],
            mean_rr_ms=0.0,
            heart_rate_bpm=0.0,
            qrs_duration_ms=qrs_duration_ms,
            qt_interval_ms=qt_ms,
            qtc_ms=None,
            r_peak_indices=peaks,
            r_peak_count=len(peaks),
            rhythm_descriptor="insufficient data for rhythm estimation",
            r_peak_confidence=0.0,
            arrhythmia_instability_score=0.0,
            conduction_delay_score=0.0,
            warnings=warnings,
            method="waveform_analysis_insufficient_data",
        )

    rr_intervals = compute_rr_intervals(peaks, sampling_rate_hz)
    mean_rr = sum(rr_intervals) / len(rr_intervals)
    hr = 60000.0 / mean_rr

    rr_std = math.sqrt(sum((r - mean_rr) ** 2 for r in rr_intervals) / len(rr_intervals))
    arrhythmia_score = compute_arrhythmia_instability(rr_intervals)
    rhythm = classify_rhythm(mean_rr, rr_std)

    qtc = None
    if qt_ms is not None:
        qtc = compute_qtc_bazett(qt_ms, mean_rr)

    conduction_delay = 0.0
    if qrs_duration_ms is not None:
        if qrs_duration_ms > 120:
            conduction_delay = min(1.0, (qrs_duration_ms - 120) / 80.0)

    return EcgFeatures(
        rr_intervals_ms=rr_intervals,
        mean_rr_ms=round(mean_rr, 1),
        heart_rate_bpm=round(hr, 1),
        qrs_duration_ms=qrs_duration_ms,
        qt_interval_ms=qt_ms,
        qtc_ms=qtc,
        r_peak_indices=peaks,
        r_peak_count=len(peaks),
        rhythm_descriptor=rhythm,
        r_peak_confidence=confidence,
        arrhythmia_instability_score=arrhythmia_score,
        conduction_delay_score=round(conduction_delay, 4),
        warnings=warnings,
        method="waveform_analysis",
    )
