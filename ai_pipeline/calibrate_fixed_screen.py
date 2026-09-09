"""Find the fixed oscilloscope graticule from a set of phone photographs.

The camera and scope are fixed, so a median reference suppresses the changing
hysteresis trace while retaining the stationary grid.  The script writes a
diagnostic overlay; physical-value fitting is deliberately a later step.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "dataset" / "roboflow_upload_v1" / "images"
CONFIG = ROOT / "dataset" / "segmentation_v1" / "dataset_config.json"
OUT = ROOT / "calibration" / "fixed_screen_v1"


def fit_grid_lattice(signal: np.ndarray, min_spacing: float, max_spacing: float) -> list[float]:
    """Fit an evenly spaced lattice to a 1-D grid-strength projection."""
    length = len(signal)
    background = cv2.GaussianBlur(signal.reshape(1, -1), (0, 0), sigmaX=18).ravel()
    detail = signal - background
    best: tuple[float, float, float] | None = None
    for spacing in np.arange(min_spacing, max_spacing + 0.01, 0.25):
        for offset in np.arange(0, spacing, 0.5):
            positions = np.arange(offset, length, spacing)
            if len(positions) < 5:
                continue
            value = sum(detail[max(0, round(point) - 3):min(length, round(point) + 4)].mean() for point in positions)
            if best is None or value > best[0]:
                best = (float(value), float(offset), float(spacing))
    if best is None:
        raise RuntimeError("Could not fit grid lattice")
    _, offset, spacing = best
    positions = np.arange(offset, length, spacing)
    refined = []
    for point in positions:
        center = round(point)
        lo, hi = max(0, center - 10), min(length, center + 11)
        refined.append(float(lo + np.argmax(detail[lo:hi])))
    return refined


def main() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    left, top, right, bottom = config["source_roi_xyxy"]
    width, height = config["target_size_wh"]
    paths = sorted(SOURCE.glob("*.jpg"))
    indices = np.linspace(0, len(paths) - 1, 31, dtype=int)
    frames = []
    for index in indices:
        image = cv2.imread(str(paths[index]), cv2.IMREAD_COLOR)
        crop = image[top:bottom, left:right]
        frames.append(cv2.resize(crop, (width, height), interpolation=cv2.INTER_AREA))
    reference = np.median(np.stack(frames, axis=0), axis=0).astype(np.uint8)
    # The changing trace is cyan/green and the graticule is red.  This
    # chromatic separation survives the multi-image median much better than
    # generic edge detection in the glare-heavy CRT photos.
    blue, green, red = cv2.split(reference)
    grid_strength = np.maximum(0, red.astype(np.float32) - green.astype(np.float32))
    vertical_projection = grid_strength[45:575, :].mean(axis=0)
    horizontal_projection = grid_strength[:, 10:620].mean(axis=1)
    vertical = fit_grid_lattice(vertical_projection, 68, 90)
    horizontal = fit_grid_lattice(horizontal_projection, 68, 90)
    overlay = reference.copy()
    for y in horizontal:
        cv2.line(overlay, (0, round(y)), (width - 1, round(y)), (0, 0, 255), 2)
    for x in vertical:
        cv2.line(overlay, (round(x), 0), (round(x), height - 1), (255, 0, 0), 2)

    OUT.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT / "median_reference.jpg"), reference)
    cv2.imwrite(str(OUT / "grid_candidates.jpg"), overlay)
    result = {
        "reference_images": len(frames),
        "roi_xyxy_source": [left, top, right, bottom],
        "roi_size": [width, height],
        "horizontal_grid_candidates_y": [round(value, 2) for value in horizontal],
        "vertical_grid_candidates_x": [round(value, 2) for value in vertical],
    }
    (OUT / "grid_candidates.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
