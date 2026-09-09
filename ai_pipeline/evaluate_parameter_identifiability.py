"""Cross-validated check of which acquisition parameters are visible in a photo.

This is deliberately a classical baseline using only the U-Net curve and grid
features. It does not feed CSV targets, filenames, defect labels or instructions
to the model, avoiding an artificial 'recognition' result from metadata leakage.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
from sklearn.model_selection import KFold, cross_val_predict
from sklearn.pipeline import make_pipeline


TARGETS = [
    "HMAX", "HC", "BR", "BS", "LOOP_HZ", "X_GAIN", "Y_GAIN", "X_OFFSET",
    "Y_OFFSET", "XY_COUPLING", "ASYMMETRY", "AMPLITUDE",
]
NON_FEATURES = {
    "sample_id", "DATASET_SPLIT", "QUALITY_CLASS", "DEFECT_TYPE",
    "CAPTURE_INSTRUCTION", "EXPECTED_EFFECT", "image",
    *TARGETS,
}


def evaluate(frame: pd.DataFrame, feature_columns: list[str], name: str) -> list[dict[str, object]]:
    x = frame[feature_columns].apply(pd.to_numeric, errors="coerce")
    cv = KFold(n_splits=5, shuffle=True, random_state=20260814)
    rows: list[dict[str, object]] = []
    for target in TARGETS:
        y = pd.to_numeric(frame[target], errors="coerce")
        valid = y.notna()
        model = make_pipeline(
            SimpleImputer(strategy="median"),
            ExtraTreesRegressor(n_estimators=300, min_samples_leaf=2, random_state=20260814, n_jobs=-1),
        )
        prediction = cross_val_predict(model, x.loc[valid], y.loc[valid], cv=cv, n_jobs=1)
        mae = mean_absolute_error(y.loc[valid], prediction)
        rmse = root_mean_squared_error(y.loc[valid], prediction)
        value_range = float(y.loc[valid].max() - y.loc[valid].min())
        rows.append({
            "subset": name,
            "target": target,
            "samples": int(valid.sum()),
            "cv_r2": r2_score(y.loc[valid], prediction),
            "mae": mae,
            "rmse": rmse,
            "mae_over_range": mae / value_range if value_range else np.nan,
            "rmse_over_range": rmse / value_range if value_range else np.nan,
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("calibration/fixed_screen_v1/parameter_supervision_v1.csv"))
    parser.add_argument("--output", type=Path, default=Path("calibration/fixed_screen_v1/parameter_identifiability_report.csv"))
    args = parser.parse_args()
    frame = pd.read_csv(args.input)
    feature_columns = [
        column for column in frame.columns
        if column not in NON_FEATURES and pd.api.types.is_numeric_dtype(frame[column])
    ]
    if not feature_columns:
        raise RuntimeError("No numeric image-derived features found")

    report = evaluate(frame, feature_columns, "all_500")
    normal = frame.loc[frame["DATASET_SPLIT"].eq("normal")].copy()
    if len(normal) >= 25:
        report.extend(evaluate(normal, feature_columns, "normal_only"))

    result = pd.DataFrame(report).sort_values(["subset", "cv_r2"], ascending=[True, False])
    result["assessment"] = np.select(
        [result.cv_r2 >= 0.70, result.cv_r2 >= 0.30],
        ["visually predictable", "weak / conditional"],
        default="not reliably identifiable",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False, encoding="utf-8-sig", float_format="%.6f")
    print(f"Features used ({len(feature_columns)}): {', '.join(feature_columns)}")
    print(result.to_string(index=False))
    print(f"Wrote report to {args.output}")


if __name__ == "__main__":
    main()
