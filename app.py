import streamlit as st
from PIL import Image, ImageDraw
from streamlit_image_coordinates import streamlit_image_coordinates
import json
import base64
import io
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy.interpolate import PchipInterpolator
from openai import OpenAI

# ================= 1. 页面基本设置 =================
st.set_page_config(page_title="智眼识磁系统", layout="wide", initial_sidebar_state="expanded")

st.title("🧲 智眼识磁：磁滞回线智能分析系统")
st.markdown("> **学术前沿版**：支持 PCHIP 保形插值、全对称差分去偏置。集成多视角视图（原图/物理量图/归一化图），直击实验本质。")

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
st.sidebar.header("⚙️ 实验仪参数录入")
st.sidebar.markdown("系统将同时并行计算**真实物理量(B-H)**与**归一化参数**。")

st.sidebar.subheader("🔌 示波器读取参数")
x_volts = st.sidebar.number_input("X 轴档位 Sx (V/div)", value=0.20, step=0.05) 
y_volts = st.sidebar.number_input("Y 轴档位 Sy (V/div)", value=0.05, step=0.01) 

st.sidebar.subheader("📐 实验仪硬件参数")
R1 = st.sidebar.number_input("取样电阻 R1 (Ω)", value=1.0, step=0.5)
N1 = st.sidebar.number_input("励磁线圈匝数 N1", value=50, step=10)
L_mm = st.sidebar.number_input("磁路长度 L (mm)", value=60.0, step=1.0)
R2 = st.sidebar.number_input("积分电阻 R2 (kΩ)", value=10.0, step=1.0)
C_uF = st.sidebar.number_input("积分电容 C (μF)", value=10.0, step=1.0)
N2 = st.sidebar.number_input("感应线圈匝数 N2", value=150, step=10)
S_mm2 = st.sidebar.number_input("截面积 S (mm²)", value=80.0, step=1.0)

# 计算绝对物理系数
L_m = L_mm / 1000.0
S_m2 = S_mm2 / 1.0e6
R2_ohm = R2 * 1000.0
C_F = C_uF * 1.0e-6

Kx = N1 / (L_m * R1)
Ky = (R2_ohm * C_F) / (N2 * S_m2)

st.sidebar.markdown(f"**计算系数：**\n*   $K_x = {Kx:.2f}$ `A/(V·m)`\n*   $K_y = {Ky:.3f}$ `T/V`")

