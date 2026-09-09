import base64
import hashlib
import html
import io
import json
import os
import re
import time

import cv2
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from openai import OpenAI
from PIL import Image, ImageDraw
from scipy.interpolate import PchipInterpolator
from scipy.signal import find_peaks
from streamlit_image_coordinates import streamlit_image_coordinates
from ai_model.unet_measurement import UNetLoopMeasurer


st.set_page_config(page_title="智眼识磁系统", layout="wide", initial_sidebar_state="expanded")
st.title("🧲 智眼识磁：磁滞回线智能分析系统")
st.markdown(
    "> **机器视觉 + AI 教学版**：图像算法负责可复核的像素测量，AI 负责证据解释和学习反馈；"
    "保留正负方向原始物理量，不强制回线中心对称。"
)


# Never commit a cloud credential.  A missing secrets.toml must not prevent the
# local U-Net measurement feature from starting.
try:
    AI_API_KEY = st.secrets.get("DASHSCOPE_API_KEY", os.getenv("DASHSCOPE_API_KEY", ""))
except Exception:
    AI_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
AI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
AI_MODEL = "qwen-vl-max"


STATE_SCHEMA_VERSION = 7
if st.session_state.get("state_schema_version") != STATE_SCHEMA_VERSION:
    for stale_key in [
        "clicks", "aux_branches", "upload_digest", "ai_measurement_meta",
        "ai_diagnostic", "student_feedback", "student_analysis_text",
        "recalibrate_index", "learning_task", "learning_submitted",
        "guidance_result", "guidance_history", "assessment_active",
        "assessment_start_time", "assessment_end_time", "assessment_adjustments",
        "assessment_result", "assessment_last_upload",
        "unet_result",
    ]:
        st.session_state.pop(stale_key, None)
    st.session_state["state_schema_version"] = STATE_SCHEMA_VERSION

STATE_DEFAULTS = {
    "clicks": [],
    "aux_branches": [],
    "img_key_counter": 0,
    "upload_digest": None,
    "ai_measurement_meta": None,
    "ai_diagnostic": None,
    "student_feedback": None,
    "recalibrate_index": None,
    "learning_task": None,
    "learning_submitted": False,
    "guidance_result": None,
    "guidance_history": [],
    "assessment_active": False,
    "assessment_start_time": None,
    "assessment_end_time": None,
    "assessment_adjustments": 0,
    "assessment_result": None,
    "assessment_last_upload": None,
    "unet_result": None,
}
for state_key, default_value in STATE_DEFAULTS.items():
    if state_key not in st.session_state:
        st.session_state[state_key] = default_value


def get_ai_client():
    if not AI_API_KEY:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY；本地 U-Net 测量仍可使用，AI 教学反馈暂不可用。")
    return OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL, timeout=45.0, max_retries=1)


@st.cache_resource(show_spinner=False)
def get_unet_measurer():
    """Cache the locally trained TensorFlow model for the whole Streamlit process."""
    return UNetLoopMeasurer()


def fixed_crop_points_to_display(point_map, original_size, display_size):
    """Map 640x600 U-Net crop points to the resized image used for clicking."""
    left, top, right, bottom = UNetLoopMeasurer.ROI
    sx = display_size[0] / original_size[0]
    sy = display_size[1] / original_size[1]
    mapped = {}
    for name, (x, y) in point_map.items():
        source_x = left + float(x) / UNetLoopMeasurer.TARGET_SIZE[0] * (right - left)
        source_y = top + float(y) / UNetLoopMeasurer.TARGET_SIZE[1] * (bottom - top)
        mapped[name] = (int(round(source_x * sx)), int(round(source_y * sy)))
    return mapped


def encode_image(pil_img):
    buffered = io.BytesIO()
    pil_img.convert("RGB").save(buffered, format="JPEG", quality=90)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")


def parse_json_object(raw_text):
    text = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError("AI 返回内容不是 JSON 对象")
    return result


CARD_COLORS = {
    "blue": ("#dbeafe", "#1e3a8a", "#2563eb"),
    "green": ("#dcfce7", "#14532d", "#16a34a"),
    "orange": ("#ffedd5", "#7c2d12", "#f97316"),
    "purple": ("#f3e8ff", "#581c87", "#9333ea"),
    "red": ("#fee2e2", "#7f1d1d", "#dc2626"),
    "gray": ("#f1f5f9", "#334155", "#64748b"),
}


