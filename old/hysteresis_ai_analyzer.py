#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智眼识磁：基于手机视觉的磁滞回线提取与参数分析工具
========================================================
功能：
1. 从手机拍摄/示波器截图中提取磁滞回线轨迹；
2. 支持手动 ROI 裁剪和颜色模式选择；
3. 将像素坐标转换为归一化坐标、示波器电压坐标；
4. 可选输入实验仪参数，进一步换算 H(A/m)、B(T)；
5. 自动计算 Br、Hc、Bm、Hm、回线面积等参数；
6. 输出 overlay 图、mask 图、重建回线图、CSV、JSON 和 Markdown 报告。

安装依赖：
    pip install opencv-python numpy matplotlib pandas

基本用法：
    python hysteresis_ai_analyzer.py image.jpg --roi 58,20,260,220 --color magenta \
        --x-vdiv 0.5 --y-vdiv 0.5 --x-divs 10 --y-divs 8 --R1 2.5 --U 2.5

若已知样品参数：
    python hysteresis_ai_analyzer.py image.jpg --roi 58,20,260,220 --color magenta \
        --x-vdiv 0.5 --y-vdiv 0.5 --R1 2.5 --l 0.13 --S 1.25e-4
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# =========================
# 数据结构
# =========================

@dataclass
class Calibration:
    # 示波器参数
    x_vdiv: float = 1.0       # X volts/div
    y_vdiv: float = 1.0       # Y volts/div
    x_divs: float = 10.0      # 横向格数
    y_divs: float = 8.0       # 纵向格数

    # 实验仪参数
    R1: Optional[float] = None        # 励磁电流取样电阻，ohm
    U: Optional[float] = None         # 励磁电压档位，V，仅作为实验条件记录
    n: float = 150.0                 # 励磁线圈匝数，图中 n=150
    N: float = 50.0                  # 感应线圈匝数，图中 N=50
    R2: float = 10000.0              # 积分电阻，图中 R2=10.0kΩ
    C2: float = 10e-6                # 积分电容，图中 C2=10μF
    l: Optional[float] = None        # 样品平均磁路长度，m
    S: Optional[float] = None        # 样品截面积，m^2


@dataclass
class AxisInfo:
    x0: float
    y0: float
    px_per_div_x: float
    px_per_div_y: float
    roi_w: int
    roi_h: int


# =========================
# 基础工具函数
# =========================

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def parse_roi(text: Optional[str], img_shape: Tuple[int, int, int]) -> Tuple[int, int, int, int]:
    """
    ROI 格式：x1,y1,x2,y2。
    若不输入，则默认整张图。
    """
    h, w = img_shape[:2]
    if text is None or text.strip() == "":
        return 0, 0, w, h

    parts = [int(float(p.strip())) for p in text.split(',')]
    if len(parts) != 4:
        raise ValueError("--roi 必须是 x1,y1,x2,y2 格式，例如 --roi 58,20,260,220")
    x1, y1, x2, y2 = parts
    x1 = max(0, min(w - 1, x1))
    x2 = max(1, min(w, x2))
    y1 = max(0, min(h - 1, y1))
    y2 = max(1, min(h, y2))
    if x2 <= x1 or y2 <= y1:
        raise ValueError("ROI 范围错误：x2/y2 必须大于 x1/y1")
    return x1, y1, x2, y2


def resize_if_needed(img: np.ndarray, max_width: int = 1600) -> np.ndarray:
    h, w = img.shape[:2]
    if w <= max_width:
        return img
    scale = max_width / w
    return cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


# =========================
# 图像分割与轨迹提取
# =========================

