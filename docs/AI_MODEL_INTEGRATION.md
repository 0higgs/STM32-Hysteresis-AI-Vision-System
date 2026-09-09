# 已训练 U-Net 的项目集成方案

## 这次训练已经增加了什么 AI 能力

模型位于 `runs/unet_v1_tensorflow/best.keras`。它不是颜色阈值，而是由人工标注曲线训练出的 TensorFlow U-Net，输入固定相机/示波器位置的照片，输出像素级磁滞回线掩膜。当前清洁标注验证集 Dice 为 `0.880`（9 张验证图），所以应在答辩中如实称为“原型验证结果”，而不是泛化性能结论。

完整链路为：**照片 -> U-Net 语义分割 -> 固定网格几何测量 -> Hc/Br/极值（格数/通道电压） -> 教学解释与人工复核**。

## 替换旧 Streamlit 代码

旧版 `detect_core_points_cv()` 使用 HSV 颜色阈值和连通域。保留它作为“传统视觉基线/失败回退”，但默认使用：

```python
from ml.unet_measurement import UNetLoopMeasurer

@st.cache_resource
def get_unet_measurer():
    return UNetLoopMeasurer()

# original_image 是 PIL.Image.Image；示波器两通道均为 0.5 V/div
result = get_unet_measurer().analyse(original_image, volts_per_div=0.5)
st.image(result["overlay"], caption=result["method"])
st.json({key: result[key] for key in (
    "hc_negative_div", "hc_positive_div", "br_positive_div", "br_negative_div",
    "hc_half_span_div", "br_half_span_div", "trace_pixels",
)})
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
