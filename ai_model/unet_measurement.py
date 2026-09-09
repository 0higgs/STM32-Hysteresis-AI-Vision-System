"""U-Net magnetic-loop segmentation and fixed-grid measurement."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy.signal import find_peaks


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "hysteresis_unet_v1.keras"
GRID = ROOT / "ai_model" / "fixed_screen_grid.json"


class UNetLoopMeasurer:
    """Lazy-loadable local TensorFlow model for the fixed acquisition setup."""

    # Original phone photo ROI and the U-Net input resolution.
    ROI = (2059, 404, 3800, 2054)
    TARGET_SIZE = (640, 600)

    def __init__(self) -> None:
        import tensorflow as tf

        if not MODEL.is_file():
            raise FileNotFoundError(f"Missing trained model: {MODEL}")
        grid = json.loads(GRID.read_text(encoding="utf-8"))
        xs = np.asarray(grid["vertical_grid_candidates_x"], dtype=float)
        ys = np.asarray(grid["horizontal_grid_candidates_y"], dtype=float)
        # These are only fallbacks. The actual origin/grid is detected per photo
        # because small camera translations make a fixed origin visibly wrong.
        self.x0 = 301.0
        self.y0 = 339.0
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
            "hc_negative": (x0 + hc_neg * x_div, y0),
            "hc_positive": (x0 + hc_pos * x_div, y0),
            "br_positive": (x0, y0 - br_pos * y_div),
            "br_negative": (x0, y0 - br_neg * y_div),
            "extreme_positive": (xs[pos], ys[pos]), "extreme_negative": (xs[neg], ys[neg]),
        }
        base = np.asarray(crop, dtype=np.float32)
        blue = np.zeros_like(base); blue[..., 2] = 255
        overlay = Image.fromarray((base * (1 - mask[..., None] * .55) + blue * (mask[..., None] * .55)).astype(np.uint8))
        return {
            "points_in_crop": points, "overlay": overlay,
            "features_div": {"hc_negative": hc_neg, "hc_positive": hc_pos, "br_positive": br_pos, "br_negative": br_neg},
            "trace_pixels": int(len(xs)), "mean_probability_on_trace": float(probability[mask].mean()),
            "grid_size_px": float((x_div + y_div) / 2), "grid_origin_px": (x0, y0),
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
            return float(close[np.argmin(abs(close - reference))]) if len(close) else reference

        def spacing(candidates, fallback):
            gaps = np.diff(candidates.astype(float))
            gaps = gaps[(gaps >= 55) & (gaps <= 100)]
            return float(np.median(gaps)) if len(gaps) >= 3 else fallback

        x0, y0 = near_axis(x_peaks, self.x0), near_axis(y_peaks, self.y0)
        x_div, y_div = spacing(x_peaks, self.x_div), spacing(y_peaks, self.y_div)
        quality = "dynamic" if abs(x0 - self.x0) <= 45 and abs(y0 - self.y0) <= 45 else "fallback"
        return x0, y0, x_div, y_div, quality