def render_card(title, content, tone="blue"):
    """渲染适合实验报告的分色信息块。"""
    background, foreground, accent = CARD_COLORS.get(tone, CARD_COLORS["blue"])
    safe_title = html.escape(str(title))
    if isinstance(content, (list, tuple)):
        items = "".join(f"<li>{html.escape(str(item))}</li>" for item in content)
        safe_content = f"<ul style='margin:8px 0 0 20px'>{items}</ul>"
    else:
        safe_content = html.escape(str(content)).replace("\n", "<br>")
    st.markdown(
        f"""
        <div style="
            background:{background}; color:{foreground}; border-left:6px solid {accent};
            border-radius:12px; padding:16px 18px; margin:8px 0 14px 0;
            box-shadow:0 2px 8px rgba(15,23,42,0.08);">
            <div style="font-size:1.05rem;font-weight:750;margin-bottom:4px;">{safe_title}</div>
            <div style="line-height:1.65;">{safe_content}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def call_vision_json(pil_img, prompt):
    response = get_ai_client().chat.completions.create(
        model=AI_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{encode_image(pil_img)}"},
                    },
                ],
            }
        ],
        temperature=0.1,
    )
    return parse_json_object(response.choices[0].message.content)


def convert_ai_core_points(point_map, ordered_names, suggestion, image_width, image_height):
    """兼容模型返回像素坐标或 0~1000 归一化坐标，优先采用明确声明。"""
    raw_points = {}
    for name in ordered_names:
        if name not in point_map:
            raise ValueError(f"缺少特征点 {name}")
        xy = point_map[name]
        if not isinstance(xy, list) or len(xy) != 2:
            raise ValueError(f"特征点 {name} 坐标格式错误")
        raw_points[name] = (float(xy[0]), float(xy[1]))

    coordinate_system = str(suggestion.get("coordinate_system", "")).lower()
    seen_size = suggestion.get("image_size_seen")
    if "normal" in coordinate_system or "1000" in coordinate_system:
        mode = "normalized_1000"
    elif "pixel" in coordinate_system or "像素" in coordinate_system:
        mode = "pixel"
    else:
        # Qwen-VL 实测常返回当前输入图的像素坐标，即使提示要求归一化。
        # 只要全部坐标落在当前图像范围内，就按像素处理，避免再次缩小。
        all_inside = all(
            0 <= x <= image_width and 0 <= y <= image_height
            for x, y in raw_points.values()
        )
        mode = "pixel" if all_inside else "normalized_1000"

    converted = {}
    if mode == "normalized_1000":
        for name, (x, y) in raw_points.items():
            converted[name] = (x / 1000.0 * image_width, y / 1000.0 * image_height)
    else:
        scale_x = scale_y = 1.0
        if isinstance(seen_size, list) and len(seen_size) == 2:
            seen_w, seen_h = float(seen_size[0]), float(seen_size[1])
            if seen_w > 0 and seen_h > 0:
                scale_x, scale_y = image_width / seen_w, image_height / seen_h
        for name, (x, y) in raw_points.items():
            converted[name] = (x * scale_x, y * scale_y)

    return converted, mode


def validate_ai_core_points(points, image_width, image_height):
    """拒绝明显错误的坐标，防止模型输出未经检查就进入物理计算。"""
    errors = []
    for name, (x, y) in points.items():
        if not (0 <= x < image_width and 0 <= y < image_height):
            errors.append(f"{name} 超出图像范围")

    origin = points["origin"]
    scale = points["scale_right"]
    hc_neg, hc_pos = points["hc_negative"], points["hc_positive"]
    br_pos, br_neg = points["br_positive"], points["br_negative"]
    ext_pos, ext_neg = points["extreme_positive"], points["extreme_negative"]

    grid = scale[0] - origin[0]
    if grid <= max(8.0, image_width * 0.015) or grid >= image_width * 0.30:
        errors.append("右标尺必须位于原点右侧约一个主网格")
    if abs(scale[1] - origin[1]) > max(10.0, abs(grid) * 0.25):
        errors.append("右标尺与原点不在同一水平线上")
    if not (hc_neg[0] < origin[0] < hc_pos[0]):
        errors.append("Hc-、原点、Hc+ 的左右顺序错误")
    if abs(hc_neg[1] - origin[1]) > max(14.0, abs(grid) * 0.40) or abs(hc_pos[1] - origin[1]) > max(14.0, abs(grid) * 0.40):
        errors.append("Hc± 没有靠近 B=0 水平轴")
    if not (br_pos[1] < origin[1] < br_neg[1]):
        errors.append("Br+、原点、Br- 的上下顺序错误")
    if abs(br_pos[0] - origin[0]) > max(14.0, abs(grid) * 0.40) or abs(br_neg[0] - origin[0]) > max(14.0, abs(grid) * 0.40):
        errors.append("Br± 没有靠近 H=0 垂直轴")
    if not (ext_pos[0] > origin[0] and ext_pos[1] < origin[1]):
        errors.append("正极值不在原点右上方")
    if not (ext_neg[0] < origin[0] and ext_neg[1] > origin[1]):
        errors.append("负极值不在原点左下方")
    if (ext_pos[0] - ext_neg[0]) < image_width * 0.18 or (ext_neg[1] - ext_pos[1]) < image_height * 0.18:
        errors.append("两个极值跨度过小，疑似整体坐标缩放错误")

    return errors


def detect_core_points_cv(pil_img):
    """用机器视觉从荧光轨迹和示波器屏幕网格中提取 8 个测量点。"""
    rgb = np.asarray(pil_img.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    height, width = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(hsv)

    screen_mask = (
        (hue >= 70) & (hue <= 115) & (saturation >= 45) & (value >= 45)
    ).astype(np.uint8) * 255
    screen_mask = cv2.morphologyEx(
        screen_mask, cv2.MORPH_CLOSE, np.ones((21, 21), np.uint8)
    )
    contours, _ = cv2.findContours(screen_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("未识别到示波器蓝绿色屏幕区域")
    screen_contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(screen_contour) < width * height * 0.20:
        raise ValueError("示波器屏幕区域过小，请上传包含完整网格的正面照片")
    screen_x, screen_y, screen_w, screen_h = cv2.boundingRect(screen_contour)

    blue, green, red = cv2.split(bgr)
    trace_mask = (
        (green > 175)
        & (green.astype(np.int16) - red.astype(np.int16) > 35)
        & (green >= blue * 0.82)
    ).astype(np.uint8) * 255
    trace_mask[:screen_y, :] = 0
    trace_mask[screen_y + screen_h :, :] = 0
    trace_mask[:, :screen_x] = 0
    trace_mask[:, screen_x + screen_w :] = 0
    trace_mask = cv2.morphologyEx(
        trace_mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)
    )

    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(trace_mask)
    components = []
    for label in range(1, component_count):
        _, _, component_w, component_h, area = stats[label]
        if area > 50 and component_w > width * 0.05 and component_h > height * 0.10:
            components.append((area * (component_w + component_h), label, area, component_w, component_h))
    if not components:
        raise ValueError("未识别到连续荧光磁滞回线，请改用人工标定")
    _, best_label, trace_area, trace_w, trace_h = max(components)
    trace_mask = (labels == best_label).astype(np.uint8)

    # 从真实网格暗线序列中选择最靠近屏幕中心的主轴，避免上方反光
    # 扩大屏幕外接框后把几何中心推离实际 H=0/B=0 轴线。
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    grid_roi = gray[screen_y : screen_y + screen_h, screen_x : screen_x + screen_w]
    darkness = 255.0 - grid_roi.astype(np.float32)
    column_score = np.percentile(darkness, 70, axis=0)
    row_score = np.percentile(darkness, 70, axis=1)
    column_peaks, _ = find_peaks(
        column_score, distance=max(20, int(screen_w / 14)), prominence=5
    )
    row_peaks, _ = find_peaks(
        row_score, distance=max(20, int(screen_h / 12)), prominence=5
    )

    if len(column_peaks) >= 5:
        center_column = int(column_peaks[np.argmin(np.abs(column_peaks - screen_w / 2.0))])
    else:
        center_column = screen_w // 2
    if len(row_peaks) >= 5:
        center_row = int(row_peaks[np.argmin(np.abs(row_peaks - screen_h / 2.0))])
    else:
        center_row = screen_h // 2
    origin_x = screen_x + center_column
    origin_y = screen_y + center_row

    spacing_candidates = []
    for peaks, extent in ((column_peaks, screen_w), (row_peaks, screen_h)):
        differences = np.diff(peaks)
        differences = differences[
            (differences > extent / 20.0) & (differences < extent / 6.0)
        ]
        if len(differences):
            spacing_candidates.append(float(np.median(differences)))
    grid_size = (
        float(np.mean(spacing_candidates))
        if spacing_candidates
        else (screen_w / 10.0 + screen_h / 8.0) / 2.0
    )
    scale_right = (int(round(origin_x + grid_size)), origin_y)

    trace_ys, trace_xs = np.nonzero(trace_mask)
    band = max(5, int(round(grid_size * 0.12)))
    horizontal_xs = trace_xs[np.abs(trace_ys - origin_y) <= band]
    vertical_ys = trace_ys[np.abs(trace_xs - origin_x) <= band]
    if len(horizontal_xs) < 10:
        raise ValueError("荧光轨迹未与 B=0 水平轴形成两个清晰交点，请人工标定 Hc±")
    if len(vertical_ys) < 10:
        raise ValueError("荧光轨迹未与 H=0 垂直轴形成两个清晰交点，请人工标定 Br±")

    hc_negative_x = int(round(np.percentile(horizontal_xs, 10)))
    hc_positive_x = int(round(np.percentile(horizontal_xs, 90)))
    br_positive_y = int(round(np.percentile(vertical_ys, 10)))
    br_negative_y = int(round(np.percentile(vertical_ys, 90)))

    diagonal_score = (
        (trace_xs - origin_x) / max(screen_w, 1)
        - (trace_ys - origin_y) / max(screen_h, 1)
    )
    positive_index = int(np.argmax(diagonal_score))
    negative_index = int(np.argmin(diagonal_score))
    extreme_positive = (int(trace_xs[positive_index]), int(trace_ys[positive_index]))
    extreme_negative = (int(trace_xs[negative_index]), int(trace_ys[negative_index]))

    points = {
        "origin": (origin_x, origin_y),
        "scale_right": scale_right,
        "hc_negative": (hc_negative_x, origin_y),
        "hc_positive": (hc_positive_x, origin_y),
        "br_positive": (origin_x, br_positive_y),
        "br_negative": (origin_x, br_negative_y),
        "extreme_positive": extreme_positive,
        "extreme_negative": extreme_negative,
    }
    validation_errors = validate_ai_core_points(points, width, height)
    if validation_errors:
        raise ValueError("；".join(validation_errors))

    metadata = {
        "source": "computer_vision",
        "geometry_validation": "passed",
        "screen_roi": [screen_x, screen_y, screen_w, screen_h],
        "grid_size_px": round(grid_size, 2),
        "trace_pixels": int(trace_area),
        "trace_bbox": [int(trace_w), int(trace_h)],
        "evidence": "程序检测蓝绿色网格屏幕和连续荧光轨迹，并直接计算轴线交点与轨迹端点。",
        "warnings": ["自动点仍应由学生与原始荧光轨迹逐点核验。"],
    }
    return points, metadata


def reset_measurement_state():
    st.session_state["clicks"] = []
    st.session_state["aux_branches"] = []
    st.session_state["ai_measurement_meta"] = None
    st.session_state["ai_diagnostic"] = None
    st.session_state["student_feedback"] = None
    st.session_state["recalibrate_index"] = None
    st.session_state["learning_task"] = None
    st.session_state["learning_submitted"] = False
    st.session_state["guidance_result"] = None
    st.session_state["unet_result"] = None
    st.session_state["img_key_counter"] += 1


def average_duplicate_x(h_values, b_values):
    h_arr = np.asarray(h_values, dtype=float)
    b_arr = np.asarray(b_values, dtype=float)
    order = np.argsort(h_arr)
    h_arr, b_arr = h_arr[order], b_arr[order]
    unique_h, inverse = np.unique(h_arr, return_inverse=True)
    mean_b = np.array([b_arr[inverse == i].mean() for i in range(len(unique_h))])
    return unique_h, mean_b


def build_pchip(h_values, b_values):
    unique_h, mean_b = average_duplicate_x(h_values, b_values)
    if len(unique_h) < 2:
        return None, 0.0, 0.0
    return PchipInterpolator(unique_h, mean_b), float(unique_h.min()), float(unique_h.max())


st.sidebar.header("🧭 实验模式")
experiment_mode = st.sidebar.radio(
    "选择当前使用方式",
    ["学习模式", "指导模式", "考核模式"],
    key="experiment_mode",
)
MODE_DESCRIPTIONS = {
    "学习模式": "AI 指出现象，学生选择原因、旋钮和预期结果，提交后查看解析。",
    "指导模式": "系统检测当前状态，每次只给出一个可执行操作建议。",
    "考核模式": "不提供诊断提示，只记录调节次数、用时、回线质量、误差和得分。",
}
st.sidebar.caption(MODE_DESCRIPTIONS[experiment_mode])

assessment_ref_hc = assessment_ref_br = 0.0
assessment_target_seconds = 180
assessment_max_adjustments = 8
if experiment_mode == "考核模式":
    st.sidebar.subheader("📝 考核参数")
    assessment_ref_hc = st.sidebar.number_input(
        "标准矫顽力 |Hc| (A/m，0 表示不计误差)",
        min_value=0.0,
        value=0.0,
        step=10.0,
    )
    assessment_ref_br = st.sidebar.number_input(
        "标准剩磁 |Br| (T，0 表示不计误差)",
        min_value=0.0,
        value=0.0,
        step=0.01,
        format="%.4f",
    )
    assessment_target_seconds = st.sidebar.number_input(
        "目标完成时间 (s)", min_value=30, value=180, step=30
    )
    assessment_max_adjustments = st.sidebar.number_input(
        "建议最大调节次数", min_value=1, value=8, step=1
    )

st.sidebar.divider()
st.sidebar.header("⚙️ 实验仪参数录入")
st.sidebar.markdown("先从示波器图像测得格数/电压；只有填入真实电路标定后才换算 B-H 物理量。")

st.sidebar.subheader("🔌 示波器读取参数")
x_volts = st.sidebar.number_input("X 轴档位 Sx (V/div)", min_value=0.001, value=0.50, step=0.05)
y_volts = st.sidebar.number_input("Y 轴档位 Sy (V/div)", min_value=0.001, value=0.50, step=0.05)

physical_calibration_enabled = st.sidebar.checkbox(
    "已完成真实电路参数标定（才计算 A/m、T）", value=False,
    help="未勾选时，系统只报告可靠的格数和通道电压；不会使用旧项目的默认电路参数。",
)

if physical_calibration_enabled:
    st.sidebar.subheader("📐 已标定的实验仪硬件参数")
    R1 = st.sidebar.number_input("取样电阻 R1 (Ω)", min_value=0.001, value=1.0, step=0.5)
    N1 = st.sidebar.number_input("励磁线圈匝数 N1", min_value=1, value=50, step=10)
    L_mm = st.sidebar.number_input("磁路长度 L (mm)", min_value=0.001, value=60.0, step=1.0)
    R2 = st.sidebar.number_input("积分电阻 R2 (kΩ)", min_value=0.001, value=10.0, step=1.0)
    C_uF = st.sidebar.number_input("积分电容 C (μF)", min_value=0.001, value=10.0, step=1.0)
    N2 = st.sidebar.number_input("感应线圈匝数 N2", min_value=1, value=150, step=10)
    S_mm2 = st.sidebar.number_input("截面积 S (mm²)", min_value=0.001, value=80.0, step=1.0)
    Kx = N1 / ((L_mm / 1000.0) * R1)
    Ky = ((R2 * 1000.0) * (C_uF * 1.0e-6)) / (N2 * (S_mm2 / 1.0e6))
    st.sidebar.markdown(f"**计算系数：**\n\n- $K_x = {Kx:.2f}$ `A/(V·m)`\n- $K_y = {Ky:.3f}$ `T/V`")
else:
    Kx = Ky = 1.0
    st.sidebar.info("当前为屏幕读数模式：输出格数和 V；需填入真实电路常数后才输出 A/m、T。")
center_for_display = st.sidebar.checkbox(
    "仅在曲线显示中扣除估计中心偏移",
    value=False,
    help="原始正负物理量始终保留。只有确认偏移来自仪器零点时，才建议勾选。",
)


uploaded_file = st.file_uploader("请上传示波器图像", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    uploaded_bytes = uploaded_file.getvalue()
    file_digest = hashlib.sha256(uploaded_bytes).hexdigest()
    if st.session_state["upload_digest"] != file_digest:
        if (
            experiment_mode == "考核模式"
            and st.session_state["assessment_active"]
            and st.session_state["assessment_last_upload"] is not None
        ):
            st.session_state["assessment_adjustments"] += 1
        if experiment_mode == "考核模式" and st.session_state["assessment_active"]:
            st.session_state["assessment_last_upload"] = file_digest
        reset_measurement_state()
        st.session_state["upload_digest"] = file_digest
        st.rerun()

    try:
        original_image = Image.open(io.BytesIO(uploaded_bytes)).convert("RGB")
    except Exception as exc:
        st.error(f"图像读取失败：{exc}")
        st.stop()

    max_width = 800
    if original_image.width > max_width:
        ratio = max_width / original_image.width
        new_size = (max_width, max(1, int(original_image.height * ratio)))
        analysis_image = original_image.resize(new_size, Image.Resampling.LANCZOS)
    else:
        analysis_image = original_image.copy()

    display_image = analysis_image.copy()
    draw = ImageDraw.Draw(display_image)
    core_colors = ["white", "white", "red", "red", "blue", "blue", "purple", "purple"]
    core_labels = ["1.原点", "2.右标尺", "3.Hc-", "4.Hc+", "5.Br+", "6.Br-", "7.正极值", "8.负极值"]

    aux_branches = st.session_state["aux_branches"]
    recalibrate_index = st.session_state["recalibrate_index"]
    for i, point in enumerate(st.session_state["clicks"]):
        if i < 8 and i == recalibrate_index:
            continue
        x, y = point
        if i < 8:
            draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=core_colors[i], outline="black", width=2)
            draw.text((x + 12, y - 10), core_labels[i], fill="white")
        else:
            aux_index = i - 8
            branch = aux_branches[aux_index] if aux_index < len(aux_branches) else "未标记"
            color = "cyan" if branch == "上分支" else "orange"
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=color, outline="black", width=1)
            draw.text((x + 8, y - 8), f"{branch[0]}{aux_index + 1}", fill=color)

    clicks = st.session_state["clicks"]
    is_ready = len(clicks) >= 8 and recalibrate_index is None
    pixels_per_div = 0.0

    h_c_neg = h_c_pos = b_r_pos = b_r_neg = 0.0
    h_m_pos = h_m_neg = b_m_pos = b_m_neg = 0.0
    h_bias = b_bias = h_c_half_span = b_r_half_span = 0.0
    h_shape_asymmetry = b_shape_asymmetry = shape_asymmetry = 0.0
    h_center_offset_ratio = b_center_offset_ratio = 0.0
    shape_symmetry_status = "尚未测量"

    if is_ready:
        p_center, p_scale = clicks[0], clicks[1]
        p_hc_neg, p_hc_pos = clicks[2], clicks[3]
        p_br_pos, p_br_neg = clicks[4], clicks[5]
        p_extreme_pos, p_extreme_neg = clicks[6], clicks[7]
        pixels_per_div = abs(p_scale[0] - p_center[0])

        if pixels_per_div > 1.0:
            def point_to_physical(point):
                px, py = point
                h_value = (px - p_center[0]) / pixels_per_div * x_volts * Kx
                b_value = (p_center[1] - py) / pixels_per_div * y_volts * Ky
                return float(h_value), float(b_value)

            h_c_neg = point_to_physical(p_hc_neg)[0]
            h_c_pos = point_to_physical(p_hc_pos)[0]
            b_r_pos = point_to_physical(p_br_pos)[1]
            b_r_neg = point_to_physical(p_br_neg)[1]
            h_m_pos, b_m_pos = point_to_physical(p_extreme_pos)
            h_m_neg, b_m_neg = point_to_physical(p_extreme_neg)
            h_bias = (h_c_pos + h_c_neg) / 2.0
            b_bias = (b_r_pos + b_r_neg) / 2.0
            h_c_half_span = (h_c_pos - h_c_neg) / 2.0
            b_r_half_span = (b_r_pos - b_r_neg) / 2.0

            # 严格区分“曲线中心相对坐标原点的平移”和“扣除平移后的形状不对称”。
            h_positive_centered = abs(h_m_pos - h_bias)
            h_negative_centered = abs(h_m_neg - h_bias)
            b_positive_centered = abs(b_m_pos - b_bias)
            b_negative_centered = abs(b_m_neg - b_bias)
            h_shape_asymmetry = abs(h_positive_centered - h_negative_centered) / max(
                (h_positive_centered + h_negative_centered) / 2.0, 1e-12
            )
            b_shape_asymmetry = abs(b_positive_centered - b_negative_centered) / max(
                (b_positive_centered + b_negative_centered) / 2.0, 1e-12
            )
            shape_asymmetry = max(h_shape_asymmetry, b_shape_asymmetry)
            h_center_offset_ratio = abs(h_bias) / max(abs(h_c_half_span), 1e-12)
            b_center_offset_ratio = abs(b_bias) / max(abs(b_r_half_span), 1e-12)
            if shape_asymmetry <= 0.15:
                shape_symmetry_status = "扣除中心平移后，回线形状近似中心对称"
            elif shape_asymmetry <= 0.30:
                shape_symmetry_status = "扣除中心平移后，回线形状存在轻度不对称"
            else:
                shape_symmetry_status = "扣除中心平移后，回线形状存在明显不对称"

    st.divider()
    tab1, tab2, tab3 = st.tabs(
        ["📷 1. 机器视觉/人工协同标定", "📈 2. B-H 结果图", "📉 3. 无量纲归一化图"]
    )

    with tab1:
        st.info(
            "机器视觉会直接检测荧光轨迹和网格，计算 8 个核心点：原点、右侧一格标尺、Hc-、Hc+、Br+、Br-、正极值、负极值。"
            "检测不可靠时会拒绝输出并要求人工标定；第 8 点后添加辅助点时需明确选择上下分支。"
        )

        ai_col, branch_col = st.columns([1, 1])
        with ai_col:
            if st.button("🤖 已训练 U-Net 自动标定（推荐）", use_container_width=True):
                with st.spinner("正在运行本地 TensorFlow U-Net，分割磁滞回线..."):
                    try:
                        result = get_unet_measurer().analyse(original_image)
                        point_map = fixed_crop_points_to_display(
                            result["points_in_crop"], original_image.size, analysis_image.size
                        )
                        ordered_names = [
                            "origin", "scale_right", "hc_negative", "hc_positive",
                            "br_positive", "br_negative", "extreme_positive", "extreme_negative",
                        ]
                        st.session_state["clicks"] = [point_map[name] for name in ordered_names]
                        st.session_state["aux_branches"] = []
                        st.session_state["recalibrate_index"] = None
                        st.session_state["unet_result"] = result
                        st.session_state["ai_measurement_meta"] = {
                            "source": "trained_unet",
                            "geometry_validation": "fixed-grid",
                            "trace_pixels": result["trace_pixels"],
                            "grid_size_px": result["grid_size_px"],
                            "confidence": result["mean_probability_on_trace"],
                            "warnings": ["AI 结果应与原始荧光轨迹复核；图片须来自固定相机与示波器位置。"],
                        }
                        st.session_state["ai_diagnostic"] = None
                        st.session_state["student_feedback"] = None
                        st.session_state["img_key_counter"] += 1
                        st.rerun()
                    except Exception as exc:
                        st.error(f"U-Net 自动标定失败：{exc}。可使用传统视觉或人工标定。")
            if st.button("🎯 传统视觉自动标定（回退）", use_container_width=True):
                with st.spinner("正在检测示波器屏幕、网格和荧光磁滞回线..."):
                    try:
                        point_map, suggestion = detect_core_points_cv(analysis_image)
                        ordered_names = [
                            "origin", "scale_right", "hc_negative", "hc_positive",
                            "br_positive", "br_negative", "extreme_positive", "extreme_negative",
                        ]
                        converted = [point_map[name] for name in ordered_names]

                        st.session_state["clicks"] = converted
                        st.session_state["aux_branches"] = []
                        st.session_state["recalibrate_index"] = None
                        st.session_state["unet_result"] = None
                        st.session_state["ai_measurement_meta"] = suggestion
                        st.session_state["ai_diagnostic"] = None
                        st.session_state["student_feedback"] = None
                        st.session_state["img_key_counter"] += 1
                        st.rerun()
                    except Exception as exc:
                        st.error(f"机器视觉自动标定失败：{exc}。请使用人工标定。")

        with branch_col:
            aux_branch_choice = st.radio(
                "第 8 点后的辅助点归属",
                ["上分支", "下分支"],
                horizontal=True,
                help="蓝绿色为上分支，橙色为下分支；不再使用对角线自动猜测。",
            )

        meta = st.session_state.get("ai_measurement_meta")
        if meta:
            if meta.get("source") == "trained_unet":
                st.success(
                    f"U-Net 语义分割完成；轨迹像素：{meta.get('trace_pixels', 0)}；"
                    f"掩膜内平均置信度：{meta.get('confidence', 0):.3f}。"
                )
                st.image(st.session_state["unet_result"]["overlay"], caption="蓝色：已训练 U-Net 识别出的磁滞回线")
                st.caption("标记说明：紫色为正、负饱和端点（右上/左下）；红色为 Hc−、Hc+；蓝色为 Br+、Br−；白色为原点与一格标尺。")
            st.success(
                f"机器视觉几何校验：通过；检测轨迹像素：{meta.get('trace_pixels', 0)}；"
                f"估计网格：{meta.get('grid_size_px', 0):.1f} px/div。"
            )
            if meta.get("evidence"):
                st.caption(f"识别依据：{meta['evidence']}")
            for warning in meta.get("warnings", []):
                st.caption(f"注意：{warning}")

        col_img, col_btn = st.columns([2, 1])
        with col_img:
            current_key = f"pil_fixed_{st.session_state['img_key_counter']}"
            value = streamlit_image_coordinates(display_image, key=current_key)
            if value is not None:
                point = (value["x"], value["y"])
                if recalibrate_index is not None:
                    st.session_state["clicks"][recalibrate_index] = point
                    st.session_state["recalibrate_index"] = None
                    st.session_state["ai_diagnostic"] = None
                    st.session_state["student_feedback"] = None
                    st.session_state["learning_task"] = None
                    st.session_state["guidance_result"] = None
                    st.session_state["img_key_counter"] += 1
                    st.rerun()
                elif not clicks or clicks[-1] != point:
                    if len(clicks) >= 8:
                        st.session_state["aux_branches"].append(aux_branch_choice)
                    st.session_state["clicks"].append(point)
                    st.session_state["ai_diagnostic"] = None
                    st.session_state["student_feedback"] = None
                    st.rerun()

        with col_btn:
            if len(st.session_state["clicks"]) >= 8:
                selected_core_index = st.selectbox(
                    "指定要重新标定的核心点",
                    options=list(range(8)),
                    format_func=lambda index: core_labels[index],
                    key="selected_core_recalibration",
                )
                if st.button("🎯 删除并重新标定此点", use_container_width=True):
                    st.session_state["recalibrate_index"] = selected_core_index
                    st.session_state["ai_diagnostic"] = None
                    st.session_state["student_feedback"] = None
                    st.session_state["learning_task"] = None
                    st.session_state["guidance_result"] = None
                    st.session_state["img_key_counter"] += 1
                    st.rerun()

            if recalibrate_index is not None:
                st.warning(f"请在图像上重新点击：{core_labels[recalibrate_index]}")
                if st.button("取消本次单点重标", use_container_width=True):
                    st.session_state["recalibrate_index"] = None
                    st.session_state["img_key_counter"] += 1
                    st.rerun()

            if st.button("⏪ 撤销上一步", use_container_width=True):
                if st.session_state["recalibrate_index"] is not None:
                    st.session_state["recalibrate_index"] = None
                    st.session_state["img_key_counter"] += 1
                    st.rerun()
                elif st.session_state["clicks"]:
                    if len(st.session_state["clicks"]) > 8 and st.session_state["aux_branches"]:
                        st.session_state["aux_branches"].pop()
                    st.session_state["clicks"].pop()
                    st.session_state["ai_diagnostic"] = None
                    st.session_state["student_feedback"] = None
                    st.session_state["img_key_counter"] += 1
                    st.rerun()

            if st.button("🔄 清空所有点", use_container_width=True):
                reset_measurement_state()
                st.rerun()

            if is_ready and pixels_per_div > 1.0:
                st.success("核心标定完成，请检查正负符号和机器视觉标定点。")
                st.metric("网格像素比", f"{pixels_per_div:.1f} px/div")
                measurement_source = "机器视觉标定后人工复核" if meta else "人工标定"
                st.metric("测量方式", measurement_source)
            elif is_ready:
                st.error("标尺点与原点过近，请撤销并重新标定右侧一格标尺。")

    def plot_loop(normalized=False):
        h_offset = h_bias if center_for_display else 0.0
        b_offset = b_bias if center_for_display else 0.0
        h_scale = max(abs(h_m_neg - h_offset), abs(h_m_pos - h_offset), 1e-12) if normalized else 1.0
        b_scale = max(abs(b_m_neg - b_offset), abs(b_m_pos - b_offset), 1e-12) if normalized else 1.0

        def transform(h_value, b_value):
            return (h_value - h_offset) / h_scale, (b_value - b_offset) / b_scale

        upper_raw = [(h_m_neg, b_m_neg), (h_c_neg, 0.0), (0.0, b_r_pos), (h_m_pos, b_m_pos)]
        lower_raw = [(h_m_neg, b_m_neg), (0.0, b_r_neg), (h_c_pos, 0.0), (h_m_pos, b_m_pos)]
        upper = [transform(h, b) for h, b in upper_raw]
        lower = [transform(h, b) for h, b in lower_raw]

        aux_upper, aux_lower = [], []
        for point, branch in zip(clicks[8:], st.session_state["aux_branches"]):
            h_value, b_value = point_to_physical(point)
            transformed = transform(h_value, b_value)
            (aux_upper if branch == "上分支" else aux_lower).append(transformed)
        upper.extend(aux_upper)
        lower.extend(aux_lower)

        upper_h, upper_b = zip(*upper)
        lower_h, lower_b = zip(*lower)
        pchip_up, min_h_up, max_h_up = build_pchip(upper_h, upper_b)
        pchip_dn, min_h_dn, max_h_dn = build_pchip(lower_h, lower_b)

        fig = go.Figure()
        if pchip_up is not None:
            x_up = np.linspace(min_h_up, max_h_up, 240)
            fig.add_trace(go.Scatter(x=x_up, y=pchip_up(x_up), mode="lines", line=dict(color="#00a878", width=3), name="上分支"))
        if pchip_dn is not None:
            x_dn = np.linspace(min_h_dn, max_h_dn, 240)
            fig.add_trace(go.Scatter(x=x_dn, y=pchip_dn(x_dn), mode="lines", line=dict(color="#f28e2b", width=3), name="下分支"))

        core_points = [transform(h, b) for h, b in [
            (h_c_neg, 0.0), (h_c_pos, 0.0), (0.0, b_r_pos), (0.0, b_r_neg),
            (h_m_pos, b_m_pos), (h_m_neg, b_m_neg),
        ]]
        fig.add_trace(go.Scatter(
            x=[p[0] for p in core_points], y=[p[1] for p in core_points], mode="markers",
            marker=dict(size=10, color="gold", line=dict(width=2, color="black")), name="实测特征点",
        ))
        if aux_upper:
            fig.add_trace(go.Scatter(x=[p[0] for p in aux_upper], y=[p[1] for p in aux_upper], mode="markers", marker=dict(color="cyan", symbol="cross", size=9), name="上分支辅助点"))
        if aux_lower:
            fig.add_trace(go.Scatter(x=[p[0] for p in aux_lower], y=[p[1] for p in aux_lower], mode="markers", marker=dict(color="orange", symbol="cross", size=9), name="下分支辅助点"))

        unit_h, unit_b = ("H/Hm", "B/Bm") if normalized else (("H (A/m)", "B (T)") if physical_calibration_enabled else ("X channel (V)", "Y channel (V)"))
        title = "无量纲磁滞回线" if normalized else ("保留正负方向的 B-H 磁滞回线" if physical_calibration_enabled else "示波器通道电压回线（未使用旧默认电路参数）")
        if center_for_display:
            title += "（仅显示时扣除估计中心偏移）"
        fig.update_layout(
            title=title, xaxis_title=unit_h, yaxis_title=unit_b, hovermode="closest", height=520,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(zeroline=True, zerolinewidth=1), yaxis=dict(zeroline=True, zerolinewidth=1),
        )
        return fig

    with tab2:
        assessment_locked = (
            experiment_mode == "考核模式"
            and st.session_state["assessment_active"]
            and st.session_state["assessment_result"] is None
        )
        if assessment_locked:
            st.info("考核进行中，B-H 数值与曲线将在提交考核后显示。")
        elif is_ready and pixels_per_div > 1.0:
            st.plotly_chart(plot_loop(normalized=False), use_container_width=True)
            metric_cols = st.columns(4)
            h_unit, b_unit = ("A/m", "T") if physical_calibration_enabled else ("V", "V")
            metric_cols[0].metric("Hc-", f"{h_c_neg:.2f} {h_unit}")
            metric_cols[1].metric("Hc+", f"{h_c_pos:.2f} {h_unit}")
            metric_cols[2].metric("Br+", f"{b_r_pos:.4f} {b_unit}")
            metric_cols[3].metric("Br-", f"{b_r_neg:.4f} {b_unit}")
            st.caption(
                f"估计水平中心偏移 H_bias={h_bias:.2f} {h_unit}；垂直中心偏移 B_bias={b_bias:.4f} {b_unit}。"
                "这些量不会被自动删除，可用于判断仪器零偏或真实物理不对称。"
            )
        else:
            st.info("请先完成 8 个核心点标定。")

    with tab3:
        if assessment_locked:
            st.info("考核进行中，归一化结果将在提交考核后显示。")
        elif is_ready and pixels_per_div > 1.0:
            st.plotly_chart(plot_loop(normalized=True), use_container_width=True)
            st.caption("此图使用 H/Hm 与 B/Bm，为真正的无量纲归一化；示波器电压不再称为归一化参数。")
        else:
            st.info("请先完成 8 个核心点标定。")

    measurement_ready = is_ready and pixels_per_div > 1.0
    measurement_payload = {}
    table_data = None
    if measurement_ready:
        measurement_payload = {
            "Hc_negative_A_per_m": h_c_neg,
            "Hc_positive_A_per_m": h_c_pos,
            "Br_positive_T": b_r_pos,
            "Br_negative_T": b_r_neg,
            "Hm_positive_A_per_m": h_m_pos,
            "Hm_negative_A_per_m": h_m_neg,
            "Bm_positive_T": b_m_pos,
            "Bm_negative_T": b_m_neg,
            "estimated_H_bias_A_per_m": h_bias,
            "estimated_B_bias_T": b_bias,
            "shape_symmetry_status": shape_symmetry_status,
            "H_endpoint_asymmetry_after_centering": h_shape_asymmetry,
            "B_endpoint_asymmetry_after_centering": b_shape_asymmetry,
            "H_center_offset_ratio": h_center_offset_ratio,
            "B_center_offset_ratio": b_center_offset_ratio,
        }
        table_data = {
            "测量节点": ["Hc-", "Hc+", "Br+", "Br-", "正极值", "负极值", "半宽/半高", "中心偏移"],
            "H (A/m)": [
                f"{h_c_neg:.2f}", f"{h_c_pos:.2f}", "0.00", "0.00",
                f"{h_m_pos:.2f}", f"{h_m_neg:.2f}", f"{h_c_half_span:.2f}", f"{h_bias:.2f}",
            ],
            "B (T)": [
                "0.0000", "0.0000", f"{b_r_pos:.4f}", f"{b_r_neg:.4f}",
                f"{b_m_pos:.4f}", f"{b_m_neg:.4f}", f"{b_r_half_span:.4f}", f"{b_bias:.4f}",
            ],
        }

    st.divider()

    if experiment_mode == "学习模式":
        st.header("🎓 学习模式：观察—判断—反馈")
        if not measurement_ready:
            render_card("等待测量", "完成 8 个核心点标定后，AI 才会生成针对当前现象的选择题。", "gray")
        else:
            st.table(pd.DataFrame(table_data))
            if st.button("🤖 AI 识别现象并生成学习任务", type="primary", use_container_width=True):
                with st.spinner("AI 正在把当前实验现象转化为学习任务..."):
                    try:
                        learning_prompt = f"""
你是大学物理实验教师。根据磁滞回线图像和测量数据：
{json.dumps(measurement_payload, ensure_ascii=False)}
生成一道三部分选择题，训练学生判断实验操作。严格返回 JSON：
{{
  "phenomenon": "只描述观察到的现象，不泄露原因和答案",
  "cause_options": ["原因A", "原因B", "原因C", "原因D"],
  "knob_options": ["应调节的旋钮或操作A", "操作B", "操作C", "操作D"],
  "result_options": ["预期结果A", "预期结果B", "预期结果C", "预期结果D"],
  "correct_cause": "必须与 cause_options 中某项完全一致",
  "correct_knob": "必须与 knob_options 中某项完全一致",
  "correct_result": "必须与 result_options 中某项完全一致",
  "analysis": "提交后显示的正确物理分析，解释现象、操作和结果之间的因果链",
  "evidence": ["支持现象判断的图像或数据证据"]
}}
必须区分回线中心偏移与形状不对称，不得把 H_bias/B_bias 非零直接说成形状不对称。
"""
                        task = call_vision_json(analysis_image, learning_prompt)
                        for option_key, answer_key in [
                            ("cause_options", "correct_cause"),
                            ("knob_options", "correct_knob"),
                            ("result_options", "correct_result"),
                        ]:
                            options = task.get(option_key, [])
                            if len(options) < 2 or task.get(answer_key) not in options:
                                raise ValueError(f"AI 返回的 {option_key} 或正确答案无效")
                        st.session_state["learning_task"] = task
                        st.session_state["learning_submitted"] = False
                        for key in ["learning_cause", "learning_knob", "learning_result"]:
                            st.session_state.pop(key, None)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"学习任务生成失败：{exc}")

            learning_task = st.session_state.get("learning_task")
            if learning_task:
                render_card("观察到的实验现象", learning_task.get("phenomenon", "未给出"), "blue")
                cause_choice = st.radio(
                    "① 最可能的原因",
                    learning_task["cause_options"],
                    key="learning_cause",
                )
                knob_choice = st.radio(
                    "② 应调节的旋钮或操作",
                    learning_task["knob_options"],
                    key="learning_knob",
                )
                result_choice = st.radio(
                    "③ 调节后的预期结果",
                    learning_task["result_options"],
                    key="learning_result",
                )
                if st.button("提交学习作答", use_container_width=True):
                    st.session_state["learning_submitted"] = True

                if st.session_state["learning_submitted"]:
                    checks = [
                        cause_choice == learning_task["correct_cause"],
                        knob_choice == learning_task["correct_knob"],
                        result_choice == learning_task["correct_result"],
                    ]
                    score = sum(checks)
                    render_card(
                        f"作答结果：{score}/3",
                        [
                            f"可能原因：{'正确' if checks[0] else '错误'}",
                            f"旋钮或操作：{'正确' if checks[1] else '错误'}",
                            f"预期结果：{'正确' if checks[2] else '错误'}",
                        ],
                        "green" if score == 3 else "orange",
                    )
                    render_card(
                        "正确选项",
                        [
                            f"原因：{learning_task['correct_cause']}",
                            f"操作：{learning_task['correct_knob']}",
                            f"预期：{learning_task['correct_result']}",
                        ],
                        "purple",
                    )
                    render_card("物理分析", learning_task.get("analysis", "未给出"), "blue")
                    render_card("判断证据", learning_task.get("evidence", []), "gray")

    elif experiment_mode == "指导模式":
        st.header("🧭 指导模式：一次只执行一个建议")
        if not measurement_ready:
            render_card("等待检测", "完成核心点标定后，系统将检测当前实验状态。", "gray")
        else:
            st.table(pd.DataFrame(table_data))
            if st.button("🔍 检测状态并给出下一条操作", type="primary", use_container_width=True):
                with st.spinner("系统正在生成一条最优先的操作建议..."):
                    try:
                        guidance_prompt = f"""
你是大学物理实验现场指导教师。根据当前磁滞回线图像和测量值：
{json.dumps(measurement_payload, ensure_ascii=False)}
每次只能给出一个最优先、可直接执行的操作，不得罗列多个步骤。严格返回 JSON：
{{
  "experiment_status": "当前状态的简短判断",
  "single_action": "本次只执行的一个动作，明确旋钮、方向或检查对象",
  "expected_change": "执行后图像应发生的可观察变化",
  "completion_check": "学生如何判断该动作已完成",
  "reason": "为什么当前优先做这一步",
  "confidence": 0.0
}}
必须区分中心偏移与形状不对称；若回线已经合格，应建议保持参数并进入测量，而不是继续无意义调节。
"""
                        result = call_vision_json(analysis_image, guidance_prompt)
                        st.session_state["guidance_result"] = result
                        st.session_state["guidance_history"].append(result)
                    except Exception as exc:
                        st.error(f"指导建议生成失败：{exc}")

            guidance = st.session_state.get("guidance_result")
            if guidance:
                render_card("当前实验状态", guidance.get("experiment_status", "未给出"), "blue")
                render_card("本次唯一操作", guidance.get("single_action", "未给出"), "orange")
                two_cols = st.columns(2)
                with two_cols[0]:
                    render_card("预期变化", guidance.get("expected_change", "未给出"), "green")
                with two_cols[1]:
                    render_card("完成判据", guidance.get("completion_check", "未给出"), "purple")
                render_card("优先执行原因", guidance.get("reason", "未给出"), "gray")
                st.caption(f"AI 置信度：{float(guidance.get('confidence', 0.0)):.0%}")
            if st.session_state["guidance_history"]:
                with st.expander(f"查看历史指导记录（{len(st.session_state['guidance_history'])} 条）"):
                    for index, item in enumerate(st.session_state["guidance_history"], start=1):
                        st.markdown(f"**第 {index} 条：** {item.get('single_action', '未给出')}")

    else:
        st.header("🧪 考核模式")
        if not st.session_state["assessment_active"] and st.session_state["assessment_result"] is None:
            render_card(
                "考核规则",
                "开始后系统不提供状态诊断和操作建议，只记录操作次数、完成时间、回线质量与测量误差。",
                "gray",
            )
            if st.button("▶️ 开始考核", type="primary", use_container_width=True):
                st.session_state["assessment_active"] = True
                st.session_state["assessment_start_time"] = time.time()
                st.session_state["assessment_end_time"] = None
                st.session_state["assessment_adjustments"] = 0
                st.session_state["assessment_result"] = None
                st.session_state["assessment_last_upload"] = (
                    st.session_state["upload_digest"] if uploaded_file is not None else None
                )
                st.rerun()

        if st.session_state["assessment_active"]:
            elapsed_seconds = max(0.0, time.time() - st.session_state["assessment_start_time"])
            metric_cols = st.columns(3)
            metric_cols[0].metric("已用时间", f"{elapsed_seconds:.1f} s")
            metric_cols[1].metric("调节次数", st.session_state["assessment_adjustments"])
            metric_cols[2].metric("测量状态", "已完成" if measurement_ready else "未完成")
            if st.button("记录一次旋钮调节", use_container_width=True):
                st.session_state["assessment_adjustments"] += 1
                st.rerun()

            if measurement_ready:
                if st.button("⏹️ 提交考核", type="primary", use_container_width=True):
                    end_time = time.time()
                    elapsed_seconds = max(1.0, end_time - st.session_state["assessment_start_time"])
                    qualified = (
                        shape_asymmetry <= 0.25
                        and h_center_offset_ratio <= 0.40
                        and b_center_offset_ratio <= 0.40
                        and abs(h_c_half_span) > 0
                        and abs(b_r_half_span) > 0
                    )
                    relative_errors = []
                    if assessment_ref_hc > 0:
                        relative_errors.append(abs(abs(h_c_half_span) - assessment_ref_hc) / assessment_ref_hc)
                    if assessment_ref_br > 0:
                        relative_errors.append(abs(abs(b_r_half_span) - assessment_ref_br) / assessment_ref_br)
                    mean_error = float(np.mean(relative_errors)) if relative_errors else None

                    earned = 40.0 if qualified else 0.0
                    available = 40.0
                    time_score = 15.0 * min(1.0, assessment_target_seconds / elapsed_seconds)
                    adjustment_score = 10.0 * max(
                        0.0,
                        1.0 - st.session_state["assessment_adjustments"] / assessment_max_adjustments,
                    )
                    earned += time_score + adjustment_score
                    available += 25.0
                    accuracy_score = None
                    if mean_error is not None:
                        accuracy_score = 35.0 * max(0.0, 1.0 - mean_error)
                        earned += accuracy_score
                        available += 35.0
                    final_score = 100.0 * earned / available
                    result = {
                        "elapsed_seconds": elapsed_seconds,
                        "adjustments": st.session_state["assessment_adjustments"],
                        "qualified": qualified,
                        "measurement_error": mean_error,
                        "quality_score": 40.0 if qualified else 0.0,
                        "accuracy_score": accuracy_score,
                        "time_score": time_score,
                        "adjustment_score": adjustment_score,
                        "final_score": final_score,
                    }
                    st.session_state["assessment_result"] = result
                    st.session_state["assessment_end_time"] = end_time
                    st.session_state["assessment_active"] = False
                    st.rerun()
            else:
                st.caption("完成图像采集和核心点标定后才能提交考核。")

        assessment_result = st.session_state.get("assessment_result")
        if assessment_result:
            status_text = "获得合格回线" if assessment_result["qualified"] else "未获得合格回线"
            render_card("考核结论", status_text, "green" if assessment_result["qualified"] else "red")
            score_cols = st.columns(4)
            score_cols[0].metric("最终得分", f"{assessment_result['final_score']:.1f}")
            score_cols[1].metric("操作时间", f"{assessment_result['elapsed_seconds']:.1f} s")
            score_cols[2].metric("调节次数", assessment_result["adjustments"])
            error_text = (
                f"{assessment_result['measurement_error']:.2%}"
                if assessment_result["measurement_error"] is not None
                else "未设置标准值"
            )
            score_cols[3].metric("平均测量误差", error_text)
            score_table = {
                "评分项目": ["回线质量", "测量精度", "完成时间", "调节次数"],
                "得分": [
                    f"{assessment_result['quality_score']:.1f}/40",
                    (
                        f"{assessment_result['accuracy_score']:.1f}/35"
                        if assessment_result["accuracy_score"] is not None
                        else "未纳入"
                    ),
                    f"{assessment_result['time_score']:.1f}/15",
                    f"{assessment_result['adjustment_score']:.1f}/10",
                ],
            }
            st.table(pd.DataFrame(score_table))
            if measurement_ready:
                st.plotly_chart(
                    plot_loop(normalized=False),
                    use_container_width=True,
                    key="assessment_result_plot",
                )
                st.table(pd.DataFrame(table_data))
            if st.button("重新开始考核", use_container_width=True):
                st.session_state["assessment_result"] = None
                st.session_state["assessment_adjustments"] = 0
                st.session_state["assessment_start_time"] = None
                st.session_state["assessment_end_time"] = None
                st.rerun()

else:
    st.info("上传示波器图片后，可使用机器视觉自动标定或完全人工标定；自动结果始终允许人工复核与修正。")

