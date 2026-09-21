"""Numerical metrics calculated from reconstructed hysteresis-loop branches."""

from __future__ import annotations

import numpy as np
from scipy.interpolate import PchipInterpolator


def _branch_interpolator(
    branch: list[tuple[float, float]],
) -> tuple[np.ndarray, np.ndarray, PchipInterpolator]:
    points = np.asarray(branch, dtype=float)
    if points.ndim != 2 or points.shape[0] < 2 or points.shape[1] != 2:
        raise ValueError("回线分支至少需要两个二维点")
    if not np.all(np.isfinite(points)):
        raise ValueError("回线分支包含无效数值")

    order = np.argsort(points[:, 0])
    x_values, y_values = points[order, 0], points[order, 1]
    unique_x, inverse = np.unique(x_values, return_inverse=True)
    mean_y = np.asarray(
        [y_values[inverse == index].mean() for index in range(len(unique_x))],
        dtype=float,
    )
    if len(unique_x) < 2:
        raise ValueError("回线分支横坐标范围不足")
    return unique_x, mean_y, PchipInterpolator(unique_x, mean_y)


def calculate_loop_area(
    upper_branch: list[tuple[float, float]],
    lower_branch: list[tuple[float, float]],
    *,
    samples: int = 1200,
) -> dict[str, float]:
    """Integrate the enclosed area between the final plotted branches.

    The magnitude of ``integral((B_upper - B_lower) dH)`` equals the closed
    contour magnitude ``|integral(H dB)|``.  Small negative gaps introduced by
    endpoint pixel noise are clipped, while ``crossing_fraction`` exposes a
    materially invalid branch ordering to the UI instead of hiding it.
    """

    upper_x, upper_y, upper_curve = _branch_interpolator(upper_branch)
    lower_x, lower_y, lower_curve = _branch_interpolator(lower_branch)
    common_min = max(float(upper_x.min()), float(lower_x.min()))
    common_max = min(float(upper_x.max()), float(lower_x.max()))
    if common_max <= common_min:
        raise ValueError("上下分支没有可积分的共同横坐标范围")

    sample_count = max(200, int(samples))
    h_values = np.linspace(common_min, common_max, sample_count)
    gap = np.asarray(upper_curve(h_values) - lower_curve(h_values), dtype=float)
    b_span = max(float(np.ptp(np.concatenate([upper_y, lower_y]))), 1e-12)
    significant_crossing = gap < -(0.01 * b_span)
    physical_gap = np.maximum(gap, 0.0)
    area = float(np.trapezoid(physical_gap, h_values))

    return {
        "area": area,
        "crossing_fraction": float(np.mean(significant_crossing)),
        "common_h_min": common_min,
        "common_h_max": common_max,
    }
