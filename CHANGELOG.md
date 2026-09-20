# Changelog

## 2026-09-20 full-curve reconstruction

### Changed

- U-Net 掩膜经连通域清理、分支中心提取和平滑后，作为 B-H 主曲线的数据源。
- 八个核心点改为特征测量、人工复核与完整曲线不可用时的 PCHIP 回退，不再默认承担主曲线重建。
- 横纵网格格距分别检测并分别用于 H、B 换算，避免透视或非等比缩放造成纵向误差。
- 修复固定参考值被误报为动态网格检测成功的问题；网格不完整时明确拒识。
- 界面分别说明模型裁剪坐标与显示坐标的 px/div，避免 70 px/div 与 37 px/div 等数值被误解为冲突。

### Validation

- 新增网格失败与双分支中心线单元测试。
- 26 张留出验证图像中，25 张完成严格横纵网格检测与完整回线重建；1 张过曝图因网格不完整被正确标记为需回退复核。

## 2026-09-19 model refresh

### Changed

- 使用最新 136 份 LabelMe 标注和对应原图重训并替换部署 U-Net。
- 训练/验证划分扩展为 110/26，并纳入全部 9 类拍摄条件。
- 统一训练数据路径为 `python/images/` 与 `python/dataset/labelme/annotations/`。
- 更新部署 ROI、网格标定、模型元数据和 README 指标口径。
- 恢复 `UNetLoopMeasurer.ROI/TARGET_SIZE` 类级兼容接口，修复 Streamlit 自动标定启动失败。

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
