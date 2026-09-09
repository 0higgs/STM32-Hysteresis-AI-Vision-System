"""CPU/GPU PyTorch U-Net training for the prepared hysteresis segmentation set."""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance
import torch
from torch import Tensor, nn
from torch.utils.data import DataLoader, Dataset


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "dataset" / "segmentation_v1"


class HysteresisDataset(Dataset):
    def __init__(self, rows: list[dict[str, str]], augment: bool) -> None:
        self.rows, self.augment = rows, augment

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> tuple[Tensor, Tensor]:
        row = self.rows[index]
        image = Image.open(DATASET / row["image"]).convert("RGB")
        mask = Image.open(DATASET / row["mask"]).convert("L")
        if self.augment:
            # Keep geometry intact: flips/rotations would change H-B physical meaning.
            image = ImageEnhance.Brightness(image).enhance(random.uniform(0.88, 1.12))
            image = ImageEnhance.Contrast(image).enhance(random.uniform(0.90, 1.12))
        image_array = np.asarray(image, dtype=np.float32).transpose(2, 0, 1) / 255.0
        mask_array = (np.asarray(mask, dtype=np.float32) > 127).astype(np.float32)[None, :, :]
        return torch.from_numpy(image_array), torch.from_numpy(mask_array)


class DoubleConv(nn.Module):
    def __init__(self, input_channels: int, output_channels: int) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(input_channels, output_channels, 3, padding=1), nn.BatchNorm2d(output_channels), nn.ReLU(inplace=True),
            nn.Conv2d(output_channels, output_channels, 3, padding=1), nn.BatchNorm2d(output_channels), nn.ReLU(inplace=True),
        )

    def forward(self, value: Tensor) -> Tensor:
        return self.block(value)


class UNet(nn.Module):
    def __init__(self, base: int = 16) -> None:
        super().__init__()
        self.enc1, self.enc2, self.enc3 = DoubleConv(3, base), DoubleConv(base, base * 2), DoubleConv(base * 2, base * 4)
        self.pool = nn.MaxPool2d(2)
        self.bottleneck = DoubleConv(base * 4, base * 8)
        self.up3 = nn.ConvTranspose2d(base * 8, base * 4, 2, stride=2)
        self.dec3 = DoubleConv(base * 8, base * 4)
        self.up2 = nn.ConvTranspose2d(base * 4, base * 2, 2, stride=2)
        self.dec2 = DoubleConv(base * 4, base * 2)
        self.up1 = nn.ConvTranspose2d(base * 2, base, 2, stride=2)
        self.dec1 = DoubleConv(base * 2, base)
        self.output = nn.Conv2d(base, 1, 1)

    def forward(self, value: Tensor) -> Tensor:
        first = self.enc1(value)
        second = self.enc2(self.pool(first))
        third = self.enc3(self.pool(second))
        center = self.bottleneck(self.pool(third))
        third_out = self.dec3(torch.cat((self.up3(center), third), dim=1))
        second_out = self.dec2(torch.cat((self.up2(third_out), second), dim=1))
        first_out = self.dec1(torch.cat((self.up1(second_out), first), dim=1))
        return self.output(first_out)


def dice_loss(logits: Tensor, targets: Tensor) -> Tensor:
    probabilities = torch.sigmoid(logits)
    intersection = (probabilities * targets).sum(dim=(1, 2, 3))
    union = probabilities.sum(dim=(1, 2, 3)) + targets.sum(dim=(1, 2, 3))
    return 1 - ((2 * intersection + 1) / (union + 1)).mean()


@torch.no_grad()
def metrics(model: nn.Module, loader: DataLoader, device: torch.device) -> tuple[float, float]:
    model.eval()
    dices, ious = [], []
    for images, masks in loader:
        pred = torch.sigmoid(model(images.to(device))) >= 0.5
        truth = masks.to(device) >= 0.5
        intersection = (pred & truth).sum(dim=(1, 2, 3)).float()
        dice = (2 * intersection + 1) / (pred.sum(dim=(1, 2, 3)) + truth.sum(dim=(1, 2, 3)) + 1)
        iou = (intersection + 1) / ((pred | truth).sum(dim=(1, 2, 3)) + 1)
        dices.extend(dice.cpu().tolist())
        ious.extend(iou.cpu().tolist())
    return float(np.mean(dices)), float(np.mean(ious))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--seed", type=int, default=20260814)
    args = parser.parse_args()

    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    with (DATASET / "samples.csv").open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    train_rows = [row for row in rows if row["split"] == "train"]
    valid_rows = [row for row in rows if row["split"] == "valid"]
    if not train_rows or not valid_rows:
        raise RuntimeError("Dataset must contain both train and valid samples")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train_loader = DataLoader(HysteresisDataset(train_rows, augment=True), batch_size=args.batch_size, shuffle=True, num_workers=0)
    valid_loader = DataLoader(HysteresisDataset(valid_rows, augment=False), batch_size=1, shuffle=False, num_workers=0)
    model = UNet().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
    bce = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([10.0], device=device))
    run_dir = ROOT / "runs" / "unet_v1"
    run_dir.mkdir(parents=True, exist_ok=True)
    history: list[dict[str, float]] = []
    best_dice = -1.0

    print(f"DEVICE={device.type} TRAIN={len(train_rows)} VALID={len(valid_rows)}")
    for epoch in range(1, args.epochs + 1):
        model.train()
        losses = []
        for images, masks in train_loader:
            images, masks = images.to(device), masks.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(images)
            loss = bce(logits, masks) + dice_loss(logits, masks)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        valid_dice, valid_iou = metrics(model, valid_loader, device)
        row = {"epoch": epoch, "train_loss": float(np.mean(losses)), "valid_dice": valid_dice, "valid_iou": valid_iou}
        history.append(row)
        print("EPOCH={epoch} LOSS={train_loss:.5f} VALID_DICE={valid_dice:.4f} VALID_IOU={valid_iou:.4f}".format(**row), flush=True)
        if valid_dice > best_dice:
            best_dice = valid_dice
            torch.save({"model": model.state_dict(), "epoch": epoch, "valid_dice": valid_dice}, run_dir / "best.pt")

    (run_dir / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
    print(f"BEST_DICE={best_dice:.4f}")


if __name__ == "__main__":
    main()
