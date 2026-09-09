# 智眼识磁：STM32 磁滞回线生成、采集与 AI 视觉分析平台

从 STM32F407 双 DAC 生成磁滞回线、手机有线 ADB 同步拍照，到人工标注训练 TensorFlow U-Net，并在 Web 中自动提取回线与关键特征点的一体化项目。

## 项目亮点

- **可编程磁滞回线发生器**：STM32F407 通过 `PA5/DAC2 -> X`、`PA4/DAC1 -> Y` 输出回线；JDY-34 蓝牙串口接收整组参数并实时更新。
- **自动化数据采集**：Windows 上位机按 CSV/XLSX 参数表逐行下发；等待示波器稳定后，以有线 ADB 触发 Android 手机拍照、回传图像、按 `sample_id` 命名并维护采集清单，支持重试和断点续拍。
- **本地 AI 模型**：使用 LabelMe 人工曲线标注训练 TensorFlow U-Net。模型分割磁滞轨迹而非依赖 HSV 颜色阈值；清洁留出验证集 Dice 为 `0.880`（9 张验证图，属原型验证结果）。
- **逐图网格校正**：U-Net 分割曲线后，从当前照片检测网格和零轴，减少手机轻微平移导致特征点整体错位。
- **智眼识磁 Web**：显示曲线掩膜、自动特征点、Hc/Br/饱和端点、偏移、归一化曲线，以及学习、指导、考核三类交互模式。

## 系统流程

```text
参数 CSV/XLSX -> Windows 上位机 -> JDY-34 -> STM32 双 DAC -> 示波器 X-Y
                                                        |
                                             手机有线 ADB 自动拍照
                                                        |
参数真值表 + LabelMe 标注 -> U-Net 训练 -> 曲线分割 -> 网格测量 -> Web 分析
```

## 目录结构

| 路径 | 内容 |
| --- | --- |
| `firmware/` | STM32F407 Keil 工程、HAL/CMSIS、DAC 磁滞模型与蓝牙协议 |
| `desktop_capture/` | Windows 控制端、ADB 相机控制、500 组参数表与断点续拍逻辑 |
| `ai_pipeline/` | 数据转换、LabelMe 预处理、U-Net 训练、批量推理、网格特征和可识别性评估 |
| `data/metadata/` | 500 张图片的参数真值表与采集清单 |
| `data/labelme_annotations/` | 人工曲线标注 JSON 与标签定义 |
| `models/` | 直接部署的 `hysteresis_unet_v1.keras` |
| `evaluation/` | 训练历史、批量预测表与可视化示例 |
| `ai_model/` | Streamlit 使用的 U-Net 推理与逐图网格检测模块 |
| `app_fixed.py` | Web 应用入口 |

## 快速启动 Web 应用

```powershell
cd ai_hysteresis_system
D:\ProgramFiles\anaconda3\python.exe -m pip install -r requirements.txt
D:\ProgramFiles\anaconda3\python.exe -m streamlit run app_fixed.py
```

上传固定相机、固定示波器位置拍摄的照片后，点击 **“已训练 U-Net 自动标定（推荐）”**。

页面中的关键点：白色为原点和一格标尺；红色为 `Hc−/Hc+`；蓝色为 `Br+/Br−`；紫色为正负饱和端点（右上、左下）。若 U-Net 结果与荧光轨迹不符，请使用人工标定或传统视觉回退。

## 数据集说明

原始 500 张 JPG 约 1GB，未放入普通 Git 历史，避免仓库膨胀和 GitHub 限制。仓库保留可复现数据资产：采集清单、参数真值、标签定义、人工标注、标定文件、训练和预测脚本。

需要重新训练时，将原图按 `sample_id` 放入本地 `dataset/images/`，并参考 `data/metadata/` 和 `ai_pipeline/`。原始图像请放在网盘或发布版本附件中，而不是常规 Git 提交。

## 科学边界

- 默认示波器档位为 X/Y 均 `0.5 V/div`。未填写真实线圈、电阻、电容、磁路与截面积等标定信息时，Web 仅显示可靠的格数和通道电压，不会沿用旧默认物理参数伪造 A/m、T。
- `LOOP_HZ` 不能由一张静态照片推断，需来自 STM32 通信记录或视频时间信息。
- 当前固件对一部分物理量归一化显示，因此 `HMAX`、`BS` 等绝对参数不能只凭静态照片唯一恢复；`parameters.csv` 是采集真值和模型评估标签，不能作为未知图像推理时的输入。

## 云端教学功能（可选）

本地 U-Net 推理不需要密钥。若启用云端教学反馈，在 `.streamlit/secrets.toml` 中配置：

```toml
DASHSCOPE_API_KEY = "your-new-key"
```

密钥不应写入源代码或提交到 Git。
