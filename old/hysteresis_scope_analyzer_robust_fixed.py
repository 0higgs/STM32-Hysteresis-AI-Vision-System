#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hysteresis_scope_analyzer_robust.py

面向“手机拍摄模拟示波器磁滞回线”的完整分析程序。
核心目标：
1. 从模拟示波器照片中提取绿色荧光磁滞回线；
2. 自动过滤网格线、边框反光、文字、底部横线等干扰；
3. 将粗亮线压缩为上下两条平滑分支，解决“边缘毛躁/双边缘/乱线”问题；
4. 输出归一化参数、电压坐标参数；
5. 输入样品参数后，输出 H-B 物理量参数；
6. 自动生成 overlay、平滑回线图、CSV、JSON、Markdown 报告。

依赖：
pip install opencv-python numpy matplotlib pandas scipy

基础用法：
python hysteresis_scope_analyzer_robust.py test.jpg --roi 95,80,1780,1365 --threshold auto

带示波器参数：
python hysteresis_scope_analyzer_robust.py test.jpg --roi 95,80,1780,1365 --x-vdiv 0.5 --y-vdiv 0.5 --R1 2.5 --U 2.5

带真实物理参数：
python hysteresis_scope_analyzer_robust.py test.jpg --roi 95,80,1780,1365 --x-vdiv 0.5 --y-vdiv 0.5 --R1 2.5 --l 0.13 --S 1.25e-4
"""

import argparse
import json
import math
import os
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

try:
    from scipy.signal import savgol_filter, medfilt
    HAS_SCIPY = True
except Exception:
    HAS_SCIPY = False


# -----------------------------
# 基础工具
# -----------------------------

def imread_unicode(path: str):
    """兼容中文路径读取图像。"""
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    return img


def imwrite_unicode(path: str, img):
    """兼容中文路径保存图像。"""
    ext = os.path.splitext(path)[1]
    ok, buf = cv2.imencode(ext, img)
    if ok:
        buf.tofile(path)
    return ok


def parse_roi(roi_str):
    if roi_str is None or str(roi_str).lower() in ["none", "auto"]:
        return None
    parts = [int(float(x)) for x in roi_str.split(",")]
    if len(parts) != 4:
        raise ValueError("--roi 格式必须是 x1,y1,x2,y2")
    x1, y1, x2, y2 = parts
    if x2 <= x1 or y2 <= y1:
        raise ValueError("--roi 中 x2/y2 必须大于 x1/y1")
    return x1, y1, x2, y2


def robust_mkdir(path):
    Path(path).mkdir(parents=True, exist_ok=True)


def to_float_or_none(v):
    return None if v is None else float(v)

def make_json_safe(obj):
    """
    将 numpy 类型递归转换为 Python 原生类型，避免 json.dump 报错：
    TypeError: Object of type int32 is not JSON serializable
    """
    if isinstance(obj, dict):
        return {str(k): make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [make_json_safe(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        if not np.isfinite(v):
            return None
        return v
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, float):
        if not np.isfinite(obj):
            return None
        return obj
    return obj


# -----------------------------
# ROI
# -----------------------------

def auto_crop_scope_screen(img):
    """
    自动估计示波器屏幕区域。
    说明：手机拍摄角度差异较大，自动 ROI 不可能对所有图片都完美。
    若结果不好，请手动传 --roi x1,y1,x2,y2。
    """
    h, w = img.shape[:2]

    # HSV中找偏蓝/偏青且较暗的屏幕区域
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    H, S, V = cv2.split(hsv)

    # 模拟示波器屏幕通常是青蓝色，饱和度中等，亮度中等偏低
    mask1 = cv2.inRange(hsv, np.array([70, 20, 20]), np.array([110, 255, 230]))
    # 兼容偏绿屏幕
    mask2 = cv2.inRange(hsv, np.array([35, 20, 20]), np.array([90, 255, 230]))
    mask = cv2.bitwise_or(mask1, mask2)

    kernel = np.ones((25, 25), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)

    best = None
    best_area = 0
    for i in range(1, num):
        x, y, bw, bh, area = stats[i]
        if area < 0.08 * w * h:
            continue
        ratio = bw / max(bh, 1)
        if 0.8 < ratio < 2.2 and area > best_area:
            best_area = area
            best = (x, y, x + bw, y + bh)

    if best is None:
        # 保守兜底：去掉外缘 5%
        return int(0.05 * w), int(0.05 * h), int(0.95 * w), int(0.95 * h)

    x1, y1, x2, y2 = best
    # 略收缩，避免黑边框进入
    pad_x = int(0.02 * (x2 - x1))
    pad_y = int(0.02 * (y2 - y1))
    return max(0, x1 + pad_x), max(0, y1 + pad_y), min(w, x2 - pad_x), min(h, y2 - pad_y)


# -----------------------------
# 轨迹提取
# -----------------------------

def compute_neon_score(roi_bgr):
    """
    计算绿色荧光轨迹增强图。
    关键思路：
    - 背景也是青绿色，所以不能只按绿色HSV提取；
    - 荧光轨迹比周围更亮、更“绿白”；
    - 用绿色通道 top-hat + 颜色差分增强细亮线。
    """
    b, g, r = cv2.split(roi_bgr)
    b = b.astype(np.float32)
    g = g.astype(np.float32)
    r = r.astype(np.float32)

    # 颜色优势：真实荧光轨迹 G 通道明显较强
    color_excess = g - 0.45 * r - 0.35 * b
    color_excess = np.clip(color_excess, 0, 255)

    # 大尺度背景估计，突出细亮线
    g_u8 = np.clip(g, 0, 255).astype(np.uint8)
    kernel_size = max(31, int(min(roi_bgr.shape[:2]) * 0.035) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    opened = cv2.morphologyEx(g_u8, cv2.MORPH_OPEN, kernel)
    tophat = cv2.subtract(g_u8, opened).astype(np.float32)

    # HSV约束，减少蓝色背景和暗网格影响
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    H, S, V = cv2.split(hsv)
    hsv_gate = ((H >= 35) & (H <= 95) & (S >= 25) & (V >= 80)).astype(np.float32)

    score = 0.65 * tophat + 0.35 * color_excess
    score = score * (0.45 + 0.55 * hsv_gate)

    # 归一化
    score = cv2.GaussianBlur(score, (3, 3), 0)
    score_u8 = cv2.normalize(score, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return score_u8


def threshold_trace(score_u8, threshold="auto"):
    """
    自适应阈值。
    threshold:
    - "auto": 自动 Otsu + 分位数兜底
    - 数值：手动阈值
    """
    if str(threshold).lower() == "auto":
        # 先用 Otsu
        _, m1 = cv2.threshold(score_u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # 再用高分位数，防止 Otsu 过低吃进背景
        nz = score_u8[score_u8 > 0]
        if len(nz) == 0:
            return np.zeros_like(score_u8)
        q = np.percentile(nz, 96.5)
        _, m2 = cv2.threshold(score_u8, max(10, q), 255, cv2.THRESH_BINARY)

        # 两者取交集偏保守；若太少，再退回 m1
        m = cv2.bitwise_and(m1, m2)
        if cv2.countNonZero(m) < 80:
            m = m2 if cv2.countNonZero(m2) > 80 else m1
        return m
    else:
        th = float(threshold)
        _, m = cv2.threshold(score_u8, th, 255, cv2.THRESH_BINARY)
        return m


def filter_components(mask, score_u8, min_area=80, border_margin=12):
    """
    连通域过滤。
    解决：
    - 底部横线/边框被误提取；
    - 网格线被误提取；
    - 反光碎片被误提取。

    保留特点：
    - 面积足够；
    - 不贴边；
    - 不是过长水平线/垂直线；
    - 亮度评分较高。
    """
    h, w = mask.shape[:2]
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)

    candidates = []
    for i in range(1, num):
        x, y, bw, bh, area = stats[i]

        if area < min_area:
            continue

        # 去掉贴边的横线、边框和外壳反光
        touches_border = (x <= border_margin or y <= border_margin or
                          x + bw >= w - border_margin or y + bh >= h - border_margin)
        if touches_border:
            # 真实回线一般不应该贴屏幕边缘；如果你们回线贴边，应该调示波器位置
            continue

        aspect = bw / max(bh, 1)
        # 去掉明显水平/垂直网格线
        if aspect > 7.0 and bh < 0.12 * h:
            continue
        if aspect < 0.12 and bw < 0.12 * w:
            continue

        # 磁滞回线通常同时有一定宽高
        if bw < 0.025 * w or bh < 0.04 * h:
            continue

        comp_mask = (labels == i)
        mean_score = float(score_u8[comp_mask].mean())
        # 评分：亮度越高、面积越大越可信，但不要只按面积
        comp_score = mean_score * math.sqrt(area)
        candidates.append((comp_score, i, x, y, bw, bh, area, mean_score))

    cleaned = np.zeros_like(mask)

    if not candidates:
        return cleaned, []

    candidates.sort(reverse=True, key=lambda t: t[0])
    best_score = candidates[0][0]

    kept = []
    for item in candidates:
        comp_score, i, x, y, bw, bh, area, mean_score = item
        # 保留得分较高的多个片段，允许回线断裂为几段
        if comp_score >= 0.18 * best_score or len(kept) < 3:
            cleaned[labels == i] = 255
            kept.append(item)

        if len(kept) >= 12:
            break

    # 轻微闭运算连接断裂，不做强开运算，避免细线被抹掉
    kernel = np.ones((3, 3), np.uint8)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel, iterations=1)

    return cleaned, kept


def extract_trace_mask(roi_bgr, threshold="auto", min_area=80):
    score = compute_neon_score(roi_bgr)
    mask0 = threshold_trace(score, threshold=threshold)

    # 轻微膨胀连接断点，但别太大
    kernel = np.ones((2, 2), np.uint8)
    mask0 = cv2.dilate(mask0, kernel, iterations=1)

    mask, comps = filter_components(mask0, score, min_area=min_area)

    # 如果过滤过严导致为空，放宽边界兜底
    if cv2.countNonZero(mask) < 80:
        mask, comps = filter_components(mask0, score, min_area=max(10, min_area // 3), border_margin=3)

    return mask, score, comps


def points_from_mask(mask):
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        raise RuntimeError("未提取到有效回线：请检查 ROI 是否框住屏幕，或降低 --threshold，例如 --threshold 15。")
    return xs.astype(np.float64), ys.astype(np.float64)


# -----------------------------
# 坐标换算
# -----------------------------

def normalize_and_voltage(xs, ys, roi_shape, args):
    """
    从 ROI 坐标下的像素点转换为：
    1. 归一化坐标 H*, B*
    2. 电压坐标 U_H, U_B

    默认原点为 ROI 中心；如果指定 --origin x,y，则使用 ROI 内像素坐标。
    """
    h, w = roi_shape[:2]

    if args.origin is not None:
        ox, oy = [float(v) for v in args.origin.split(",")]
    else:
        ox, oy = w / 2.0, h / 2.0

    px_per_div_x = w / float(args.x_divs)
    px_per_div_y = h / float(args.y_divs)

    # 归一化：以半屏为1
    Hs = (xs - ox) / (w / 2.0)
    Bs = -(ys - oy) / (h / 2.0)

    UH = (xs - ox) / px_per_div_x * float(args.x_vdiv)
    UB = -(ys - oy) / px_per_div_y * float(args.y_vdiv)

    return Hs, Bs, UH, UB, {
        "origin_x_roi_px": ox,
        "origin_y_roi_px": oy,
        "px_per_div_x": px_per_div_x,
        "px_per_div_y": px_per_div_y
    }


def voltage_to_HB(UH, UB, args):
    """
    由电压坐标转换为实际 H, B。
    若缺 l 或 S，则返回 None。
    H = n * UH / (l * R1)
    B = R2 * C2 * UB / (N * S)
    """
    H = None
    B = None
    if args.l is not None and args.R1 is not None:
        H = args.n * UH / (args.l * args.R1)
    if args.S is not None:
        B = args.R2 * args.C2 * UB / (args.N * args.S)
    return H, B


# -----------------------------
# 分支重建和平滑
# -----------------------------

def moving_average(y, win=7):
    if win <= 1:
        return y
    win = int(win)
    if win % 2 == 0:
        win += 1
    pad = win // 2
    ypad = np.pad(y, (pad, pad), mode="edge")
    kernel = np.ones(win) / win
    return np.convolve(ypad, kernel, mode="valid")


def smooth_array(y, window=21, poly=3):
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 5:
        return y

    window = int(window)
    if window % 2 == 0:
        window += 1
    window = min(window, n if n % 2 == 1 else n - 1)

    if window < 5:
        return moving_average(y, 3)

    if HAS_SCIPY:
        # 先中值滤波去毛刺，再 SG 平滑
        k = min(7, window)
        if k % 2 == 0:
            k += 1
        try:
            y2 = medfilt(y, kernel_size=k)
            return savgol_filter(y2, window_length=window, polyorder=min(poly, window - 2), mode="interp")
        except Exception:
            return moving_average(y, min(9, window))
    else:
        return moving_average(y, min(9, window))


def split_two_clusters(values, min_gap_ratio=0.12):
    """
    对同一 H bin 内的 B 值进行上下分支中心估计。
    不是简单取最大/最小，而是找两簇的中位数，避免提取到粗边缘。
    """
    v = np.sort(np.asarray(values, dtype=float))
    if len(v) < 4:
        return None

    # 去掉极端点
    lo, hi = np.percentile(v, [8, 92])
    v = v[(v >= lo) & (v <= hi)]
    if len(v) < 4:
        return None

    span = v[-1] - v[0]
    if span < 1e-9:
        med = float(np.median(v))
        return med, med

    gaps = np.diff(v)
    idx = int(np.argmax(gaps))
    max_gap = gaps[idx]

    # 如果明显是两簇，分开；否则当作一条线
    if max_gap > min_gap_ratio * span and idx >= 1 and idx < len(v) - 2:
        lower = v[:idx + 1]
        upper = v[idx + 1:]
        return float(np.median(lower)), float(np.median(upper))
    else:
        med = float(np.median(v))
        return med, med


def reconstruct_branches(x, y, bins=140, smooth_window=21, min_points_per_bin=8):
    """
    输入散点 x,y，输出按 x 分箱后的上下分支。
    用于：
    - H*-B*
    - UH-UB
    - H-B
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)

    finite = np.isfinite(x) & np.isfinite(y)
    x = x[finite]
    y = y[finite]

    # 先去掉极端离群点，避免底部边框或反光残留影响
    x1, x2 = np.percentile(x, [1, 99])
    y1, y2 = np.percentile(y, [1, 99])
    keep = (x >= x1) & (x <= x2) & (y >= y1) & (y <= y2)
    x = x[keep]
    y = y[keep]

    if len(x) < 50:
        raise RuntimeError("有效点太少，无法重建分支。请降低 threshold 或检查 ROI。")

    # 进一步用 PCA 思路筛掉远离主斜带的孤立点
    pts = np.column_stack([x, y])
    mu = pts.mean(axis=0)
    X = pts - mu
    cov = np.cov(X.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    # 沿主轴和副轴坐标
    V = eigvecs[:, np.argsort(eigvals)[::-1]]
    uv = X @ V
    # 对副轴方向按分位数裁掉严重离群
    qlo, qhi = np.percentile(uv[:, 1], [0.5, 99.5])
    keep2 = (uv[:, 1] >= qlo) & (uv[:, 1] <= qhi)
    x = x[keep2]
    y = y[keep2]

    xmin, xmax = np.percentile(x, [1, 99])
    edges = np.linspace(xmin, xmax, int(bins) + 1)

    xc_list, lower_list, upper_list = [], [], []

    for i in range(len(edges) - 1):
        a, b = edges[i], edges[i + 1]
        m = (x >= a) & (x < b)
        vals = y[m]
        if len(vals) < min_points_per_bin:
            continue

        pair = split_two_clusters(vals)
        if pair is None:
            continue

        lower, upper = pair
        xc = 0.5 * (a + b)
        xc_list.append(xc)
        lower_list.append(lower)
        upper_list.append(upper)

    xc = np.asarray(xc_list, dtype=float)
    lower = np.asarray(lower_list, dtype=float)
    upper = np.asarray(upper_list, dtype=float)

    if len(xc) < 8:
        raise RuntimeError("分支重建失败：可尝试降低 --bins，或降低 --min-points-per-bin。")

    # 保证 upper >= lower
    low = np.minimum(lower, upper)
    up = np.maximum(lower, upper)

    # 去掉明显异常的垂直宽度点
    width = up - low
    w_med = np.median(width)
    w_mad = np.median(np.abs(width - w_med)) + 1e-9
    keepw = width < (w_med + 5.0 * w_mad)
    # 不要过度过滤
    if keepw.sum() > 0.6 * len(keepw):
        xc, low, up = xc[keepw], low[keepw], up[keepw]

    # 平滑
    sw = int(smooth_window)
    if sw >= len(xc):
        sw = len(xc) - 1
    if sw % 2 == 0:
        sw -= 1
    sw = max(5, sw)

    low_s = smooth_array(low, window=sw)
    up_s = smooth_array(up, window=sw)

    return xc, low_s, up_s


def interp_crossing_x(x, y, target=0.0):
    """
    求 y=target 的 x 交点，可能有多个。
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    out = []

    for i in range(len(x) - 1):
        y1, y2 = y[i], y[i + 1]
        if not np.isfinite(y1) or not np.isfinite(y2):
            continue
        if (y1 - target) == 0:
            out.append(x[i])
        if (y1 - target) * (y2 - target) < 0 and abs(y2 - y1) > 1e-12:
            t = (target - y1) / (y2 - y1)
            out.append(x[i] + t * (x[i + 1] - x[i]))
    return out


def interp_y_at_x(x, y, target=0.0):
    """
    求 x=target 时 y 的插值。
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    order = np.argsort(x)
    x = x[order]
    y = y[order]

    if target < x.min() or target > x.max():
        return None
    return float(np.interp(target, x, y))


def branch_parameters(x, lower, upper, prefix=""):
    """
    对上下分支计算 Br, Hc, Hm, Bm, 面积。
    """
    x = np.asarray(x, dtype=float)
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)

    Hm = float(np.nanmax(np.abs(x)))
    Bm = float(max(np.nanmax(np.abs(lower)), np.nanmax(np.abs(upper))))

    br_values = []
    y0u = interp_y_at_x(x, upper, 0.0)
    y0l = interp_y_at_x(x, lower, 0.0)
    if y0u is not None:
        br_values.append(y0u)
    if y0l is not None:
        br_values.append(y0l)

    hc_values = []
    hc_values.extend(interp_crossing_x(x, upper, 0.0))
    hc_values.extend(interp_crossing_x(x, lower, 0.0))

    area = float(abs(np.trapezoid(upper - lower, x)))

    return {
        f"{prefix}Hm": Hm,
        f"{prefix}Bm": Bm,
        f"{prefix}Br_values": [float(v) for v in br_values],
        f"{prefix}Br_abs_mean": float(np.mean(np.abs(br_values))) if br_values else None,
        f"{prefix}Hc_values": [float(v) for v in hc_values],
        f"{prefix}Hc_abs_mean": float(np.mean(np.abs(hc_values))) if hc_values else None,
        f"{prefix}LoopArea": area,
    }


