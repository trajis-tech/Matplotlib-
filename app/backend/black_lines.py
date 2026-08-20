# -*- coding: utf-8 -*-
"""Find visual horizontal black bands, ignoring scattered specks."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np


DIR_KEYS = ("tl", "bl", "tr", "br")
DIR_LABELS = {
    "tl": "左上",
    "bl": "左下",
    "tr": "右上",
    "br": "右下",
}

LINE_COUNT = 3
MIN_BAND_RUN = 3
COLOR_PASS = (94, 197, 34)


def _open_black_specks(binary: np.ndarray) -> np.ndarray:
    """Opening on black-as-foreground to drop salt-and-pepper, keep bands."""
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    black = np.where(binary == 0, 255, 0).astype(np.uint8)
    black = cv2.morphologyEx(black, cv2.MORPH_OPEN, kernel)
    return np.where(black > 0, 0, 255).astype(np.uint8)


def _window_half_width(width: int) -> int:
    return max(12, int(round(0.04 * float(width))))


def _effective_min_run(min_run: int) -> int:
    return max(MIN_BAND_RUN, int(min_run))


def _black_fraction_profile(binary: np.ndarray, x: int, half_w: int) -> np.ndarray:
    h, w = binary.shape[:2]
    x0 = max(0, int(x) - half_w)
    x1 = min(w, int(x) + half_w + 1)
    strip = binary[:, x0:x1]
    return (strip == 0).mean(axis=1)


def _expand_band(active: np.ndarray, y: int) -> Tuple[int, int]:
    h = int(active.shape[0])
    y0 = y1 = int(y)
    while y0 > 0 and active[y0 - 1]:
        y0 -= 1
    while y1 + 1 < h and active[y1 + 1]:
        y1 += 1
    return y0, y1


def _collect_bands(
    active: np.ndarray,
    start_y: int,
    step: int,
    min_run: int,
    count: int,
) -> List[Tuple[int, int]]:
    h = int(active.shape[0])
    y = int(start_y)
    bands: List[Tuple[int, int]] = []
    while 0 <= y < h and len(bands) < count:
        if active[y]:
            y0, y1 = _expand_band(active, y)
            if (y1 - y0 + 1) >= min_run:
                bands.append((y0, y1))
            y = y0 - 1 if step < 0 else y1 + 1
        else:
            y += step
    return bands


def _start_after_seed(active: np.ndarray, seed_y: int, step: int) -> int:
    """Skip the connected band at the seed, regardless of thickness."""
    h = int(active.shape[0])
    y = max(0, min(int(seed_y), h - 1))
    if not active[y]:
        return y + step
    y0, y1 = _expand_band(active, y)
    return (y0 - 1) if step < 0 else (y1 + 1)


def search_black_lines(
    binary: np.ndarray,
    crop_origin: Tuple[int, int],
    seeds_xy: Dict[str, Tuple[int, int]],
    center: Tuple[float, float],
    min_run: int,
    line_fill: float = 0.55,
) -> Dict[str, Any]:
    """Skip seed band, then take the next 3 visual bands as the official lines."""
    if binary.ndim != 2:
        raise ValueError("二值圖必須是單通道。")
    cleaned = _open_black_specks(binary)
    h, w = cleaned.shape[:2]
    ox, oy = int(crop_origin[0]), int(crop_origin[1])
    cx, cy = float(center[0]), float(center[1])
    min_run = _effective_min_run(min_run)
    half_w = _window_half_width(w)
    fill = min(0.95, max(0.2, float(line_fill)))

    directions: Dict[str, List[Dict[str, Any]]] = {k: [] for k in DIR_KEYS}
    warnings: List[str] = []
    missing: List[str] = []
    pass_counts: Dict[str, int] = {k: 0 for k in DIR_KEYS}
    fail_counts: Dict[str, int] = {k: 0 for k in DIR_KEYS}

    side_map = (
        ("left", "tl", -1),
        ("left", "bl", 1),
        ("right", "tr", -1),
        ("right", "br", 1),
    )

    for side, key, step in side_map:
        sx, sy = seeds_xy[side]
        lx = int(sx) - ox
        ly = int(sy) - oy
        if lx < 0 or lx >= w or ly < 0 or ly >= h:
            warnings.append(f"{DIR_LABELS[key]}起點落在裁剪圖外")
            missing.append(DIR_LABELS[key])
            continue
        score = _black_fraction_profile(cleaned, lx, half_w)
        active = score >= fill
        start_y = _start_after_seed(active, ly, step)
        bands = _collect_bands(active, start_y, step, min_run, LINE_COUNT)
        for idx, (y0, y1) in enumerate(bands, start=1):
            length = int(y1 - y0 + 1)
            img_x = ox + lx
            img_y0 = oy + int(y0)
            img_y1 = oy + int(y1)
            mid_y = 0.5 * (img_y0 + img_y1)
            directions[key].append(
                {
                    "index": idx,
                    "x": img_x,
                    "x0": img_x - half_w,
                    "x1": img_x + half_w,
                    "y0": img_y0,
                    "y1": img_y1,
                    "length": length,
                    "meetsThreshold": True,
                    "halfWidth": half_w,
                    "rel": {
                        "x": img_x - cx,
                        "y0": img_y0 - cy,
                        "y1": img_y1 - cy,
                        "midY": mid_y - cy,
                    },
                }
            )
        found = len(bands)
        pass_counts[key] = found
        fail_counts[key] = 0
        if found < LINE_COUNT:
            warnings.append(f"{DIR_LABELS[key]}只找到 {found} 條（需要 {LINE_COUNT} 條）")
            missing.append(DIR_LABELS[key])

    return {
        "directions": directions,
        "warnings": warnings,
        "missingRegions": missing,
        "minRun": min_run,
        "lineFill": fill,
        "halfWidth": half_w,
        "passCounts": pass_counts,
        "failCounts": fail_counts,
    }


def draw_labeled_lines(
    canvas_bgr: np.ndarray,
    result: Dict[str, Any],
    seeds_xy: Optional[Dict[str, Tuple[int, int]]] = None,
    seed_color: Tuple[int, int, int] = (255, 255, 0),
) -> np.ndarray:
    out = canvas_bgr.copy()
    width = out.shape[1]
    if seeds_xy:
        for _side, (sx, sy) in seeds_xy.items():
            cv2.drawMarker(out, (int(sx), int(sy)), seed_color, markerType=cv2.MARKER_CROSS, markerSize=12, thickness=1)
    for key in DIR_KEYS:
        for line in result["directions"].get(key, []):
            color = COLOR_PASS if line.get("meetsThreshold", True) else (49, 49, 224)
            x = int(line["x"])
            y0 = int(line["y0"])
            y1 = int(line["y1"])
            mid_y = int(round(0.5 * (y0 + y1)))
            half = int(line.get("halfWidth") or result.get("halfWidth") or 12)
            x0 = max(0, int(line.get("x0", x - half)))
            x1 = min(width - 1, int(line.get("x1", x + half)))
            cv2.line(out, (x0, mid_y), (x1, mid_y), color, 2, cv2.LINE_AA)
            cv2.putText(
                out,
                str(line["index"]),
                (min(width - 12, x1 + 6), mid_y + 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
                cv2.LINE_AA,
            )
    return out
