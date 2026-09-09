"""Local U-Net inference for a fixed oscilloscope/camera arrangement.

This module replaces colour-threshold trace extraction.  It returns screen-grid
measurements in divisions and volts.  It intentionally does *not* invent H/B
physical units from legacy circuit defaults: conversion to H and B needs the
real experimental calibration supplied by the operator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "runs" / "unet_v1_tensorflow" / "best.keras"
DEFAULT_DATASET_CONFIG = ROOT / "dataset" / "segmentation_v1" / "dataset_config.json"
DEFAULT_GRID_CONFIG = ROOT / "calibration" / "fixed_screen_v1" / "grid_candidates.json"


class UNetLoopMeasurer:
    """Load the trained segmentation model once, then analyse uploaded images."""

    def __init__(
        self,
        model_path: Path = DEFAULT_MODEL,
        dataset_config_path: Path = DEFAULT_DATASET_CONFIG,
        grid_config_path: Path = DEFAULT_GRID_CONFIG,
    ) -> None:
        # Delayed import keeps normal desktop-control startup free of TensorFlow.
        import tensorflow as tf

        dataset = json.loads(Path(dataset_config_path).read_text(encoding="utf-8"))
        grid = json.loads(Path(grid_config_path).read_text(encoding="utf-8"))
        self.roi = tuple(int(value) for value in dataset["source_roi_xyxy"])
        self.target_size = tuple(int(value) for value in dataset["target_size_wh"])
        xlines = np.asarray(grid["vertical_grid_candidates_x"], dtype=float)
        ylines = np.asarray(grid["horizontal_grid_candidates_y"], dtype=float)
        self.x0 = float(xlines[np.argmin(abs(xlines - np.median(xlines)))])
        self.y0 = float(ylines[np.argmin(abs(ylines - np.median(ylines)))])
        self.x_div = float(np.median(np.diff(xlines)))
        self.y_div = float(np.median(np.diff(ylines)))
        self.model = tf.keras.models.load_model(model_path, compile=False)

    def analyse(self, image: Image.Image, *, threshold: float = 0.50, volts_per_div: float = 0.5) -> dict[str, Any]:
        """Return prediction mask, review overlay and trace measurements.

        ``volts_per_div`` is a screen setting, not a material calibration. The
        returned ``*_volts`` values are channel voltages only.
        """
        image = image.convert("RGB")
        left, top, right, bottom = self.roi
        if image.width < right or image.height < bottom:
            raise ValueError(
                f"Image is {image.width}x{image.height}, smaller than the fixed trained ROI "
                f"({left}, {top}, {right}, {bottom}). Use a photo from the same camera setup."
            )
        crop = image.crop(self.roi).resize(self.target_size, Image.Resampling.LANCZOS)
        batch = np.asarray(crop, dtype=np.float32)[None, ...] / 255.0
        probability = self.model.predict(batch, verbose=0)[0, ..., 0]
        mask = probability >= threshold
        measurements = self._measure_mask(mask, volts_per_div)
        measurements["mean_probability_on_trace"] = float(probability[mask].mean())
        overlay = self._overlay(crop, mask)
        measurements.update({
            "crop": crop,
            "overlay": overlay,
            "mask": Image.fromarray((mask * 255).astype(np.uint8), mode="L"),
            "probability": probability,
            "threshold": float(threshold),
            "roi_xyxy_source": self.roi,
            "screen_calibration": {
                "origin_px_in_crop": [self.x0, self.y0],
                "pixels_per_div": [self.x_div, self.y_div],
                "volts_per_div": float(volts_per_div),
            },
            "method": "TensorFlow U-Net segmentation + fixed-grid geometric measurement",
            "physical_unit_notice": "Only divisions and channel volts are measured. H/B conversion requires real circuit calibration, not old defaults.",
        })
        return measurements

    def _measure_mask(self, mask: np.ndarray, volts_per_div: float) -> dict[str, Any]:
        ys, xs = np.where(mask)
        if len(xs) < 50:
            raise ValueError("U-Net did not find enough trace pixels; check camera position and exposure.")
        gx = (xs - self.x0) / self.x_div
        gy = (self.y0 - ys) / self.y_div
        band = 0.12 * min(self.x_div, self.y_div)
        horizontal = gx[np.abs(ys - self.y0) <= band]
        vertical = gy[np.abs(xs - self.x0) <= band]

        def pair(values: np.ndarray) -> tuple[float, float]:
            if len(values) < 10:
                return float("nan"), float("nan")
            return float(np.percentile(values, 10)), float(np.percentile(values, 90))

        hc_negative, hc_positive = pair(horizontal)
        # Image y increases downwards: larger grid-y means positive B.
        br_negative, br_positive = pair(vertical)
        diagonal = gx - gy
        positive_index, negative_index = int(np.argmax(diagonal)), int(np.argmin(diagonal))
        fields = {
            "hc_negative_div": hc_negative,
            "hc_positive_div": hc_positive,
            "br_positive_div": br_positive,
            "br_negative_div": br_negative,
            "h_bias_div": (hc_positive + hc_negative) / 2,
            "br_bias_div": (br_positive + br_negative) / 2,
            "hc_half_span_div": (hc_positive - hc_negative) / 2,
            "br_half_span_div": (br_positive - br_negative) / 2,
            "h_extreme_positive_div": float(gx[positive_index]),
            "b_extreme_positive_div": float(gy[positive_index]),
            "h_extreme_negative_div": float(gx[negative_index]),
            "b_extreme_negative_div": float(gy[negative_index]),
        }
        fields.update({key.replace("_div", "_volts"): value * volts_per_div for key, value in fields.items() if key.endswith("_div")})
        fields["trace_pixels"] = int(len(xs))
        return fields

    @staticmethod
    def _overlay(crop: Image.Image, mask: np.ndarray) -> Image.Image:
        base = np.asarray(crop.convert("RGB"), dtype=np.float32)
        blue = np.zeros_like(base)
        blue[..., 2] = 255
        alpha = (mask.astype(np.float32) * 0.55)[..., None]
        return Image.fromarray((base * (1 - alpha) + blue * alpha).astype(np.uint8))