def make_color_mask(roi: np.ndarray, color: str = "auto") -> np.ndarray:
    """
    根据颜色模式提取示波器轨迹。
    color 可选：auto, magenta, green, cyan, bright
    """
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    masks: Dict[str, np.ndarray] = {}

    # 品红/紫红，很多数字示波器 CH2 或截图轨迹使用该色
    masks["magenta"] = cv2.inRange(hsv, np.array([130, 60, 60]), np.array([175, 255, 255]))

    # 绿色，模拟示波器常见荧光轨迹
    masks["green"] = cv2.inRange(hsv, np.array([35, 45, 45]), np.array([95, 255, 255]))

    # 青色/蓝绿色，部分示波器轨迹
    masks["cyan"] = cv2.inRange(hsv, np.array([80, 40, 50]), np.array([110, 255, 255]))

    # 高亮轨迹：适合白色/亮色轨迹，但容易混入文字网格
    # 用较高分位阈值而非 Otsu，避免背景偏亮时阈值过低
    thr = max(140, int(np.percentile(gray, 93)))
    _, masks["bright"] = cv2.threshold(gray, thr, 255, cv2.THRESH_BINARY)

    color = color.lower().strip()
    if color in masks and color != "auto":
        mask = masks[color]
    elif color == "auto":
        # 自动选择：优先选择连通域面积适中、靠近中心且非大面积背景的颜色
        best_name, best_score, best_mask = None, -1.0, None
        h, w = gray.shape
        center = np.array([w / 2, h / 2])
        for name, m in masks.items():
            m2 = clean_mask(m, light=True)
            num, labels, stats, centroids = cv2.connectedComponentsWithStats(m2, 8)
            if num <= 1:
                continue
            areas = stats[1:, cv2.CC_STAT_AREA]
            if len(areas) == 0:
                continue
            max_idx = int(np.argmax(areas)) + 1
            area = float(stats[max_idx, cv2.CC_STAT_AREA])
            if area < 20:
                continue
            # 太大的高亮区域可能是文字/背景，不优先
            area_ratio = area / (h * w)
            c = centroids[max_idx]
            dist = np.linalg.norm(c - center) / max(w, h)
            score = area * (1.0 - min(dist, 0.8))
            if name == "bright" and area_ratio > 0.15:
                score *= 0.3
            if score > best_score:
                best_name, best_score, best_mask = name, score, m2
        if best_mask is None:
            best_mask = masks["bright"]
            best_name = "bright"
        print(f"[INFO] 自动颜色模式选择：{best_name}")
        mask = best_mask
    else:
        raise ValueError("--color 只能是 auto/magenta/green/cyan/bright")

    return mask


def clean_mask(mask: np.ndarray, light: bool = False) -> np.ndarray:
    """
    清理 mask。
    注意：示波器轨迹可能只有 1~2 像素粗，不要轻易开运算。
    """
    out = mask.copy()
    # 闭运算连接轻微断裂
    k = np.ones((2, 2), np.uint8)
    out = cv2.morphologyEx(out, cv2.MORPH_CLOSE, k, iterations=1)
    if not light:
        # 轻微膨胀，方便轮廓面积计算；不要过度
        out = cv2.dilate(out, np.ones((2, 2), np.uint8), iterations=1)
    return out


def keep_central_components(mask: np.ndarray, min_area: int = 20, max_components: int = 8) -> np.ndarray:
    """
    保留主要轨迹连通域，尽量去掉文字、刻度。
    规则：面积足够 + 靠近 ROI 中心。
    """
    h, w = mask.shape
    num, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    if num <= 1:
        return mask

    center = np.array([w / 2, h / 2])
    comps = []
    for i in range(1, num):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        x, y, bw, bh = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP], stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        c = centroids[i]
        dist = float(np.linalg.norm(c - center) / max(w, h))
        # 分数：面积越大越好，越靠中心越好，过于扁长文字降权
        aspect_penalty = 1.0
        if bw > 0 and bh > 0:
            aspect = max(bw / bh, bh / bw)
            if aspect > 12:
                aspect_penalty = 0.3
        score = area * (1.0 - min(dist, 0.9)) * aspect_penalty
        comps.append((score, i))

    comps.sort(reverse=True)
    cleaned = np.zeros_like(mask)
    for _, i in comps[:max_components]:
        cleaned[labels == i] = 255
    return cleaned


