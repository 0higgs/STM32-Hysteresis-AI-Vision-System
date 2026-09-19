"""Evaluate a deployed Keras U-Net on the reproducible prepared split."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image
import tensorflow as tf


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "python" / "dataset" / "segmentation_v1"
DEFAULT_MODEL = ROOT / "models" / "hysteresis_unet_v1.keras"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--split", choices=("train", "valid"), default="valid")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    model_path = args.model.resolve()
    if not model_path.is_file():
        raise FileNotFoundError(model_path)
    with (DATASET / "samples.csv").open(newline="", encoding="utf-8-sig") as handle:
        rows = [row for row in csv.DictReader(handle) if row["split"] == args.split]
    if not rows:
        raise RuntimeError(f"No samples in split: {args.split}")

    model = tf.keras.models.load_model(model_path, compile=False)
    measurements: list[dict[str, str]] = []
    durations: list[float] = []
    for index, row in enumerate(rows):
        image = Image.open(DATASET / row["image"]).convert("RGB")
        truth = np.asarray(Image.open(DATASET / row["mask"]).convert("L")) > 127
        array = np.asarray(image, dtype=np.float32)[None, ...] / 255.0
        start = time.perf_counter()
        probability = model.predict(array, verbose=0)[0, ..., 0]
        durations.append(time.perf_counter() - start)
        predicted = probability >= args.threshold
        intersection = int((truth & predicted).sum())
        union = int((truth | predicted).sum())
        dice = (2 * intersection + 1) / (int(truth.sum()) + int(predicted.sum()) + 1)
        iou = (intersection + 1) / (union + 1)
        measurements.append({
            "id": row["id"],
            "condition": row["condition"],
            "dice": f"{dice:.8f}",
            "iou": f"{iou:.8f}",
            "truth_pixels": str(int(truth.sum())),
            "predicted_pixels": str(int(predicted.sum())),
            "mean_probability": f"{float(probability.mean()):.8f}",
        })
        print(f"EVALUATED={index + 1}/{len(rows)}", flush=True)

    dice_values = np.asarray([float(row["dice"]) for row in measurements])
    iou_values = np.asarray([float(row["iou"]) for row in measurements])
    dataset_config = json.loads((DATASET / "dataset_config.json").read_text(encoding="utf-8"))
    summary = {
        "model": model_path.name,
        "model_sha256": sha256_file(model_path),
        "dataset_source_fingerprint_sha256": dataset_config.get("source_fingerprint_sha256"),
        "split": args.split,
        "sample_count": len(rows),
        "threshold": args.threshold,
        "mean_dice": float(dice_values.mean()),
        "median_dice": float(np.median(dice_values)),
        "min_dice": float(dice_values.min()),
        "mean_iou": float(iou_values.mean()),
        "median_inference_seconds": float(np.median(durations)),
        "tensorflow_version": tf.__version__,
        "device": "GPU" if tf.config.list_physical_devices("GPU") else "CPU",
    }

    if args.output_dir:
        output_dir = args.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        with (output_dir / "per_image_metrics.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(measurements[0]))
            writer.writeheader()
            writer.writerows(measurements)
        (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("SUMMARY=" + json.dumps(summary))


if __name__ == "__main__":
    main()
