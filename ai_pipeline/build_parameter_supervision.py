"""Build a one-row-per-photo table for parameter-identifiability experiments.

The parameter CSV is the acquisition ground truth.  Image-derived features are
kept separate so this script cannot silently substitute legacy default values.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parameters", type=Path, default=Path("dataset/parameters.csv"))
    parser.add_argument(
        "--features",
        type=Path,
        default=Path("calibration/fixed_screen_v1/curve_features_grid_units.csv"),
    )
    parser.add_argument(
        "--predictions", type=Path, default=Path("predictions/unet_v1/predictions.csv")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("calibration/fixed_screen_v1/parameter_supervision_v1.csv"),
    )
    args = parser.parse_args()

    params = pd.read_csv(args.parameters)
    features = pd.read_csv(args.features)
    predictions = pd.read_csv(args.predictions)

    params["sample_id"] = params["sample_id"].astype(str)
    features["sample_id"] = features["image"].map(lambda value: Path(str(value)).stem)

    # Prediction filenames vary by script version; discover the filename column
    # rather than baking in a legacy output schema.
    filename_col = next(
        (column for column in predictions.columns if column.lower() in {"image", "filename", "file"}),
        None,
    )
    if filename_col is None:
        raise ValueError(f"No image filename column found in {args.predictions}: {list(predictions.columns)}")
    predictions["sample_id"] = predictions[filename_col].map(lambda value: Path(str(value)).stem)

    for title, frame in [("parameters", params), ("curve features", features), ("predictions", predictions)]:
        duplicated = frame["sample_id"].duplicated(keep=False)
        if duplicated.any():
            bad = frame.loc[duplicated, "sample_id"].head(10).tolist()
            raise ValueError(f"Duplicate sample_id in {title}: {bad}")

    feature_columns = [column for column in features.columns if column not in {"image", "sample_id"}]
    prediction_columns = [
        column
        for column in predictions.columns
        if column not in {filename_col, "sample_id"} and column not in feature_columns
    ]
    prediction_subset = predictions[["sample_id", *prediction_columns]].copy()
    joined = params.merge(features[["sample_id", *feature_columns]], on="sample_id", how="left", validate="one_to_one")
    joined = joined.merge(prediction_subset, on="sample_id", how="left", validate="one_to_one")

    if len(joined) != len(params):
        raise RuntimeError("Row count changed while joining parameter ground truth")
    missing_features = joined[feature_columns].isna().all(axis=1).sum()
    if missing_features:
        raise RuntimeError(f"{missing_features} parameter rows have no curve features")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    joined.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"Wrote {len(joined)} rows to {args.output}")
    print(f"Ground-truth targets: {', '.join(params.select_dtypes(include='number').columns)}")
    print(f"Image-derived feature columns: {len(feature_columns) + len(prediction_columns)}")


if __name__ == "__main__":
    main()
