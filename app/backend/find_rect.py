# -*- coding: utf-8 -*-
"""Find a possibly rotated large rectangle on the single-Gaussian map."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np


def _aspect(w: float, h: float) -> float:
    short = min(float(w), float(h))
    if short <= 0:
        return 0.0
    return float(max(float(w), float(h))) / short


def _clamp_box(x: int, y: int, w: int, h: int, width: int, height: int) -> Tuple[int, int, int, int]:
    x = max(0, min(int(x), width - 1))
    y = max(0, min(int(y), height - 1))
    w = max(1, min(int(w), width - x))
    h = max(1, min(int(h), height - y))
    return x, y, w, h


def _edge_score(mag: np.ndarray, x: int, y: int, w: int, h: int) -> float:
    height, width = mag.shape[:2]
    x, y, w, h = _clamp_box(x, y, w, h, width, height)
    top = float(np.mean(mag[y, x : x + w]))
    bottom = float(np.mean(mag[y + h - 1, x : x + w]))
    left = float(np.mean(mag[y : y + h, x]))
    right = float(np.mean(mag[y : y + h, x + w - 1]))
    return (top + bottom + left + right) / 4.0


def _fill_score(mask: Optional[np.ndarray], x: int, y: int, w: int, h: int) -> float:
    if mask is None:
        return 0.0
    patch = mask[y : y + h, x : x + w]
    if patch.size == 0:
        return 0.0
    return float(np.mean(patch > 0))


def _touches_frame(x: int, y: int, w: int, h: int, width: int, height: int) -> int:
    n = 0
    if x <= 1:
        n += 1
    if y <= 1:
        n += 1
    if x + w >= width - 1:
        n += 1
    if y + h >= height - 1:
        n += 1
    return n


def _is_background_box(x: int, y: int, w: int, h: int, width: int, height: int) -> bool:
    img_area = float(width * height)
    if float(w * h) > 0.72 * img_area:
        return True
    if _touches_frame(x, y, w, h, width, height) >= 3:
        return True
    if w >= int(0.95 * width) and h >= int(0.55 * height):
        return True
    if h >= int(0.95 * height) and w >= int(0.55 * width):
        return True
    return False


def _normalize_min_area_rect(
    raw: Tuple[Tuple[float, float], Tuple[float, float], float],
) -> Tuple[float, float, float, float, float]:
    """Make W the long side; angle is that side vs image +x, in (-90, 90]."""
    (cx, cy), (rw, rh), ang = raw
    cx, cy = float(cx), float(cy)
    rw, rh, ang = float(rw), float(rh), float(ang)
    if rw < rh:
        rw, rh = rh, rw
        ang += 90.0
    while ang > 90.0:
        ang -= 180.0
    while ang <= -90.0:
        ang += 180.0
    return cx, cy, rw, rh, ang


def _add_box(
    boxes: List[Dict[str, Any]],
    seen: set,
    x: int,
    y: int,
    w: int,
    h: int,
    width: int,
    height: int,
    mag: np.ndarray,
    mask: Optional[np.ndarray],
    min_area: float,
    source: str,
    contour: Optional[np.ndarray] = None,
) -> None:
    x, y, w, h = _clamp_box(x, y, w, h, width, height)
    if _is_background_box(x, y, w, h, width, height):
        return
    area = float(w * h)
    if area < min_area:
        return
    key = (x, y, w, h, source)
    if key in seen:
        return
    seen.add(key)
    boxes.append(
        {
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "aspect": _aspect(w, h),
            "area": area,
            "edgeScore": _edge_score(mag, x, y, w, h),
            "fillScore": _fill_score(mask, x, y, w, h),
            "source": source,
            "contour": contour,
        }
    )


def _largest_contour(mask: np.ndarray) -> Optional[np.ndarray]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    return max(contours, key=cv2.contourArea)


def _boxes_from_mask(
    mask: np.ndarray,
    mag: np.ndarray,
    min_area: float,
    source: str,
    boxes: List[Dict[str, Any]],
    seen: set,
) -> None:
    height, width = mask.shape[:2]
    n_labels, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    ranked = []
    for i in range(1, n_labels):
        x, y, w, h, cc_area = stats[i]
        if _is_background_box(int(x), int(y), int(w), int(h), width, height):
            continue
        ranked.append((int(w) * int(h), int(cc_area), int(i), int(x), int(y), int(w), int(h)))
    ranked.sort(reverse=True)
    for _bbox_area, _cc_area, idx, x, y, w, h in ranked[:8]:
        cc_mask = (labels == idx).astype(np.uint8) * 255
        cnt = _largest_contour(cc_mask)
        _add_box(boxes, seen, x, y, w, h, width, height, mag, mask, min_area, source, contour=cnt)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:6]
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        _add_box(boxes, seen, int(x), int(y), int(w), int(h), width, height, mag, mask, min_area, source, contour=cnt)


def find_large_rect(y_rect: np.ndarray, params: Dict[str, Any]) -> Dict[str, Any]:
    """Pick the large dark blob, then fit a rotated min-area rectangle to it."""
    if y_rect.ndim != 2:
        raise ValueError("單高斯圖必須是單通道。")
    height, width = y_rect.shape[:2]
    min_area_ratio = float(params.get("min_area_ratio", 0.05))
    min_area = max(1.0, min_area_ratio * float(width * height))

    y32 = y_rect.astype(np.float32)
    gx = cv2.Sobel(y32, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(y32, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)

    boxes: List[Dict[str, Any]] = []
    seen: set = set()

    close_k = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    merge_k = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 11))

    for t in (16, 48, 96, 128):
        dark = (y_rect <= t).astype(np.uint8) * 255
        dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, close_k)
        _boxes_from_mask(dark, mag, min_area, f"dark<{t}", boxes, seen)

    merged = cv2.morphologyEx((y_rect <= 48).astype(np.uint8) * 255, cv2.MORPH_CLOSE, merge_k)
    _boxes_from_mask(merged, mag, min_area, "dark-merge", boxes, seen)

    _otsu_t, otsu_inv = cv2.threshold(y_rect, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    otsu_inv = cv2.morphologyEx(otsu_inv, cv2.MORPH_CLOSE, close_k)
    _boxes_from_mask(otsu_inv, mag, min_area, "otsu-dark", boxes, seen)

    for t in (208, 224):
        bright = (y_rect >= t).astype(np.uint8) * 255
        bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, close_k)
        _boxes_from_mask(bright, mag, min_area, f"bright>={t}", boxes, seen)

    if not boxes:
        raise ValueError(f"單高斯圖上找不到面積至少 {min_area_ratio:.3f} 的矩形。")

    def sort_key(item: Dict[str, Any]) -> Tuple[float, float, float]:
        return (
            float(item["area"]),
            float(item["fillScore"]),
            float(item["edgeScore"]),
        )

    boxes.sort(key=sort_key, reverse=True)
    best = boxes[0]
    contour = best.get("contour")
    if contour is None or len(contour) < 3:
        raise ValueError("入選暗區沒有可用輪廓，無法估計傾斜矩形。")

    cx, cy, rw, rh, angle = _normalize_min_area_rect(cv2.minAreaRect(contour.astype(np.float32)))
    corners = cv2.boxPoints(((cx, cy), (rw, rh), angle)).astype(np.float64)
    xs = corners[:, 0]
    ys = corners[:, 1]
    env_x = int(np.floor(xs.min()))
    env_y = int(np.floor(ys.min()))
    env_w = int(np.ceil(xs.max())) - env_x
    env_h = int(np.ceil(ys.max())) - env_y
    env_x, env_y, env_w, env_h = _clamp_box(env_x, env_y, env_w, env_h, width, height)

    return {
        "x": env_x,
        "y": env_y,
        "w": float(rw),
        "h": float(rh),
        "cx": float(cx),
        "cy": float(cy),
        "angle": float(angle),
        "corners": corners.tolist(),
        "aspect": _aspect(rw, rh),
        "area": float(rw * rh),
        "edgeScore": float(best["edgeScore"]),
        "candidateCount": len(boxes),
        "source": str(best["source"]),
        "aabb": {"x": env_x, "y": env_y, "w": env_w, "h": env_h},
    }
