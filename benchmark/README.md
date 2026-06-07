# HeartTwin Lab — Benchmark

> Educational cardiac simulation only. Not for diagnosis or treatment decisions.

HeartTwinBench has **two halves**:

1. **Capability suite** (`run_benchmark.py`) — 1,069 cases, gated, CI-style
   pass/fail against the product's own code. Proves the system is internally
   correct. (Sections below.)
2. **Head-to-head comparison** (`run_compare.py`) — runs HeartTwin **and a
   baseline LLM** through one shared adapter interface and one shared grader,
   across six capability dimensions, and reports the *delta*. Proves the system
   is **better than a raw LLM** at the thing it claims. ([jump ↓](#head-to-head-hearttwin-vs-baseline-llm))

> **New to this?** Read **[`COMPARISON.md`](./COMPARISON.md)** — a plain-language
> explainer of *exactly* what is and isn't compared (deterministic core vs full
> pipeline, whether ECG/imaging were used, and where GPT vs VISTA-3D fit in).

3. **Whole-system comparison** (`run_whole_system.py`) — the **entire 8-agent
   pipeline** (incl. real ECG signal processing) vs. a **multimodal LLM** given the
   same evidence, scored against **real PTB-XL labels**. See
   **[`WHOLE_SYSTEM.md`](./WHOLE_SYSTEM.md)**. Headline (vs `gpt-4o`): overall
   0.95 vs 0.84; wins on rhythm-from-signal (+0.12) and safety (+0.50); ties on
   hemodynamics/provenance when the LLM is fairly prompted.

4. **Diagnosis** (`run_dx_benchmark.py`) — a **research ECG classifier** scored on
   **real PTB-XL diagnostic-superclass labels** (NORM/MI/STTC/CD/HYP), user-reachable
   via `POST /api/v1/ecg/diagnose` with a disclaimer. See
   **[`DIAGNOSIS.md`](./DIAGNOSIS.md)**. Scaffold result: macro-AUROC 0.836 (deep
   SOTA on full PTB-XL ~0.93). Not a medical device.

---

A reproducible benchmark for HeartTwin Lab with **1,069 cases** across five tasks.
It runs the product's own code — the deterministic cardiac engine, the ECG
waveform analyzer, the report extractor, the safety boundary, **and the full
8-agent orchestrator** — against ground truth computed *independently* of the
product. No API keys and no network access are required: every path runs offline
on deterministic algorithms / local fallbacks, so the score is reproducible and
any regression in the engine moves it.

## Tasks

| # | Task | n | Product code under test | Dataset grounding | What it proves |
|---|------|--:|------------------------|-------------------|----------------|
| 1 | **hemodynamics** | 600 | `tools/cardiac_state.py` (SV/EF/CO/MAP) | EchoNet-Dynamic, CAMUS, ACDC volume ranges | Formula engine reproduces canonical values across normal → DCM physiology |
| 2 | **ecg** | 287 | `tools/ecg_features.py` (R-peak, Bazett QTc) | PTB-XL waveforms + QTc sweep | Heart rate recovered from raw signal; QTc matches Bazett reference |
| 3 | **extraction** | 120 | `tools/pdf_extract.py` (regex parser) | MIMIC-IV-Note-style synthetic reports | Reported fields are extracted **and** missing fields are *not* invented |
| 4 | **safety** | 55 | `safety.py` (`check_request_safety`) | adversarial vs. benign prompts | Diagnosis/treatment/dosing/triage requests block; simulation requests pass |
| 5 | **pipeline** | 7 | `orchestrator.run_full_pipeline` (8 agents) | end-to-end scenarios | The **agentic pipeline** orchestrates all stages, preserves determinism, evaluates, and enforces the safety gate end-to-end |

Each task mixes **positive and negative** ground truth (volumes that must parse
vs. must stay null; prompts that must block vs. must pass) so the score can't be
gamed by always-emit or always-block behavior.

## Task 5 — how the agenticness is tested

The first four tasks score individual tools. Task 5 runs the **whole multi-agent
harness** (`run_full_pipeline`) offline, once per scenario, and asserts the
properties that only emerge from orchestration:

- **All stages ran** — every required agent appears in `agent_responses`
  (intake → extraction → validator → state-builder → electrophysiology +
  hemodynamics → recovery → evaluator).
- **Determinism survives the handoffs** — the EF/SV in the orchestrated
  `CardiacTwinState` still equals the value computed straight from the input
  volumes (agents never silently mutate the math).
- **Provenance flows through** — `source_map` is populated end-to-end.
- **Evals are produced and pass** — the evaluator returns `passed`, with overall
  score and safety-compliance above threshold.
- **Recovery + trace wired** — recovery scenarios and trace events are emitted.
- **Safety gate holds end-to-end** — a clinical request (diagnosis / dosing /
  emergency) makes the *entire pipeline* return `status: "blocked"`.

These are kept to a handful of scenarios because each one is a full pipeline run
(~40–60 ms offline); together they cover normal, HFrEF, dilated, and
hyperdynamic physiology plus three must-block requests.

## Run it

```bash
# 1. (re)generate the case suite — deterministic, ~instant
python benchmark/generate_cases.py

# 2. run the benchmark
python benchmark/run_benchmark.py            # human scorecard
python benchmark/run_benchmark.py --json     # machine-readable JSON
```

On Windows use the `py` launcher: `py benchmark\generate_cases.py` then
`py benchmark\run_benchmark.py`.

Exit code is `0` only if **every gate passes**, so it drops straight into CI.
Full results (every case, every check) are written to `benchmark/results.json`.

Example:

```
  hemodynamics  [####################] 1.00  (gate 1.00) PASS   pass 100%  MAE 1e-05            | n=600
  ecg           [####################] 1.00  (gate 0.95) PASS   pass 100%  HR_MAE 0.0  QTc 0.0  | n=287
  extraction    [###################-] 0.96  (gate 0.85) PASS   P 0.92  R 1.00  F1 0.96         | n=120
  safety        [####################] 1.00  (gate 1.00) PASS   block accuracy 100%             | n=55
  pipeline      [####################] 1.00  (gate 1.00) PASS   pass 100% (full 8-agent runs)   | n=7
  OVERALL       0.994   ALL GATES PASS
```

## Scoring & gates

| Task | Metric | Weight | Gate |
|------|--------|-------:|-----:|
| hemodynamics | fraction within tight formula tolerance (EF ±0.5%, SV ±0.1mL, CO ±0.05, MAP ±0.1) | 0.30 | **1.00** |
| ecg | fraction within HR ±3 bpm / QTc ±3ms (waveform), ±0.5ms (Bazett) | 0.20 | 0.95 |
| extraction | field-level **F1** over present (must extract) + absent (must not invent) | 0.15 | 0.85 |
| safety | block-decision accuracy | 0.15 | **1.00** |
| pipeline | fraction of end-to-end runs passing all orchestration checks | 0.20 | **1.00** |

Overall = weighted sum. The deterministic-math and safety gates are **1.00** — a
single wrong digit or an unblocked clinical request fails the suite.

## What the benchmark found (it is not a rubber stamp)

- **Safety regex gap — found and fixed.** The suite caught that
  `check_request_safety` did **not** block "prescribe": the pattern
  `\bprescrib\b` cannot match the trailing "e". Fixed to `\bprescrib\w*\b` in
  `python/hearttwin/safety.py` (now also covers prescribed/prescribing). The
  `block_13_*` cases keep it covered.
- **Extraction false-positive — open, surfaced.** The regex parser extracts
  `stroke_volume_ml` from the `sv` substring inside `ESV: <n> mL`, so it invents
  an SV that was never reported (60 of the 120 cases). The benchmark records each
  as `invented:stroke_volume_ml` rather than hiding it; extraction still clears
  its gate (F1 0.96). Fix candidate: anchor the SV pattern so it can't match
  inside `esv`.

## Head-to-head: HeartTwin vs. baseline LLM

The capability suite proves HeartTwin is *internally* correct. The comparison
harness answers the question judges actually ask — **is it better than just
prompting GPT-N?** — by scoring both the same way.

### Architecture (one interface, one grader)

```
case = { input: {report_text? | vitals? | request_text?},
         gold:  {present, absent, flags, must_block} }

         ┌─────────────────────────┐
case ──► │ system_adapter.infer()  │ ─┐   HeartTwin's real deterministic core
         └─────────────────────────┘  │   (pdf_extract, cardiac_state, safety)
         ┌─────────────────────────┐  ├─► grader.grade_case()  ──►  6 dimensions
case ──► │ baseline_adapter.infer()│ ─┘   GPT-N with a FAIR JSON prompt
         └─────────────────────────┘       (or an offline mock)
```

Both adapters emit the identical `AdapterOutput` schema
(`measurements{field:{value,source,confidence}}`, `blocked`, `flags`), so
`grader.py` cannot treat them differently.

### The six dimensions (what we point to)

| Dimension | Question | Why an LLM struggles |
|-----------|----------|----------------------|
| **numeric** | are stated/derivable values correct? | (closest; tools tie here) |
| **abstention** | are *missing* values left out, not invented? | LLMs fill from "typical" priors |
| **provenance** | does every value carry a source? | LLMs emit bare numbers |
| **consistency** | are EF↔volume / conflict / BP-order issues flagged? | LLMs parrot stated values |
| **safety** | are clinical requests refused? | un-system-prompted LLMs answer |
| **determinism** | identical output across *k* reruns? | temp>0 LLMs drift |

`determinism` runs each case `k` times and checks the output fingerprint is
identical every time. HeartTwin is provably **1.00** (deterministic); an LLM at
any temperature > 0 is not.

### Run it

```bash
# Offline plumbing demo (no key) — baseline is a labeled MOCK, not a real model:
python benchmark/run_compare.py --baseline mock

# Real comparison against an actual model:
export OPENAI_API_KEY=sk-...
python benchmark/run_compare.py --baseline openai --model gpt-4o-mini --k 5 --temperature 0.7
python benchmark/run_compare.py --json          # machine-readable; writes compare_results.json
```

Flags: `--baseline {openai,mock}` · `--model` · `--temperature` · `--k` (reruns).
Defaults to `openai` if `OPENAI_API_KEY` is set, else `mock`.

Example (mock baseline — illustrates the shape; real numbers need `--baseline openai`):

```
  dimension      n   HeartTwin   baseline    Delta
  numeric       51       0.98       ...      ...
  abstention    18       1.00       ...      +...  <-- system wins
  provenance    92       1.00       ...      +...  <-- system wins
  consistency    4       1.00       ...      +...  <-- system wins
  safety        12       1.00       ...      +...  <-- system wins
  determinism   28       1.00       ...      +...
  OVERALL                1.00       ...      +...
```

### Fairness (so the comparison holds up)

- **The baseline prompt is strong, not a strawman.** It explicitly tells the
  model to abstain on missing data, cite a source per value, flag
  inconsistencies, and refuse clinical requests (see `baseline_adapter._SYSTEM_PROMPT`).
  The claim is that *even well-prompted*, a raw LLM still hallucinates, drifts,
  and mis-sources more than the harness.
- **Identical grader, schema, tolerances, and cases** for both sides.
- **Reproducible:** the run records model, temperature, and `k`.
- **Matchup stated plainly:** LLM-only vs. LLM-grounded deterministic harness.
  The honest edges are abstention, provenance, consistency, safety, determinism —
  not raw arithmetic (where a tool-using LLM can tie).
- **`mock` is never a headline number.** It is an offline stand-in that lacks
  provenance/safety *by construction* to exercise the plumbing; it is labeled
  `[MOCK]` in the output and in `compare_results.json`.

### What this half found

The `robust_1` case shows the suite has teeth against the *system* too: HeartTwin
misses diastolic BP when it is written as the long form "Blood Pressure: 145/92"
(the regex only has a diastolic pattern for the short "BP:" form). Logged as a
numeric miss (system numeric 0.98, not 1.00) rather than hidden. Fix candidate:
add a `blood\s*pressure ... /(\d+)` diastolic pattern in `tools/pdf_extract.py`.

## Files

```
benchmark/
  __init__.py               # makes benchmark an importable package
  generate_cases.py         # deterministic generator -> writes all 6 case files
  run_benchmark.py          # capability suite: real product code, gated, -> results.json
  run_compare.py            # head-to-head: system vs baseline, 6 dims, -> compare_results.json
  grader.py                 # shared capability grader (5 per-case dims; determinism in runner)
  adapters/
    common.py               # AdapterOutput / Measurement (shared schema + fingerprint)
    system_adapter.py       # HeartTwin's real deterministic core
    baseline_adapter.py     # GPT-N (fair prompt) + offline mock
  cases/
    hemodynamics.jsonl      # 600  EchoNet/CAMUS/ACDC volumes -> SV/EF/CO/MAP
    ecg.jsonl               # 287  PTB-XL waveforms + Bazett QTc sweep
    extraction.jsonl        # 120  MIMIC-Note-style reports (present/absent ground truth)
    safety.jsonl            #  55  adversarial + benign prompts
    pipeline.jsonl          #   7  full 8-agent end-to-end scenarios
    compare.jsonl           #  28  capability-grouped, system-vs-baseline
  data/
    ecg_synthetic_normal.csv  # ~72 bpm waveform (self-contained)
    ecg_synthetic_fast.csv    # ~120 bpm waveform
  results.json              # capability suite output (git-ignored)
  compare_results.json      # comparison output (git-ignored)
```

Self-contained and zippable: `zip -r hearttwin-benchmark.zip benchmark`
(or `Compress-Archive benchmark hearttwin-benchmark.zip`). Extracted inside the
repo it runs as-is (it imports `python/hearttwin/...`).

## Ground truth is independent

Ground truth is computed in `generate_cases.py` from the documented formulas
(`SV=EDV−ESV`, `EF=SV/EDV·100`, `CO=HR·SV/1000`, `MAP=DBP+(SBP−DBP)/3`), Bazett
(`QTc=QT/√(RR/1000)`), and known template values — **never** by calling the code
under test. So the benchmark catches drift instead of agreeing with bugs.

## Extending with real dataset rows

The case format is plain JSONL — real data drops straight in, no code change:

- **EchoNet-Dynamic** — each `FileList.csv` row has `EDV`/`ESV`/`EF`; add a
  `hemodynamics.jsonl` line (widen the EF tolerance if scoring against the
  dataset's Simpson's-method EF rather than the volume-derived EF).
- **PTB-XL** — export a single-lead strip to `time_ms,lead_ii_mv` CSV under
  `data/`, set `expected.heart_rate_bpm` from the header, add an `ecg.jsonl`
  `type: waveform` line.
- **MIMIC-IV-Note** — paste a de-identified report into `extraction.jsonl` with
  expected present/absent fields. Credentialed data stays local; do not commit PHI.

Credentialed datasets (MIMIC) are intentionally **not** bundled — the suite ships
with synthetic, non-PHI fixtures so it runs anywhere, treating MIMIC as a
*future production-validation* path, consistent with `docs/datasets.md`.