# -----------------------------
# 绘图和输出
# -----------------------------

def plot_overlay(roi, mask, out_path):
    overlay = roi.copy()
    red = np.zeros_like(roi)
    red[:, :, 2] = 255
    mask3 = cv2.merge([mask, mask, mask])
    overlay = np.where(mask3 > 0, cv2.addWeighted(overlay, 0.55, red, 0.45, 0), overlay)
    imwrite_unicode(out_path, overlay)


def plot_raw_and_smooth(x_raw, y_raw, x, low, up, xlabel, ylabel, title, out_path):
    plt.figure(figsize=(7, 7))
    plt.scatter(x_raw, y_raw, s=2, alpha=0.18, label="raw extracted points")
    plt.plot(x, up, linewidth=2.2, label="upper branch")
    plt.plot(x, low, linewidth=2.2, label="lower branch")
    plt.axhline(0, linewidth=1)
    plt.axvline(0, linewidth=1)
    plt.grid(True)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.title(title)
    plt.axis("equal")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=240)
    plt.close()


def plot_smooth_only(x, low, up, xlabel, ylabel, title, out_path):
    plt.figure(figsize=(7, 7))
    plt.plot(x, up, linewidth=2.4, label="upper branch")
    plt.plot(x, low, linewidth=2.4, label="lower branch")
    plt.fill_between(x, low, up, alpha=0.12, label="loop area")
    plt.axhline(0, linewidth=1)
    plt.axvline(0, linewidth=1)
    plt.grid(True)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.title(title)
    plt.axis("equal")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=240)
    plt.close()


