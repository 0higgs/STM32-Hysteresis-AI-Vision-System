"""Convert LabelMe line-strip annotations into a compact U-Net dataset.

Only annotated images are considered.  By default the first dataset excludes
the capture conditions that the user decided are outside the v1 target scope:
over/under exposure and screen clipping.  Their JSON annotations are retained
unchanged and can be included in a later version with --include-optional.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ANNOTATIONS = ROOT / "dataset" / "labelme" / "annotations"
MANIFEST = ROOT / "dataset" / "manifest.csv"
OUTPUT = ROOT / "dataset" / "segmentation_v1"
# The phone photographs include the full bench.  Train on the fixed CRT region
# rather than downsampling the actual curve into a few pixels.
TARGET_SIZE = (640, 600)
ROI_MARGIN_X = 300
ROI_MARGIN_Y = 250
OPTIONAL_CONDITIONS = {"overexposed", "underexposed", "partial_frame", "scale_clipping"}


def read_manifest() -> dict[str, dict[str, str]]:
    with MANIFEST.open(newline="", encoding="utf-8-sig") as handle:
        return {Path(row["image"]).name: row for row in csv.DictReader(handle)}


def resolve_image(json_path: Path, annotation: dict) -> Path:
    reference = annotation.get("imagePath", "")
    image_path = (json_path.parent / reference).resolve()
    if not image_path.is_file():
        raise FileNotFoundError(f"{json_path.name}: source image not found: {image_path}")
    return image_path


def draw_linestrip_mask(annotation: dict, width: int) -> Image.Image:
    source_width = int(annotation["imageWidth"])
    source_height = int(annotation["imageHeight"])
    mask = Image.new("L", (source_width, source_height), 0)
    painter = ImageDraw.Draw(mask)
    kept = 0
    for shape in annotation.get("shapes", []):
        if shape.get("label") != "hysteresis_loop" or shape.get("shape_type") != "linestrip":
            continue
        points = [tuple(map(float, point)) for point in shape.get("points", [])]
        if len(points) >= 2:
            painter.line(points, fill=255, width=width, joint="curve")
            # Make ends round, avoiding a visual bias at the end points.
            radius = width / 2
            for x, y in (points[0], points[-1]):
                painter.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
            kept += 1
    if not kept:
        raise ValueError("no valid hysteresis_loop linestrip found")
    return mask


def annotation_bounds(annotation: dict) -> tuple[float, float, float, float]:
    points = [point for shape in annotation.get("shapes", [])
              if shape.get("label") == "hysteresis_loop" and shape.get("shape_type") == "linestrip"
              for point in shape.get("points", [])]
    if len(points) < 2:
        raise ValueError("no valid hysteresis_loop points found")
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def assign_splits(records: list[dict[str, str]], seed: int = 20260814) -> None:
    """Set a reproducible 80/20 train/valid split, balanced where possible."""
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for record in records:
        grouped[record["condition"]].append(record)
    rng = random.Random(seed)
    for condition, rows in grouped.items():
        rng.shuffle(rows)
        valid_count = max(1, round(len(rows) * 0.2)) if len(rows) >= 3 else 0
        for index, record in enumerate(rows):
            record["split"] = "valid" if index < valid_count else "train"


def write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-optional", action="store_true", help="include clipping/exposure conditions in v1")
    parser.add_argument("--overwrite", action="store_true", help="replace generated dataset output")
    args = parser.parse_args()

    if not ANNOTATIONS.is_dir():
        raise FileNotFoundError(ANNOTATIONS)
    manifest = read_manifest()
    json_paths = sorted(ANNOTATIONS.glob("*.json"))
    if not json_paths:
        raise RuntimeError("No LabelMe JSON files found")

    if OUTPUT.exists() and args.overwrite:
        shutil.rmtree(OUTPUT)
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise RuntimeError(f"Output already exists: {OUTPUT}. Use --overwrite to regenerate it.")

    records: list[dict[str, str]] = []
    excluded: list[dict[str, str]] = []
    pending: list[tuple[Path, dict, Path, dict[str, str]]] = []
    for json_path in json_paths:
        try:
            annotation = json.loads(json_path.read_text(encoding="utf-8"))
            image_path = resolve_image(json_path, annotation)
            image_name = image_path.name
            metadata = manifest.get(image_name)
            if metadata is None:
                raise KeyError(f"not found in manifest: {image_name}")
            condition = metadata.get("DEFECT_TYPE", "UNSPECIFIED")
            if not args.include_optional and condition in OPTIONAL_CONDITIONS:
                excluded.append({"json": json_path.name, "image": image_name, "condition": condition, "reason": "outside_v1_scope"})
                continue
            # Validate annotation before generating any output files.
            draw_linestrip_mask(annotation, width=12)
            pending.append((json_path, annotation, image_path, metadata))
        except Exception as exc:  # Report all problematic source annotations together.
            excluded.append({"json": json_path.name, "image": "", "condition": "", "reason": f"invalid: {exc}"})

    if len(pending) < 10:
        raise RuntimeError(f"Only {len(pending)} trainable annotations after filtering; need at least 10")

    # All captures use the same phone/scope geometry.  The union of annotated
    # curves, with a generous margin, is a reproducible CRT region of interest.
    bounds = [annotation_bounds(annotation) for _, annotation, _, _ in pending]
    left = max(0, int(min(item[0] for item in bounds) - ROI_MARGIN_X))
    top = max(0, int(min(item[1] for item in bounds) - ROI_MARGIN_Y))
    right = int(max(item[2] for item in bounds) + ROI_MARGIN_X)
    bottom = int(max(item[3] for item in bounds) + ROI_MARGIN_Y)

    for directory in (OUTPUT / "images", OUTPUT / "masks"):
        directory.mkdir(parents=True, exist_ok=True)
    for json_path, annotation, image_path, metadata in pending:
        name = image_path.stem
        with Image.open(image_path) as source:
            crop = (left, top, min(right, source.width), min(bottom, source.height))
            rgb = source.convert("RGB").crop(crop).resize(TARGET_SIZE, Image.Resampling.LANCZOS)
        # Draw at native resolution then resize; this preserves sub-pixel path geometry.
        native_mask = draw_linestrip_mask(annotation, width=24)
        mask = native_mask.crop(crop).resize(TARGET_SIZE, Image.Resampling.NEAREST)
        # Ensure a trainable stroke width after downsampling.
        mask = mask.point(lambda value: 255 if value > 0 else 0)
        rgb.save(OUTPUT / "images" / f"{name}.jpg", quality=95)
        mask.save(OUTPUT / "masks" / f"{name}.png")
        records.append(
            {
                "id": name,
                "image": f"images/{name}.jpg",
                "mask": f"masks/{name}.png",
                "source_json": json_path.name,
                "condition": metadata.get("DEFECT_TYPE", ""),
                "split": "",
            }
        )

    assign_splits(records)
    write_csv(OUTPUT / "samples.csv", records, ["id", "image", "mask", "source_json", "condition", "split"])
    write_csv(OUTPUT / "excluded_from_v1.csv", excluded, ["json", "image", "condition", "reason"])
    (OUTPUT / "dataset_config.json").write_text(json.dumps({"source_roi_xyxy": [left, top, right, bottom], "target_size_wh": list(TARGET_SIZE)}, indent=2), encoding="utf-8")

    # Create visual audit panels for the first six records.
    preview_dir = OUTPUT / "previews"
    preview_dir.mkdir(exist_ok=True)
    for record in records[:6]:
        with Image.open(OUTPUT / record["image"]) as image, Image.open(OUTPUT / record["mask"]) as mask:
            overlay = image.convert("RGBA")
            tint = Image.new("RGBA", TARGET_SIZE, (255, 32, 32, 0))
            tint.putalpha(mask.point(lambda value: 135 if value else 0))
            Image.alpha_composite(overlay, tint).convert("RGB").save(preview_dir / f"{record['id']}_overlay.jpg", quality=95)

    print(f"OUTPUT={OUTPUT}")
    print(f"TRAINABLE={len(records)}")
    print(f"EXCLUDED={len(excluded)}")
    print("SPLITS=" + ", ".join(f"{split}:{sum(row['split'] == split for row in records)}" for split in ("train", "valid")))


if __name__ == "__main__":
    main()
