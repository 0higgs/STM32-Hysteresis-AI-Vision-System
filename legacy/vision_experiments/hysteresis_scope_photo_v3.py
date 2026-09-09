#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手机拍摄模拟示波器磁滞回线提取程序 V3
适用于：绿色/青绿色荧光轨迹 + 蓝绿色背景 + 网格较暗的模拟示波器照片

运行示例：
python hysteresis_scope_photo_v3.py input.jpg --roi 95,80,1780,1365 --mode green_tophat
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd

try:
    from skimage.morphology import skeletonize
    HAS_SKIMAGE = True
except Exception:
    HAS_SKIMAGE = False


def parse_roi(s):
    if s is None:
        return None
    parts = [int(v.strip()) for v in s.split(",")]
    if len(parts) != 4:
        raise ValueError("ROI格式应为 x1,y1,x2,y2")
    return tuple(parts)


def ensure_dir(p):
    Path(p).mkdir(parents=True, exist_ok=True)


def crop_roi(img, roi):
    if roi is None:
        return img, (0, 0, img.shape[1], img.shape[0])
    x1, y1, x2, y2 = roi
    return img[y1:y2, x1:x2].copy(), roi


def extract_green_tophat(crop, threshold=35, min_area=500):
    """
    专门处理模拟示波器绿色荧光轨迹：
    1. 用绿色通道
    2. 大尺度开运算估计背景
    3. top-hat 提取亮曲线
    4. 绿色优势筛选，避免网格/背景
    """
    b, g, r = cv2.split(crop)

    kernel_bg = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41))
    bg = cv2.morphologyEx(g, cv2.MORPH_OPEN, kernel_bg)
    top_hat = cv2.subtract(g, bg)

    mask = (
        (top_hat > threshold) &
        (g > 120) &
        (g.astype(np.int16) > r.astype(np.int16) + 30)
    ).astype(np.uint8) * 255

    # 闭运算连接小断点，不使用开运算，避免细曲线被抹掉
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

    # 去掉小连通域
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    clean = np.zeros_like(mask)

    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        if area >= min_area:
            clean[labels == i] = 255

    return clean, top_hat


def skeletonize_binary(mask):
    if HAS_SKIMAGE:
        return (skeletonize(mask > 0).astype(np.uint8) * 255)

    # 没有 skimage 时，保留原mask
    print("[WARN] 未安装 scikit-image，跳过骨架化。建议：pip install scikit-image")
    return mask


def points_from_mask(mask):
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        raise RuntimeError("未提取到回线，请调整ROI或threshold。")
    return xs.astype(float), ys.astype(float)


def pixel_to_normalized(xs, ys, w, h, origin=None):
    """
    使用绘图区中心作为默认原点。
    后续如果你们手动标定原点，可以传 origin=(x0,y0)
    """
    if origin is None:
        x0, y0 = w / 2.0, h / 2.0
    else:
        x0, y0 = origin

    Hs = (xs - x0) / (w / 2.0)
    Bs = -(ys - y0) / (h / 2.0)
    return Hs, Bs, x0, y0


def pixel_to_voltage(xs, ys, w, h, x_vdiv, y_vdiv, x_divs, y_divs, origin=None):
    if origin is None:
        x0, y0 = w / 2.0, h / 2.0
    else:
        x0, y0 = origin

    px_per_div_x = w / x_divs
    px_per_div_y = h / y_divs

    U_H = (xs - x0) / px_per_div_x * x_vdiv
    U_B = -(ys - y0) / px_per_div_y * y_vdiv
    return U_H, U_B


def voltage_to_HB(U_H, U_B, R1, n=150, N=50, R2=10000.0, C2=10e-6, l=None, S=None):
    H = None
    B = None
    if l is not None and R1 is not None:
        H = n * U_H / (l * R1)
    if S is not None:
        B = R2 * C2 * U_B / (N * S)
    return H, B


def estimate_abs_crossing(x, y, tol_ratio=0.02):
    """
    用散点近轴点估计截距。
    x: 横轴变量
    y: 纵轴变量
    求 y=0 时 |x| 的平均值。
    """
    yrange = np.max(y) - np.min(y)
    tol = max(yrange * tol_ratio, 1e-12)
    vals = np.abs(x[np.abs(y) < tol])
    if len(vals) == 0:
        return None
    return float(np.mean(vals))