def diagnose(params_norm, comps, mask_count, args):
    msgs = []

    area = params_norm.get("star_LoopArea")
    br = params_norm.get("star_Br_abs_mean")
    hc = params_norm.get("star_Hc_abs_mean")

    if mask_count < 300:
        msgs.append("有效轨迹点偏少，可能是回线过暗、ROI不准或阈值过高。建议降低 threshold 或提高示波器亮度。")

    if area is not None and area < 0.05:
        msgs.append("回线面积较小，可能励磁不足或材料磁滞效应较弱。")

    if br is None:
        msgs.append("未稳定得到 Br，可能坐标原点不准或回线未覆盖 H=0 位置。建议使用 --origin 手动标定原点。")

    if hc is None:
        msgs.append("未稳定得到 Hc，可能回线未穿过 B=0 轴或坐标原点不准。")

    if len(comps) > 5:
        msgs.append("提取到多个亮线片段，图像中可能存在反光或噪声。建议固定手机、减少屏幕反光。")

    if args.origin is None:
        msgs.append("当前默认使用ROI中心作为坐标原点。若示波器零点未居中，Br/Hc会有系统偏差，建议使用 --origin x,y 手动标定。")

    if not msgs:
        msgs.append("回线提取和分支重建正常，可用于后续磁学参数分析。")

    return msgs


