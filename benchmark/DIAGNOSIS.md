# HeartTwinBench — Diagnosis (Research ECG Classifier)

> HeartTwin Lab is **not a medical tool / not a medical device**. The classifier
> below is an **experimental research screening** output, **not a diagnosis** and
> not medical advice. Every result carries that disclaimer.

This adds a *diagnosis* capability so the system can be scored on a real,
diagnostic-label benchmark (PTB-XL diagnostic superclasses) — the most compelling
ECG benchmark available. It is **user-reachable** (an API endpoint) with a
mandatory disclaimer, and evaluated against real labels.

## What it is

A research classifier that maps a 12-lead ECG to probabilities over the five
PTB-XL **diagnostic superclasses**:

| code | meaning |
|------|---------|
| NORM | Normal ECG |
| MI   | Myocardial infarction pattern |
| STTC | ST/T change pattern |
| CD   | Conduction disturbance pattern |
| HYP  | Hypertrophy pattern |

Pipeline: deterministic feature extraction (`research/ecg_dx/features.py` —
per-lead morphology stats + RR/HR rhythm features) → a multi-label OneVsRest
random forest (`research/ecg_dx/classifier.py`). It is intentionally a **scaffold**
(feature-based, ~290 training records) — see "Improving it" for the path to SOTA.

## Results (held-out PTB-XL test split, n=97)

```
research classifier:  macro-AUROC = 0.836   macro-F1 = 0.493
  per-class AUROC:  NORM 0.92   CD 0.91   HYP 0.89   MI 0.80   STTC 0.65
gpt-4o (reads ECG strip image):  macro-AUROC = 0.566   macro-F1 = 0.155
                                 Delta macro-AUROC = +0.270  (system)
```

This is the compelling head-to-head: a small trained signal classifier beats
gpt-4o-vision reading the ECG strip by **+0.27 macro-AUROC** — and gpt-4o at 0.566
is barely above random (0.5). A generalist looking at a picture of an ECG cannot
do multi-label diagnostic screening; a model trained on the waveform can.

Context: deep models on the full 21k-record PTB-XL reach ~0.93 macro-AUROC. 0.84
from a feature-based RF on ~290 records is a solid scaffold and a clear baseline to
beat.

## User-reachable endpoint (with disclaimer)

```
POST /api/v1/ecg/diagnose      (multipart: file=<ECG CSV>)
```

Accepts a `time_ms,ecg` single-lead CSV (placed at lead II) or a 12-lead matrix.
Returns per-superclass probabilities, flagged classes, and **two disclaimers**
(the research-screening disclaimer + the standard HeartTwin safety disclaimer):

```json
{
  "task": "ecg_superclass_screening",
  "probabilities": {"NORM": 0.24, "MI": 0.29, "STTC": 0.50, "CD": 0.31, "HYP": 0.21},
  "flagged": ["STTC"],
  "disclaimer": "RESEARCH SCREENING OUTPUT — NOT A DIAGNOSIS. ...",
  "safety_disclaimer": "Educational cardiac simulation only. ..."
}
```

The trained `model.joblib` ships with the repo, so the endpoint works out of the
box. If absent, it returns 503 with instructions to train.

## Run / reproduce the benchmark

```bash
# 1. fetch PTB-XL diagnostic slice (CC-BY; ~8 MB of waveforms)
python benchmark/datasets/prep_ptbxl_dx.py --per-class 100
# 2. train (saves model.joblib + held-out split)
python -m python.hearttwin.research.ecg_dx.train
# 3. score vs PTB-XL labels  (+ optional gpt-4o-from-image baseline)
python benchmark/run_dx_benchmark.py
python benchmark/run_dx_benchmark.py --llm-baseline --model gpt-4o --limit 20
```

The `--llm-baseline` arm renders each ECG as a strip image and asks a vision LLM
for the same superclass probabilities — the head-to-head where a trained signal
model is expected to lead an image-reading generalist by a wide margin.

## Safety / framing

HeartTwin is *allowed* to do this — it only has to be marked as not a medical tool.
So the classifier is user-reachable, but **every** output is labelled research /
not-a-diagnosis, and the standard safety disclaimer is attached. The product makes
no clinical claim; it surfaces model probabilities for an educational/research
screening task.

## Improving it (scaffold → strong)

1. **Full PTB-XL** (`--per-class 2000`+, all 21k records, the standard 10-fold
   patient-stratified split).
2. **A 1-D CNN/ResNet** on the raw waveforms instead of features (the published
   PTB-XL SOTA architecture; ~0.93 macro-AUROC).
3. **Subclasses** (71-way) and **MIMIC-IV-ECG** for scale.
4. Calibrated thresholds + per-class operating points.

## Files

```
benchmark/datasets/prep_ptbxl_dx.py          # PTB-XL diagnostic-label slice -> dx_dataset.npz
benchmark/run_dx_benchmark.py                # classifier vs PTB-XL labels (+ LLM baseline)
python/hearttwin/research/ecg_dx/
  features.py                                # deterministic ECG features
  classifier.py                              # load model, classify() + DISCLAIMER
  train.py                                   # train OneVsRest RF, save model.joblib
  model.joblib                               # shipped trained model (endpoint works as-is)
python/hearttwin/api.py  ->  POST /api/v1/ecg/diagnose
```
