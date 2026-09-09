"""Render model predictions against manual masks for visual validation."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from PIL import Image
import tensorflow as tf


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "dataset" / "segmentation_v1"
RUN = ROOT / "runs" / "unet_v1_tensorflow"


def overlay(base: Image.Image, mask: np.ndarray, color: tuple[int, int, int], alpha: int) -> Image.Image:
    layer = Image.new("RGBA", base.size, color + (0,))
    layer.putalpha(Image.fromarray(np.where(mask, alpha, 0).astype(np.uint8)))
    return Image.alpha_composite(base, layer)


def main() -> None:
    with (DATASET / "samples.csv").open(newline="", encoding="utf-8-sig") as handle:
        valid_rows = [row for row in csv.DictReader(handle) if row["split"] == "valid"]
    model = tf.keras.models.load_model(RUN / "best.keras", compile=False)
    output = RUN / "validation_previews"
    output.mkdir(exist_ok=True)
    summary: list[str] = ["id,condition,dice,iou"]
    for row in valid_rows:
        image = Image.open(DATASET / row["image"]).convert("RGB")
        truth = np.asarray(Image.open(DATASET / row["mask"]).convert("L")) > 127
        array = np.asarray(image, dtype=np.float32)[None, ...] / 255.0
        predicted = model.predict(array, verbose=0)[0, ..., 0] >= 0.5
        intersection = (truth & predicted).sum()
        dice = (2 * intersection + 1) / (truth.sum() + predicted.sum() + 1)
        iou = (intersection + 1) / ((truth | predicted).sum() + 1)
        canvas = image.convert("RGBA")
        canvas = overlay(canvas, truth, (255, 40, 40), 110)      # manual target: red
        canvas = overlay(canvas, predicted, (30, 120, 255), 110) # prediction: blue
        canvas.convert("RGB").save(output / f"{row['id']}_truth_red_prediction_blue.jpg", quality=95)
        summary.append(f"{row['id']},{row['condition']},{dice:.6f},{iou:.6f}")
    (output / "metrics.csv").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print(f"PREVIEWS={len(valid_rows)} OUTPUT={output}")


if __name__ == "__main__":
    main()