def write_report(out_path, image_name, args, params, diagnostics):
    lines = []
    lines.append(f"# 磁滞回线智能分析报告\n")
    lines.append(f"## 1. 输入图像\n")
    lines.append(f"- 图像文件：`{image_name}`\n")
    lines.append(f"## 2. 实验参数\n")
    lines.append(f"- X volts/div：{args.x_vdiv} V/div")
    lines.append(f"- Y volts/div：{args.y_vdiv} V/div")
    lines.append(f"- 横向格数：{args.x_divs}")
    lines.append(f"- 纵向格数：{args.y_divs}")
    lines.append(f"- R1：{args.R1} Ω" if args.R1 is not None else "- R1：未输入")
    lines.append(f"- 励磁电压 U：{args.U} V" if args.U is not None else "- 励磁电压 U：未输入")
    lines.append(f"- n：{args.n}")
    lines.append(f"- N：{args.N}")
    lines.append(f"- R2：{args.R2} Ω")
    lines.append(f"- C2：{args.C2} F")
    lines.append(f"- l：{args.l} m" if args.l is not None else "- l：未输入，无法计算真实 H")
    lines.append(f"- S：{args.S} m²" if args.S is not None else "- S：未输入，无法计算真实 B")
    lines.append("")
    lines.append("## 3. 归一化参数")
    for k, v in params.get("normalized", {}).items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## 4. 电压坐标参数")
    for k, v in params.get("voltage", {}).items():
        lines.append(f"- {k}: {v}")
    if "physical" in params:
        lines.append("")
        lines.append("## 5. 物理量参数")
        for k, v in params.get("physical", {}).items():
            lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## 6. 实验状态诊断")
    for m in diagnostics:
        lines.append(f"- {m}")
    lines.append("")
    lines.append("## 7. 说明")
    lines.append("本报告中的归一化参数基于图像坐标计算。若要得到真实磁场强度 H 和磁感应强度 B，需要输入示波器档位、取样电阻、线圈匝数、样品平均磁路长度和截面积等参数。")
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")


