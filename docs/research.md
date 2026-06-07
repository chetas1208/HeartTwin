# HeartTwin Lab — Research Basis

> **Educational simulation only. Not for diagnosis or treatment decisions.**

This document describes the peer-reviewed research, algorithms, and datasets
that underpin the HeartTwin Lab cardiac digital twin simulation. Every numeric
formula in the deterministic physics core is traced to a verifiable source.

---

## Cardiac Digital Twins

HeartTwin follows the cardiac digital twin paradigm, which represents individual
patients as computational models capturing structure, function, and
electrophysiology. The concept is grounded in work such as:

- Niederer et al. (2019). "Computational models in cardiology." *Nature Reviews Cardiology* 16(2), 100–111.
- Corral-Acero et al. (2020). "The Digital Twin to enable the vision of precision cardiology." *European Heart Journal* 41(48), 4556–4564.
- Trayanova et al. (2021). "Machine learning in cardiology." *Annual Review of Medicine* 72, 1–27.

Our approach: a deterministic physics core computes canonical hemodynamic
quantities (SV, EF, CO, MAP, QTc) from extracted clinical parameters. An LLM
orchestration layer narrates and orchestrates — never computes.

---

## Deterministic Cardiac Formulas

All numeric simulations use well-established formulas:

| Quantity | Formula | Reference |
|---|---|---|
| Stroke Volume (SV) | `SV = EDV − ESV` | Guyton & Hall, *Textbook of Medical Physiology* |
| Ejection Fraction (EF) | `EF = SV / EDV × 100` | Lang et al. (2015), *JASE* |
| Cardiac Output (CO) | `CO = HR × SV / 1000` | Guyton & Hall |
| Mean Arterial Pressure (MAP) | `MAP = DBP + (SBP − DBP) / 3` | Palatini & Julius (1997) |
| RR Interval | `RR = 60000 / HR` (ms) | AHA ECG standards |
| QTc (Bazett) | `QTc = QT / √(RR/1000)` | Bazett (1920) |
| Body Surface Area | Mosteller formula: `BSA = √(H × W / 3600)` | Mosteller (1987) |

Pressure-volume loops use a time-varying elastance model derived from:
- Suga & Sagawa (1974). "Instantaneous pressure-volume relationships and their ratio in the excised, supported canine left ventricle." *Circulation Research* 35(1), 117–126.

---

## ECG Feature Extraction

R-peak detection uses the **Pan-Tompkins algorithm** (1985):
- Pan J, Tompkins WJ. "A real-time QRS detection algorithm." *IEEE Transactions on Biomedical Engineering* 32(3), 230–236.

QRS width, RR intervals, and PR/QT durations are computed deterministically
from the detected R-peak positions. ECG labels reported in clinical documents
are stored as *reported descriptors* only — never re-stated as clinical conclusions.

---

## Echocardiography Reference Models

EDV/ESV normal ranges and EF classifications follow:
- Lang et al. (2015). "Recommendations for cardiac chamber quantification." *JASE* 28(1), 1–39.e14.
- Nagueh et al. (2016). "Recommendations for the evaluation of left ventricular diastolic function." *JASE* 29(4), 277–314.

---

## Population Priors

Default values for unmeasured parameters use population-level reference ranges.
Priors are explicitly labeled as `default_model_prior` with confidence ≤ 0.45 in
all outputs, ensuring they are clearly distinguishable from extracted evidence.

Sources include:
- ACC/AHA heart failure guidelines
- ESC 2021 Guidelines on Cardiovascular Disease Prevention
- NHANES reference ranges

---

## 3D Cardiac Segmentation: VISTA-3D and TotalSegmentator

HeartTwin optionally orchestrates CT segmentation via:
- **VISTA-3D** (MONAI Research): Butoi et al. (2023). "VISTA3D: Versatile Imaging SegmenTation and Annotation model for 3D medical imaging." *arXiv:2406.05285*.
- **TotalSegmentator**: Wasserthal et al. (2023). "TotalSegmentator: Robust segmentation of 104 anatomical structures in CT images." *Radiology: Artificial Intelligence*.

VISTA-3D emits the heart as a single label (class 115). Chamber-level
segmentation masks are not separately available on our deployment.
All segmentation outputs are labeled *research segmentation only*.

---

## EchoNet-Dynamic

Used as a reference dataset for echocardiographic EF estimation methodology:
- Ouyang et al. (2020). "Video-based AI for beat-to-beat assessment of cardiac function." *Nature* 580, 252–256.

---

## CAMUS (Cardiac Acquisitions for Multi-structure Ultrasound Segmentation)

Cardiac ultrasound segmentation benchmark. Used to validate 2D echocardiographic
extraction patterns:
- Leclerc et al. (2019). "Deep learning for segmentation using an open large-scale dataset in 2D echocardiography." *IEEE Transactions on Medical Imaging* 38(9), 2198–2210.

---

## ACDC (Automated Cardiac Diagnosis Challenge)

Cardiac MRI segmentation reference:
- Bernard et al. (2018). "Deep learning techniques for automatic MRI cardiac multi-structures segmentation and diagnosis." *IEEE Transactions on Medical Imaging* 37(11), 2514–2525.

---

## PTB-XL (ECG Dataset)

12-lead ECG reference database used in development and testing:
- Wagner et al. (2020). "PTB-XL, a large publicly available electrocardiography dataset." *Scientific Data* 7, 154.

---

## FDA and Clinical Decision Support (CDS) Safety Boundary

HeartTwin follows FDA guidance on Software as a Medical Device (SaMD) and
Clinical Decision Support (CDS) software boundaries:
- FDA (2022). *Clinical Decision Support Software: Final Guidance*.
- All outputs include the required disclaimer: *"Educational cardiac simulation only. Not for diagnosis or treatment decisions."*
- No output provides, infers, or suggests a diagnosis or treatment recommendation.
- The Evaluator & Critic agent actively scans all generated text for unsafe clinical language.

---

## Multi-Agent Orchestration Architecture

HeartTwin uses an 8-agent pipeline inspired by:
- Anthropic (2023). *Building Effective Agents* — the "orchestrator-workers" multi-agent pattern.
- LangChain/LangGraph architectural patterns for agent handoffs.
- CopilotKit's AG-UI protocol for human-in-the-loop agent orchestration.

Each agent has unique domain logic and a deterministic physics boundary. The LLM
orchestration layer (CopilotKit + GPT-5.5 class models) reasons and narrates;
Python tools compute.
