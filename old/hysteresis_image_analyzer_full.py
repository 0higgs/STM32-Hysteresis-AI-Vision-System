#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智眼识磁：手机拍摄模拟示波器磁滞回线图像分析程序

功能：
1. 任意输入一张手机拍摄/示波器截图图片；
2. 自动估计示波器屏幕区域，或手动输入 ROI；
3. 提取绿色/青色/品红色/白色荧光轨迹；
4. 去噪、骨架化、压缩粗轨迹；
5. 将毛躁散点重建为上、下两条平滑磁滞分支；
6. 输出归一化坐标、电压坐标、可选真实 H-B 坐标；
7. 计算 Br、Hc、Bm、Hm、回线面积等参数；
8. 生成 overlay 图、平滑回线图、CSV、JSON、Markdown 报告。

依赖：
    pip install opencv-python numpy matplotlib pandas scipy

基础用法：
    python hysteresis_image_analyzer_full.py photo.jpg

建议用法（手动 ROI 更稳）：
    python hysteresis_image_analyzer_full.py photo.jpg --roi 95,80,1780,1365 --x-vdiv 0.5 --y-vdiv 0.5 --R1 2.5 --U 2.5

如果知道样品参数 l、S，可进一步输出真实 H、B：
    python hysteresis_image_analyzer_full.py photo.jpg --roi 95,80,1780,1365 --x-vdiv 0.5 --y-vdiv 0.5 --R1 2.5 --l 0.13 --S 1.25e-4