def polygon_area_from_mask(mask, x_scale=1.0, y_scale=1.0):
    """
    用最大外轮廓面积估算回线面积。
    对闭合磁滞回线比按散点角度排序更稳。
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    area_px = cv2.contourArea(c)
    return float(area_px * x_scale * y_scale)


def calculate_params(Hs, Bs, U_H=None, U_B=None, H=None, B=None, w=None, h=None, mask=None, x_divs=10, y_divs=8, x_vdiv=1.0, y_vdiv=1.0):
    params = {}

    params["Hm_star"] = float(np.max(np.abs(Hs)))
    params["Bm_star"] = float(np.max(np.abs(Bs)))
    params["Hc_star_abs"] = estimate_abs_crossing(Hs, Bs)
    params["Br_star_abs"] = estimate_abs_crossing(Bs, Hs)

    if mask is not None:
        # 归一化面积：1 pixel 对应的归一化单位
        x_scale_star = 2.0 / w
        y_scale_star = 2.0 / h
        params["LoopArea_star"] = polygon_area_from_mask(mask, x_scale_star, y_scale_star)

    if U_H is not None and U_B is not None:
        params["UH_max_V"] = float(np.max(np.abs(U_H)))
        params["UB_max_V"] = float(np.max(np.abs(U_B)))
        params["UHc_abs_V"] = estimate_abs_crossing(U_H, U_B)
        params["UBr_abs_V"] = estimate_abs_crossing(U_B, U_H)

        if mask is not None and w is not None and h is not None:
            px_per_div_x = w / x_divs
            px_per_div_y = h / y_divs
            x_scale_v = x_vdiv / px_per_div_x
            y_scale_v = y_vdiv / px_per_div_y
            params["LoopArea_UH_UB_V2"] = polygon_area_from_mask(mask, x_scale_v, y_scale_v)

    if H is not None and B is not None:
        params["Hm_A_per_m"] = float(np.max(np.abs(H)))
        params["Bm_T"] = float(np.max(np.abs(B)))
        params["Hc_abs_A_per_m"] = estimate_abs_crossing(H, B)
        params["Br_abs_T"] = estimate_abs_crossing(B, H)

    return params


def diagnose(params):
    msgs = []
    if params.get("LoopArea_star") is not None and params["LoopArea_star"] < 0.05:
        msgs.append("回线面积偏小，可能励磁不足或图像提取不完整。")
    if params.get("Hc_star_abs") is None:
        msgs.append("未能稳定提取矫顽力，建议检查回线是否穿过B=0轴。")
    if params.get("Br_star_abs") is None:
        msgs.append("未能稳定提取剩磁，建议检查坐标原点标定。")
    if params.get("Hm_star", 0) < 0.2 or params.get("Bm_star", 0) < 0.2:
        msgs.append("回线在屏幕中幅度过小，建议增大显示比例或重新拍摄。")
    if not msgs:
        msgs.append("回线提取基本正常，可进行磁滞参数分析。")
    return msgs


def save_visuals(base, outdir, crop, mask, skel, Hs, Bs, U_H=None, U_B=None, params=None):
    cv2.imwrite(str(Path(outdir) / f"{base}_roi.jpg"), crop)
    cv2.imwrite(str(Path(outdir) / f"{base}_mask.png"), mask)
    cv2.imwrite(str(Path(outdir) / f"{base}_skeleton.png"), skel)

    overlay = crop.copy()
    overlay[mask > 0] = (0, 0, 255)
    cv2.imwrite(str(Path(outdir) / f"{base}_overlay.jpg"), overlay)

    plt.figure(figsize=(6, 6))
    plt.scatter(Hs, Bs, s=1)
    plt.axhline(0, linewidth=0.8)
    plt.axvline(0, linewidth=0.8)
    plt.axis("equal")
    plt.grid(True)
    plt.xlabel("H*")
    plt.ylabel("B*")
    plt.title("Extracted normalized hysteresis loop")
    plt.savefig(str(Path(outdir) / f"{base}_loop_normalized.png"), dpi=250, bbox_inches="tight")
    plt.close()

    if U_H is not None and U_B is not None:
        plt.figure(figsize=(6, 6))
        plt.scatter(U_H, U_B, s=1)
        plt.axhline(0, linewidth=0.8)
        plt.axvline(0, linewidth=0.8)
        plt.axis("equal")
        plt.grid(True)
        plt.xlabel("U_H / V")
        plt.ylabel("U_B / V")
        plt.title("Extracted voltage-coordinate hysteresis loop")
        plt.savefig(str(Path(outdir) / f"{base}_loop_voltage.png"), dpi=250, bbox_inches="tight")
        plt.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image", help="输入示波器照片")
    parser.add_argument("--roi", default=None, help="绘图区ROI: x1,y1,x2,y2")
    parser.add_argument("--threshold", type=float, default=35, help="绿色top-hat阈值，默认35")
    parser.add_argument("--min-area", type=int, default=500, help="最小连通域面积")
    parser.add_argument("--outdir", default="output_scope_photo", help="输出目录")

    parser.add_argument("--x-vdiv", type=float, default=1.0, help="X volts/div")
    parser.add_argument("--y-vdiv", type=float, default=1.0, help="Y volts/div")
    parser.add_argument("--x-divs", type=float, default=10.0, help="横向格数")
    parser.add_argument("--y-divs", type=float, default=8.0, help="纵向格数")

    parser.add_argument("--R1", type=float, default=None, help="取样电阻 R1 / ohm")
    parser.add_argument("--U", type=float, default=None, help="励磁电压档位，仅记录")
    parser.add_argument("--n", type=float, default=150.0, help="励磁线圈匝数")
    parser.add_argument("--N", type=float, default=50.0, help="感应线圈匝数")
    parser.add_argument("--R2", type=float, default=10000.0, help="积分电阻")
    parser.add_argument("--C2", type=float, default=10e-6, help="积分电容")
    parser.add_argument("--l", type=float, default=None, help="平均磁路长度 / m")
    parser.add_argument("--S", type=float, default=None, help="样品截面积 / m^2")

    args = parser.parse_args()

    img = cv2.imread(args.image)
    if img is None:
        raise FileNotFoundError(args.image)

    roi = parse_roi(args.roi)
    crop, roi_used = crop_roi(img, roi)
    h, w = crop.shape[:2]

    mask, top_hat = extract_green_tophat(crop, threshold=args.threshold, min_area=args.min_area)
    skel = skeletonize_binary(mask)
    xs, ys = points_from_mask(skel)

    Hs, Bs, x0, y0 = pixel_to_normalized(xs, ys, w, h)

    U_H, U_B = pixel_to_voltage(
        xs, ys, w, h,
        args.x_vdiv, args.y_vdiv,
        args.x_divs, args.y_divs
    )

    H, B = voltage_to_HB(
        U_H, U_B,
        R1=args.R1,
        n=args.n,
        N=args.N,
        R2=args.R2,
        C2=args.C2,
        l=args.l,
        S=args.S
    )

    params = calculate_params(
        Hs, Bs,
        U_H=U_H, U_B=U_B,
        H=H, B=B,
        w=w, h=h,
        mask=mask,
        x_divs=args.x_divs,
        y_divs=args.y_divs,
        x_vdiv=args.x_vdiv,
        y_vdiv=args.y_vdiv
    )

    msgs = diagnose(params)

    ensure_dir(args.outdir)
    base = Path(args.image).stem

    save_visuals(base, args.outdir, crop, mask, skel, Hs, Bs, U_H, U_B, params=params)

    df = pd.DataFrame({
        "x_pixel": xs,
        "y_pixel": ys,
        "H_star": Hs,
        "B_star": Bs,
        "U_H_V": U_H,
        "U_B_V": U_B
    })
    if H is not None:
        df["H_A_per_m"] = H
    if B is not None:
        df["B_T"] = B
    df.to_csv(Path(args.outdir) / f"{base}_points.csv", index=False)

    result = {
        "image": args.image,
        "roi": roi_used,
        "settings": vars(args),
        "params": params,
        "diagnosis": msgs
    }
    with open(Path(args.outdir) / f"{base}_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    report = []
    report.append("# 磁滞回线图像分析报告\n")
    report.append("## 1. 参数结果\n")
    for k, v in params.items():
        report.append(f"- {k}: {v if v is not None else 'None'}")
    report.append("\n## 2. 实验诊断\n")
    for m in msgs:
        report.append(f"- {m}")
    report.append("\n## 3. 说明\n")
    report.append("- 若未输入 l 和 S，真实 H、B 物理量不会输出。")
    report.append("- U 为励磁电压档位记录值，不直接代替图像中每个点对应的 U_H。")
    with open(Path(args.outdir) / f"{base}_report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    print("处理完成。输出目录：", args.outdir)
    print("关键结果：")
    for k, v in params.items():
        print(f"{k}: {v}")
    print("诊断：")
    for m in msgs:
        print("-", m)


if __name__ == "__main__":
    main()