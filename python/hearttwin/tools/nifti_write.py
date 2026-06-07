"""Minimal single-file NIfTI-1 (`n+1`) writer for synthetic label-map masks.

Used only to create synthetic VISTA-3D-style segmentation masks for tests and
the offline dataset — NOT a clinical I/O path. numpy only.
"""
from __future__ import annotations

import gzip
import struct

import numpy as np


def write_nifti_labelmap(
    mask: np.ndarray,
    spacing_mm: tuple[float, float, float] = (1.5, 1.5, 1.5),
    *,
    gzip_output: bool = True,
) -> bytes:
    """Serialize an integer label-map to single-file NIfTI-1 bytes (uint16)."""
    if mask.ndim != 3:
        raise ValueError("expected a 3D label-map")
    data = np.ascontiguousarray(mask.astype("<u2").transpose(2, 1, 0))  # to column-major

    hdr = bytearray(352)
    struct.pack_into("<i", hdr, 0, 348)                       # sizeof_hdr
    struct.pack_into("<8h", hdr, 40, 3, *mask.shape, 1, 1, 1, 1)  # dim
    struct.pack_into("<h", hdr, 70, 512)                      # datatype = uint16
    struct.pack_into("<h", hdr, 72, 16)                       # bitpix
    struct.pack_into("<8f", hdr, 76, 1.0, spacing_mm[0], spacing_mm[1], spacing_mm[2], 1.0, 1.0, 1.0, 1.0)
    struct.pack_into("<f", hdr, 108, 352.0)                   # vox_offset
    struct.pack_into("<f", hdr, 112, 1.0)                     # scl_slope
    hdr[344:348] = b"n+1\x00"                                 # magic

    payload = bytes(hdr) + data.tobytes()
    return gzip.compress(payload) if gzip_output else payload
