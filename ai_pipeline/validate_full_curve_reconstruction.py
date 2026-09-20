"""Validate grid detection and full-curve reconstruction on a dataset split."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_model.unet_measurement import UNetLoopMeasurer  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="valid")
    args = parser.parse_args()

    dataset = ROOT / "python" / "dataset" / "segmentation_v1"
    originals = ROOT / "python" / "images"
    with (dataset / "samples.csv").open(encoding="utf-8-sig", newline="") as handle:
        sample_ids = [row["id"] for row in csv.DictReader(handle) if row["split"] == args.split]

    measurer = UNetLoopMeasurer()
    rows = []
    for sample_id in sample_ids:
        try:
            result = measurer.analyse(Image.open(originals / f"{sample_id}.jpg"))
            rows.append(
                {
                    "sample_id": sample_id,
                    "status": result["grid_quality"]["status"],
                    "grid_x": round(result["grid_size_x_px"], 2),
                    "grid_y": round(result["grid_size_y_px"], 2),
                    "upper_points": len(result["branches_in_crop"]["upper"]),
                    "lower_points": len(result["branches_in_crop"]["lower"]),
                }
            )
        except Exception as exc:
            rows.append({"sample_id": sample_id, "status": "error", "error": str(exc)})

    summary = {
        "split": args.split,
        "sample_count": len(rows),
        "status_counts": dict(Counter(row["status"] for row in rows)),
        "failures": [row for row in rows if row["status"] != "detected"],
        "minimum_branch_points": min(
            (min(row["upper_points"], row["lower_points"]) for row in rows if "upper_points" in row),
            default=0,
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
