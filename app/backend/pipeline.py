# -*- coding: utf-8 -*-
"""Pipeline: chain A (rectangle on single Gaussian) then chain B (lines on binary)."""

from __future__ import annotations

import base64
from typing import Any, Dict, Tuple

import cv2
import numpy as np

from black_lines import draw_labeled_lines, search_black_lines
from find_rect import find_large_rect
from four_gauss import chain_b_maps
from single_gauss import single_gaussian_map

_BOOL_KEYS = {"invert"}
_INT_KEYS = {"min_run"}
_FLOAT_KEYS = {
    "rect_mu",
    "rect_sigma2",
    "min_area_ratio",
    "A0",
    "mu1",
    "mu2",
    "mu3",
    "mu4",
    "sigma2",
    "T",
    "crop_ratio",
    "line_fill",
}


def coerce_params(params: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(params or {})
    for key in _BOOL_KEYS:
        if key not in out:
            continue
        value = out[key]
        if isinstance(value, str):
            out[key] = value.strip().lower() in {"1", "true", "yes", "y", "on"}
        else:
            out[key] = bool(value)
    for key in _INT_KEYS:
        if key not in out or out[key] in ("", None):
            continue
        try:
            val = float(out[key])
        except (TypeError, ValueError):
            continue
        if val != val:
            continue
        out[key] = int(val)
    for key in _FLOAT_KEYS:
        if key not in out or out[key] in ("", None):
            continue
        try:
            val = float(out[key])
        except (TypeError, ValueError):
            continue
        if val != val:
            continue
        out[key] = val

    defaults = {
        "rect_mu": 172.0,
        "rect_sigma2": 25.0,
        "min_area_ratio": 0.05,
        "A0": 186.0,
        "mu1": 83.0,
        "mu2": 101.0,
        "mu3": 119.0,
        "mu4": 145.0,
        "sigma2": 25.0,
        "T": 150.0,
        "invert": True,
        "crop_ratio": 0.5,
        "min_run": 3,
        "line_fill": 0.55,
    }
    for key, default in defaults.items():
        if key not in out or out[key] in ("", None):
            out[key] = default
    out["invert"] = bool(out.get("invert", True))
    out["min_run"] = int(out.get("min_run", 3))
    if out["min_run"] == 5:
        out["min_run"] = 3
    out["min_run"] = max(3, out["min_run"])
    out["line_fill"] = float(out.get("line_fill", 0.55))
    if out["line_fill"] <= 0 or out["line_fill"] >= 1:
        out["line_fill"] = 0.55
    out["crop_ratio"] = float(out.get("crop_ratio", 0.5))
    if out["crop_ratio"] <= 0:
        out["crop_ratio"] = 0.5
    return out


def load_gray(path: str) -> np.ndarray:
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        raise ValueError("影像檔為空。")
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("無法解碼影像。")
    if img.ndim == 2:
        gray = img
    else:
        gray = img[:, :, 0]
    if gray.dtype != np.uint8:
        gray = np.clip(gray, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(gray)


def _rect_corners(rect: Dict[str, Any]) -> np.ndarray:
    corners = np.asarray(rect["corners"], dtype=np.float64).reshape(-1, 2)
    if corners.shape[0] < 3:
        raise ValueError("矩形缺少四角座標。")
    return np.round(corners).astype(np.int32)


def outside_mean(gray: np.ndarray, rect: Dict[str, Any]) -> float:
    inside = np.zeros(gray.shape[:2], dtype=np.uint8)
    cv2.fillConvexPoly(inside, _rect_corners(rect), 255)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    inside = cv2.dilate(inside, kernel)
    outside = inside == 0
    if not np.any(outside):
        raise ValueError("矩形外部沒有可計算的像素。")
    return float(np.mean(gray[outside].astype(np.float64)))


def rotate_around_center(
    image: np.ndarray,
    cx: float,
    cy: float,
    angle_deg: float,
) -> np.ndarray:
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((float(cx), float(cy)), float(angle_deg), 1.0)
    return cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )


def center_crop(
    gray: np.ndarray,
    cx: float,
    cy: float,
    crop_w: int,
    crop_h: int,
) -> Tuple[np.ndarray, int, int, int, int]:
    height, width = gray.shape[:2]
    crop_w = max(1, int(crop_w))
    crop_h = max(1, int(crop_h))
    x0 = int(round(cx - crop_w / 2.0))
    y0 = int(round(cy - crop_h / 2.0))
    x1 = x0 + crop_w
    y1 = y0 + crop_h
    x0c = max(0, x0)
    y0c = max(0, y0)
    x1c = min(width, x1)
    y1c = min(height, y1)
    if x1c <= x0c or y1c <= y0c:
        raise ValueError("裁剪區域落在影像外。")
    crop = gray[y0c:y1c, x0c:x1c]
    return crop, x0c, y0c, int(crop.shape[1]), int(crop.shape[0])


def encode_png_b64(image: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("無法編碼 PNG。")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def save_png(path: str, image: np.ndarray) -> None:
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("無法編碼 PNG。")
    buf.tofile(path)


def to_bgr(gray: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def paste_on_full(full_bgr: np.ndarray, crop: np.ndarray, x0: int, y0: int) -> np.ndarray:
    canvas = np.zeros_like(full_bgr)
    dim = (full_bgr.astype(np.float32) * 0.25).astype(np.uint8)
    canvas[:, :] = dim
    patch = crop if crop.ndim == 3 else to_bgr(crop)
    h, w = patch.shape[:2]
    canvas[y0 : y0 + h, x0 : x0 + w] = patch
    return canvas


def run_pipeline(image_path: str, param_values: Dict[str, Any]) -> Dict[str, Any]:
    params = coerce_params(param_values)
    gray = load_gray(image_path)
    original_bgr = to_bgr(gray)

    y_rect = single_gaussian_map(gray, params["rect_mu"], params["rect_sigma2"])
    rect = find_large_rect(y_rect, params)
    cx = float(rect["cx"])
    cy = float(rect["cy"])
    W = float(rect["w"])
    H = float(rect["h"])
    angle = float(rect["angle"])

    A = outside_mean(gray, rect)
    rotated = rotate_around_center(gray, cx, cy, angle)
    rotated_bgr = to_bgr(rotated)
    crop_w = int(round(float(params["crop_ratio"]) * W))
    crop_h = int(round(float(params["crop_ratio"]) * H))
    crop_gray, crop_x, crop_y, actual_w, actual_h = center_crop(rotated, cx, cy, crop_w, crop_h)

    y_cap, binary, r, mu_prime, t_prime = chain_b_maps(crop_gray, A, params)

    left_x = int(round(cx - crop_w / 4.0))
    right_x = int(round(cx + crop_w / 4.0))
    seed_y = int(round(cy))
    seeds_xy = {
        "left": (left_x, seed_y),
        "right": (right_x, seed_y),
    }

    lines = search_black_lines(
        binary,
        (crop_x, crop_y),
        seeds_xy,
        (cx, cy),
        params["min_run"],
        line_fill=float(params["line_fill"]),
    )
    overlay = draw_labeled_lines(rotated_bgr, lines, seeds_xy=seeds_xy)

    rect_view = to_bgr(y_rect)
    quad = _rect_corners(rect)
    cv2.polylines(rect_view, [quad], True, (40, 220, 40), 2, cv2.LINE_AA)
    cv2.drawMarker(
        rect_view,
        (int(round(cx)), int(round(cy))),
        (0, 255, 255),
        markerType=cv2.MARKER_CROSS,
        markerSize=14,
        thickness=1,
    )

    warning = "；".join(lines["warnings"]) if lines["warnings"] else ""
    counts = {k: len(v) for k, v in lines["directions"].items()}
    pass_counts = lines.get("passCounts") or {k: 0 for k in counts}
    fail_counts = lines.get("failCounts") or {k: 0 for k in counts}
    aabb = rect.get("aabb") or {"x": int(rect["x"]), "y": int(rect["y"]), "w": int(round(W)), "h": int(round(H))}

    metrics = {
        "A": A,
        "r": r,
        "muPrime": list(mu_prime),
        "Tprime": t_prime,
        "rect": {
            "x": int(aabb["x"]),
            "y": int(aabb["y"]),
            "w": W,
            "h": H,
            "angle": angle,
            "corners": rect["corners"],
        },
        "angle": angle,
        "aspect": float(rect["aspect"]),
        "candidateCount": int(rect["candidateCount"]),
        "edgeScore": float(rect["edgeScore"]),
        "center": {"x": cx, "y": cy},
        "crop": {"x": crop_x, "y": crop_y, "w": actual_w, "h": actual_h, "requestedW": crop_w, "requestedH": crop_h},
        "seeds": {
            "left": {"x": left_x, "y": seed_y, "relX": left_x - cx, "relY": seed_y - cy},
            "right": {"x": right_x, "y": seed_y, "relX": right_x - cx, "relY": seed_y - cy},
        },
        "lineCounts": counts,
        "lineCountsPass": pass_counts,
        "lineCountsFail": fail_counts,
        "lineMinRun": lines.get("minRun"),
        "lineFill": lines.get("lineFill"),
        "lines": lines["directions"],
        "missingRegions": lines["missingRegions"],
        "warning": warning,
        "rectSource": rect.get("source"),
    }

    stage_images = {
        "original": encode_png_b64(original_bgr),
        "single_gauss": encode_png_b64(to_bgr(y_rect)),
        "rectangle": encode_png_b64(rect_view),
        "four_gauss": encode_png_b64(paste_on_full(rotated_bgr, y_cap, crop_x, crop_y)),
        "binary": encode_png_b64(paste_on_full(rotated_bgr, binary, crop_x, crop_y)),
        "overlay": encode_png_b64(overlay),
    }

    return {
        "ok": True,
        "metrics": metrics,
        "stageImages": stage_images,
        "overlayBgr": overlay,
    }
