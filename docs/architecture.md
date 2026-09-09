# 系统架构

## 四层组成

1. **回线发生层**：STM32F407 根据 `HystParams` 生成离散轨迹，通过 PA5/DAC2 输出 X、PA4/DAC1 输出 Y。
2. **实验控制层**：Windows 上位机通过 JDY-34 串口下发参数、确认状态、等待稳定，并使用 ADB 控制 Android 拍摄。
3. **视觉测量层**：LabelMe 曲线标注转换为掩膜；TensorFlow U-Net 输出回线概率图；部署模块检测网格和零轴并计算可见几何特征。
4. **应用交互层**：Streamlit `app.py` 提供上传、U-Net 自动标定、传统视觉回退、人工复核和教学反馈。

## 关键数据流

`desktop_capture/capture_parameters_500.csv` 定义批量控制行；采集端生成图像与 `data/metadata/manifest.csv`；人工标注 JSON 与原图一一对应；训练导出的模型存放于 `models/`；Web 仅从上传图像和部署模型计算结果，不读取未知图像对应的 `parameters.csv`。

## 稳定边界

串口协议字段、STM32 参数范围、ADB 拍照策略和 U-Net 输入输出尺寸是现有实验契约。V1.0 文档整理未改动这些契约。运行时模型路径由 `ai_model/unet_measurement.py` 按项目根目录相对定位，避免依赖开发机工作目录。
