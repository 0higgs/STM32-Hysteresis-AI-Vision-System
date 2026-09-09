"""Run the trained fixed-ROI U-Net on every captured photograph."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
from PIL import Image
import tensorflow as tf


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "dataset" / "roboflow_upload_v1" / "images"
DATASET = ROOT / "dataset" / "segmentation_v1"
MODEL = ROOT / "runs" / "unet_v1_tensorflow" / "best.keras"
OUTPUT = ROOT / "predictions" / "unet_v1"


def tint(base: Image.Image, mask: np.ndarray, rgb: tuple[int, int, int]) -> Image.Image:
    overlay = Image.new("RGBA", base.size, rgb + (0,))
    overlay.putalpha(Image.fromarray(np.where(mask, 140, 0).astype(np.uint8)))
    return Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    config = json.loads((DATASET / "dataset_config.json").read_text(encoding="utf-8"))
    left, top, right, bottom = config["source_roi_xyxy"]
    target_size = tuple(config["target_size_wh"])
    if not MODEL.is_file():
        raise FileNotFoundError(MODEL)
    images = sorted(SOURCE.glob("*.jpg"))
    if len(images) != 500:
        raise RuntimeError(f"Expected 500 captured JPG images, found {len(images)}")
    if OUTPUT.exists() and not args.overwrite:
        raise RuntimeError(f"Output exists: {OUTPUT}. Use --overwrite to regenerate.")
    mask_dir, preview_dir = OUTPUT / "masks_640x600", OUTPUT / "previews"
    mask_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    model = tf.keras.models.load_model(MODEL, compile=False)
    rows: list[dict[str, str]] = []
    # One preview roughly every 20 samples, including both ends of the run.
    preview_indices = set(np.linspace(0, len(images) - 1, 26, dtype=int).tolist())
    for index, path in enumerate(images):
        with Image.open(path) as original:
            original = original.convert("RGB")
            if original.width < right or original.height < bottom:
                raise RuntimeError(f"{path.name}: fixed ROI exceeds image dimensions")
            crop = original.crop((left, top, right, bottom)).resize(target_size, Image.Resampling.LANCZOS)
        array = np.asarray(crop, dtype=np.float32)[None, ...] / 255.0
        probability = model.predict(array, verbose=0)[0, ..., 0]
        binary = probability >= args.threshold
        Image.fromarray((binary * 255).astype(np.uint8), mode="L").save(mask_dir / f"{path.stem}.png")
        if index in preview_indices:
            tint(crop, binary, (30, 120, 255)).save(preview_dir / f"{path.stem}_prediction_blue.jpg", quality=95)
        rows.append({
            "image": path.name,
            "mask": f"masks_640x600/{path.stem}.png",
            "roi_xyxy_source": f"{left},{top},{right},{bottom}",
            "threshold": f"{args.threshold:.2f}",
            "predicted_pixels": str(int(binary.sum())),
            "mean_probability": f"{float(probability.mean()):.6f}",
            "max_probability": f"{float(probability.max()):.6f}",
        })
        if (index + 1) % 50 == 0:
            print(f"PREDICTED={index + 1}/500", flush=True)
    with (OUTPUT / "predictions.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    (OUTPUT / "README.md").write_text(
        "# U-Net v1 predictions\n\n"
        "Each mask is in the fixed screen ROI coordinate system at 640x600. "
        f"The corresponding original-image ROI is ({left}, {top}, {right}, {bottom}).\n",
        encoding="utf-8",
    )
    print(f"OUTPUT={OUTPUT} MASKS={len(rows)} PREVIEWS={len(preview_indices)}")


if __name__ == "__main__":
    main()
