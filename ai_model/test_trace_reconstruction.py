"""Unit tests for grid validation and full-loop branch reconstruction."""

from __future__ import annotations

import unittest

import numpy as np
from PIL import Image

from ai_model.unet_measurement import UNetLoopMeasurer, extract_trace_branches


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


if __name__ == "__main__":
    unittest.main()
