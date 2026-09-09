"""Extract Hc/Br/extreme features in oscilloscope divisions from U-Net masks.

This is the deterministic successor to the old Streamlit CV point extractor:
the old method's physical definitions are retained, while the trace source is
the learned U-Net mask rather than a colour threshold.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MASKS = ROOT / "predictions" / "unet_v1" / "masks_640x600"
GRID = ROOT / "calibration" / "fixed_screen_v1" / "grid_candidates.json"
OUT = ROOT / "calibration" / "fixed_screen_v1"


def main() -> None:
    grid = json.loads(GRID.read_text(encoding="utf-8"))
    xlines = np.array(grid["vertical_grid_candidates_x"], dtype=float)
    ylines = np.array(grid["horizontal_grid_candidates_y"], dtype=float)
    x0 = float(xlines[np.argmin(abs(xlines - np.median(xlines)))])
    y0 = float(ylines[np.argmin(abs(ylines - np.median(ylines)))])
    x_div = float(np.median(np.diff(xlines)))
    y_div = float(np.median(np.diff(ylines)))
    band = 0.12 * min(x_div, y_div)
    rows: list[dict[str, str]] = []

    for path in sorted(MASKS.glob("*.png")):
        mask = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        ys, xs = np.where(mask > 0)
        if len(xs) < 50:
            continue
        gx = (xs - x0) / x_div
        gy = (y0 - ys) / y_div
        horizontal = gx[np.abs(ys - y0) <= band]
        vertical = gy[np.abs(xs - x0) <= band]
        # The 10/90 percentiles reject the thickened-mask edges while retaining
        # the two physical crossings when the trace is bright or slightly fuzzy.
        hc_neg = float(np.percentile(horizontal, 10)) if len(horizontal) else float("nan")
        hc_pos = float(np.percentile(horizontal, 90)) if len(horizontal) else float("nan")
        br_neg = float(np.percentile(vertical, 10)) if len(vertical) else float("nan")
        br_pos = float(np.percentile(vertical, 90)) if len(vertical) else float("nan")
        diagonal = gx - gy
        positive = int(np.argmax(diagonal))
        negative = int(np.argmin(diagonal))
        rows.append({
            "image": f"{path.stem}.jpg",
            "hc_negative_div": f"{hc_neg:.6f}",
            "hc_positive_div": f"{hc_pos:.6f}",
            "br_positive_div": f"{br_pos:.6f}",
            "br_negative_div": f"{br_neg:.6f}",
            "h_bias_div": f"{((hc_pos + hc_neg) / 2):.6f}",
            "br_bias_div": f"{((br_pos + br_neg) / 2):.6f}",
            "hc_half_span_div": f"{((hc_pos - hc_neg) / 2):.6f}",
            "br_half_span_div": f"{((br_pos - br_neg) / 2):.6f}",
            "h_extreme_positive_div": f"{gx[positive]:.6f}",
            "b_extreme_positive_div": f"{gy[positive]:.6f}",
            "h_extreme_negative_div": f"{gx[negative]:.6f}",
            "b_extreme_negative_div": f"{gy[negative]:.6f}",
            "grid_origin_x_px": f"{x0:.2f}",
            "grid_origin_y_px": f"{y0:.2f}",
            "x_pixels_per_div": f"{x_div:.2f}",
            "y_pixels_per_div": f"{y_div:.2f}",
        })

    if len(rows) != 500:
        raise RuntimeError(f"Expected 500 prediction masks, extracted {len(rows)}")
    output = OUT / "curve_features_grid_units.csv"
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    print(f"OUTPUT={output} ROWS={len(rows)} ORIGIN=({x0:.2f},{y0:.2f}) DIV=({x_div:.2f},{y_div:.2f})")


if __name__ == "__main__":
    main()
