# AI 数据与训练管线

本目录的正式训练实现是 TensorFlow 脚本 `train_unet_tensorflow.py`；部署模型固定为 `../models/hysteresis_unet_v1.keras`。历史 PyTorch 训练和早期推理实现在 `../legacy/ai_pipeline/`，仅为研究记录，不是 V1.0 推荐入口。

## 可复现流程

1. 将原始照片按 `sample_id` 放到本机 `../dataset/images/`（不入 Git）。
2. 使用 LabelMe 标注单类 `hysteresis_loop` 曲线；JSON 放在 `../data/labelme_annotations/annotations/`。
3. 执行 `prepare_segmentation_dataset.py`，生成本地 segmentation 数据集与训练/验证划分。
4. 执行 `train_unet_tensorflow.py`，训练 TensorFlow U-Net 并导出 `.keras` 模型。
5. 用 `predict_all_images.py` 批量预测，必要时用 `export_validation_previews.py` 生成有限预览。
6. 用 `extract_grid_features.py` 与 `calibrate_fixed_screen.py` 提取网格、零轴与标定配置。
7. 用 `build_parameter_supervision.py` 和 `evaluate_parameter_identifiability.py` 评估哪些控制参数可从图像中识别。

## 脚本职责

| 脚本 | 用途 |
| --- | --- |
| `prepare_segmentation_dataset.py` | LabelMe JSON 转换为图像/掩膜数据集并生成划分。 |
| `train_unet_tensorflow.py` | V1.0 正式 TensorFlow U-Net 训练。 |
| `predict_all_images.py` | 批量运行已训练模型。 |
| `extract_grid_features.py` | 从图像/预测结果提取网格特征。 |
| `calibrate_fixed_screen.py` | 固定相机/示波器布局的标定工具。 |
| `build_parameter_supervision.py` | 合并图像特征与采集参数表。 |
| `evaluate_parameter_identifiability.py` | 评估各参数由静态图像识别的可行性。 |
| `export_validation_previews.py` | 生成小规模验证可视化。 |

训练中不可将参数真值表直接输入未知图像推理；它只用于监督/评估。不要替换或改写 `models/hysteresis_unet_v1.keras`，除非形成一个带训练记录的新模型版本。
