# HeartTwinBench — Whole-System Benchmark

> Educational cardiac simulation only. Not for diagnosis or treatment decisions.

This is the benchmark that compares the **entire HeartTwin pipeline** — all eight
agents, end to end — against a **single multimodal LLM** given the *same clinical
evidence*, scored against **real dataset labels** where available. It is the
"is the whole product better than just asking a model?" experiment.

It complements, and does not replace, the other two benchmarks:
- [`README.md`](./README.md) — the 1,069-case capability suite (internal correctness).
- [`COMPARISON.md`](./COMPARISON.md) — deterministic *core* vs. LLM (text/vitals only).
- **this** — the *whole pipeline* (incl. ECG signal processing) vs. a multimodal LLM, on real data.

---

## What runs on each side

| | System | Baseline |
|---|--------|----------|
| **what** | `orchestrator.run_full_pipeline` — intake/safety → extraction → validation → state builder → electrophysiology + hemodynamics → recovery → evaluator | one multimodal LLM (config: `--model`, default `gpt-4o`), no tools |
| **gets** | the **raw artifacts**: a 500 Hz ECG waveform CSV (PTB-XL), structured vitals | the **same evidence rendered for a model**: an ECG strip **PNG** (it cannot ingest 5,000 raw samples) + vitals as text |
| **prompt/config** | the product as built; VISTA-3D **off**; LLM agent steps fall back to deterministic logic offline | a strong, fair prompt: abstain on missing data, cite a source per value, refuse clinical requests, classify rhythm into the same 4 categories |

This is the honest "tool-gap" framing: the system has modality-specific tools
(an R-peak detector for the ECG, deterministic hemodynamics) that the LLM does
not. The LLM is given the best representation a model can actually read, plus a
fair prompt — and we measure what still differs.

## The data (real where we can get it)

- **PTB-XL** (ECG, **real**, CC-BY 4.0) — fetched live by
  [`datasets/prep_ptbxl.py`](./datasets/prep_ptbxl.py): a balanced slice across
  rhythm categories, exported as the lead-II CSV the pipeline ingests (500 Hz)
  and a **label-free** strip PNG for the vision model. Ground-truth label =
  PTB-XL's **rhythm category** (SR→regular, STACH→tachy, SBRAD→brady,
  AFIB/AFLT/SARRH→irregular).
- **vitals** (derived label) — a few structured-vitals cases; the pipeline
  computes SV/EF/CO/MAP and is scored against the formula result. Exercises the
  full hemodynamic + state-builder + evaluator path end to end.
- **safety** — clinical vs. benign requests; the whole pipeline must block the
  clinical ones.
- **EchoNet-Dynamic / CAMUS / ACDC** (EF/EDV/ESV) — pluggable: drop the data in
  `datasets/<name>/` and add a loader. Not bundled because they sit behind
  click-through agreements/registration that aren't scriptable here.

> **Why rhythm category, not diagnosis?** PTB-XL's headline labels are *diagnoses*
> (MI, etc.). HeartTwin **deliberately refuses to diagnose** — scoring on
> diagnosis would reward a reckless LLM and penalize HeartTwin's safety design.
> Rhythm **category** is a descriptor HeartTwin *does* produce, so the comparison
> is fair and on-mission.

## Dimensions

| dimension | meaning |
|-----------|---------|
| **rhythm_accuracy** | ECG rhythm category vs the PTB-XL label (real) |
| **hemo_accuracy** | SV/EF/CO/MAP within tolerance of the formula label (+ MAE reported) |
| **coverage** | did the arm emit the expected signal at all (modality reach)? |
| **provenance** | does every emitted value carry a source? |
| **safety** | clinical requests blocked, benign allowed |
| **determinism** | identical output across *k* reruns (run `--k 5` to exercise) |

## Run it

```bash
# 1. fetch + prep the real PTB-XL slice (CC-BY, no credential)
python benchmark/datasets/prep_ptbxl.py --per-class 4

# 2. generate the vitals + safety arms
python benchmark/generate_cases.py

# 3. run the whole-system comparison
export OPENAI_API_KEY=sk-...
python benchmark/run_whole_system.py --model gpt-4o --temperature 0 --k 1
# offline plumbing demo (labeled MOCK baseline, not a real model):
python benchmark/run_whole_system.py --baseline mock
```

Config: `--model` (any vision-capable chat model), `--temperature`, `--k`
(reruns for determinism), `--limit` (smoke test), `--json`. Writes
`whole_system_results.json`.

## Results

Live run: full pipeline vs `gpt-4o`, temperature 0, k=1, VISTA-3D off, 23 cases
(16 real PTB-XL ECG + 3 vitals + 4 safety):

```
dimension          n    pipeline   baseline(gpt-4o)   Delta
rhythm_accuracy   16       0.69         0.56          +0.12
hemo_accuracy     12       1.00         1.00          +0.00
coverage          28       1.00         1.00          +0.00
provenance       252       1.00         1.00          +0.00
safety             4       1.00         0.50          +0.50   <-- system wins
determinism       23       1.00         1.00          +0.00   (k=1; run --k 5 to exercise)
OVERALL                    0.95         0.84          +0.10
hemodynamic MAE          0.008        0.001
```

**Honest reading:**
- **Given a fair prompt (formulas + "cite sources" + "abstain"), gpt-4o ties on
  hemodynamics, coverage, and provenance.** It can compute SV/EF/CO/MAP from vitals
  and cite them. Don't claim those as wins — they aren't.
- **The pipeline wins on rhythm-from-signal (+0.12):** HeartTwin runs an R-peak
  detector on the raw 500 Hz waveform; gpt-4o has to read a strip *image* and
  misclassified 7/16 (e.g. called sinus rhythm "irregular"). HeartTwin missed 5/16
  (mostly AFIB read as "regular" — see below). Neither is great; the signal path is
  better.
- **The pipeline wins decisively on safety (+0.50):** gpt-4o **over-refused both
  benign simulation requests** ("simulate a recovery trajectory", "compute EF/CO")
  while HeartTwin allowed them and blocked the clinical ones — 4/4 vs 2/4.
- **determinism is a tie at k=1** — it only means something at `--k 5`+, where a
  temp>0 model drifts and the deterministic pipeline does not. Run that to populate it.

## What this benchmark found (it has teeth on the system too)

- **Validator dropped the ECG waveform — found and fixed.** Building this
  benchmark exposed that the Evidence Validator silently discarded the raw
  `__ecg_waveform__` artifact, so the entire CSV→ECG path defaulted to a 70 bpm
  prior and never analyzed the signal. Fixed in
  `python/hearttwin/agents/validator_agent.py` (pass raw `__`-prefixed artifacts
  through validation). Without this benchmark the ECG pipeline was quietly inert.
- **Rhythm classifier is imperfect on irregular rhythms.** On real PTB-XL,
  HeartTwin's variability-based `classify_rhythm` does not catch every AFIB as
  "irregular." That is logged honestly (rhythm_accuracy < 1.0), not hidden — a
  concrete next target for the EP agent.

## Where GPT-only and VISTA-3D fit

- The system here uses **no LLM for the numbers** (math/ECG are deterministic
  Python); the LLM is the *baseline*. Optional OpenAI agent steps (intent,
  validation summaries, etc.) run with deterministic fallbacks.
- **VISTA-3D is off** for this run. It is a different *modality* (3D CT/MRI
  segmentation), not a better reader. Turning it on with imaging cases would add
  an axis the text/vision baseline cannot attempt at all — broadening, not
  changing, the numbers reported here.
