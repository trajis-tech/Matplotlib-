# -*- coding: utf-8 -*-
"""Chain B: four-Gaussian map and inverted binary on the center crop."""

from __future__ import annotations

from typing import Dict, Sequence, Tuple

import numpy as np


def scale_params(
    A: float,
    A0: float,
    mus: Sequence[float],
    T: float,
) -> Tuple[float, Tuple[float, float, float, float], float]:
    """r = A / A0; mu_i' and T' keep fractions (no rounding)."""
    base = float(A0) if float(A0) else 186.0
    r = float(A) / base
    mu_prime = tuple(float(m) * r for m in mus)
    while len(mu_prime) < 4:
        mu_prime = mu_prime + (mu_prime[-1] if mu_prime else 0.0,)
    mu_prime = mu_prime[:4]
    t_prime = float(T) * r
    return r, mu_prime, t_prime


def four_gaussian_map(
    gray: np.ndarray,
    mu_prime: Sequence[float],
    sigma2: float = 25.0,
) -> np.ndarray:
    """y_cap(x) = 255 * (1 - max_i exp(-(x - mu_i')^2 / (2 * sigma2))).

    With sigma2 = 25 this is exp(-d^2 / 50). No per-step LUT.
    """
    x = gray.astype(np.float64)
    var = max(float(sigma2), 1e-12)
    g_max = None
    for mu in mu_prime[:4]:
        g = np.exp(-np.square(x - float(mu)) / (2.0 * var))
        g_max = g if g_max is None else np.maximum(g_max, g)
    y = 255.0 * (1.0 - g_max)
    return np.clip(np.round(y), 0, 255).astype(np.uint8)


def invert_binary(y_cap: np.ndarray, t_prime: float, invert: bool = True) -> np.ndarray:
    """Compare y_cap with T'. Invert: <= T' white 255, > T' black 0."""
    dark = y_cap.astype(np.float64) <= float(t_prime)
    if invert:
        out = np.where(dark, 255, 0).astype(np.uint8)
    else:
        out = np.where(dark, 0, 255).astype(np.uint8)
    return out


def chain_b_maps(
    crop_gray: np.ndarray,
    A: float,
    params: Dict,
) -> Tuple[np.ndarray, np.ndarray, float, Tuple[float, float, float, float], float]:
    mus = (params["mu1"], params["mu2"], params["mu3"], params["mu4"])
    r, mu_prime, t_prime = scale_params(A, params["A0"], mus, params["T"])
    y_cap = four_gaussian_map(crop_gray, mu_prime, params["sigma2"])
    binary = invert_binary(y_cap, t_prime, bool(params.get("invert", True)))
    return y_cap, binary, r, mu_prime, t_prime
