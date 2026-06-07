# What HeartTwinBench Actually Compares

> Educational cardiac simulation only. Not for diagnosis or treatment decisions.

This document explains, for someone who has never seen this benchmark, **exactly
what `run_compare.py` puts head-to-head with GPT-4o-mini** — and, just as
importantly, what it does *not*. Read this before quoting any number.

---

## 1. The one-sentence version

The comparison feeds the **same cardiac inputs** (a report, a set of vitals, or a
user request) to two things — **HeartTwin's deterministic grounding layer** and a
**plain GPT-4o-mini given a fair prompt** — and grades both with the **same
grader** on six reliability dimensions. It measures whether *grounding extraction,
math, consistency-checking, and safety in deterministic code* beats *asking a good
LLM to do the same job*.

It is a test of **reliability**, not of who is the smarter reader.

---

## 2. "HeartTwin" means two different things — know which one is being tested

There are two distinct systems people call "HeartTwin", and the benchmark tests
them in two different places.

### (A) The production pipeline — the full product

This is what runs when you use the app. It is an **8-agent orchestrator**
(`python/hearttwin/orchestrator.py`) that runs in stages:

| Stage | Agent | What it does | Uses an LLM? |
|------|-------|--------------|--------------|
| 1 | Intake & Safety | classify intent, enforce the safety boundary | optional GPT, **rule fallback** |
| 2 | Multimodal Extraction | pull values from PDF / image / CSV / text | **no** (regex + signal code; vision optional for images) |
| 3 | Evidence Validator | sanity-check extracted values | optional GPT, **rule fallback** |
| 4 | Cardiac State Builder | assemble the canonical `CardiacTwinState` | optional GPT, **rule fallback** |
| 5a | Electrophysiology | analyze the ECG waveform (R-peaks, QTc, rhythm) | **no** (deterministic DSP) |
| 5b | Hemodynamics | compute SV/EF/CO/MAP, build the PV loop | **no** (deterministic formulas) |
| 6 | Recovery Orchestration | simulate bounded recovery trajectories | optional GPT, **rule fallback** |
| 7 | Evaluator & Critic | score the run (safety, plausibility, etc.) | optional GPT, **rule fallback** |

Key point: **the numbers are never produced by an LLM.** Math is pure Python; the
LLM (when configured) only does soft reasoning like intent classification, and
*every* LLM step has a deterministic fallback, so the product runs fully offline.

### (B) The deterministic core — what the *comparison* tests

`run_compare.py`'s "HeartTwin" column does **not** run the 8-agent orchestrator.
It runs the **deterministic functions the agents wrap**, directly and offline
(`benchmark/adapters/system_adapter.py`):

- report text → `tools/pdf_extract._extract_cardiac_values` (the real regex parser)
- vitals → `agents/extraction_agent._extract_user_vitals` (the real sourced wrap)
- SV/EF/CO/MAP → `tools/cardiac_state` (the real formulas)
- EF↔volume / conflict / BP-order → `tools/cardiac_state.check_ef_consistency` + guards
- clinical request → `safety.check_request_safety` (the real safety boundary)

**No LLM is called on the HeartTwin side of the comparison.** That is deliberate:
it is the only way to make the determinism claim meaningful (you cannot ask
"is this run-to-run identical?" of a system that itself calls a sampling LLM), and
it isolates the actual question — *does deterministic grounding beat a raw LLM?*

> So the honest headline is **not** "HeartTwin-the-product vs GPT." It is
> **"HeartTwin's deterministic grounding layer vs GPT-4o-mini."** That layer is
> precisely the thing the product adds *on top of* an LLM, which is what makes the
> comparison fair and meaningful.

---

## 3. Walk-through of one case (both sides, start to finish)

Take an abstention case. Input:

```
"Heart rate: 80 bpm. BP: 128/82 mmHg. Reported ejection fraction: 55%.
 SpO2: 97%. Volumes not reported."
gold: present = {heart_rate_bpm:80, ejection_fraction_pct:55}
      absent  = [edv_ml, esv_ml, stroke_volume_ml]
```

**HeartTwin side:** the regex parser extracts HR 80, BP 128/82, EF 55, SpO2 97,
each tagged with a `source`. There are no volumes in the text, so it emits
nothing for EDV/ESV/SV and does not compute SV (it refuses to invent). Output is
identical every run.

**GPT side:** the same text goes to GPT-4o-mini with a prompt that explicitly
says "if a value is not stated and cannot be computed, set it to null — never
guess; cite a source for every value; refuse clinical requests." GPT returns its
own JSON in the same schema.

**Grader (identical for both):** numeric = did stated values come back correct?
abstention = were the absent fields left out? provenance = does every emitted
value carry a source? The case is run **k=5 times** and the outputs are
fingerprinted to check determinism.

---

## 4. Is the multi-agent pipeline being tested?

**Not in the comparison.** The comparison tests the deterministic core (§2B), not
the orchestrator.

**Yes, elsewhere.** The *capability suite* (`run_benchmark.py`) has a dedicated
`pipeline` task (`cases/pipeline.jsonl`) that runs the **full 8-agent
orchestrator end-to-end** (`run_full_pipeline`) and asserts: all eight stages
ran, EF/SV stay deterministic through the agent hand-offs, provenance flows
through, the evaluator passes, recovery scenarios + traces are produced, and a
clinical request blocks the whole pipeline. That task ran **offline** (no key),
so it also demonstrates the agents' deterministic fallbacks work.

