# 软著原创源码推荐顺序

以下文件是 V1.0 推荐的原创代码选取顺序。选取时保持文件名、页眉软件名称和版本一致；如有第三方片段，应按登记要求遮蔽或替换为自研调用层说明。

1. `desktop_capture/main.py`：参数控制、自动化调度、状态机和 UI。
2. `desktop_capture/adb_camera.py`：ADB 拍照与回传封装。
3. `desktop_capture/dataset_manifest.py`：断点续拍清单逻辑。
4. `firmware/User/main.c`：硬件初始化及回线输出调度。
5. `firmware/User/bt_protocol.c` 与 `firmware/User/bt_protocol.h`：协议解析和参数校验。
6. `firmware/User/hyst_model.c` 与 `firmware/User/hyst_model.h`：磁滞回线离散模型和 DAC 缓冲。
7. `ai_pipeline/prepare_segmentation_dataset.py`：LabelMe 到分割数据转换。
8. `ai_pipeline/train_unet_tensorflow.py`：正式 TensorFlow U-Net 训练。
9. `ai_pipeline/predict_all_images.py`：批量推理。
10. `ai_pipeline/extract_grid_features.py`、`calibrate_fixed_screen.py`：网格与标定。
11. `ai_model/unet_measurement.py`：部署推理、逐图网格检测与几何量测。
12. `analyzer.py`：保留的独立分析辅助实现。
13. `app.py`：正式 Web 交互与结果呈现。

## 不建议作为原创主体

- `firmware/Drivers/`、`firmware/Middlewares/`、CMSIS、STM32 HAL、启动文件、ST/Keil 工程模板。
- `__pycache__/`、`*.pyc`、构建产物、日志、IDE 配置。
- `models/*.keras`、CSV、JPG、JSON 标注和其他二进制数据资产。
- Python 依赖源码、ADB/LabelMe 等外部工具。
- `legacy/` 内的历史实验和旧版本实现。

## 注意事项

软著保护具体代码和文档表达，不保护磁滞理论、U-Net 通用思想、数据集或硬件电路本身。若共同作者、委托关系或学校/单位职务成果存在争议，必须先取得书面权属说明。
