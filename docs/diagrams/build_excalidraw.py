#!/usr/bin/env python3
"""Convert the compact diagram sources in ``source/*.json`` into valid, openable
``.excalidraw`` files (the schema excalidraw.com / the VS Code extension expect).

The sources use the streaming-friendly element format produced by the Excalidraw
MCP tool: inline ``label`` on shapes/arrows and ``cameraUpdate`` pseudo-elements.
This script:

  * drops camera / delete / restoreCheckpoint pseudo-elements,
  * expands inline ``label`` into a separate bound text element,
  * fills in the full Excalidraw element schema with deterministic seeds.

Usage:
    python docs/diagrams/build_excalidraw.py

Re-run after editing any ``source/*.json`` to regenerate the exports. The same
source files can be fed straight back to the Excalidraw MCP ``create_view`` tool
to re-render the animated walkthrough.
"""

from __future__ import annotations

import json
import pathlib
import random

HERE = pathlib.Path(__file__).resolve().parent
SRC_DIR = HERE / "source"
DROP_TYPES = {"cameraUpdate", "delete", "restoreCheckpoint"}

# Deterministic output so regeneration produces a stable git diff.
_RNG = random.Random(20260606)


def _nonce() -> int:
    return _RNG.randint(1, 2_000_000_000)


def _estimate_width(text: str, font_size: int) -> int:
    longest = max((len(line) for line in text.split("\n")), default=0)
    return max(10, int(longest * font_size * 0.6))


def _estimate_height(text: str, font_size: int) -> int:
    lines = text.count("\n") + 1
    return int(lines * font_size * 1.25)


def _base(el: dict, extra: dict) -> dict:
    out = {
        "id": el["id"],
        "type": el["type"],
        "x": el["x"],
        "y": el["y"],
        "width": el.get("width", 0),
        "height": el.get("height", 0),
        "angle": 0,
        "strokeColor": el.get("strokeColor", "#1e1e1e"),
        "backgroundColor": el.get("backgroundColor", "transparent"),
        "fillStyle": el.get("fillStyle", "solid"),
        "strokeWidth": el.get("strokeWidth", 2),
        "strokeStyle": el.get("strokeStyle", "solid"),
        "roughness": el.get("roughness", 1),
        "opacity": el.get("opacity", 100),
        "groupIds": [],
        "frameId": None,
        "roundness": el.get("roundness"),
        "seed": _nonce(),
        "version": 1,
        "versionNonce": _nonce(),
        "isDeleted": False,
        "boundElements": [],
        "updated": 1,
        "link": None,
        "locked": False,
    }
    out.update(extra)
    return out


def _text_element(
    text_id: str,
    text: str,
    font_size: int,
    *,
    color: str,
    cx: float | None = None,
    cy: float | None = None,
    left: float | None = None,
    top: float | None = None,
    container_id: str | None = None,
) -> dict:
    width = _estimate_width(text, font_size)
    height = _estimate_height(text, font_size)
    if cx is not None and cy is not None:
        x, y = cx - width / 2, cy - height / 2
        align, valign = "center", "middle"
    else:
        x, y = left, top
        align, valign = "left", "top"
    return {
        "id": text_id,
        "type": "text",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "angle": 0,
        "strokeColor": color,
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 1,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "roundness": None,
        "seed": _nonce(),
        "version": 1,
        "versionNonce": _nonce(),
        "isDeleted": False,
        "boundElements": [],
        "updated": 1,
        "link": None,
        "locked": False,
        "text": text,
        "fontSize": font_size,
        "fontFamily": 1,
        "textAlign": align,
        "verticalAlign": valign,
        "containerId": container_id,
        "originalText": text,
        "lineHeight": 1.25,
    }


def convert(elements: list[dict]) -> list[dict]:
    out: list[dict] = []
    for el in elements:
        kind = el.get("type")
        if kind in DROP_TYPES:
            continue

        if kind in ("rectangle", "ellipse", "diamond"):
            shape = _base(el, {})
            out.append(shape)
            label = el.get("label")
            if label:
                text_id = f"{el['id']}_t"
                shape["boundElements"] = [{"type": "text", "id": text_id}]
                out.append(
                    _text_element(
                        text_id,
                        label["text"],
                        label.get("fontSize", 20),
                        color=el.get("strokeColor", "#1e1e1e"),
                        cx=el["x"] + el.get("width", 0) / 2,
                        cy=el["y"] + el.get("height", 0) / 2,
                        container_id=el["id"],
                    )
                )

        elif kind == "text":
            out.append(
                _text_element(
                    el["id"],
                    el["text"],
                    el.get("fontSize", 20),
                    color=el.get("strokeColor", "#1e1e1e"),
                    left=el["x"],
                    top=el["y"],
                )
            )

        elif kind == "arrow":
            points = el.get("points", [[0, 0], [el.get("width", 0), el.get("height", 0)]])
            arrow = _base(
                el,
                {
                    "points": points,
                    "lastCommittedPoint": None,
                    "startBinding": None,
                    "endBinding": None,
                    "startArrowhead": el.get("startArrowhead"),
                    "endArrowhead": el.get("endArrowhead", "arrow"),
                    "elbowed": False,
                },
            )
            out.append(arrow)
            label = el.get("label")
            if label:
                text_id = f"{el['id']}_t"
                arrow["boundElements"] = [{"type": "text", "id": text_id}]
                out.append(
                    _text_element(
                        text_id,
                        label["text"],
                        label.get("fontSize", 16),
                        color=el.get("strokeColor", "#1e1e1e"),
                        cx=el["x"] + el.get("width", 0) / 2,
                        cy=el["y"] + el.get("height", 0) / 2,
                        container_id=el["id"],
                    )
                )

    return out


def wrap(elements: list[dict]) -> dict:
    return {
        "type": "excalidraw",
        "version": 2,
        "source": "https://github.com/Cuuper22/wesave4hacks",
        "elements": elements,
        "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None},
        "files": {},
    }


def main() -> None:
    for src in sorted(SRC_DIR.glob("*.json")):
        raw = json.loads(src.read_text())
        doc = wrap(convert(raw))
        out_path = HERE / f"{src.stem}.excalidraw"
        out_path.write_text(json.dumps(doc, indent=2))
        print(f"wrote {out_path.relative_to(HERE.parent.parent)} ({len(doc['elements'])} elements)")


if __name__ == "__main__":
    main()
