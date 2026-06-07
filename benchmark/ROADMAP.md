# HeartTwinBench — Raising Pipeline Scores + the Diagnosis Question

> Educational cardiac simulation only. Not for diagnosis or treatment decisions.

Scoping report. Branch: `feat/pipeline-eval-and-diagnosis` (off
`feat/copilotkit-next-frontend`). No model/pipeline code changed yet — this is the
plan and the trade-offs.

## Where we are (whole-system run vs gpt-4o, k=1)

```
rhythm_accuracy  0.69   hemo 1.00   coverage 1.00   provenance 1.00   safety 1.00   determinism 1.00(k=1)
OVERALL 0.95  (baseline gpt-4o 0.84)
```

Only one dimension is actually low: **rhythm_accuracy (0.69)**. Everything else is
already at ceiling. So "getting the pipeline results up" is mostly one focused job
plus making the numbers statistically meaningful.

---

## Part A — Raising the existing scores

### A1. Rhythm accuracy 0.69 → ~0.90 (the real gap) — ~0.5–1 day
Root cause: `tools/ecg_features.classify_rhythm` is a crude RR-variability + HR-band
heuristic on a lightweight detector, evaluated on noisy real PTB-XL. It misses AFIB
(irregular → "regular") and some tachy/brady boundaries (5/16 misses).

Fixes, in order of payoff:
1. **Robust R-peak detection.** Replace the in-house Pan-Tompkins with a vetted
   detector (`neurokit2.ecg_peaks`, or `wfdb`/`scipy` with proper bandpass +
   baseline-wander removal). PTB-XL has real noise our toy filter doesn't handle.
2. **Real irregularity features.** Classify with RMSSD / pNN50 / sample-entropy
   thresholds instead of the current `variability_ratio > 0.25`. AFIB is
   *irregularly irregular* — entropy/pNN50 separates it cleanly.
3. **Calibrate, don't guess.** Split PTB-XL into train/test, fit the thresholds on
   train, report on held-out. Right now thresholds are eyeballed.
4. **Use >1 lead** (currently lead II only) for robustness.

Keep it deterministic (no LLM) so the determinism dimension stays 1.00.

### A2. Make the numbers meaningful — ~0.5 day
- Scale the real-label slice from 16 → a few hundred PTB-XL records
  (`prep_ptbxl.py --per-class N`). 16 cases is a demo, not a measurement.
- Add the EchoNet / CAMUS / ACDC EF/EDV/ESV loaders (data is access-gated; the
  loader + manifest is ready in `WHOLE_SYSTEM.md`).

### A3. Actually exercise determinism — trivial
Run `run_whole_system.py --k 5 --temperature 0.7` for the baseline. The pipeline
stays 1.00; a temp>0 LLM drifts. Currently k=1, so the dimension is a free tie.

**Part A total: ~1.5–2 days** to move rhythm to ~0.9 and make the suite credible.

---

## Part B — A diagnosis feature + a diagnosis-golden benchmark

This is the high-upside, high-care idea. Worth doing — *if* it's walled off
correctly.

### Why it's compelling
PTB-XL ships **21,799 records** labelled with **5 diagnostic superclasses**
(NORM, MI, STTC, CD, HYP) and 71 subclasses — the standard public ECG-diagnosis
benchmark, with **published SOTA (~0.93 macro-AUROC)** to compare against. MIMIC-IV-ECG
adds ~800k more. That turns our ECG arm from "4 rhythm categories, 16 cases" into
"real multi-label diagnosis, thousands of records, a number reviewers recognize."
And the head-to-head is brutal for the baseline: gpt-4o reading a *strip image*
will badly trail a trained 1-D CNN on multi-label ECG diagnosis — a large,
defensible delta.

### The catch (must be addressed head-on)
HeartTwin's entire identity is **"not a medical device; does not diagnose."** The
safety benchmark *rewards* refusing "what is my diagnosis?". Bolting diagnosis onto
the product would:
- contradict the safety positioning and break the safety dimension,
- make any shipped claim **Software as a Medical Device** (FDA/CE) — out of scope
  for a hackathon product,
- blur the line the whole design defends.

### The resolution: a walled-off *research classifier*, not a product feature
Keep the product exactly as-is (still blocks "tell me my diagnosis"). Add a
**separate, clearly-labeled research module** used **only for benchmarking**:
- `research/ecg_dx/` — a 1-D CNN/ResNet trained on PTB-XL superclasses (reference
  implementations hit ~0.93 macro-AUROC; ~1–2 days incl. training + eval, GPU
  helpful, CPU workable for a small net).
- Outputs **class probabilities for evaluation**, never phrased as advice to a
  person. The distinction we hold: *"classify this record's superclass for
  research scoring"* (allowed, batch, labelled RESEARCH-ONLY) vs *"tell me, the
  patient, my diagnosis"* (still blocked in the product). These are different acts.
- A new benchmark arm: the research classifier vs PTB-XL labels (**macro-AUROC,
  macro-F1**) **and** vs the gpt-4o-from-image baseline. Report both.
- The safety benchmark is unchanged and still passes — the product still refuses.
  Add one assertion: the research model is never reachable from the user/product
  path.

### Build plan (Part B) — ~2–3 days
1. Full PTB-XL download (~3 GB) + the standard 10-fold split (strat by patient).
2. Train a small 1-D CNN on records100 superclasses; target macro-AUROC ≥ 0.90.
3. `run_dx_benchmark.py`: classifier vs labels (AUROC/F1) + gpt-4o-image baseline,
   same adapter/grader pattern we already have.
4. Wall + label: `RESEARCH ONLY — not a medical device, not user-facing` on every
   surface; a test asserting the product path can't import it as advice.

### Honest risks
- **Real ML work**, not a prompt: class imbalance, leakage-free splits, calibration.
- **Framing risk**: if presented as "HeartTwin now diagnoses," it undermines the
  safety story that's currently a *strength*. Present it as "we also built and
  benchmarked a research ECG classifier; the product itself still refuses to
  diagnose — by design."
- Don't score the product against diagnosis labels — only the walled research model.

---

## Recommendation

1. **Do Part A first** (1.5–2 days): it's cheap, lifts the one weak number, and
   makes the suite statistically real.
2. **Do Part B as a clearly-walled research arm** (2–3 days): it's the most
   *compelling* benchmark you can show (real labels, known SOTA, big LLM delta) —
   but only if the product keeps refusing diagnosis and the research model is
   labelled and isolated. Done that way it strengthens the story ("we measured both,
   and chose safety for the product") instead of undermining it.
