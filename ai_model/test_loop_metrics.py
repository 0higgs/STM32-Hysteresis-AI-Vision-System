"""Tests for hysteresis-loop area calculation."""

from __future__ import annotations

import unittest

import numpy as np

from ai_model.loop_metrics import calculate_loop_area


class LoopAreaTests(unittest.TestCase):
    def test_constant_branches_have_expected_rectangular_area(self) -> None:
        x_values = np.linspace(-2.0, 2.0, 21)
        upper = [(float(x), 1.0) for x in x_values]
        lower = [(float(x), -1.0) for x in x_values]

        result = calculate_loop_area(upper, lower)

        self.assertAlmostEqual(result["area"], 8.0, places=6)
        self.assertEqual(result["crossing_fraction"], 0.0)

    def test_small_endpoint_crossing_cannot_make_area_negative(self) -> None:
        upper = [(-1.0, 0.0), (0.0, 1.0), (1.0, -0.10)]
        lower = [(-1.0, 0.10), (0.0, -1.0), (1.0, 0.0)]

        result = calculate_loop_area(upper, lower)

        self.assertGreater(result["area"], 0.0)
        self.assertGreater(result["crossing_fraction"], 0.0)

    def test_rejects_nonoverlapping_branches(self) -> None:
        with self.assertRaisesRegex(ValueError, "共同横坐标范围"):
            calculate_loop_area([(0.0, 1.0), (1.0, 1.0)], [(2.0, -1.0), (3.0, -1.0)])


if __name__ == "__main__":
    unittest.main()