def skeletonize_cv(mask: np.ndarray) -> np.ndarray:
    """
    不依赖 skimage 的骨架化。若轨迹太细，直接返回也可。
    """
    img = (mask > 0).astype(np.uint8) * 255
    skel = np.zeros(img.shape, np.uint8)
    element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    while True:
        eroded = cv2.erode(img, element)
        temp = cv2.dilate(eroded, element)
        temp = cv2.subtract(img, temp)
        skel = cv2.bitwise_or(skel, temp)
        img = eroded.copy()
        if cv2.countNonZero(img) == 0:
            break
    return skel


def extract_points(mask: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        raise RuntimeError("没有提取到轨迹点。请尝试：换 --color；缩小 --roi；提高示波器亮度。")
    return xs.astype(float), ys.astype(float)


# =========================
# 坐标换算与参数计算
# =========================

def build_axis_info(roi_shape: Tuple[int, int, int], calib: Calibration,
                    origin: Optional[str] = None) -> AxisInfo:
    h, w = roi_shape[:2]
    if origin:
        parts = [float(p.strip()) for p in origin.split(',')]
        if len(parts) != 2:
            raise ValueError("--origin 必须是 x0,y0 格式，例如 --origin 160,120")
        x0, y0 = parts
    else:
        x0, y0 = w / 2.0, h / 2.0

    px_per_div_x = w / calib.x_divs
    px_per_div_y = h / calib.y_divs
    return AxisInfo(x0=x0, y0=y0, px_per_div_x=px_per_div_x, px_per_div_y=px_per_div_y,
                    roi_w=w, roi_h=h)


def pixel_to_units(xs: np.ndarray, ys: np.ndarray, axis: AxisInfo, calib: Calibration) -> pd.DataFrame:
    """
    像素 -> 归一化坐标 -> 示波器电压 -> 可选 H/B。
    """
    H_star = (xs - axis.x0) / (axis.roi_w / 2.0)
    B_star = -(ys - axis.y0) / (axis.roi_h / 2.0)

    U_H = (xs - axis.x0) / axis.px_per_div_x * calib.x_vdiv
    U_B = -(ys - axis.y0) / axis.px_per_div_y * calib.y_vdiv

    data = {
        "x_px": xs,
        "y_px": ys,
        "H_star": H_star,
        "B_star": B_star,
        "U_H_V": U_H,
        "U_B_V": U_B,
    }

    if calib.R1 is not None and calib.l is not None:
        data["H_A_per_m"] = calib.n * U_H / (calib.l * calib.R1)

    if calib.S is not None:
        data["B_T"] = calib.R2 * calib.C2 * U_B / (calib.N * calib.S)

    return pd.DataFrame(data)


def axis_crossing_abs(df: pd.DataFrame, x_col: str, y_col: str, band: float) -> Optional[float]:
    """
    估计 y轴/ x轴交点绝对值：
    例如 Br：取 |H| 很小的点，统计 B 的正负截距；
    Hc：取 |B| 很小的点，统计 H 的正负截距。
    """
    sub = df[np.abs(df[x_col]) <= band]
    if len(sub) < 5:
        # 退化：找最靠近轴的若干点
        sub = df.iloc[np.argsort(np.abs(df[x_col].values))[:max(5, min(30, len(df)))]]
    vals = sub[y_col].dropna().values
    if len(vals) == 0:
        return None

    pos = vals[vals > 0]
    neg = vals[vals < 0]
    candidates = []
    if len(pos) > 0:
        candidates.append(float(np.percentile(pos, 80)))
    if len(neg) > 0:
        candidates.append(float(np.percentile(np.abs(neg), 80)))
    if not candidates:
        return None
    return float(np.mean(candidates))


def contour_area_in_units(mask: np.ndarray, x_scale: float, y_scale: float) -> float:
    """
    用轮廓面积估计回线面积。
    x_scale/y_scale 是每像素对应的坐标单位。
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return 0.0
    # 取面积最大的闭合轮廓
    c = max(contours, key=cv2.contourArea)
    area_px = float(cv2.contourArea(c))
    return abs(area_px * x_scale * y_scale)


def calculate_params(df: pd.DataFrame, mask: np.ndarray, axis: AxisInfo, calib: Calibration) -> Dict[str, Optional[float]]:
    params: Dict[str, Optional[float]] = {}

    # 归一化参数
    params["Hm_star"] = float(np.nanmax(np.abs(df["H_star"])))
    params["Bm_star"] = float(np.nanmax(np.abs(df["B_star"])))
    params["Br_star_abs"] = axis_crossing_abs(df, "H_star", "B_star", band=0.025)
    params["Hc_star_abs"] = axis_crossing_abs(df, "B_star", "H_star", band=0.025)
    params["LoopArea_star"] = contour_area_in_units(mask, 2.0 / axis.roi_w, 2.0 / axis.roi_h)

    # 电压参数
    params["UH_max_V"] = float(np.nanmax(np.abs(df["U_H_V"])))
    params["UB_max_V"] = float(np.nanmax(np.abs(df["U_B_V"])))
    params["UB_r_abs_V"] = axis_crossing_abs(df, "U_H_V", "U_B_V", band=calib.x_vdiv * 0.05)
    params["UH_c_abs_V"] = axis_crossing_abs(df, "U_B_V", "U_H_V", band=calib.y_vdiv * 0.05)
    x_scale_u = calib.x_vdiv / axis.px_per_div_x
    y_scale_u = calib.y_vdiv / axis.px_per_div_y
    params["LoopArea_UH_UB_V2"] = contour_area_in_units(mask, x_scale_u, y_scale_u)

    # 真实 H/B 参数
    if "H_A_per_m" in df.columns:
        params["Hm_A_per_m"] = float(np.nanmax(np.abs(df["H_A_per_m"])))
    else:
        params["Hm_A_per_m"] = None

    if "B_T" in df.columns:
        params["Bm_T"] = float(np.nanmax(np.abs(df["B_T"])))
    else:
        params["Bm_T"] = None

    if "H_A_per_m" in df.columns and "B_T" in df.columns:
        # Br: H=0 时 B；Hc: B=0 时 H
        params["Br_abs_T"] = axis_crossing_abs(df, "H_A_per_m", "B_T", band=max(abs(params["Hm_A_per_m"] or 1) * 0.025, 1e-9))
        params["Hc_abs_A_per_m"] = axis_crossing_abs(df, "B_T", "H_A_per_m", band=max(abs(params["Bm_T"] or 1) * 0.025, 1e-12))
        # 面积单位：B*T times H*A/m = J/m^3 的量纲
        H_per_px = abs(calib.n / (calib.l * calib.R1)) * x_scale_u if calib.l and calib.R1 else 0
        B_per_px = abs(calib.R2 * calib.C2 / (calib.N * calib.S)) * y_scale_u if calib.S else 0
        params["LoopArea_BH_J_per_m3"] = contour_area_in_units(mask, H_per_px, B_per_px)
    else:
        params["Br_abs_T"] = None
        params["Hc_abs_A_per_m"] = None
        params["LoopArea_BH_J_per_m3"] = None

    return params


# =========================
# 诊断与报告
# =========================

def diagnose(df: pd.DataFrame, params: Dict[str, Optional[float]], mask: np.ndarray) -> List[str]:
    msgs: List[str] = []
    n_points = int(len(df))
    area_star = params.get("LoopArea_star") or 0
    hm = params.get("Hm_star") or 0
    bm = params.get("Bm_star") or 0

    # 点数与面积质量
    if n_points < 120:
        msgs.append("有效轨迹点偏少：可能拍摄不清晰、回线过暗，或 ROI/颜色模式设置不合适。")
    if area_star < 0.05:
        msgs.append("回线面积很小：可能未形成明显磁滞回线，或曲线提取不完整。")
    elif area_star < 0.25:
        msgs.append("回线面积偏小：可能励磁电压不足，样品未充分磁化，建议适当增大 U 档位。")

    if hm < 0.35 or bm < 0.35:
        msgs.append("回线在屏幕中幅度偏小：建议调节示波器 X/Y 灵敏度或增大励磁信号，使回线占据更多网格。")

    # 中心偏移：均值偏离过大
    h_mean = float(np.nanmean(df["H_star"]))
    b_mean = float(np.nanmean(df["B_star"]))
    if abs(h_mean) > 0.18 or abs(b_mean) > 0.18:
        msgs.append("回线中心存在明显偏移：建议重新调节示波器 X/Y 位置旋钮或检查零点校准。")

    # 回线是否靠近边界
    if hm > 0.95 or bm > 0.95:
        msgs.append("回线接近屏幕边界：可能存在截断风险，建议调小 X/Y 灵敏度或重新居中。")

    # mask 连通性粗略判断
    num, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    large = 0
    for i in range(1, num):
        if stats[i, cv2.CC_STAT_AREA] > 20:
            large += 1
    if large > 5:
        msgs.append("提取到多个较大连通区域：可能混入文字、网格或噪声，建议缩小 ROI 或改用更合适的颜色模式。")

    if not msgs:
        msgs.append("图像质量与回线提取状态较好，可用于磁滞参数分析。")
    return msgs


def write_markdown_report(path: str, image_path: str, calib: Calibration, axis: AxisInfo,
                          params: Dict[str, Optional[float]], diagnoses: List[str]) -> None:
    def fmt(v, unit=""):
        if v is None:
            return "未标定/未计算"
        if isinstance(v, float):
            return f"{v:.6g}{unit}"
        return str(v)

    lines = []
    lines.append("# 磁滞回线智能分析报告\n")
    lines.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 输入图像：`{image_path}`\n")

    lines.append("## 1. 参数设置\n")
    lines.append(f"- X volts/div：{calib.x_vdiv} V/div")
    lines.append(f"- Y volts/div：{calib.y_vdiv} V/div")
    lines.append(f"- 横向格数：{calib.x_divs} div")
    lines.append(f"- 纵向格数：{calib.y_divs} div")
    lines.append(f"- R1：{calib.R1 if calib.R1 is not None else '未输入'} Ω")
    lines.append(f"- U：{calib.U if calib.U is not None else '未输入'} V")
    lines.append(f"- n：{calib.n}")
    lines.append(f"- N：{calib.N}")
    lines.append(f"- R2：{calib.R2} Ω")
    lines.append(f"- C2：{calib.C2} F")
    lines.append(f"- l：{calib.l if calib.l is not None else '未输入'} m")
    lines.append(f"- S：{calib.S if calib.S is not None else '未输入'} m²\n")

    lines.append("## 2. 图像坐标设置\n")
    lines.append(f"- 坐标原点：({axis.x0:.2f}, {axis.y0:.2f}) px")
    lines.append(f"- X方向每格像素数：{axis.px_per_div_x:.2f} px/div")
    lines.append(f"- Y方向每格像素数：{axis.px_per_div_y:.2f} px/div\n")

    lines.append("## 3. 归一化参数\n")
    lines.append(f"- 最大磁场相对值 Hm*：{fmt(params.get('Hm_star'))}")
    lines.append(f"- 最大磁感应强度相对值 Bm*：{fmt(params.get('Bm_star'))}")
    lines.append(f"- 剩磁相对值 |Br*|：{fmt(params.get('Br_star_abs'))}")
    lines.append(f"- 矫顽力相对值 |Hc*|：{fmt(params.get('Hc_star_abs'))}")
    lines.append(f"- 归一化回线面积 S*：{fmt(params.get('LoopArea_star'))}\n")

    lines.append("## 4. 电压坐标参数\n")
    lines.append(f"- X轴最大电压 |UH|max：{fmt(params.get('UH_max_V'), ' V')}")
    lines.append(f"- Y轴最大电压 |UB|max：{fmt(params.get('UB_max_V'), ' V')}")
    lines.append(f"- H=0处Y轴电压 |UB,r|：{fmt(params.get('UB_r_abs_V'), ' V')}")
    lines.append(f"- B=0处X轴电压 |UH,c|：{fmt(params.get('UH_c_abs_V'), ' V')}")
    lines.append(f"- 电压坐标回线面积：{fmt(params.get('LoopArea_UH_UB_V2'), ' V²')}\n")

    lines.append("## 5. 物理量参数\n")
    lines.append(f"- Hm：{fmt(params.get('Hm_A_per_m'), ' A/m')}")
    lines.append(f"- Bm：{fmt(params.get('Bm_T'), ' T')}")
    lines.append(f"- |Br|：{fmt(params.get('Br_abs_T'), ' T')}")
    lines.append(f"- |Hc|：{fmt(params.get('Hc_abs_A_per_m'), ' A/m')}")
    lines.append(f"- 回线面积 ∮B dH：{fmt(params.get('LoopArea_BH_J_per_m3'), ' J/m³')}\n")

    if calib.l is None or calib.S is None or calib.R1 is None:
        lines.append("> 注：当前样品参数或 R1 不完整，因此部分真实物理量无法计算。系统仍可输出归一化参数与电压坐标参数，用于回线形态分析和实验状态判断。\n")

    lines.append("## 6. 实验状态诊断\n")
    for msg in diagnoses:
        lines.append(f"- {msg}")
    lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# =========================
# 可视化输出
# =========================

def save_visuals(out_dir: str, base: str, full_img: np.ndarray, roi: np.ndarray,
                 roi_xy: Tuple[int, int, int, int], mask: np.ndarray, skel: np.ndarray,
                 df: pd.DataFrame, params: Dict[str, Optional[float]]) -> None:
    ensure_dir(out_dir)
    x1, y1, x2, y2 = roi_xy

    cv2.imwrite(os.path.join(out_dir, f"{base}_roi.png"), roi)
    cv2.imwrite(os.path.join(out_dir, f"{base}_mask.png"), mask)
    cv2.imwrite(os.path.join(out_dir, f"{base}_skeleton.png"), skel)

    # ROI 覆盖图
    overlay = roi.copy()
    color_layer = np.zeros_like(overlay)
    color_layer[:, :, 1] = mask
    overlay = cv2.addWeighted(overlay, 0.75, color_layer, 0.9, 0)
    cv2.imwrite(os.path.join(out_dir, f"{base}_overlay_roi.png"), overlay)

    # 原图标出 ROI
    marked = full_img.copy()
    cv2.rectangle(marked, (x1, y1), (x2, y2), (0, 255, 255), 3)
    cv2.imwrite(os.path.join(out_dir, f"{base}_roi_marked.png"), marked)

    # 归一化图
    plt.figure(figsize=(6, 6))
    plt.scatter(df["H_star"], df["B_star"], s=1)
    plt.axhline(0, linewidth=1)
    plt.axvline(0, linewidth=1)
    plt.xlabel("H* / normalized")
    plt.ylabel("B* / normalized")
    plt.title("Extracted Hysteresis Loop (Normalized)")
    plt.axis("equal")
    plt.grid(True, alpha=0.3)
    text_items = [
        f"Hm*: {params.get('Hm_star'):.3f}" if params.get('Hm_star') is not None else "Hm*: None",
        f"Bm*: {params.get('Bm_star'):.3f}" if params.get('Bm_star') is not None else "Bm*: None",
        f"|Br*|: {params.get('Br_star_abs'):.3f}" if params.get('Br_star_abs') is not None else "|Br*|: None",
        f"|Hc*|: {params.get('Hc_star_abs'):.3f}" if params.get('Hc_star_abs') is not None else "|Hc*|: None",
        f"Area*: {params.get('LoopArea_star'):.3f}" if params.get('LoopArea_star') is not None else "Area*: None",
    ]
    plt.text(0.02, 0.98, "\n".join(text_items), transform=plt.gca().transAxes,
             va="top", bbox=dict(boxstyle="round", alpha=0.15))
    plt.savefig(os.path.join(out_dir, f"{base}_loop_normalized.png"), dpi=300, bbox_inches="tight")
    plt.close()

    # 电压图
    plt.figure(figsize=(6, 6))
    plt.scatter(df["U_H_V"], df["U_B_V"], s=1)
    plt.axhline(0, linewidth=1)
    plt.axvline(0, linewidth=1)
    plt.xlabel("U_H / V")
    plt.ylabel("U_B / V")
    plt.title("Extracted Hysteresis Loop (Oscilloscope Voltage)")
    plt.axis("equal")
    plt.grid(True, alpha=0.3)
    plt.savefig(os.path.join(out_dir, f"{base}_loop_voltage.png"), dpi=300, bbox_inches="tight")
    plt.close()

    # 物理量图：只有 H/B 都存在时输出
    if "H_A_per_m" in df.columns and "B_T" in df.columns:
        plt.figure(figsize=(6, 6))
        plt.scatter(df["H_A_per_m"], df["B_T"], s=1)
        plt.axhline(0, linewidth=1)
        plt.axvline(0, linewidth=1)
        plt.xlabel("H / (A/m)")
        plt.ylabel("B / T")
        plt.title("Extracted Hysteresis Loop (Calibrated B-H)")
        plt.axis("equal")
        plt.grid(True, alpha=0.3)
        plt.savefig(os.path.join(out_dir, f"{base}_loop_BH.png"), dpi=300, bbox_inches="tight")
        plt.close()


# =========================
# 主流程
# =========================

def run(args: argparse.Namespace) -> None:
    img = cv2.imread(args.image)
    if img is None:
        raise FileNotFoundError(f"无法读取图像：{args.image}")
    img = resize_if_needed(img, max_width=args.max_width)

    roi_xy = parse_roi(args.roi, img.shape)
    x1, y1, x2, y2 = roi_xy
    roi = img[y1:y2, x1:x2].copy()

    calib = Calibration(
        x_vdiv=args.x_vdiv,
        y_vdiv=args.y_vdiv,
        x_divs=args.x_divs,
        y_divs=args.y_divs,
        R1=args.R1,
        U=args.U,
        n=args.n,
        N=args.N,
        R2=args.R2,
        C2=args.C2,
        l=args.l,
        S=args.S,
    )

    axis = build_axis_info(roi.shape, calib, origin=args.origin)

    raw_mask = make_color_mask(roi, args.color)
    mask = clean_mask(raw_mask)
    mask = keep_central_components(mask, min_area=args.min_area, max_components=args.max_components)

    if args.skeleton:
        skel = skeletonize_cv(mask)
        points_mask = skel
    else:
        skel = skeletonize_cv(mask)
        # 默认用 skeleton 点计算坐标，mask 用于面积
        points_mask = skel

    xs, ys = extract_points(points_mask)
    df = pixel_to_units(xs, ys, axis, calib)
    params = calculate_params(df, mask, axis, calib)
    diagnoses = diagnose(df, params, mask)

    base = os.path.splitext(os.path.basename(args.image))[0]
    out_dir = args.out
    ensure_dir(out_dir)

    # 保存表格与参数
    csv_path = os.path.join(out_dir, f"{base}_points.csv")
    json_path = os.path.join(out_dir, f"{base}_result.json")
    report_path = os.path.join(out_dir, f"{base}_report.md")
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    result = {
        "image": args.image,
        "roi": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
        "calibration": asdict(calib),
        "axis": asdict(axis),
        "params": params,
        "diagnosis": diagnoses,
        "notes": "带 star 的参数为归一化参数；若未输入 R1/l/S，则部分真实物理量无法计算。"
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    write_markdown_report(report_path, args.image, calib, axis, params, diagnoses)
    save_visuals(out_dir, base, img, roi, roi_xy, mask, skel, df, params)

    # 控制台输出
    print("\n========== 分析完成 ==========")
    print(f"输入图像：{args.image}")
    print(f"输出目录：{out_dir}")
    print("\n--- 关键参数 ---")
    for k, v in params.items():
        if v is None:
            print(f"{k}: 未标定/未计算")
        else:
            print(f"{k}: {v:.6g}")
    print("\n--- 实验状态诊断 ---")
    for msg in diagnoses:
        print(f"- {msg}")
    print("\n--- 输出文件 ---")
    print(csv_path)
    print(json_path)
    print(report_path)
    print(os.path.join(out_dir, f"{base}_overlay_roi.png"))
    print(os.path.join(out_dir, f"{base}_loop_normalized.png"))


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="磁滞回线图像提取与参数分析工具")
    p.add_argument("image", help="输入图像路径")
    p.add_argument("--roi", default=None, help="手动裁剪区域 x1,y1,x2,y2；不填则使用整张图")
    p.add_argument("--origin", default=None, help="ROI 内坐标原点 x0,y0；不填默认 ROI 中心")
    p.add_argument("--color", default="auto", choices=["auto", "magenta", "green", "cyan", "bright"],
                   help="轨迹颜色模式，建议你们的紫红轨迹用 magenta")
    p.add_argument("--out", default="output_hysteresis", help="输出目录")
    p.add_argument("--max-width", type=int, default=1600, help="输入图像最大宽度，过大时自动缩放")

    # 示波器参数
    p.add_argument("--x-vdiv", type=float, default=1.0, help="X volts/div，单位 V/div")
    p.add_argument("--y-vdiv", type=float, default=1.0, help="Y volts/div，单位 V/div")
    p.add_argument("--x-divs", type=float, default=10.0, help="ROI 横向格数，常见为 10")
    p.add_argument("--y-divs", type=float, default=8.0, help="ROI 纵向格数，常见为 8")

    # 实验仪参数
    p.add_argument("--R1", type=float, default=None, help="励磁电流取样电阻 R1，单位 Ω")
    p.add_argument("--U", type=float, default=None, help="励磁电压档位 U，单位 V，仅记录实验条件")
    p.add_argument("--n", type=float, default=150.0, help="励磁线圈匝数 n，图示默认 150")
    p.add_argument("--N", type=float, default=50.0, help="感应线圈匝数 N，图示默认 50")
    p.add_argument("--R2", type=float, default=10000.0, help="积分电阻 R2，单位 Ω，图示默认 10000")
    p.add_argument("--C2", type=float, default=10e-6, help="积分电容 C2，单位 F，图示默认 10e-6")
    p.add_argument("--l", type=float, default=None, help="样品平均磁路长度，单位 m；输入后可计算 H")
    p.add_argument("--S", type=float, default=None, help="样品截面积，单位 m^2；输入后可计算 B")

    # 图像处理参数
    p.add_argument("--min-area", type=int, default=20, help="保留连通域的最小面积")
    p.add_argument("--max-components", type=int, default=8, help="最多保留的连通域数量")
    p.add_argument("--skeleton", action="store_true", help="保留此参数兼容；默认已使用骨架点计算")
    return p


if __name__ == "__main__":
    parser = build_argparser()
    args = parser.parse_args()
    run(args)