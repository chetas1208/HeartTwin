#!/usr/bin/env python3
"""Fetch a PTB-XL slice labelled with DIAGNOSTIC SUPERCLASSES for the research
ECG-diagnosis classifier (NORM / MI / STTC / CD / HYP).

PTB-XL is open (CC-BY 4.0). This downloads scp_statements.csv (the code->superclass
map) + the records100 (100 Hz) waveforms for a balanced slice, and saves one .npz:
  X  (N, 1000, 12) float32 waveforms
  Y  (N, 5) int    multi-hot superclass labels
  ids, classes, fs

Run:  python benchmark/datasets/prep_ptbxl_dx.py --per-class 100

Educational use. PTB-XL: Wagner et al. 2020, Scientific Data 7:154 (CC-BY 4.0).
"""

from __future__ import annotations

import argparse
import ast
import csv
import urllib.request
from pathlib import Path

import numpy as np
import wfdb

HERE = Path(__file__).resolve().parent
PTBXL = HERE / "ptbxl"
DB_CSV = PTBXL / "ptbxl_database.csv"
SCP_CSV = PTBXL / "scp_statements.csv"
OUT = PTBXL / "dx_dataset.npz"
BASE = "https://physionet.org/files/ptb-xl/1.0.3/"
CLASSES = ["NORM", "MI", "STTC", "CD", "HYP"]


def _dl(name: str, dst: Path) -> None:
    if dst.exists():
        return
    PTBXL.mkdir(parents=True, exist_ok=True)
    print(f"downloading {name} ...")
    urllib.request.urlretrieve(BASE + name, dst)


def _code_to_superclass() -> dict[str, str]:
    _dl("scp_statements.csv", SCP_CSV)
    mapping: dict[str, str] = {}
    with SCP_CSV.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            code = row[list(row.keys())[0]].strip()
            if str(row.get("diagnostic", "")).strip() in ("1", "1.0") and row.get("diagnostic_class"):
                mapping[code] = row["diagnostic_class"].strip()
    return mapping


def _superclasses(scp: dict, code_map: dict[str, str]) -> list[str]:
    out = set()
    for code in scp:
        sc = code_map.get(code)
        if sc in CLASSES:
            out.add(sc)
    return sorted(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=100)
    args = ap.parse_args()

    _dl("ptbxl_database.csv", DB_CSV)
    code_map = _code_to_superclass()

    counts = {c: 0 for c in CLASSES}
    chosen: list[dict] = []
    with DB_CSV.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                scp = ast.literal_eval(row["scp_codes"])
            except Exception:
                continue
            scs = _superclasses(scp, code_map)
            if not scs:
                continue
            # take the record if any of its classes still needs more samples
            if any(counts[c] < args.per_class for c in scs):
                row["_scs"] = scs
                chosen.append(row)
                for c in scs:
                    counts[c] += 1
            if all(counts[c] >= args.per_class for c in CLASSES):
                break

    print("class counts:", counts, "records:", len(chosen))

    X, Y, ids = [], [], []
    for i, row in enumerate(chosen):
        rel = row["filename_lr"]                       # records100/.../*_lr (100 Hz)
        name = rel.split("/")[-1]
        pn_dir = BASE.replace("https://physionet.org/files/", "") + "/".join(rel.split("/")[:-1])
        try:
            rec = wfdb.rdrecord(name, pn_dir=pn_dir.rstrip("/"))
        except Exception as exc:
            print(f"  skip {row['ecg_id']}: {type(exc).__name__}")
            continue
        sig = np.asarray(rec.p_signal, dtype=np.float32)   # (1000, 12)
        if sig.shape[0] < 1000:
            sig = np.pad(sig, ((0, 1000 - sig.shape[0]), (0, 0)))
        sig = sig[:1000, :12]
        sig = np.nan_to_num(sig)
        X.append(sig)
        Y.append([1 if c in row["_scs"] else 0 for c in CLASSES])
        ids.append(int(row["ecg_id"]))
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(chosen)} fetched")

    X = np.stack(X); Y = np.asarray(Y, dtype=np.int8); ids = np.asarray(ids)
    np.savez_compressed(OUT, X=X, Y=Y, ids=ids, classes=np.array(CLASSES), fs=100)
    print(f"saved {OUT.relative_to(HERE.parent.parent)}  X={X.shape} Y={Y.shape}")


if __name__ == "__main__":
    main()