# ================= 4. 主工作区：文件上传与计算 =================
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
            draw.ellipse((x-6, y-6, x+6, y+6), fill=core_colors[i], outline="black", width=2)
            draw.text((x+12, y-10), core_labels[i], fill="white")
        else:
            draw.ellipse((x-4, y-4, x+4, y+4), fill="cyan", outline="black", width=1)
            draw.text((x+8, y-8), f"辅{i-7}", fill="cyan")
            
    # 计算逻辑预备
    pixels_per_div = 0
    is_ready = len(st.session_state['clicks']) >= 8
    
    div_Hc = div_Br = div_Hm = div_Bm = 0
    Hc_phys = Br_phys = Hm_phys = Bm_phys = 0
    Hc_norm = Br_norm = Hm_norm = Bm_norm = 0
    
    if is_ready:
        clicks = st.session_state['clicks']
        p_center, p_scale = clicks[0], clicks[1]
        p_x_left, p_x_right = clicks[2], clicks[3]
        p_y_top, p_y_bottom = clicks[4], clicks[5]
        p_vertex_tr, p_vertex_bl = clicks[6], clicks[7]
        
        pixels_per_div = abs(p_scale[0] - p_center[0])
        
        if pixels_per_div != 0:
            div_Hc = (abs(p_x_right[0] - p_x_left[0]) / 2) / pixels_per_div
            div_Br = (abs(p_y_bottom[1] - p_y_top[1]) / 2) / pixels_per_div
            div_Hm = (abs(p_vertex_tr[0] - p_vertex_bl[0]) / 2) / pixels_per_div
            div_Bm = (abs(p_vertex_bl[1] - p_vertex_tr[1]) / 2) / pixels_per_div
            
            # 真实物理量 (A/m, T)
            Hc_phys = div_Hc * x_volts * Kx
            Br_phys = div_Br * y_volts * Ky
            Hm_phys = div_Hm * x_volts * Kx
            Bm_phys = div_Bm * y_volts * Ky
            
            # 归一化量 (V, V)
            Hc_norm = div_Hc * x_volts
            Br_norm = div_Br * y_volts
            Hm_norm = div_Hm * x_volts
            Bm_norm = div_Bm * y_volts

    # ================= 5. 解老师专属：三视图 Tabs 布局 =================
    st.divider()
    tab1, tab2, tab3 = st.tabs(["📷 1. 示波器交互原图", "📈 2. B-H 结果图 (真实物理量)", "📉 3. 参数归一化图 (去除硬件差异)"])
    
    with tab1:
        st.info("🎯 **核心8点标定**：1.原点 ➔ 2.右标尺 ➔ 3.左X ➔ 4.右X ➔ 5.上Y ➔ 6.下Y ➔ 7.右上极值 ➔ 8.左下极值\n\n"
                "✨ **无限制辅助点**：8 点完成后，可在陡峭处点击任意数量轮廓点，以完美贴合真实形状。")
        
        col_img, col_btn = st.columns([2, 1])
        with col_img:
            current_key = f"pil_{st.session_state['img_key_counter']}"
            value = streamlit_image_coordinates(display_image, key=current_key)
            if value is not None:
                point = (value['x'], value['y'])
                if not st.session_state['clicks'] or st.session_state['clicks'][-1] != point:
                    st.session_state['clicks'].append(point)
                    st.rerun() 
        with col_btn:
            if st.button("⏪ 撤销上一步", use_container_width=True):
                if st.session_state['clicks']:
                    st.session_state['clicks'].pop()
                    st.session_state['img_key_counter'] += 1  # 核心修复：强制刷新组件
                    st.rerun()
            
            if st.button("🔄 清空所有点", use_container_width=True):
                st.session_state['clicks'] = []
                st.session_state['img_key_counter'] += 1  # 核心修复：强制刷新组件
                st.rerun()
            
            if is_ready:
                st.success("核心标定完成！")
                st.metric("网格像素比", f"{pixels_per_div:.1f} px/div")
                analyze_button = st.button("🧠 一键生成诊断与报告", type="primary", use_container_width=True)

    # 绘图复用函数
    def plot_pchip(Hm, Hc, Bm, Br, k_x_factor, k_y_factor, unit_h, unit_b, title_text):
        Center_X_px = (p_x_left[0] + p_x_right[0]) / 2.0
        Center_Y_px = (p_y_top[1] + p_y_bottom[1]) / 2.0
        
        H_up, B_up = [-Hm, -Hc, 0.0, Hm], [-Bm, 0.0, Br, Bm]
        H_dn, B_dn = [-Hm, Hc, 0.0, Hm], [-Bm, 0.0, -Br, Bm]
        
        aux_h_list, aux_b_list = [], []
        
        for pt in clicks[8:]:
            px, py = pt
            h_ext = (px - Center_X_px) / pixels_per_div * x_volts * k_x_factor
            b_ext = (Center_Y_px - py) / pixels_per_div * y_volts * k_y_factor
            aux_h_list.append(h_ext)
            aux_b_list.append(b_ext)
            
            if Hm != 0:
                if b_ext >= (Bm / Hm) * h_ext:
                    H_up.append(h_ext)
                    B_up.append(b_ext)
                else:
                    H_dn.append(h_ext)
                    B_dn.append(b_ext)

        def fit_pchip(h_list, b_list):
            h_arr, b_arr = np.array(h_list), np.array(b_list)
            sort_idx = np.argsort(h_arr)
            h_uniq, uniq_idx = np.unique(h_arr[sort_idx], return_index=True)
            if len(h_uniq) > 1: return PchipInterpolator(h_uniq, b_arr[sort_idx][uniq_idx]), h_uniq.min(), h_uniq.max()
            return None, 0, 0

        pchip_up, min_h_up, max_h_up = fit_pchip(H_up, B_up)
        pchip_dn, min_h_dn, max_h_dn = fit_pchip(H_dn, B_dn)
        
        fig = go.Figure()
        if pchip_up:
            x_up = np.linspace(min_h_up, max_h_up, 200)
            fig.add_trace(go.Scatter(x=x_up, y=pchip_up(x_up), mode='lines', line=dict(color='#00ff88', width=3), name='上分支'))
        if pchip_dn:
            x_dn = np.linspace(min_h_dn, max_h_dn, 200)
            fig.add_trace(go.Scatter(x=x_dn, y=pchip_dn(x_dn), mode='lines', line=dict(color='#00d4ff', width=3), name='下分支'))
            
        fig.add_trace(go.Scatter(
            x=[-Hm, -Hc, 0, Hm, Hc, 0], y=[-Bm, 0, Br, Bm, 0, -Br], 
            mode='markers', marker=dict(size=10, color='gold', line=dict(width=2, color='white')), name='特征点'
        ))
        
        if aux_h_list:
            fig.add_trace(go.Scatter(
                x=aux_h_list, y=aux_b_list, mode='markers', 
                marker=dict(size=8, color='cyan', symbol='cross', line=dict(width=1, color='white')), name='辅助点'
            ))
            
        fig.update_layout(
            title=title_text, xaxis_title=f"H ({unit_h})", yaxis_title=f"B ({unit_b})",
            hovermode="x unified", height=500, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)"
        )
        return fig

    with tab2:
        if is_ready and pixels_per_div > 0:
            st.markdown("### B-H 结果图 (真实物理特性)")
            try:
                fig_phys = plot_pchip(Hm_phys, Hc_phys, Bm_phys, Br_phys, Kx, Ky, "A/m", "T", "绝对物理量磁化曲线")
                st.plotly_chart(fig_phys, use_container_width=True)
            except Exception as e:
                st.error(f"绘图失败: {e}")
        else:
            st.info("请先在【图1】中完成核心点标定。")

    with tab3:
        if is_ready and pixels_per_div > 0:
            st.markdown("### 参数归一化图 (趋势对比分析)")
            try:
                fig_norm = plot_pchip(Hm_norm, Hc_norm, Bm_norm, Br_norm, 1.0, 1.0, "V", "V", "归一化相对电压曲线")
                st.plotly_chart(fig_norm, use_container_width=True)
            except Exception as e:
                st.error(f"绘图失败: {e}")
        else:
            st.info("请先在【图1】中完成核心点标定。")

    # ================= 6. 实验报告与 AI 诊断区 =================
    if is_ready and 'analyze_button' in locals() and analyze_button:
        st.divider()
        st.header("📑 智能实验报告 (AI 生成)")
        
        col_table, col_ai = st.columns([1, 1])
        col_table, col_ai = st.columns([1, 1])
        
        with col_table:
            # --- 第一张表：详细数据记录表（完美复刻手写版） ---
            st.subheader("📊 详细数据记录表")
            st.markdown("**依据公式：** $H = X_{div} \cdot S_x \cdot K_x$ ， $B = Y_{div} \cdot S_y \cdot K_y$")
            table_data_detailed = {
                "测量节点": ["第一象限极值", "正向矫顽力", "正向剩磁", "第三象限极值", "反向矫顽力", "反向剩磁"],
                "X (div)": [f"{div_Hm:.2f}", f"{div_Hc:.2f}", "0.00", f"{-div_Hm:.2f}", f"{-div_Hc:.2f}", "0.00"],
                "Y (div)": [f"{div_Bm:.2f}", "0.00", f"{div_Br:.2f}", f"{-div_Bm:.2f}", "0.00", f"{-div_Br:.2f}"],
                "H (A/m)": [f"{Hm_phys:.2f}", f"{Hc_phys:.2f}", "0.00", f"{-Hm_phys:.2f}", f"{-Hc_phys:.2f}", "0.00"],
                "B (T)": [f"{Bm_phys:.4f}", "0.00", f"{Br_phys:.4f}", f"{-Bm_phys:.4f}", "0.00", f"{-Br_phys:.4f}"]
            }
            st.table(pd.DataFrame(table_data_detailed))
            
            # --- 第二张表：物理特性参数对比表（展示给老师看的精华总结） ---
            st.subheader("⚖️ 物理参量对比表")
            table_data_compare = {
                "物理参量": ["矫顽力 (Hc)", "剩磁 (Br)", "最大磁场 (Hm)", "最大磁感应 (Bm)"],
                "真实物理数值": [f"{Hc_phys:.2f} A/m", f"{Br_phys:.4f} T", f"{Hm_phys:.2f} A/m", f"{Bm_phys:.4f} T"],
                "归一化数据 (V)": [f"{Hc_norm:.3f}", f"{Br_norm:.3f}", f"{Hm_norm:.3f}", f"{Bm_norm:.3f}"]
            }
            st.table(pd.DataFrame(table_data_compare))
            
        with col_ai:
            st.subheader("🤖 实验结果讨论与指导")
            with st.spinner("Qwen-VL 正在审阅数据..."):
                try:
                    client = OpenAI(
                        api_key="sk-ws-H.EDRMLHM.TfUd.MEUCIDHQ5iXFJhzN3SaixunpWQq_9XewZjCAFpmqZW139muwAiEAvR4MsYCMwORHfx00j9reLpV7u2XdBGtF9N5fgVpNLDY",
                        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
                    )
                    base64_image = encode_image(display_image)
                    param_text = f"Hc: {Hc_phys:.2f} A/m, Br: {Br_phys:.4f} T, Hm: {Hm_phys:.2f} A/m, Bm: {Bm_phys:.4f} T"
                    
                    prompt = f"""
                    你是大学物理实验助教。这是一张磁滞回线实验照片，核心去偏置物理参数为：{param_text}。
                    请根据图像诊断操作问题，撰写报告。严格输出JSON格式：
                    {{
                      "experiment_status": "正常饱和/未饱和/波形严重偏移等",
                      "operation_advice": "给学生的具体调参指导",
                      "report_paragraph": "长约100字的正式实验结论，适合直接抄入报告的'误差分析与讨论'部分。"
                    }}
                    """
                    response = client.chat.completions.create(
                        model="qwen-vl-max",
                        messages=[{
                            "role": "user", 
                            "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]
                        }],
                        temperature=0.1
                    )
                    raw_text = response.choices[0].message.content.strip()
                    if raw_text.startswith("```json"): raw_text = raw_text[7:-3].strip()
                    elif raw_text.startswith("```"): raw_text = raw_text[3:-3].strip()
                    result = json.loads(raw_text)
                    
                    st.success(f"**📌 图像判定**：{result.get('experiment_status', '未知')}")
                    st.warning(f"**💡 调参指导**：{result.get('operation_advice', '无')}")
                    st.info(f"**📝 报告结论**：\n{result.get('report_paragraph', '无')}")
                except Exception as e:
                    st.error(f"AI 调用失败: {e}")