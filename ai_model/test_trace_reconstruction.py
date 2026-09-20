"""Unit tests for grid validation and full-loop branch reconstruction."""

from __future__ import annotations

import unittest

import numpy as np
from PIL import Image

from ai_model.unet_measurement import (
    UNetLoopMeasurer,
    extract_trace_branches,
    measure_trace_features,
)


class TraceReconstructionTests(unittest.TestCase):
    def test_extracts_two_ordered_branches_from_thick_mask(self) -> None:
        mask = np.zeros((120, 160), dtype=np.uint8)
        xs = np.arange(15, 145)
        upper = 42.0 - 12.0 * np.tanh((xs - 80.0) / 24.0)
        lower = 78.0 - 12.0 * np.tanh((xs - 80.0) / 24.0)
        for x, y_upper, y_lower in zip(xs, upper, lower):
            mask[int(round(y_upper)) - 2 : int(round(y_upper)) + 3, x] = 1
            mask[int(round(y_lower)) - 2 : int(round(y_lower)) + 3, x] = 1

        branches = extract_trace_branches(mask)
        self.assertGreater(len(branches["upper"]), 100)
        self.assertEqual(len(branches["upper"]), len(branches["lower"]))
        upper_y = np.asarray([point[1] for point in branches["upper"]])
        lower_y = np.asarray([point[1] for point in branches["lower"]])
        self.assertTrue(np.all(upper_y < lower_y))

    def test_blank_grid_is_reported_as_fallback(self) -> None:
        measurer = UNetLoopMeasurer.__new__(UNetLoopMeasurer)
        measurer.x0, measurer.y0 = 313.0, 326.0
        measurer.x_div, measurer.y_div = 70.0, 70.0
        crop = Image.fromarray(np.full((600, 640, 3), 220, dtype=np.uint8))

        _, _, _, _, quality = measurer._locate_grid(crop)
        self.assertEqual(quality["status"], "fallback")
        self.assertFalse(quality["x_axis_detected"])
        self.assertFalse(quality["y_axis_detected"])

    def test_features_are_measured_from_reconstructed_branches(self) -> None:
        xs = np.arange(15.0, 146.0)
        upper_y = 80.0 - 40.0 / (1.0 + np.exp(-(xs - 50.0) / 10.0))
        lower_y = 80.0 - 40.0 / (1.0 + np.exp(-(xs - 100.0) / 10.0))
        branches = {
            "upper": list(zip(xs, upper_y)),
            "lower": list(zip(xs, lower_y)),
        }

        points, features = measure_trace_features(branches, x0=80.0, y0=60.0, x_div=20.0, y_div=20.0)
        self.assertLess(points["hc_negative"][0], 80.0)
        self.assertGreater(points["hc_positive"][0], 80.0)
        self.assertLess(points["br_positive"][1], 60.0)
        self.assertGreater(points["br_negative"][1], 60.0)
        self.assertLess(features["hc_negative"], 0.0)
        self.assertGreater(features["hc_positive"], 0.0)
        self.assertGreater(features["br_positive"], 0.0)
        self.assertLess(features["br_negative"], 0.0)


if __name__ == "__main__":
    unittest.main()
