# HeartTwin Lab — Datasets Reference

> **Educational simulation only. Not for diagnosis or treatment decisions.**

This document lists the public cardiac datasets that inform HeartTwin Lab's
model priors, validation benchmarks, and extraction patterns. No raw patient
data is embedded in this codebase. Datasets are used for reference ranges,
algorithm development, and system validation only.

---

## Echocardiography

### EchoNet-Dynamic
| Property | Details |
|---|---|
| Description | 10,030 apical-4-chamber echocardiogram videos with EF labels and LV segmentation traces |
| Source | Stanford AIMI |
| Paper | Ouyang et al. (2020). *Nature* 580, 252–256 |
| License | Stanford University Dataset Research Use Agreement |
| Use in HeartTwin | Informs EF extraction confidence thresholds; reference for video-based EF patterns |
| URL | https://echonet.github.io/dynamic/ |

### CAMUS (Cardiac Acquisitions for Multi-structure Ultrasound Segmentation)
| Property | Details |
|---|---|
| Description | 500 patients, 2D echocardiographic sequences with expert segmentations |
| Source | CREATIS Laboratory (Lyon) |
| Paper | Leclerc et al. (2019). *IEEE TMI* 38(9), 2198–2210 |
| Use in HeartTwin | Validation reference for 2D echo extraction patterns; normal/abnormal EF reference |
| URL | https://www.creatis.insa-lyon.fr/Challenge/camus/ |

---

## Cardiac MRI

### ACDC (Automated Cardiac Diagnosis Challenge)
| Property | Details |
|---|---|
| Description | 150 patients, cine-MRI with manual segmentations and 5 pathology classes |
| Source | CREATIS Laboratory |
| Paper | Bernard et al. (2018). *IEEE TMI* 37(11), 2514–2525 |
| Use in HeartTwin | EDV/ESV normal ranges; multi-pathology simulation scenario templates |
| URL | https://acdc.creatis.insa-lyon.fr/ |

---

## ECG

### PTB-XL
| Property | Details |
|---|---|
| Description | 21,799 clinical 12-lead ECG records from 18,869 patients |
| Source | Physikalisch-Technische Bundesanstalt (PTB), Germany |
| Paper | Wagner et al. (2020). *Scientific Data* 7, 154 |
| License | Creative Commons Attribution 4.0 International |
| Use in HeartTwin | ECG label taxonomy reference; Pan-Tompkins R-peak detection validation |
| URL | https://physionet.org/content/ptb-xl/1.0.3/ |

### MIMIC-IV-ECG
| Property | Details |
|---|---|
| Description | ~800,000 12-lead ECGs from MIMIC-IV patients with waveform data |
| Source | MIT Laboratory for Computational Physiology |
| Paper | Gow et al. (2023). *PhysioNet* |
| License | PhysioNet Credentialed Health Data License |
| Use in HeartTwin | ECG waveform extraction pattern reference; RR interval population statistics |
| URL | https://physionet.org/content/mimic-iv-ecg/1.0/ |

---

## Clinical Notes

### MIMIC-IV-Note
| Property | Details |
|---|---|
| Description | De-identified clinical notes from MIMIC-IV ICU/hospital patients |
| Source | MIT Laboratory for Computational Physiology |
| License | PhysioNet Credentialed Health Data License |
| Use in HeartTwin | Reference for cardiac measurement extraction patterns from unstructured clinical text |
| URL | https://physionet.org/content/mimic-iv-note/2.2/ |

---

## Chest Imaging

### MIMIC-CXR
| Property | Details |
|---|---|
| Description | 377,110 chest X-ray images with radiology reports |
| Source | MIT Laboratory for Computational Physiology |
| Paper | Johnson et al. (2019). *Scientific Data* 6, 317 |
| License | PhysioNet Credentialed Health Data License |
| Use in HeartTwin | Cardiomegaly detection reference; image extraction confidence calibration |
| URL | https://physionet.org/content/mimic-cxr/2.0.0/ |

---

## 3D Segmentation

### VISTA-3D (MONAI)
| Property | Details |
|---|---|
| Description | Foundation model for 3D medical image segmentation; 117+ classes including cardiac structures |
| Source | MONAI / NVIDIA Research |
| Paper | Butoi et al. (2023). *arXiv:2406.05285* |
| Use in HeartTwin | Optional CT cardiac segmentation; heart (class 115), aorta (class 6) |
| URL | https://monai.io/model-zoo.html |

### TotalSegmentator
| Property | Details |
|---|---|
| Description | nnU-Net-based model for segmentation of 104 anatomical structures in CT |
| Source | University Hospital Basel |
| Paper | Wasserthal et al. (2023). *Radiology: AI* |
| License | Apache 2.0 |
| Use in HeartTwin | Complementary cardiac structure reference; aorta, pulmonary vessels |
| URL | https://github.com/wasserth/TotalSegmentator |

---

## Population Reference Values

HeartTwin uses population-level reference ranges derived from:

- **ACC/AHA 2022 Guideline for the Diagnosis and Management of Heart Failure**
- **ESC 2021 Guidelines on Cardiovascular Disease Prevention**
- **NHANES (National Health and Nutrition Examination Survey)** — US population cardiovascular reference values
- **Lang et al. (2015)** — Chamber quantification reference ranges (JASE)

All prior values are explicitly labeled `default_model_prior` with confidence ≤ 0.45.

---

## Testing with synthetic fixtures

The automated test suite **does not download or commit any of the datasets above.**
It uses small, synthetic, non-PHI fixtures in `fixtures/hearttwin/` whose
*structure* is inspired by these public resources:

- **EchoNet-Dynamic** — echo video / EF / EDV / ESV / LV tracing concepts.
- **PTB-XL** — ECG waveform testing concepts (`ecg_synthetic_*.csv`).
- **CAMUS** — echo segmentation concepts.
- **ACDC** — cardiac MRI segmentation concepts.
- **MIMIC-IV-ECG** — production ECG scale (concept only).
- **MIMIC-IV-Note** — clinical note/report extraction structure (`report_*.txt`).
- **VISTA-3D** — 3D segmentation endpoint behavior (`vista3d_*_response.json`).
- **TotalSegmentator** — organ segmentation expansion concepts.

By default the suite uses synthetic data only. Tests that would call external
dataset/model endpoints are skipped unless `RUN_EXTERNAL_INTEGRATION_TESTS=true`
and the relevant credentials are provided. See [`docs/testing.md`](./testing.md).

## Data Privacy

No raw patient data is stored or transmitted by HeartTwin Lab. Uploaded files are
processed in memory, not persisted as raw content. PII is redacted from trace logs
before storage. Redis/Upstash stores only JSON metadata (not file contents).
