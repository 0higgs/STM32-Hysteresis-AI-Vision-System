from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Mapping


MANIFEST_FIELDS = [
    "sample_id", "shot", "status", "image", "captured_at", "device_serial",
    "phone_name", "error", "DATASET_SPLIT", "QUALITY_CLASS", "DEFECT_TYPE",
    "CAPTURE_INSTRUCTION", "EXPECTED_EFFECT", "HMAX", "HC", "BR", "BS", "LOOP_HZ",
    "X_GAIN", "Y_GAIN", "X_OFFSET", "Y_OFFSET", "XY_COUPLING",
    "ASYMMETRY", "AMPLITUDE",
]


def successful_shots(path: Path, root: Path) -> dict[str, set[int]]:
    completed: dict[str, set[int]] = {}
    if not path.exists():
        return completed
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("status") != "ok" or not row.get("image"):
                continue
            image_path = root / row["image"]
            try:
                shot = int(row.get("shot", "1"))
            except ValueError:
                continue
            if image_path.is_file() and image_path.stat().st_size > 0:
                completed.setdefault(row.get("sample_id", ""), set()).add(shot)
    return completed


def append_manifest(path: Path, row: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    record = {field: row.get(field, "") for field in MANIFEST_FIELDS}
    record["captured_at"] = row.get("captured_at") or datetime.now().astimezone().isoformat(timespec="seconds")
    encoding = "utf-8" if exists else "utf-8-sig"
    with path.open("a", encoding=encoding, newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow(record)
