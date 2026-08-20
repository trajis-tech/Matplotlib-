# -*- coding: utf-8 -*-
"""Chain A: single-Gaussian map on the full original grayscale."""

from __future__ import annotations

import numpy as np


def single_gaussian_map(gray: np.ndarray, mu: float = 172.0, sigma2: float = 25.0) -> np.ndarray:
    """y_rect(x) = 255 * (1 - exp(-(x - mu)^2 / (2 * sigma2))).

    Writes 8-bit by rounding only; no per-step quantization LUT.
    """
    x = gray.astype(np.float64)
    var = max(float(sigma2), 1e-12)
    y = 255.0 * (1.0 - np.exp(-np.square(x - float(mu)) / (2.0 * var)))
    return np.clip(np.round(y), 0, 255).astype(np.uint8)
