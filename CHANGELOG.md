# Changelog

## V1.0.0

### Added

- STM32F407 双 DAC 磁滞回线发生。
- 蓝牙串口参数控制与 `SETALL` 兼容路径。
- Windows 上位机、参数表批量实验、ADB 自动拍照、断点续拍、重试和 manifest。
- LabelMe 数据标注转换、TensorFlow U-Net 训练、部署和批量预测。
- 网格自动检测、Hc/Br/饱和端点提取。
- Streamlit Web 分析平台与学习、指导、考核交互模式。
- V1.0 发布审计、文档、依赖与软著源码清单。

### Changed

- 正式 Web 入口统一为 `app.py`；旧入口归档到 `legacy/app_legacy.py`。
- 固件构建输出不再入库，发布镜像统一位于 `release/firmware/hysteresis_v1.hex`。