If you want a head-to-head of the *whole agentic pipeline* vs an LLM agent, that
is a deliberate future extension (see §7) — it would add the orchestration
overhead to both sides and is a different, heavier experiment.

---

## 5. Was ECG given? Would it help?

**No ECG was given in the comparison.** Every `compare.jsonl` case is report
text, structured vitals, or a request string. There are no waveforms.

ECG *is* tested — but in the capability suite (`cases/ecg.jsonl`, 287 cases)
against the real `tools/ecg_features.analyze_waveform`, where HeartTwin recovers
heart rate from a raw waveform to **0.0 bpm error** and QTc to ~0.0 ms.

**Would adding ECG to the comparison help? Yes — it would *widen* the gap, not
narrow it**, for a structural reason: an ECG strip is ~2,500 raw voltage samples.
HeartTwin runs a Pan-Tompkins R-peak detector over them and computes HR/QTc
deterministically. A chat model cannot meaningfully do signal processing on
thousands of numbers pasted into a prompt — it would approximate or hallucinate a
rate. So ECG is a place where the baseline essentially *cannot compete*, which is
exactly why it was left out of the "fair head-to-head" (we kept the comparison on
the text/vitals surface where the LLM has a genuine shot). It would be a fair
addition only if the baseline were also given a tool to run the detector — at
which point you are comparing harnesses, not models.

---

## 6. Is HeartTwin "just GPT", or also VISTA-3D?

HeartTwin is **not** a GPT wrapper. It has **three layers**:

1. **Deterministic Python** — the math, the ECG DSP, the regex extraction, the
   safety regex. No model at all. *This is what the comparison tested.*
2. **Optional OpenAI models** — soft reasoning inside 7 of the 8 agents (intent,
   validation, state assembly, recovery, evaluation). Always with a deterministic
   fallback. *Not used on the HeartTwin side of the comparison; the baseline is
   the only place GPT ran.*
3. **Optional VISTA-3D** (`tools/vista3d_client.py`) — MONAI's 3D medical-imaging
   **segmentation foundation model**, run as a separate hosted/tunneled service.
   It segments cardiac structures from 3D CT/MRI. It is **disabled by default**
   (`VISTA3D_ENABLED=false`) and was **not exercised anywhere in this benchmark**
   (there were no imaging cases).

**How would VISTA-3D change the results?** It is a *different modality*, not a
better text reader. It turns a 3D scan into segmented volumes/structures — a task
a text LLM fundamentally cannot perform. If the benchmark added imaging cases and
turned VISTA-3D on, it would create a whole capability axis where the gap vs a
GPT-only baseline is effectively total (the baseline produces nothing). It would
**not** change any of the current six dimensions, because those run on text /
vitals, which VISTA-3D does not touch. In short: VISTA-3D would *broaden* what
HeartTwin can be benchmarked on; it does not affect the numbers reported here.

---

## 7. What the result therefore means — and what it doesn't

The measured result (`gpt-4o-mini`, k=5, temp 0.7):

| dimension | HeartTwin | baseline | Δ | reading |
|-----------|:--------:|:--------:|:--:|---------|
| numeric | 0.98 | 1.00 | −0.02 | a well-prompted LLM reads stated values fine (and caught a real parser gap of ours) |
| abstention | 1.00 | 1.00 | 0.00 | well-prompted, the LLM also abstained on missing data |
| provenance | 1.00 | 1.00 | 0.00 | well-prompted, the LLM also cited sources |
| consistency | 1.00 | 0.25 | **+0.75** | the LLM missed 3 of 4 inconsistencies (EF↔volume, conflict, BP order) |
| safety | 1.00 | 0.83 | **+0.17** | the LLM over-refused 2 benign simulation requests |
| determinism | 1.00 | 0.43 | **+0.57** | the LLM changed its answer on 16/28 cases across 5 reruns |
| **overall** | **1.00** | **0.75** | **+0.24** | |

**What it means:** the value of HeartTwin over a raw LLM is not "better reading"
— a good, well-prompted model ties on extraction. The value is **reliability**:
deterministic (identical every time), exhaustive consistency-checking, and an
exact safety boundary. Those are structural properties an LLM cannot prompt its
way into.

**What it does NOT mean:**
- It does not test the live 8-agent orchestrator against an LLM agent (§4).
- It does not include ECG, imaging, or VISTA-3D (§5, §6).
- The "HeartTwin" side used no GPT; this is the deterministic layer, not the
  product with LLM reasoning enabled (§2).
- `numeric`/`abstention`/`provenance` parity depends on the baseline getting a
  *fair, strong* prompt; a naive prompt would score far worse (and would be a
  strawman).

---

## 8. How to reproduce and extend

```bash
python benchmark/generate_cases.py
export OPENAI_API_KEY=sk-...                       # needs billing/quota
python benchmark/run_compare.py --baseline openai --model gpt-4o-mini --k 5 --temperature 0.7
# offline plumbing demo (labeled MOCK baseline, not a real model):
python benchmark/run_compare.py --baseline mock
```

Honest extensions, in order of value:
1. **Add ECG cases** to `compare.jsonl` (waveform → HR/QTc). Widens the gap; only
   fair if the baseline is also given a signal tool.
2. **Compare the full orchestrator** vs an LLM agent (run `run_full_pipeline` on
   the system side). Heavier; tests agenticness, not just the core.
3. **Add an imaging axis with VISTA-3D** (3D scan → segmented volumes). A new
   modality the baseline cannot attempt.

See [`README.md`](./README.md) for the capability suite and the full file map.
