import streamlit as st
from PIL import Image, ImageDraw
from streamlit_image_coordinates import streamlit_image_coordinates
import json
import base64
import io
import os
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy.interpolate import PchipInterpolator
from openai import OpenAI

# ================= 1. 页面基本设置 =================
st.set_page_config(page_title="智眼识磁系统", layout="wide", initial_sidebar_state="expanded")

st.title("🧲 智眼识磁：磁滞回线智能分析系统")
st.markdown("> **高精度 PCHIP 拟合模式**：支持 8 点核心物理标定，并开放无限量辅助轮廓点，完美还原真实陡峭磁化曲线。")

# ================= 2. 状态管理 =================
if 'clicks' not in st.session_state:
    st.session_state['clicks'] = []
if 'img_key_counter' not in st.session_state:
    st.session_state['img_key_counter'] = 0

def encode_image(pil_img):
    buffered = io.BytesIO()
    pil_img.convert('RGB').save(buffered, format="JPEG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

# ================= 3. 侧边栏：参数输入 =================
st.sidebar.header("⚙️ 实验参数设置")

calc_mode = st.sidebar.radio("📊 数据分析模式", ["真实物理量模式", "归一化模式 (仅看趋势)"])

st.sidebar.markdown("---")
st.sidebar.subheader("🔌 示波器读取参数")
x_volts = st.sidebar.number_input("X 轴档位 Sx (V/div)", value=0.20, step=0.05) 
y_volts = st.sidebar.number_input("Y 轴档位 Sy (V/div)", value=0.05, step=0.01) 

st.sidebar.subheader("📐 实验仪硬件参数")
R1 = st.sidebar.number_input("取样电阻 R1 (Ω)", value=1.0, step=0.5)

if calc_mode == "真实物理量模式":
    N1 = st.sidebar.number_input("励磁线圈匝数 N1", value=50, step=10)
    L_mm = st.sidebar.number_input("磁路长度 L (mm)", value=60.0, step=1.0)
    R2 = st.sidebar.number_input("积分电阻 R2 (kΩ)", value=10.0, step=1.0)
    C_uF = st.sidebar.number_input("积分电容 C (μF)", value=10.0, step=1.0)
    N2 = st.sidebar.number_input("感应线圈匝数 N2", value=150, step=10)
    S_mm2 = st.sidebar.number_input("截面积 S (mm²)", value=80.0, step=1.0)
    
    L_m = L_mm / 1000.0
    S_m2 = S_mm2 / 1.0e6
    R2_ohm = R2 * 1000.0
    C_F = C_uF * 1.0e-6
    
    Kx = N1 / (L_m * R1)
    Ky = (R2_ohm * C_F) / (N2 * S_m2)
    
    st.sidebar.markdown(f"**计算系数：**\n*   $K_x = {Kx:.2f}$ `A/(V·m)`\n*   $K_y = {Ky:.3f}$ `T/V`")
else:
    Kx = 1.0
    Ky = 1.0

# ================= 4. 主页面：图像上传与标定 =================
uploaded_file = st.file_uploader("请上传示波器图像", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    original_image = Image.open(uploaded_file)
    max_width = 800
    if original_image.width > max_width:
        ratio = max_width / original_image.width
        new_size = (max_width, int(original_image.height * ratio))
        display_image = original_image.resize(new_size)
    else:
        display_image = original_image.copy()

    draw = ImageDraw.Draw(display_image)
    core_colors = ["white", "white", "red", "red", "blue", "blue", "purple", "purple"]
    core_labels = ["1.原点", "2.标尺", "3.左X", "4.右X", "5.上Y", "6.下Y", "7.右上点", "8.左下点"]
    
    for i, point in enumerate(st.session_state['clicks']):
        x, y = point
        if i < 8:
            # 前8个核心物理锚点
            draw.ellipse((x-6, y-6, x+6, y+6), fill=core_colors[i], outline="black", width=2)
            draw.text((x+12, y-10), core_labels[i], fill="white")
        else:
            # 无限制轮廓辅助点
            draw.ellipse((x-4, y-4, x+4, y+4), fill="cyan", outline="black", width=1)
            draw.text((x+8, y-8), f"辅{i-7}", fill="cyan")

    st.info("🎯 **第一阶段（核心 8 点）**：1.原点 ➔ 2.右标尺 ➔ 3.左X ➔ 4.右X ➔ 5.上Y ➔ 6.下Y ➔ 7.右上极值 ➔ 8.左下极值\n\n"
            "✨ **第二阶段（无限制辅助点）**：8 点完成后，您可以在曲线的陡峭处或转折处继续点击**任意数量**的辅助点，以完美贴合真实形状。")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        current_key = f"pil_{st.session_state['img_key_counter']}"
        value = streamlit_image_coordinates(display_image, key=current_key)
        
        if value is not None:
            point = (value['x'], value['y'])
            if not st.session_state['clicks'] or st.session_state['clicks'][-1] != point:
                st.session_state['clicks'].append(point)
                st.rerun() 
        
        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button("⏪ 撤销上一步", use_container_width=True):
                if st.session_state['clicks']:
                    st.session_state['clicks'].pop()
                    st.session_state['img_key_counter'] += 1 
                    st.rerun()
        with btn_col2:
            if st.button("🔄 清空所有点", use_container_width=True):
                st.session_state['clicks'] = []
                st.session_state['img_key_counter'] += 1 
                st.rerun()

    with col2:
        st.subheader("📊 实时计算面板")
        clicks = st.session_state['clicks']
        
        if len(clicks) < 8:
            st.warning(f"核心标定中: {len(clicks)}/8 个关键点...")
        else:
            st.success(f"🎉 核心标定完成！当前已添加 {len(clicks)-8} 个辅助轮廓点。")
            
            p_center, p_scale = clicks[0], clicks[1]
            p_x_left, p_x_right = clicks[2], clicks[3]
            p_y_top, p_y_bottom = clicks[4], clicks[5]
            p_vertex_tr, p_vertex_bl = clicks[6], clicks[7]
            
            pixels_per_div = abs(p_scale[0] - p_center[0])
            
            if pixels_per_div == 0:
                st.error("标尺点不能与原点重合！")
            else:
                div_Hc = (abs(p_x_right[0] - p_x_left[0]) / 2) / pixels_per_div
                div_Br = (abs(p_y_bottom[1] - p_y_top[1]) / 2) / pixels_per_div
                div_Hm = (abs(p_vertex_tr[0] - p_vertex_bl[0]) / 2) / pixels_per_div
                div_Bm = (abs(p_vertex_bl[1] - p_vertex_tr[1]) / 2) / pixels_per_div
                
                Hc_val = div_Hc * x_volts * Kx
                Br_val = div_Br * y_volts * Ky
                Hm_val = div_Hm * x_volts * Kx
                Bm_val = div_Bm * y_volts * Ky
                
                st.markdown(f"### 🎯 {'物理量提取结果' if calc_mode == '真实物理量模式' else '归一化提取结果'}")
                st.markdown(f"- **网格比例**: `{pixels_per_div:.1f}` 像素/div")
                
                if calc_mode == "真实物理量模式":
                    st.markdown(f"- **矫顽力 ($H_c$)**: `{Hc_val:.2f}` A/m")
                    st.markdown(f"- **剩磁 ($B_r$)**: `{Br_val:.4f}` T")
                    st.markdown(f"- **最大磁场 ($H_m$)**: `{Hm_val:.2f}` A/m")
                else:
                    st.markdown(f"- **归一化矫顽力 ($H_c^*$)**: `{Hc_val:.3f}` V")
                    st.markdown(f"- **归一化剩磁 ($B_r^*$)**: `{Br_val:.3f}` V")
                    st.markdown(f"- **最大磁场 ($H_m^*$)**: `{Hm_val:.3f}` V")
                
                st.divider()
                analyze_button = st.button("🧠 应用 PCHIP 算法生成报告", type="primary", use_container_width=True)

    # ================= 5. 下半部分：沉浸式报告与数据表 =================
    if len(clicks) >= 8 and pixels_per_div != 0 and analyze_button:
        st.divider()
        st.header("📑 智能实验报告 (自动生成)")
        
        unit_H = "A/m" if calc_mode == "真实物理量模式" else "V"
        unit_B = "T" if calc_mode == "真实物理量模式" else "V"
        
        # --- 报告模块 1: 原理与数据表 ---
        st.subheader("1. 实验数据记录表")
        table_data = {
            "测量节点": ["第一象限极值点", "正向矫顽力", "正向剩磁", "第三象限极值点", "反向矫顽力", "反向剩磁"],
            "X (cm/div)": [round(div_Hm, 2), round(div_Hc, 2), 0.00, round(-div_Hm, 2), round(-div_Hc, 2), 0.00],
            "Y (cm/div)": [round(div_Bm, 2), 0.00, round(div_Br, 2), round(-div_Bm, 2), 0.00, round(-div_Br, 2)],
            f"H ({unit_H})": [round(Hm_val, 2), round(Hc_val, 2), 0.00, round(-Hm_val, 2), round(-Hc_val, 2), 0.00],
            f"B ({unit_B})": [round(Bm_val, 4), 0.00, round(Br_val, 4), round(-Bm_val, 4), 0.00, round(-Br_val, 4)]
        }
        st.table(pd.DataFrame(table_data))
        
        report_col1, report_col2 = st.columns([1.5, 1])
        
        # --- 报告模块 2: 高精度 PCHIP 图像重构 ---
        with report_col1:
            st.subheader("2. 磁滞回线重建图 (PCHIP保形插值)")
            try:
                # 提取光学真中心，消除全局 DC 偏移
                Center_X_px = (p_x_left[0] + p_x_right[0]) / 2.0
                Center_Y_px = (p_y_top[1] + p_y_bottom[1]) / 2.0
                
                # 初始化核心物理锚点
                H_up = [-Hm_val, -Hc_val, 0.0, Hm_val]
                B_up = [-Bm_val, 0.0, Br_val, Bm_val]
                H_dn = [-Hm_val, Hc_val, 0.0, Hm_val]
                B_dn = [-Bm_val, 0.0, -Br_val, Bm_val]
                
                aux_h_list, aux_b_list = [], []
                
                # 将辅助点映射到物理坐标，并智能分配到上下分支
                for pt in clicks[8:]:
                    px, py = pt
                    h_ext = (px - Center_X_px) / pixels_per_div * x_volts * Kx
                    b_ext = (Center_Y_px - py) / pixels_per_div * y_volts * Ky
                    aux_h_list.append(h_ext)
                    aux_b_list.append(b_ext)
                    
                    # 依据对角线判定点归属
                    if Hm_val != 0:
                        line_b = (Bm_val / Hm_val) * h_ext
                        if b_ext >= line_b:
                            H_up.append(h_ext)
                            B_up.append(b_ext)
                        else:
                            H_dn.append(h_ext)
                            B_dn.append(b_ext)

                # PCHIP 拟合函数
                def fit_pchip(h_list, b_list):
                    h_arr, b_arr = np.array(h_list), np.array(b_list)
                    sort_idx = np.argsort(h_arr)
                    h_sort, b_sort = h_arr[sort_idx], b_arr[sort_idx]
                    # 去重，防止插值算法崩溃
                    h_uniq, uniq_idx = np.unique(h_sort, return_index=True)
                    b_uniq = b_sort[uniq_idx]
                    if len(h_uniq) > 1:
                        return PchipInterpolator(h_uniq, b_uniq), h_uniq.min(), h_uniq.max()
                    return None, 0, 0

                pchip_up, min_h_up, max_h_up = fit_pchip(H_up, B_up)
                pchip_dn, min_h_dn, max_h_dn = fit_pchip(H_dn, B_dn)
                
                x_plot_up = np.linspace(min_h_up, max_h_up, 200)
                x_plot_dn = np.linspace(min_h_dn, max_h_dn, 200)
                
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=x_plot_up, y=pchip_up(x_plot_up), mode='lines', line=dict(color='#00ff88', width=3), name='磁化上分支'))
                fig.add_trace(go.Scatter(x=x_plot_dn, y=pchip_dn(x_plot_dn), mode='lines', line=dict(color='#00d4ff', width=3), name='磁化下分支'))
                
                # 绘制核心特征点
                fig.add_trace(go.Scatter(
                    x=[-Hm_val, -Hc_val, 0, Hm_val, Hc_val, 0], 
                    y=[-Bm_val, 0, Br_val, Bm_val, 0, -Br_val], 
                    mode='markers', marker=dict(size=10, color='gold', line=dict(width=2, color='white')), name='核心物理锚点'
                ))
                
                # 绘制用户添加的辅助点
                if aux_h_list:
                    fig.add_trace(go.Scatter(
                        x=aux_h_list, y=aux_b_list, 
                        mode='markers', marker=dict(size=8, color='cyan', symbol='cross', line=dict(width=1, color='white')), name='用户辅助轮廓点'
                    ))
                
                fig.update_layout(
                    xaxis_title=f"磁场强度 H ({unit_H})", yaxis_title=f"磁感应强度 B ({unit_B})",
                    hovermode="x unified", height=450, margin=dict(l=20, r=20, t=30, b=20),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)"
                )
                st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.error(f"曲线重构失败，可能是辅助点位置过于集中，错误: {e}")

        # --- 报告模块 3: AI 诊断分析 ---
        with report_col2:
            st.subheader("3. 实验结果讨论与指导")
            with st.spinner("AI 助教正在批改生成结论..."):
                try:
                    client = OpenAI(
                        api_key=os.getenv("DASHSCOPE_API_KEY", ""),
                        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
                    )
                    base64_image = encode_image(display_image)
                    param_text = f"Hc: {Hc_val:.3f}, Br: {Br_val:.3f}, Hm: {Hm_val:.3f}, Bm: {Bm_val:.3f}"
                    
                    prompt = f"""
                    你是大学物理实验助教。这是一张磁滞回线实验的照片，核心去偏置物理参数为：{param_text}。
                    请根据图像诊断实验操作问题，并撰写实验结论。
                    严格输出 JSON 格式：
                    {{
                      "experiment_status": "正常饱和/未饱和/波形严重偏移等",
                      "operation_advice": "给学生的具体调参指导",
                      "report_paragraph": "写一段长约100字的正式实验结论，适合直接抄入物理实验报告。"
                    }}
                    """
                    
                    response = client.chat.completions.create(
                        model="qwen-vl-max",
                        messages=[
                            {"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}
                        ],
                        temperature=0.1
                    )
                    
                    raw_text = response.choices[0].message.content.strip()
                    if raw_text.startswith("```json"): raw_text = raw_text[7:-3].strip()
                    elif raw_text.startswith("```"): raw_text = raw_text[3:-3].strip()
                    result = json.loads(raw_text)
                    
                    st.success(f"**📌 图像状态判定**：{result.get('experiment_status', '未知')}")
                    st.warning(f"**💡 纠错与调参指导**：{result.get('operation_advice', '无')}")
                    st.info(f"**📝 报告讨论区 (直接可用)**：\n\n{result.get('report_paragraph', '无')}")
                    
                except Exception as e:
                    st.error(f"调用 AI 模型失败: {e}")
