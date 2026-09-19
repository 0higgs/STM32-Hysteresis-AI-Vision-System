"""Regression tests for the deployment model's public geometry contract."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from ai_model.unet_measurement import MODEL_METADATA, UNetLoopMeasurer


class ModelGeometryContractTests(unittest.TestCase):
    def test_class_geometry_matches_deployed_model_metadata(self) -> None:
        metadata = json.loads(Path(MODEL_METADATA).read_text(encoding="utf-8"))
        self.assertEqual(UNetLoopMeasurer.ROI, tuple(metadata["source_roi_xyxy"]))
        self.assertEqual(UNetLoopMeasurer.TARGET_SIZE, tuple(metadata["target_size_wh"]))


if __name__ == "__main__":
    unittest.main()
