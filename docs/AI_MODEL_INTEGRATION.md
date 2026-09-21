# 已训练 U-Net 的项目集成方案

## 这次训练已经增加了什么 AI 能力

部署模型位于 `models/hysteresis_unet_v1.keras`。它不是颜色阈值，而是由人工标注曲线训练出的 TensorFlow U-Net，输入固定相机/示波器位置的照片，输出像素级磁滞回线掩膜。2026-09-19 使用最新 136 份标注重训后，110/26 分层留出划分上的平均 Dice 为 `0.8952`、平均 IoU 为 `0.8117`。该结果仍来自同一固定采集装置，应称为“留出验证结果”，不是跨设备泛化结论。

完整链路为：**照片 -> U-Net 语义分割 -> 上下分支中心线重建 -> 饱和合并区局部约束平滑 -> 横纵网格几何标定 -> 在同一中心线上完成 Hc/Br/极值测量、完整 B-H 回线绘图及回线面积积分 -> 教学解释与人工复核**。八个核心点与最终绘图共用中心线数据，只承担特征测量、校验和失败回退，不再作为 U-Net 成功时的另一套独立估计或主曲线数据源。

面积按 $\int(B_{\mathrm{upper}}-B_{\mathrm{lower}})\,\mathrm{d}H$ 的正间距积分，其大小与 $|\oint H\,\mathrm{d}B|$ 相同。端部小于 1% 纵向量程的像素级反向间距会被裁为零；若显著交叉占共同横坐标范围超过 2%，界面要求人工复核。只有完成真实电路参数标定后，面积才可解释为 `J/m³`。

## 替换旧 Streamlit 代码

旧版 `detect_core_points_cv()` 使用 HSV 颜色阈值和连通域。保留它作为“传统视觉基线/失败回退”，但默认使用：

```python
from ai_model.unet_measurement import UNetLoopMeasurer

@st.cache_resource
def get_unet_measurer():
    return UNetLoopMeasurer()

# original_image 是 PIL.Image.Image；示波器两通道均为 0.5 V/div
result = get_unet_measurer().analyse(original_image)
st.image(result["overlay"], caption="U-Net segmentation")
st.json({
    "features_div": result["features_div"],
    "trace_pixels": result["trace_pixels"],
    "branches_in_crop": result["branches_in_crop"],
    "grid_size_x_px": result["grid_size_x_px"],
    "grid_size_y_px": result["grid_size_y_px"],
    "grid_quality": result["grid_quality"],
})
```

不要调用旧代码中默认 `N1/L/R1/R2/C/N2/S` 的 H/B 换算。现阶段界面应显示“div”和“V”；当实际电路常数重新标定后，再将其写入单独的校准文件。

## 参数表在系统中的正确位置

`dataset/parameters.csv` 是 500 张采集照片的真值标签：用于训练、验证和离线回归研究，**不应**在用户上传未知图片时作为模型输入。

已有报告 `calibration/fixed_screen_v1/parameter_identifiability_report.csv` 表明：幅度、X/Y 增益、部分偏移可从图形预测；HMAX、HC、BS 和 LOOP_HZ 不能可靠地由单张静态图恢复。尤其 LOOP_HZ 必须由仪器通信/视频时间信息提供。

## 下一轮增强（按优先级）

1. 再标注 80--120 张，覆盖裁切、不同亮度、偏移、饱和和小回线；保留独立测试集。
2. 将 U-Net 输出置信度、掩膜面积、交点是否存在作为质量门控；低置信度时转人工点选，不让系统静默给出错误数值。
3. 训练第二个“质量分类”模型：正常、过曝、过暗、裁切、失焦、回线过小。它比强行预测不可见物理参数更合理。
4. 只针对已证明可识别的字段训练参数回归器，并显示预测区间；其他字段从 STM32/采集 CSV 读取。
5. 做消融实验：HSV 基线 vs U-Net，报告 Dice、Hc/Br 误差、失败率和平均推理时间。这是项目 AI 含量最有力的实证材料。