# -----------------------------
# 主程序
# -----------------------------

def main():
    parser = argparse.ArgumentParser(description="手机拍摄模拟示波器磁滞回线智能分析程序（鲁棒版）")

    parser.add_argument("image", help="输入图片路径")
    parser.add_argument("--roi", default="auto", help="ROI: x1,y1,x2,y2；默认 auto")
    parser.add_argument("--threshold", default="auto", help="亮线提取阈值：auto 或数值，例如 20")
    parser.add_argument("--min-area", type=int, default=80, help="连通域最小面积")
    parser.add_argument("--outdir", default="output_hysteresis_robust", help="输出文件夹")

    parser.add_argument("--x-divs", type=float, default=10.0, help="示波器横向格数，默认10")
    parser.add_argument("--y-divs", type=float, default=8.0, help="示波器纵向格数，默认8")
    parser.add_argument("--x-vdiv", type=float, default=0.5, help="X volts/div")
    parser.add_argument("--y-vdiv", type=float, default=0.5, help="Y volts/div")
    parser.add_argument("--origin", default=None, help="ROI内原点坐标 x,y；不填则默认ROI中心")

    parser.add_argument("--R1", type=float, default=None, help="取样电阻 R1, Ω")
    parser.add_argument("--U", type=float, default=None, help="励磁电压 U, V，仅记录实验条件")
    parser.add_argument("--n", type=float, default=150.0, help="励磁线圈匝数，默认150")
    parser.add_argument("--N", type=float, default=50.0, help="感应线圈匝数，默认50")
    parser.add_argument("--R2", type=float, default=10000.0, help="积分电阻 R2, Ω，默认10000")
    parser.add_argument("--C2", type=float, default=10e-6, help="积分电容 C2, F，默认10e-6")
    parser.add_argument("--l", type=float, default=None, help="样品平均磁路长度 l, m")
    parser.add_argument("--S", type=float, default=None, help="样品截面积 S, m^2")

    parser.add_argument("--bins", type=int, default=140, help="分支重建分箱数")
    parser.add_argument("--smooth-window", type=int, default=21, help="平滑窗口，奇数，常用15~31")
    parser.add_argument("--min-points-per-bin", type=int, default=8, help="每个分箱最少点数")

    args = parser.parse_args()

    img = imread_unicode(args.image)
    if img is None:
        raise FileNotFoundError(f"无法读取图片：{args.image}")

    robust_mkdir(args.outdir)
    stem = Path(args.image).stem

    roi_given = parse_roi(args.roi)
    if roi_given is None:
        x1, y1, x2, y2 = auto_crop_scope_screen(img)
    else:
        x1, y1, x2, y2 = roi_given

    H_img, W_img = img.shape[:2]
    x1 = max(0, min(W_img - 1, x1))
    x2 = max(1, min(W_img, x2))
    y1 = max(0, min(H_img - 1, y1))
    y2 = max(1, min(H_img, y2))

    roi = img[y1:y2, x1:x2].copy()
    if roi.size == 0:
        raise RuntimeError("ROI裁剪为空，请检查 --roi。")

    # 保存 ROI
    imwrite_unicode(str(Path(args.outdir) / f"{stem}_roi.jpg"), roi)

    # 提取轨迹
    mask, score, comps = extract_trace_mask(roi, threshold=args.threshold, min_area=args.min_area)
    mask_count = int(cv2.countNonZero(mask))

    if mask_count < 50:
        # 自动再尝试更低阈值
        mask, score, comps = extract_trace_mask(roi, threshold=12, min_area=max(10, args.min_area // 3))
        mask_count = int(cv2.countNonZero(mask))

    if mask_count < 50:
        raise RuntimeError("仍未提取到足够回线点：请手动调 ROI，或使用 --threshold 10，或提高照片中回线亮度。")

    # 输出 mask/score/overlay
    cv2.imwrite(str(Path(args.outdir) / f"{stem}_score.png"), score)
    cv2.imwrite(str(Path(args.outdir) / f"{stem}_mask.png"), mask)
    plot_overlay(roi, mask, str(Path(args.outdir) / f"{stem}_overlay.jpg"))

    xs, ys = points_from_mask(mask)

    Hs, Bs, UH, UB, calib = normalize_and_voltage(xs, ys, roi.shape, args)
    H_phys, B_phys = voltage_to_HB(UH, UB, args)

    # 保存原始点
    df = pd.DataFrame({
        "x_roi_px": xs,
        "y_roi_px": ys,
        "H_star": Hs,
        "B_star": Bs,
        "U_H_V": UH,
        "U_B_V": UB,
    })
    if H_phys is not None:
        df["H_A_per_m"] = H_phys
    if B_phys is not None:
        df["B_T"] = B_phys

    df.to_csv(Path(args.outdir) / f"{stem}_raw_points.csv", index=False, encoding="utf-8-sig")

    # 分支重建：归一化坐标
    x_star, low_star, up_star = reconstruct_branches(
        Hs, Bs, bins=args.bins, smooth_window=args.smooth_window,
        min_points_per_bin=args.min_points_per_bin
    )

    params_norm = branch_parameters(x_star, low_star, up_star, prefix="star_")

    plot_raw_and_smooth(
        Hs, Bs, x_star, low_star, up_star,
        "H*", "B*", "Extracted and smoothed normalized hysteresis loop",
        str(Path(args.outdir) / f"{stem}_loop_normalized_raw_smooth.png")
    )
    plot_smooth_only(
        x_star, low_star, up_star,
        "H*", "B*", "Smoothed normalized hysteresis loop",
        str(Path(args.outdir) / f"{stem}_loop_normalized_smooth.png")
    )

    branches = pd.DataFrame({
        "H_star": x_star,
        "B_lower_star": low_star,
        "B_upper_star": up_star
    })

    # 电压坐标重建
    x_v, low_v, up_v = reconstruct_branches(
        UH, UB, bins=args.bins, smooth_window=args.smooth_window,
        min_points_per_bin=args.min_points_per_bin
    )
    params_v = branch_parameters(x_v, low_v, up_v, prefix="voltage_")
    plot_smooth_only(
        x_v, low_v, up_v,
        "U_H / V", "U_B / V", "Smoothed voltage-coordinate hysteresis loop",
        str(Path(args.outdir) / f"{stem}_loop_voltage_smooth.png")
    )
    branches["U_H_V"] = x_v[:len(branches)] if len(x_v) == len(branches) else np.nan
    if len(x_v) == len(branches):
        branches["U_B_lower_V"] = low_v
        branches["U_B_upper_V"] = up_v

    # 物理坐标重建
    params_phys = None
    if H_phys is not None and B_phys is not None:
        x_p, low_p, up_p = reconstruct_branches(
            H_phys, B_phys, bins=args.bins, smooth_window=args.smooth_window,
            min_points_per_bin=args.min_points_per_bin
        )
        params_phys = branch_parameters(x_p, low_p, up_p, prefix="physical_")
        plot_smooth_only(
            x_p, low_p, up_p,
            "H / (A/m)", "B / T", "Smoothed physical hysteresis loop",
            str(Path(args.outdir) / f"{stem}_loop_physical_smooth.png")
        )

    branches.to_csv(Path(args.outdir) / f"{stem}_smoothed_branches.csv", index=False, encoding="utf-8-sig")

    diagnostics = diagnose(params_norm, comps, mask_count, args)

    result = {
        "image": args.image,
        "roi": [int(x1), int(y1), int(x2), int(y2)],
        "calibration": calib,
        "component_count_kept": len(comps),
        "mask_pixel_count": mask_count,
        "normalized": params_norm,
        "voltage": params_v,
        "diagnostics": diagnostics
    }
    if params_phys is not None:
        result["physical"] = params_phys

    with open(Path(args.outdir) / f"{stem}_result.json", "w", encoding="utf-8") as f:
        json.dump(make_json_safe(result), f, ensure_ascii=False, indent=2)

    write_report(Path(args.outdir) / f"{stem}_report.md", Path(args.image).name, args, result, diagnostics)

    print("\n========== 分析完成 ==========")
    print(f"输出目录：{args.outdir}")
    print(f"ROI: {[x1, y1, x2, y2]}")
    print(f"有效回线像素点: {mask_count}")
    print("\n--- 归一化参数 ---")
    for k, v in params_norm.items():
        print(f"{k}: {v}")
    print("\n--- 电压坐标参数 ---")
    for k, v in params_v.items():
        print(f"{k}: {v}")
    if params_phys is not None:
        print("\n--- 物理量参数 ---")
        for k, v in params_phys.items():
            print(f"{k}: {v}")
    print("\n--- 诊断建议 ---")
    for m in diagnostics:
        print("- " + m)


if __name__ == "__main__":
    main()
