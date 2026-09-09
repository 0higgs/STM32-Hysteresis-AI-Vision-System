"""Train a first TensorFlow/Keras U-Net from LabelMe-derived masks.

This intentionally uses only the prepared v1 data.  It is a smoke-test model:
its validation score measures generalization to held-out annotated photos, not
yet the final Hc/Br/Bs physical-parameter accuracy.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

import numpy as np
from PIL import Image
import tensorflow as tf


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "dataset" / "segmentation_v1"
RUN_DIR = ROOT / "runs" / "unet_v1_tensorflow"


def load_rows() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    with (DATASET / "samples.csv").open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    return ([row for row in rows if row["split"] == "train"], [row for row in rows if row["split"] == "valid"])


def load_pair(row: dict[str, str]) -> tuple[np.ndarray, np.ndarray]:
    image = np.asarray(Image.open(DATASET / row["image"]).convert("RGB"), dtype=np.float32) / 255.0
    mask = (np.asarray(Image.open(DATASET / row["mask"]).convert("L"), dtype=np.float32) > 127).astype(np.float32)
    return image, mask[..., None]


def make_dataset(rows: list[dict[str, str]], augment: bool, batch_size: int, seed: int) -> tf.data.Dataset:
    # 45 cropped images are small enough to keep in RAM.  A tensor-slice
    # dataset has known cardinality, avoiding Keras' generator-exhaustion
    # warning and guaranteeing each epoch sees every annotated image.
    pairs = [load_pair(row) for row in rows]
    images = np.stack([pair[0] for pair in pairs])
    masks = np.stack([pair[1] for pair in pairs])
    ds = tf.data.Dataset.from_tensor_slices((images, masks))
    if augment:
        ds = ds.shuffle(len(rows), seed=seed, reshuffle_each_iteration=True)
        def photometric(image: tf.Tensor, mask: tf.Tensor) -> tuple[tf.Tensor, tf.Tensor]:
            image = tf.image.random_brightness(image, max_delta=0.06, seed=seed)
            image = tf.image.random_contrast(image, lower=0.90, upper=1.10, seed=seed)
            return tf.clip_by_value(image, 0.0, 1.0), mask
        ds = ds.map(photometric, num_parallel_calls=tf.data.AUTOTUNE)
    return ds.batch(batch_size).prefetch(tf.data.AUTOTUNE)


def block(value: tf.Tensor, filters: int) -> tf.Tensor:
    value = tf.keras.layers.Conv2D(filters, 3, padding="same", activation="relu")(value)
    value = tf.keras.layers.Conv2D(filters, 3, padding="same", activation="relu")(value)
    # Batch size is one on this CPU-only workstation. BatchNormalization would
    # learn unstable moving statistics and collapse validation predictions.
    return value


def build_unet(input_shape: tuple[int, int, int], base_filters: int = 16) -> tf.keras.Model:
    inputs = tf.keras.Input(shape=input_shape, name="oscilloscope_photo")
    first = block(inputs, base_filters)
    second = block(tf.keras.layers.MaxPooling2D()(first), base_filters * 2)
    third = block(tf.keras.layers.MaxPooling2D()(second), base_filters * 4)
    center = block(tf.keras.layers.MaxPooling2D()(third), base_filters * 8)

    def up(value: tf.Tensor, skip: tf.Tensor, filters: int) -> tf.Tensor:
        value = tf.keras.layers.Conv2DTranspose(filters, 2, strides=2, padding="same")(value)
        return block(tf.keras.layers.Concatenate()([value, skip]), filters)

    third_out = up(center, third, base_filters * 4)
    second_out = up(third_out, second, base_filters * 2)
    first_out = up(second_out, first, base_filters)
    outputs = tf.keras.layers.Conv2D(1, 1, activation="sigmoid", name="curve_mask")(first_out)
    return tf.keras.Model(inputs, outputs, name="hysteresis_unet")


def dice_coefficient(y_true: tf.Tensor, y_pred: tf.Tensor) -> tf.Tensor:
    y_pred = tf.cast(y_pred >= 0.5, tf.float32)
    intersection = tf.reduce_sum(y_true * y_pred, axis=(1, 2, 3))
    denominator = tf.reduce_sum(y_true + y_pred, axis=(1, 2, 3))
    return tf.reduce_mean((2.0 * intersection + 1.0) / (denominator + 1.0))


def dice_bce_loss(y_true: tf.Tensor, y_pred: tf.Tensor) -> tf.Tensor:
    # The trace occupies only a small fraction of the CRT crop.  Weighting its
    # pixels prevents the trivial all-background solution during early epochs.
    y_pred = tf.clip_by_value(y_pred, 1e-6, 1.0 - 1e-6)
    bce = -tf.reduce_mean(18.0 * y_true * tf.math.log(y_pred) + (1.0 - y_true) * tf.math.log(1.0 - y_pred))
    intersection = tf.reduce_sum(y_true * y_pred, axis=(1, 2, 3))
    denominator = tf.reduce_sum(y_true + y_pred, axis=(1, 2, 3))
    dice = 1.0 - tf.reduce_mean((2.0 * intersection + 1.0) / (denominator + 1.0))
    return bce + dice


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--seed", type=int, default=20260814)
    args = parser.parse_args()

    tf.keras.utils.set_random_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)
    train_rows, valid_rows = load_rows()
    if not train_rows or not valid_rows:
        raise RuntimeError("Need both training and validation samples")
    train_ds = make_dataset(train_rows, augment=True, batch_size=args.batch_size, seed=args.seed)
    valid_ds = make_dataset(valid_rows, augment=False, batch_size=1, seed=args.seed)
    input_shape, _ = load_pair(train_rows[0])
    model = build_unet(input_shape.shape)
    model.compile(optimizer=tf.keras.optimizers.AdamW(args.learning_rate, weight_decay=1e-4), loss=dice_bce_loss, metrics=[dice_coefficient])

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    (RUN_DIR / "run_config.json").write_text(json.dumps({"epochs": args.epochs, "batch_size": args.batch_size, "learning_rate": args.learning_rate, "train_count": len(train_rows), "valid_count": len(valid_rows), "input_shape": input_shape.shape}, indent=2), encoding="utf-8")
    callbacks = [
        tf.keras.callbacks.ModelCheckpoint(RUN_DIR / "best.keras", monitor="val_dice_coefficient", mode="max", save_best_only=True),
        tf.keras.callbacks.EarlyStopping(monitor="val_dice_coefficient", mode="max", patience=7, restore_best_weights=True),
        tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=3, min_lr=1e-6),
        tf.keras.callbacks.CSVLogger(RUN_DIR / "history.csv"),
    ]
    print(f"TENSORFLOW={tf.__version__} DEVICE={'GPU' if tf.config.list_physical_devices('GPU') else 'CPU'} TRAIN={len(train_rows)} VALID={len(valid_rows)}")
    model.fit(train_ds, validation_data=valid_ds, epochs=args.epochs, callbacks=callbacks, verbose=2)
    model.save(RUN_DIR / "final.keras")
    scores = model.evaluate(valid_ds, verbose=0, return_dict=True)
    print("FINAL=" + json.dumps({key: float(value) for key, value in scores.items()}))


if __name__ == "__main__":
    main()
