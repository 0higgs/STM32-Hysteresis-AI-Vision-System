"""U-Net magnetic-loop segmentation and fixed-grid measurement."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image
from scipy.signal import find_peaks, savgol_filter


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "hysteresis_unet_v1.keras"
GRID = ROOT / "ai_model" / "fixed_screen_grid.json"
MODEL_METADATA = ROOT / "ai_model" / "model_metadata.json"
MODEL_CONFIG = json.loads(MODEL_METADATA.read_text(encoding="utf-8"))


def extract_trace_branches(mask: np.ndarray) -> dict[str, list[tuple[float, float]]]:
    """Reduce a thick loop mask to ordered upper/lower centerlines.

    A hysteresis loop normally intersects a vertical image column twice.  The
    centers of the uppermost and lowermost foreground runs therefore form two
    naturally ordered branches.  At the saturation ends the runs merge; the
    shared center is retained on both branches so the rendered loop closes.
    """
    binary = np.asarray(mask, dtype=np.uint8)
    if binary.ndim != 2:
        raise ValueError("回线掩膜必须是二维数组")
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if component_count <= 1:
        raise ValueError("U-Net 掩膜中没有连续回线")
    component_areas = stats[1:, cv2.CC_STAT_AREA]
    largest_area = int(component_areas.max())
    retained_labels = 1 + np.flatnonzero(component_areas >= max(20, largest_area * 0.05))
    binary = np.isin(labels, retained_labels).astype(np.uint8)

    height, width = binary.shape
    max_run_gap = max(2, int(round(height * 0.006)))
    upper: list[tuple[float, float]] = []
    lower: list[tuple[float, float]] = []
    for x in range(width):
        ys = np.flatnonzero(binary[:, x])
        if len(ys) == 0:
            continue
        split_at = np.flatnonzero(np.diff(ys) > max_run_gap) + 1
        runs = [run for run in np.split(ys, split_at) if len(run) >= 1]
        centers = [float(np.mean(run)) for run in runs]
        upper.append((float(x), min(centers)))
        lower.append((float(x), max(centers)))

    if len(upper) < max(25, width // 20):
        raise ValueError("U-Net 回线横向跨度不足，无法重建完整分支")

    def smooth(branch: list[tuple[float, float]]) -> list[tuple[float, float]]:
        points = np.asarray(branch, dtype=float)
        sample_count = len(points)
        window = min(31, sample_count if sample_count % 2 else sample_count - 1)
        if window >= 7:
            points[:, 1] = savgol_filter(points[:, 1], window_length=window, polyorder=2, mode="interp")
        return [(float(x), float(y)) for x, y in points]

    return {"upper": smooth(upper), "lower": smooth(lower)}


class UNetLoopMeasurer:
    """Lazy-loadable local TensorFlow model for the fixed acquisition setup."""

    # Keep the geometry available on both the class and its instances.  The
    # Streamlit coordinate mapper reads these attributes before inference,
    # while their values still come from the deployed model metadata.
    ROI = tuple(MODEL_CONFIG["source_roi_xyxy"])
    TARGET_SIZE = tuple(MODEL_CONFIG["target_size_wh"])

    def __init__(self) -> None:
        import tensorflow as tf

        if not MODEL.is_file():
            raise FileNotFoundError(f"Missing trained model: {MODEL}")
        grid = json.loads(GRID.read_text(encoding="utf-8"))
        xs = np.asarray(grid["vertical_grid_candidates_x"], dtype=float)
        ys = np.asarray(grid["horizontal_grid_candidates_y"], dtype=float)
        # These are only fallbacks. The actual origin/grid is detected per photo
        # because small camera translations make a fixed origin visibly wrong.
        self.x0, self.y0 = map(float, MODEL_CONFIG["grid_origin_reference_px"])
        self.x_div = float(np.median(np.diff(xs)))
        self.y_div = float(np.median(np.diff(ys)))
        self.model = tf.keras.models.load_model(MODEL, compile=False)

    def analyse(self, image: Image.Image, *, threshold: float = 0.50) -> dict[str, Any]:
        image = image.convert("RGB")
        left, top, right, bottom = self.ROI
        if image.width < right or image.height < bottom:
            raise ValueError("图片尺寸或拍摄位置不符合训练模型的固定相机/示波器设置。")
        crop = image.crop(self.ROI).resize(self.TARGET_SIZE, Image.Resampling.LANCZOS)
        probability = self.model.predict(np.asarray(crop, dtype=np.float32)[None] / 255.0, verbose=0)[0, ..., 0]
        mask = probability >= threshold
        x0, y0, x_div, y_div, grid_quality = self._locate_grid(crop)
        ys, xs = np.where(mask)
        if len(xs) < 50:
            raise ValueError("AI 未识别到足够的回线像素，请检查拍摄位置、清晰度和曝光。")
        gx, gy = (xs - x0) / x_div, (y0 - ys) / y_div
        band = 0.12 * min(x_div, y_div)
        horizontal = gx[np.abs(ys - y0) <= band]
        vertical = gy[np.abs(xs - x0) <= band]

        def crossings(values: np.ndarray) -> tuple[float, float]:
            return (float("nan"), float("nan")) if len(values) < 10 else (float(np.percentile(values, 10)), float(np.percentile(values, 90)))

        hc_neg, hc_pos = crossings(horizontal)
        br_neg, br_pos = crossings(vertical)
        # Saturation extrema are not "diagonal-most" pixels.  Select the
        # physical outer corners of the top/bottom saturation plateaus:
        # positive = top-right; negative = bottom-left.
        top_band = np.where(ys <= np.percentile(ys, 2.0))[0]
        bottom_band = np.where(ys >= np.percentile(ys, 98.0))[0]
        pos = int(top_band[np.argmax(xs[top_band])])
        neg = int(bottom_band[np.argmin(xs[bottom_band])])
        points = {
            "origin": (x0, y0), "scale_right": (x0 + x_div, y0),
            "scale_up": (x0, y0 - y_div),
            "hc_negative": (x0 + hc_neg * x_div, y0),
            "hc_positive": (x0 + hc_pos * x_div, y0),
            "br_positive": (x0, y0 - br_pos * y_div),
            "br_negative": (x0, y0 - br_neg * y_div),
            "extreme_positive": (xs[pos], ys[pos]), "extreme_negative": (xs[neg], ys[neg]),
        }
        branches = extract_trace_branches(mask)
        base = np.asarray(crop, dtype=np.float32)
        blue = np.zeros_like(base); blue[..., 2] = 255
        overlay = Image.fromarray((base * (1 - mask[..., None] * .55) + blue * (mask[..., None] * .55)).astype(np.uint8))
        return {
            "points_in_crop": points, "overlay": overlay,
            "branches_in_crop": branches,
            "features_div": {"hc_negative": hc_neg, "hc_positive": hc_pos, "br_positive": br_pos, "br_negative": br_neg},
            "trace_pixels": int(len(xs)), "mean_probability_on_trace": float(probability[mask].mean()),
            "grid_size_px": float((x_div + y_div) / 2), "grid_origin_px": (x0, y0),
            "grid_size_x_px": float(x_div), "grid_size_y_px": float(y_div),
            "grid_quality": grid_quality,
        }

    def _locate_grid(self, crop: Image.Image):
        """Find this photo's zero axes and division size from the dark grid.

        The U-Net supplies the trace; this independent grid detector prevents a
        small phone displacement from shifting every physical feature point.
        """
        gray = np.asarray(crop.convert("L"), dtype=np.float32)
        x_score, y_score = (255.0 - gray).mean(axis=0), (255.0 - gray).mean(axis=1)

        def peaks(score):
            positions, _ = find_peaks(score, distance=25, prominence=3)
            return positions[(positions > 20) & (positions < len(score) - 20)]

        x_peaks, y_peaks = peaks(x_score), peaks(y_score)

        def near_axis(candidates, reference):
            close = candidates[np.abs(candidates - reference) <= 45]
            if len(close):
                return float(close[np.argmin(abs(close - reference))]), True
            return float(reference), False

        def spacing(candidates, fallback):
            gaps = np.diff(candidates.astype(float))
            gaps = gaps[(gaps >= 55) & (gaps <= 100)]
            if len(gaps) >= 3:
                return float(np.median(gaps)), True, int(len(gaps))
            return float(fallback), False, int(len(gaps))

        x0, x_axis_detected = near_axis(x_peaks, self.x0)
        y0, y_axis_detected = near_axis(y_peaks, self.y0)
        x_div, x_spacing_detected, x_gap_count = spacing(x_peaks, self.x_div)
        y_div, y_spacing_detected, y_gap_count = spacing(y_peaks, self.y_div)
        detected_flags = (x_axis_detected, y_axis_detected, x_spacing_detected, y_spacing_detected)
        status = "detected" if all(detected_flags) else ("partial" if any(detected_flags) else "fallback")
        quality = {
            "status": status,
            "x_axis_detected": x_axis_detected,
            "y_axis_detected": y_axis_detected,
            "x_spacing_detected": x_spacing_detected,
            "y_spacing_detected": y_spacing_detected,
            "x_peak_count": int(len(x_peaks)),
            "y_peak_count": int(len(y_peaks)),
            "x_gap_count": x_gap_count,
            "y_gap_count": y_gap_count,
        }
        return x0, y0, x_div, y_div, quality