注意：
- 如果没有输入 l 和 S，程序不会输出真实单位的 H(A/m) 与 B(T)，只输出归一化参数和示波器电压参数。
- 对于拍摄角度明显倾斜的照片，建议使用 --roi 手动裁剪屏幕，后续可再加手动四点透视校正。
"""

import argparse
import json
import os
from pathlib import Path
from typing import Dict, Optional, Tuple, List

import cv2
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

try:
    from scipy.signal import savgol_filter
    SCIPY_OK = True
except Exception:
    SCIPY_OK = False


# -----------------------------
# 基础工具
# -----------------------------

def ensure_dir(path: str):
    Path(path).mkdir(parents=True, exist_ok=True)


def parse_roi(roi_str: Optional[str]) -> Optional[Tuple[int, int, int, int]]:
    if not roi_str:
        return None
    vals = [int(float(v.strip())) for v in roi_str.split(',')]
    if len(vals) != 4:
        raise ValueError("ROI 格式应为 x1,y1,x2,y2")
    x1, y1, x2, y2 = vals
    if x2 <= x1 or y2 <= y1:
        raise ValueError("ROI 无效：必须满足 x2>x1 且 y2>y1")
    return x1, y1, x2, y2


def resize_keep_ratio(img: np.ndarray, max_width: int = 1800) -> Tuple[np.ndarray, float]:
    """限制图像宽度，返回缩放后图像和缩放比例 scale = new/old。"""
    h, w = img.shape[:2]
    if w <= max_width:
        return img, 1.0
    scale = max_width / w
    out = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return out, scale


def crop_by_roi(img: np.ndarray, roi: Optional[Tuple[int, int, int, int]]) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
    h, w = img.shape[:2]
    if roi is None:
        return img.copy(), (0, 0, w, h)
    x1, y1, x2, y2 = roi
    x1 = max(0, min(w - 1, x1)); x2 = max(1, min(w, x2))
    y1 = max(0, min(h - 1, y1)); y2 = max(1, min(h, y2))
    return img[y1:y2, x1:x2].copy(), (x1, y1, x2, y2)


# -----------------------------
# 自动屏幕区域估计
# -----------------------------

def auto_detect_screen_roi(img: np.ndarray) -> Tuple[int, int, int, int]:
    """
    自动估计示波器屏幕区域。
    原理：多数模拟示波器屏幕为蓝/青/绿高饱和区域，外壳为低饱和浅色区域。
    如果失败，则返回整张图。
    """
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    H, S, V = cv2.split(hsv)

    # 蓝青绿屏幕区域大致在 H=55~110；饱和度明显高于外壳
    mask1 = cv2.inRange(hsv, np.array([50, 25, 20]), np.array([110, 255, 255]))
    # 有些屏幕偏暗，补一个高饱和泛化 mask
    mask2 = ((S > 45) & (V > 25)).astype(np.uint8) * 255
    mask = cv2.bitwise_or(mask1, mask2)

    # 形态学闭运算，形成大块屏幕区域
    k = max(15, int(min(h, w) * 0.02))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return (0, 0, w, h)

    candidates = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < 0.08 * w * h:
            continue
        x, y, ww, hh = cv2.boundingRect(c)
        ratio = ww / max(hh, 1)
        if 0.8 <= ratio <= 2.2:
            candidates.append((area, x, y, ww, hh))

    if not candidates:
        # 兜底：取最大轮廓
        c = max(contours, key=cv2.contourArea)
        x, y, ww, hh = cv2.boundingRect(c)
    else:
        _, x, y, ww, hh = max(candidates, key=lambda t: t[0])

    # 稍微收缩，减少外壳/黑边影响；不要过度裁掉网格
    pad_x = int(0.02 * ww)
    pad_y = int(0.02 * hh)
    x1 = max(0, x + pad_x)
    y1 = max(0, y + pad_y)
    x2 = min(w, x + ww - pad_x)
    y2 = min(h, y + hh - pad_y)

    if (x2 - x1) < 0.2 * w or (y2 - y1) < 0.2 * h:
        return (0, 0, w, h)
    return (x1, y1, x2, y2)


# -----------------------------
# 图像增强与亮线提取
# -----------------------------

def robust_percentile_threshold(arr: np.ndarray, percentile: float = 99.2, min_thr: int = 8) -> int:
    vals = arr[arr > 0]
    if vals.size < 10:
        return min_thr
    p = np.percentile(vals, percentile)
    # 稍微保守一点，避免阈值过高导致断线
    return int(max(min_thr, p * 0.55))


def build_trace_score(roi_bgr: np.ndarray) -> np.ndarray:
    """
    生成亮线得分图。重点适配模拟示波器：背景偏青绿，轨迹比背景更亮且更细。
    同时兼容数字截图中的品红/绿/白轨迹。
    """
    b, g, r = cv2.split(roi_bgr)
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    H, S, V = cv2.split(hsv)

    # 1) 大尺度 Top-hat：突出比背景更亮的细线
    size = max(31, int(min(roi_bgr.shape[:2]) * 0.045))
    if size % 2 == 0:
        size += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    top_v = cv2.morphologyEx(V, cv2.MORPH_TOPHAT, kernel)
    top_g = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, kernel)

    # 2) 颜色优势：绿色/青色荧光线通常 G、V 很高
    green_excess = cv2.subtract(g, ((r.astype(np.uint16) + b.astype(np.uint16)) // 2).astype(np.uint8))
    cyan_green = cv2.addWeighted(green_excess, 0.7, top_g, 0.7, 0)

    # 3) 品红轨迹兼容
    magenta_excess = cv2.subtract(((r.astype(np.uint16) + b.astype(np.uint16)) // 2).astype(np.uint8), g)
    top_mag = cv2.morphologyEx(magenta_excess, cv2.MORPH_TOPHAT, kernel)

    # 4) 白亮线兼容
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    top_gray = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)

    score = np.maximum.reduce([top_v, top_g, cyan_green, top_mag, top_gray])
    score = cv2.GaussianBlur(score, (3, 3), 0)
    return score


def extract_trace_mask(roi_bgr: np.ndarray,
                       threshold: str = "auto",
                       min_area: int = 80,
                       debug: bool = False) -> Tuple[np.ndarray, Dict]:
    """
    从 ROI 中提取亮线 mask。
    threshold 可为 auto 或数值字符串。
    """
    score = build_trace_score(roi_bgr)

    if threshold == "auto":
        thr = robust_percentile_threshold(score, percentile=99.1, min_thr=8)
    else:
        thr = int(float(threshold))

    tried = []
    mask_final = None
    chosen_thr = thr

    # 自适应兜底：如果没点，就逐步降低阈值
    for t in [thr, int(thr * 0.75), int(thr * 0.55), int(thr * 0.35), 6, 4]:
        t = max(3, t)
        _, mask = cv2.threshold(score, t, 255, cv2.THRESH_BINARY)

        # 轻微闭运算连接断裂，但不要开运算抹掉细线
        kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close, iterations=1)

        mask = filter_components(mask, min_area=min_area)
        npts = int(np.count_nonzero(mask))
        tried.append((t, npts))
        if npts > 120:
            mask_final = mask
            chosen_thr = t
            break

    if mask_final is None:
        # 最后兜底：不做连通域过滤
        _, mask_final = cv2.threshold(score, 3, 255, cv2.THRESH_BINARY)
        chosen_thr = 3

    info = {
        "chosen_threshold": chosen_thr,
        "threshold_trials": tried,
        "score_nonzero": int(np.count_nonzero(score)),
        "mask_points": int(np.count_nonzero(mask_final))
    }
    return mask_final, info


def filter_components(mask: np.ndarray, min_area: int = 80) -> np.ndarray:
    """按连通域面积过滤噪声，同时保留多段断裂轨迹。"""
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = np.zeros_like(mask)
    for i in range(1, num):
        area = stats[i, cv2.CC_STAT_AREA]
        if area >= min_area:
            out[labels == i] = 255
    return out


# -----------------------------
# 细化/骨架化
# -----------------------------

def zhang_suen_thinning(binary: np.ndarray) -> np.ndarray:
    """
    纯 numpy/cv2 实现 Zhang-Suen thinning，避免依赖 opencv-contrib/skimage。
    输入 binary: 0/255
    输出 0/255 单像素骨架
    """
    img = (binary > 0).astype(np.uint8)
    changed = True
    h, w = img.shape
    # 防止超大 mask 过慢；如果点太多，先略微腐蚀/缩小已在前面做了
    iters = 0
    while changed and iters < 80:
        changed = False
        iters += 1
        to_remove = []
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                P1 = img[y, x]
                if P1 != 1:
                    continue
                P2 = img[y - 1, x]
                P3 = img[y - 1, x + 1]
                P4 = img[y, x + 1]
                P5 = img[y + 1, x + 1]
                P6 = img[y + 1, x]
                P7 = img[y + 1, x - 1]
                P8 = img[y, x - 1]
                P9 = img[y - 1, x - 1]
                neighbors = [P2, P3, P4, P5, P6, P7, P8, P9]
                B = sum(neighbors)
                A = sum((neighbors[i] == 0 and neighbors[(i + 1) % 8] == 1) for i in range(8))
                if 2 <= B <= 6 and A == 1 and P2 * P4 * P6 == 0 and P4 * P6 * P8 == 0:
                    to_remove.append((y, x))
        if to_remove:
            changed = True
            for y, x in to_remove:
                img[y, x] = 0

        to_remove = []
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                P1 = img[y, x]
                if P1 != 1:
                    continue
                P2 = img[y - 1, x]
                P3 = img[y - 1, x + 1]
                P4 = img[y, x + 1]
                P5 = img[y + 1, x + 1]
                P6 = img[y + 1, x]
                P7 = img[y + 1, x - 1]
                P8 = img[y, x - 1]
                P9 = img[y - 1, x - 1]
                neighbors = [P2, P3, P4, P5, P6, P7, P8, P9]
                B = sum(neighbors)
                A = sum((neighbors[i] == 0 and neighbors[(i + 1) % 8] == 1) for i in range(8))
                if 2 <= B <= 6 and A == 1 and P2 * P4 * P8 == 0 and P2 * P6 * P8 == 0:
                    to_remove.append((y, x))
        if to_remove:
            changed = True
            for y, x in to_remove:
                img[y, x] = 0
    return (img * 255).astype(np.uint8)


def skeletonize_mask(mask: np.ndarray, max_side_for_thin: int = 1000) -> np.ndarray:
    """
    骨架化。为了避免大图逐像素细化过慢，先在必要时缩小，细化后再放回。
    """
    h, w = mask.shape[:2]
    scale = 1.0
    small = mask
    if max(h, w) > max_side_for_thin:
        scale = max_side_for_thin / max(h, w)
        small = cv2.resize(mask, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_NEAREST)
    skel_small = zhang_suen_thinning(small)
    if scale != 1.0:
        skel = cv2.resize(skel_small, (w, h), interpolation=cv2.INTER_NEAREST)
    else:
        skel = skel_small
    return skel


# -----------------------------
# 坐标转换与参数计算
# -----------------------------

def points_from_mask(mask: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        raise RuntimeError("未提取到回线，请调整 ROI、threshold 或 min-area。")
    return xs.astype(float), ys.astype(float)


def coordinate_transform(xs: np.ndarray, ys: np.ndarray,
                         roi_shape: Tuple[int, int],
                         x_divs: float = 10.0, y_divs: float = 8.0,
                         x_vdiv: Optional[float] = None,
                         y_vdiv: Optional[float] = None,
                         origin: Optional[Tuple[float, float]] = None,
                         R1: Optional[float] = None,
                         n: float = 150.0,
                         l: Optional[float] = None,
                         R2: float = 10000.0,
                         C2: float = 10e-6,
                         N: float = 50.0,
                         S_sample: Optional[float] = None) -> pd.DataFrame:
    """
    像素点 -> 归一化坐标 -> 电压坐标 -> 可选 H/B 坐标。
    """
    h, w = roi_shape[:2]
    if origin is None:
        x0, y0 = w / 2.0, h / 2.0
    else:
        x0, y0 = origin

    px_per_div_x = w / float(x_divs)
    px_per_div_y = h / float(y_divs)

    # 归一化：1.0 表示半屏宽/半屏高
    H_star = (xs - x0) / (w / 2.0)
    B_star = -(ys - y0) / (h / 2.0)

    data = {
        "x_px": xs,
        "y_px": ys,
        "H_star": H_star,
        "B_star": B_star,
    }

    if x_vdiv is not None and y_vdiv is not None:
        U_H = (xs - x0) / px_per_div_x * float(x_vdiv)
        U_B = -(ys - y0) / px_per_div_y * float(y_vdiv)
        data["U_H_V"] = U_H
        data["U_B_V"] = U_B

        if R1 is not None and l is not None:
            H_A_m = float(n) * U_H / (float(l) * float(R1))
            data["H_A_per_m"] = H_A_m
        if S_sample is not None:
            B_T = float(R2) * float(C2) * U_B / (float(N) * float(S_sample))
            data["B_T"] = B_T

    return pd.DataFrame(data)


def moving_average(y: np.ndarray, window: int) -> np.ndarray:
    if window < 3 or len(y) < window:
        return y
    if window % 2 == 0:
        window += 1
    pad = window // 2
    yy = np.pad(y, (pad, pad), mode='edge')
    kernel = np.ones(window) / window
    return np.convolve(yy, kernel, mode='valid')


def smooth_series(y: np.ndarray, window: int = 21, poly: int = 3) -> np.ndarray:
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 7:
        return y
    window = min(window, n if n % 2 == 1 else n - 1)
    window = max(5, window)
    if window % 2 == 0:
        window -= 1
    if SCIPY_OK and window > poly + 2:
        try:
            return savgol_filter(y, window_length=window, polyorder=min(poly, window - 2), mode='interp')
        except Exception:
            pass
    return moving_average(y, window)


def reconstruct_branches(df: pd.DataFrame,
                         x_col: str = "H_star", y_col: str = "B_star",
                         bins: int = 120,
                         min_bin_points: int = 3,
                         q_low: float = 0.18,
                         q_high: float = 0.82,
                         smooth_window: int = 17) -> pd.DataFrame:
    """
    将毛躁散点压缩为上下两条分支。
    方法：按 x 分箱，每个箱内取 y 的低/高分位数作为下/上分支，再平滑。
    """
    x = df[x_col].to_numpy(dtype=float)
    y = df[y_col].to_numpy(dtype=float)
    good = np.isfinite(x) & np.isfinite(y)
    x = x[good]; y = y[good]
    if len(x) < 30:
        raise RuntimeError("有效点太少，无法进行分支重建。")

    # 去除极端离群点
    x1, x2 = np.percentile(x, [1, 99])
    y1, y2 = np.percentile(y, [1, 99])
    good = (x >= x1) & (x <= x2) & (y >= y1) & (y <= y2)
    x = x[good]; y = y[good]

    edges = np.linspace(np.min(x), np.max(x), bins + 1)
    xs_mid: List[float] = []
    y_upper: List[float] = []
    y_lower: List[float] = []
    counts: List[int] = []

    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        if i == bins - 1:
            idx = (x >= lo) & (x <= hi)
        else:
            idx = (x >= lo) & (x < hi)
        yy = y[idx]
        xx = x[idx]
        if len(yy) >= min_bin_points:
            xs_mid.append(float(np.median(xx)))
            y_lower.append(float(np.quantile(yy, q_low)))
            y_upper.append(float(np.quantile(yy, q_high)))
            counts.append(int(len(yy)))

    if len(xs_mid) < 8:
        raise RuntimeError("分箱后有效点不足。请降低 threshold 或检查 ROI。")

    xs_mid = np.asarray(xs_mid)
    order = np.argsort(xs_mid)
    xs_mid = xs_mid[order]
    y_upper = np.asarray(y_upper)[order]
    y_lower = np.asarray(y_lower)[order]
    counts = np.asarray(counts)[order]

    # 再次去除异常跳点：上下分支宽度太小或反转时，保守修正
    # 确保 upper >= lower
    upper = np.maximum(y_upper, y_lower)
    lower = np.minimum(y_upper, y_lower)

    sw = min(smooth_window, len(xs_mid) if len(xs_mid) % 2 == 1 else len(xs_mid) - 1)
    if sw < 5:
        sw = 5 if len(xs_mid) >= 5 else len(xs_mid)
    if sw % 2 == 0:
        sw -= 1
    upper_s = smooth_series(upper, window=sw, poly=3)
    lower_s = smooth_series(lower, window=sw, poly=3)

    return pd.DataFrame({
        x_col: xs_mid,
        f"{y_col}_upper": upper_s,
        f"{y_col}_lower": lower_s,
        "bin_count": counts,
    })


def crossing_x_for_y(x: np.ndarray, y: np.ndarray, target: float = 0.0) -> List[float]:
    roots = []
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    for i in range(len(x) - 1):
        y1, y2 = y[i], y[i + 1]
        x1, x2 = x[i], x[i + 1]
        if not np.isfinite(y1 + y2 + x1 + x2):
            continue
        if y1 == target:
            roots.append(float(x1))
        if (y1 - target) * (y2 - target) < 0 and y2 != y1:
            t = (target - y1) / (y2 - y1)
            roots.append(float(x1 + t * (x2 - x1)))
    return roots


def interp_y_at_x(x: np.ndarray, y: np.ndarray, target_x: float = 0.0) -> Optional[float]:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if target_x < np.min(x) or target_x > np.max(x):
        return None
    order = np.argsort(x)
    x = x[order]; y = y[order]
    # 去除重复 x
    uniq_x, idx = np.unique(x, return_index=True)
    uniq_y = y[idx]
    if len(uniq_x) < 2:
        return None
    return float(np.interp(target_x, uniq_x, uniq_y))


def params_from_branches(branches: pd.DataFrame,
                         x_col: str, upper_col: str, lower_col: str,
                         label_prefix: str = "") -> Dict:
    x = branches[x_col].to_numpy(dtype=float)
    up = branches[upper_col].to_numpy(dtype=float)
    lo = branches[lower_col].to_numpy(dtype=float)

    # 确保 x 递增
    order = np.argsort(x)
    x, up, lo = x[order], up[order], lo[order]

    Hm = float(np.nanmax(np.abs(x)))
    Bm = float(np.nanmax(np.abs(np.concatenate([up, lo]))))

    # Br: H=0 时上下分支的 B，取绝对值平均
    br_vals = []
    bu0 = interp_y_at_x(x, up, 0.0)
    bl0 = interp_y_at_x(x, lo, 0.0)
    if bu0 is not None:
        br_vals.append(bu0)
    if bl0 is not None:
        br_vals.append(bl0)
    Br_abs = float(np.mean(np.abs(br_vals))) if br_vals else None

    # Hc: B=0 时上下分支的 H，取绝对值平均
    hc_roots = crossing_x_for_y(x, up, 0.0) + crossing_x_for_y(x, lo, 0.0)
    Hc_abs = float(np.mean(np.abs(hc_roots))) if hc_roots else None

    # 面积：积分上分支 - 下分支
    area = float(abs(np.trapz(up - lo, x)))

    return {
        f"{label_prefix}Hm": Hm,
        f"{label_prefix}Bm": Bm,
        f"{label_prefix}Br_abs": Br_abs,
        f"{label_prefix}Hc_abs": Hc_abs,
        f"{label_prefix}LoopArea": area,
        f"{label_prefix}Br_values": br_vals,
        f"{label_prefix}Hc_roots": hc_roots,
    }


def diagnose(params: Dict, raw_points: int, mask_points: int) -> List[str]:
    messages = []
    area = params.get("star_LoopArea")
    br = params.get("star_Br_abs")
    hc = params.get("star_Hc_abs")
    hm = params.get("star_Hm")
    bm = params.get("star_Bm")

    if raw_points < 300:
        messages.append("有效轨迹点偏少，可能拍摄不清晰、阈值过高或 ROI 未准确覆盖屏幕。")
    if mask_points < 500:
        messages.append("提取到的亮线区域偏少，建议降低 threshold 或提高示波器亮度。")
    if hm is not None and bm is not None and (hm < 0.15 or bm < 0.15):
        messages.append("回线在屏幕中幅度偏小，可能励磁电压不足或示波器档位不合适。")
    if area is not None and area < 0.03:
        messages.append("回线面积较小，可能未充分磁化、材料磁滞效应较弱，或图像提取不完整。")
    if br is None:
        messages.append("未能稳定计算剩磁 Br，建议校准坐标原点或改善回线提取质量。")
    if hc is None:
        messages.append("未能稳定计算矫顽力 Hc，建议检查回线是否完整穿过 B=0 轴。")
    if not messages:
        messages.append("回线提取和分支重建正常，可用于后续参数分析。")
    return messages


# -----------------------------
# 作图与报告
# -----------------------------

def save_overlay(roi_bgr: np.ndarray, mask: np.ndarray, skel: np.ndarray, out_path: str):
    overlay = roi_bgr.copy()
    red = np.zeros_like(roi_bgr)
    red[:, :, 2] = mask
    overlay = cv2.addWeighted(overlay, 0.78, red, 0.75, 0)
    # 骨架用黄色标出
    ys, xs = np.where(skel > 0)
    overlay[ys, xs] = (0, 255, 255)
    cv2.imwrite(out_path, overlay)


def plot_raw_and_smooth(df: pd.DataFrame, branches: pd.DataFrame,
                        x_col: str, y_col: str,
                        x_label: str, y_label: str,
                        title: str, out_path: str):
    plt.figure(figsize=(7, 7))
    plt.scatter(df[x_col], df[y_col], s=1, alpha=0.25, label="raw extracted points")
    plt.plot(branches[x_col], branches[f"{y_col}_upper"], linewidth=2.2, label="upper branch")
    plt.plot(branches[x_col], branches[f"{y_col}_lower"], linewidth=2.2, label="lower branch")
    # 闭合连接方便展示
    xs = np.concatenate([branches[x_col].values, branches[x_col].values[::-1]])
    ys = np.concatenate([branches[f"{y_col}_upper"].values, branches[f"{y_col}_lower"].values[::-1]])
    plt.plot(xs, ys, linewidth=1.0, alpha=0.5)
    plt.axhline(0, linewidth=1)
    plt.axvline(0, linewidth=1)
    plt.grid(True)
    plt.xlabel(x_label)
    plt.ylabel(y_label)
    plt.title(title)
    plt.axis("equal")
    plt.legend(loc="best")
    plt.tight_layout()
    plt.savefig(out_path, dpi=250)
    plt.close()


def plot_smooth_only(branches: pd.DataFrame,
                     x_col: str, y_col: str,
                     x_label: str, y_label: str,
                     title: str, out_path: str):
    plt.figure(figsize=(7, 7))
    xs = np.concatenate([branches[x_col].values, branches[x_col].values[::-1]])
    ys = np.concatenate([branches[f"{y_col}_upper"].values, branches[f"{y_col}_lower"].values[::-1]])
    plt.plot(xs, ys, linewidth=2.5)
    plt.axhline(0, linewidth=1)
    plt.axvline(0, linewidth=1)
    plt.grid(True)
    plt.xlabel(x_label)
    plt.ylabel(y_label)
    plt.title(title)
    plt.axis("equal")
    plt.tight_layout()
    plt.savefig(out_path, dpi=250)
    plt.close()


def safe_float(v):
    if v is None:
        return None
    try:
        if isinstance(v, (list, tuple)):
            return [safe_float(x) for x in v]
        if np.isnan(v):
            return None
        return float(v)
    except Exception:
        return v


def write_report(out_path: str, result: Dict, messages: List[str], args_dict: Dict):
    lines = []
    lines.append("# 磁滞回线图像智能分析报告\n")
    lines.append("## 1. 分析模式\n")
    if result.get("has_physical_HB"):
        lines.append("当前已输入样品参数，可输出实际单位下的 $H$ 与 $B$。\n")
    elif result.get("has_voltage"):
        lines.append("当前已输入示波器档位，可输出示波器电压坐标 $U_H$ 与 $U_B$，但缺少样品参数，暂不输出真实 $H$、$B$。\n")
    else:
        lines.append("当前为归一化分析模式，仅输出 $H^*$、$B^*$ 等相对参数。\n")

    lines.append("## 2. 主要结果\n")
    for k, v in result.get("parameters", {}).items():
        if isinstance(v, list):
            continue
        if v is None:
            lines.append(f"- {k}: 暂无法计算\n")
        elif isinstance(v, float):
            lines.append(f"- {k}: {v:.6g}\n")
        else:
            lines.append(f"- {k}: {v}\n")

    lines.append("\n## 3. 实验状态诊断\n")
    for m in messages:
        lines.append(f"- {m}\n")

    lines.append("\n## 4. 参数说明\n")
    lines.append("- $B_r$：剩磁，对应 $H=0$ 时的磁感应强度。\n")
    lines.append("- $H_c$：矫顽力，对应 $B=0$ 时的磁场强度。\n")
    lines.append("- LoopArea：磁滞回线面积，可用于表征磁滞损耗。\n")
    lines.append("- 若未输入样品平均磁路长度 $l$ 与截面积 $S$，结果仅作为相对比较，不应写成真实物理单位。\n")

    lines.append("\n## 5. 输入设置\n")
    for k, v in args_dict.items():
        lines.append(f"- {k}: {v}\n")

    Path(out_path).write_text("".join(lines), encoding="utf-8")


# -----------------------------
# 主程序
# -----------------------------

def analyze_image(args):
    img0 = cv2.imread(args.image)
    if img0 is None:
        raise FileNotFoundError(f"无法读取图片：{args.image}")

    # 为速度限制大小；如果用户手动 ROI 是原图坐标，需要同步缩放
    img, scale = resize_keep_ratio(img0, max_width=args.max_width)

    roi_user = parse_roi(args.roi)
    if roi_user is not None and scale != 1.0:
        roi_user = tuple(int(v * scale) for v in roi_user)

    if roi_user is None:
        roi_auto = auto_detect_screen_roi(img)
        roi = roi_auto
        roi_source = "auto"
    else:
        roi = roi_user
        roi_source = "manual"

    roi_img, roi_used = crop_by_roi(img, roi)
    outdir = args.outdir
    ensure_dir(outdir)
    base = Path(args.image).stem

    cv2.imwrite(os.path.join(outdir, f"{base}_roi.jpg"), roi_img)

    mask, info = extract_trace_mask(roi_img, threshold=args.threshold, min_area=args.min_area)
    cv2.imwrite(os.path.join(outdir, f"{base}_mask.png"), mask)

    # 骨架化：先把 mask 略微腐蚀一下有时会减少粗线边缘，保守处理
    # 不使用强腐蚀，避免断线
    skel = skeletonize_mask(mask)
    cv2.imwrite(os.path.join(outdir, f"{base}_skeleton.png"), skel)
    save_overlay(roi_img, mask, skel, os.path.join(outdir, f"{base}_overlay.jpg"))

    xs, ys = points_from_mask(skel)

    origin = None
    if args.origin:
        ov = [float(v.strip()) for v in args.origin.split(',')]
        if len(ov) != 2:
            raise ValueError("origin 格式应为 x0,y0，且为 ROI 内坐标")
        origin = (ov[0], ov[1])

    df = coordinate_transform(
        xs, ys, roi_img.shape,
        x_divs=args.x_divs, y_divs=args.y_divs,
        x_vdiv=args.x_vdiv, y_vdiv=args.y_vdiv,
        origin=origin,
        R1=args.R1, n=args.n, l=args.l,
        R2=args.R2, C2=args.C2, N=args.N, S_sample=args.S
    )
    df.to_csv(os.path.join(outdir, f"{base}_raw_points.csv"), index=False, encoding="utf-8-sig")

    # 归一化分支重建
    branches_star = reconstruct_branches(
        df, x_col="H_star", y_col="B_star",
        bins=args.bins, min_bin_points=args.min_bin_points,
        q_low=args.q_low, q_high=args.q_high,
        smooth_window=args.smooth_window
    )
    branches_star.to_csv(os.path.join(outdir, f"{base}_branches_normalized.csv"), index=False, encoding="utf-8-sig")

    plot_raw_and_smooth(
        df, branches_star,
        x_col="H_star", y_col="B_star",
        x_label="H*", y_label="B*",
        title="Extracted and smoothed normalized hysteresis loop",
        out_path=os.path.join(outdir, f"{base}_loop_normalized_raw_smooth.png")
    )
    plot_smooth_only(
        branches_star,
        x_col="H_star", y_col="B_star",
        x_label="H*", y_label="B*",
        title="Smoothed normalized hysteresis loop",
        out_path=os.path.join(outdir, f"{base}_loop_normalized_smooth.png")
    )

    params = {}
    p_star = params_from_branches(branches_star, "H_star", "B_star_upper", "B_star_lower", label_prefix="star_")
    params.update(p_star)

    has_voltage = "U_H_V" in df.columns and "U_B_V" in df.columns
    has_physical_HB = "H_A_per_m" in df.columns and "B_T" in df.columns

    # 电压坐标分支重建
    if has_voltage:
        branches_v = reconstruct_branches(
            df, x_col="U_H_V", y_col="U_B_V",
            bins=args.bins, min_bin_points=args.min_bin_points,
            q_low=args.q_low, q_high=args.q_high,
            smooth_window=args.smooth_window
        )
        branches_v.to_csv(os.path.join(outdir, f"{base}_branches_voltage.csv"), index=False, encoding="utf-8-sig")
        plot_raw_and_smooth(
            df, branches_v,
            x_col="U_H_V", y_col="U_B_V",
            x_label="U_H / V", y_label="U_B / V",
            title="Extracted and smoothed voltage-coordinate hysteresis loop",
            out_path=os.path.join(outdir, f"{base}_loop_voltage_raw_smooth.png")
        )
        plot_smooth_only(
            branches_v,
            x_col="U_H_V", y_col="U_B_V",
            x_label="U_H / V", y_label="U_B / V",
            title="Smoothed voltage-coordinate hysteresis loop",
            out_path=os.path.join(outdir, f"{base}_loop_voltage_smooth.png")
        )
        params.update(params_from_branches(branches_v, "U_H_V", "U_B_V_upper", "U_B_V_lower", label_prefix="voltage_"))

    # 真实 H-B 坐标分支重建
    if has_physical_HB:
        branches_hb = reconstruct_branches(
            df, x_col="H_A_per_m", y_col="B_T",
            bins=args.bins, min_bin_points=args.min_bin_points,
            q_low=args.q_low, q_high=args.q_high,
            smooth_window=args.smooth_window
        )
        branches_hb.to_csv(os.path.join(outdir, f"{base}_branches_HB.csv"), index=False, encoding="utf-8-sig")
        plot_raw_and_smooth(
            df, branches_hb,
            x_col="H_A_per_m", y_col="B_T",
            x_label="H / (A/m)", y_label="B / T",
            title="Extracted and smoothed physical H-B hysteresis loop",
            out_path=os.path.join(outdir, f"{base}_loop_HB_raw_smooth.png")
        )
        plot_smooth_only(
            branches_hb,
            x_col="H_A_per_m", y_col="B_T",
            x_label="H / (A/m)", y_label="B / T",
            title="Smoothed physical H-B hysteresis loop",
            out_path=os.path.join(outdir, f"{base}_loop_HB_smooth.png")
        )
        params.update(params_from_branches(branches_hb, "H_A_per_m", "B_T_upper", "B_T_lower", label_prefix="physical_"))

    # JSON 序列化清洗
    params_clean = {k: safe_float(v) for k, v in params.items()}
    messages = diagnose(params_clean, raw_points=len(df), mask_points=info.get("mask_points", 0))

    result = {
        "image": args.image,
        "scale_used": scale,
        "roi_source": roi_source,
        "roi_used_on_resized_image": roi_used,
        "roi_used_on_original_image_approx": [int(v / scale) for v in roi_used] if scale != 0 else roi_used,
        "extraction_info": info,
        "has_voltage": has_voltage,
        "has_physical_HB": has_physical_HB,
        "parameters": params_clean,
        "diagnosis": messages,
    }

    json_path = os.path.join(outdir, f"{base}_result.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    write_report(os.path.join(outdir, f"{base}_report.md"), result, messages, vars(args))

    return result


def build_parser():
    p = argparse.ArgumentParser(description="手机/示波器图像磁滞回线自动提取、平滑重建与参数分析程序")
    p.add_argument("image", help="输入图片路径")
    p.add_argument("--outdir", default="output_hysteresis_full", help="输出目录")
    p.add_argument("--roi", default=None, help="手动 ROI，格式：x1,y1,x2,y2。若不填则自动估计屏幕区域")
    p.add_argument("--origin", default=None, help="ROI 内坐标原点，格式：x0,y0。若不填默认 ROI 中心")
    p.add_argument("--threshold", default="auto", help="亮线阈值，填 auto 或数字，例如 20")
    p.add_argument("--min-area", type=int, default=80, help="连通域最小面积，噪声多则调大，断线多则调小")
    p.add_argument("--max-width", type=int, default=1800, help="为加速处理而限制图像最大宽度")

    # 示波器参数
    p.add_argument("--x-vdiv", type=float, default=None, help="X volts/div，单位 V/div")
    p.add_argument("--y-vdiv", type=float, default=None, help="Y volts/div，单位 V/div")
    p.add_argument("--x-divs", type=float, default=10.0, help="示波器横向格数，默认 10")
    p.add_argument("--y-divs", type=float, default=8.0, help="示波器纵向格数，默认 8")

    # 磁滞实验仪参数
    p.add_argument("--R1", type=float, default=None, help="取样电阻 R1，单位 Ω")
    p.add_argument("--U", type=float, default=None, help="励磁电压档位 U，单位 V，仅用于记录实验条件")
    p.add_argument("--n", type=float, default=150.0, help="励磁线圈匝数 n，默认 150")
    p.add_argument("--N", type=float, default=50.0, help="感应线圈匝数 N，默认 50")
    p.add_argument("--R2", type=float, default=10000.0, help="积分电阻 R2，单位 Ω，默认 10000")
    p.add_argument("--C2", type=float, default=10e-6, help="积分电容 C2，单位 F，默认 10e-6")
    p.add_argument("--l", type=float, default=None, help="样品平均磁路长度 l，单位 m")
    p.add_argument("--S", type=float, default=None, help="样品截面积 S，单位 m^2")

    # 平滑参数
    p.add_argument("--bins", type=int, default=140, help="按 H 方向分箱数量，越大细节越多但更毛躁")
    p.add_argument("--min-bin-points", type=int, default=3, help="每个分箱最少点数")
    p.add_argument("--q-low", type=float, default=0.18, help="下分支分位数")
    p.add_argument("--q-high", type=float, default=0.82, help="上分支分位数")
    p.add_argument("--smooth-window", type=int, default=17, help="平滑窗口，奇数，越大越平滑")
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    result = analyze_image(args)

    print("\n========== 分析完成 ==========")
    print(f"输出目录：{args.outdir}")
    print(f"ROI来源：{result['roi_source']}")
    print(f"ROI(缩放图坐标)：{result['roi_used_on_resized_image']}")
    print(f"提取阈值：{result['extraction_info'].get('chosen_threshold')}")
    print("\n主要参数：")
    for k, v in result["parameters"].items():
        if isinstance(v, list):
            continue
        if v is None:
            print(f"  {k}: None")
        elif isinstance(v, float):
            print(f"  {k}: {v:.6g}")
        else:
            print(f"  {k}: {v}")
    print("\n诊断建议：")
    for m in result["diagnosis"]:
        print(" - " + m)

    print("\n重点查看：")
    base = Path(args.image).stem
    print(f"  {args.outdir}/{base}_overlay.jpg")
    print(f"  {args.outdir}/{base}_loop_normalized_smooth.png")
    print(f"  {args.outdir}/{base}_loop_normalized_raw_smooth.png")
    print(f"  {args.outdir}/{base}_report.md")


if __name__ == "__main__":
    main()
