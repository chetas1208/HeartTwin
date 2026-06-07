#!/usr/bin/env python3
"""Fetch a small, balanced PTB-XL slice and prep it for HeartTwinBench.

PTB-XL is open (CC-BY 4.0) on PhysioNet — no credentialing. This pulls the label
CSV, picks a few records per RHYTHM category (not diagnosis — HeartTwin does not
diagnose), exports each as the lead-II CSV the pipeline ingests (at 500 Hz, which
is the pipeline's default), and renders a clean, LABEL-FREE strip PNG for the
vision baseline. Writes cases/ptbxl_cases.jsonl.

Run:  python benchmark/datasets/prep_ptbxl.py [--per-class 4]

Educational use only. PTB-XL: Wagner et al. 2020, Scientific Data 7:154 (CC-BY 4.0).
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import urllib.request
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import wfdb

HERE = Path(__file__).resolve().parent
PTBXL = HERE / "ptbxl"
CSV_OUT = HERE.parent / "cases" / "ptbxl_cases.jsonl"
SIG_DIR = PTBXL / "signals"
PNG_DIR = PTBXL / "strips"

BASE = "https://physionet.org/files/ptb-xl/1.0.3/"
DB_CSV = PTBXL / "ptbxl_database.csv"

# PTB-XL rhythm SCP codes -> HeartTwin's rhythm CATEGORIES (descriptors, not dx)
RHYTHM_CODES = {"SR", "STACH", "SBRAD", "SARRH", "AFIB", "AFLT", "SVTAC", "PSVT", "BIGU", "TRIGU"}
CODE_TO_CATEGORY = {
    "SR": "regular",
    "STACH": "tachy",
    "SBRAD": "brady",
    "AFIB": "irregular",
    "AFLT": "irregular",
    "SARRH": "irregular",
}
TARGET_CATEGORIES = ["regular", "tachy", "brady", "irregular"]


def _download_db() -> None:
    PTBXL.mkdir(parents=True, exist_ok=True)
    if DB_CSV.exists():
        return
    print("downloading ptbxl_database.csv (6.6 MB) ...")
    urllib.request.urlretrieve(BASE + "ptbxl_database.csv", DB_CSV)


def _rows():
    import csv
    with DB_CSV.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            yield row


def _single_rhythm(scp: dict) -> str | None:
    present = [c for c in scp if c in RHYTHM_CODES]
    if len(present) != 1:
        return None
    return CODE_TO_CATEGORY.get(present[0])


def _select(per_class: int) -> dict[str, list[dict]]:
    picked: dict[str, list[dict]] = {c: [] for c in TARGET_CATEGORIES}
    for row in _rows():
        try:
            scp = ast.literal_eval(row["scp_codes"])
        except Exception:
            continue
        cat = _single_rhythm(scp)
        if cat in picked and len(picked[cat]) < per_class:
            row["_category"] = cat
            picked[cat].append(row)
        if all(len(v) >= per_class for v in picked.values()):
            break
    return picked


def _export(row: dict) -> dict | None:
    ecg_id = row["ecg_id"]
    rel = row["filename_hr"]                      # records500/xxxxx/yyyyy_hr  (500 Hz)
    name = rel.split("/")[-1]
    pn_dir = BASE.replace("https://physionet.org/files/", "") + "/".join(rel.split("/")[:-1])
    try:
        rec = wfdb.rdrecord(name, pn_dir=pn_dir.rstrip("/"))
    except Exception as exc:
        print(f"  skip {ecg_id}: {type(exc).__name__}")
        return None
    if "II" not in rec.sig_name:
        return None
    lead = rec.sig_name.index("II")
    fs = float(rec.fs)                            # 500
    sig = [round(float(v), 4) for v in rec.p_signal[:, lead]]

    SIG_DIR.mkdir(parents=True, exist_ok=True)
    PNG_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = SIG_DIR / f"{ecg_id}.csv"
    # column name "ecg" so the pipeline's CSV waveform detector picks it up
    with csv_path.open("w", encoding="utf-8") as fh:
        fh.write("time_ms,ecg\n")
        step = 1000.0 / fs
        for i, v in enumerate(sig):
            fh.write(f"{round(i*step,1)},{v}\n")

    # label-FREE strip (first 6 s) so the vision model can't read the answer
    n = int(6 * fs)
    png_path = PNG_DIR / f"{ecg_id}.png"
    fig, ax = plt.subplots(figsize=(12, 2.6), dpi=110)
    t = [i / fs for i in range(min(n, len(sig)))]
    ax.plot(t, sig[:n], linewidth=0.7, color="black")
    ax.set_xlabel("seconds"); ax.set_ylabel("lead II (mV)")
    ax.grid(True, color="#f0a0a0", linewidth=0.4)
    fig.tight_layout(); fig.savefig(png_path); plt.close(fig)

    return {
        "id": f"ptbxl_{ecg_id}",
        "dataset": "PTB-XL",
        "modality": "ecg",
        "input": {"ecg_csv": str(csv_path.relative_to(HERE.parent)),
                  "ecg_strip_png": str(png_path.relative_to(HERE.parent))},
        "gold": {"rhythm_category": row["_category"],
                 "scp_codes": row["scp_codes"], "label_source": "PTB-XL"},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=4)
    args = ap.parse_args()
    _download_db()
    picked = _select(args.per_class)
    rows = []
    for cat, recs in picked.items():
        print(f"{cat}: {len(recs)} candidates")
        for row in recs:
            case = _export(row)
            if case:
                rows.append(case)
    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    with CSV_OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    print(f"wrote {len(rows)} cases -> {CSV_OUT.relative_to(HERE.parent.parent)}")


if __name__ == "__main__":
    main()
