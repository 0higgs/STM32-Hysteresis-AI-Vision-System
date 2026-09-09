# 智眼识磁

## 磁滞回线智能视觉分析系统 V1.0

**智眼识磁**是面向示波器 X-Y 磁滞回线实验的软硬件协同系统：STM32F407 双 DAC 回线发生、Windows 参数表控制与 Android 有线 ADB 拍摄、LabelMe 标注与 TensorFlow U-Net 分割、网格视觉测量和 Streamlit 教学分析，构成一条可复现实验流程。

版本：`V1.0.0`。本仓库为软件著作权登记与正式发布准备的工程基线；权属和开放许可仍须全体项目著作权人书面确认。

## 系统架构

```text
参数表 CSV/XLSX
  -> Windows 上位机 -> JDY-34 蓝牙串口 -> STM32F407 -> DAC2(X) / DAC1(Y)
  -> 示波器 X-Y 显示 -> Android 手机 ADB 拍摄 -> 图像与 manifest
  -> LabelMe 标注 -> TensorFlow U-Net -> 网格检测与特征测量 -> Web 分析/教学反馈
```

## 功能模块

| 模块 | 作用 |
| --- | --- |
| A. STM32 可编程发生器 | 生成并通过双 DAC 输出可调磁滞回线；接收蓝牙参数协议。 |
| B. Windows 自动采集端 | 导入参数表、串口下发、等待稳定、ADB 拍摄、断点续拍、重试及 manifest 记录。 |
| C. AI 视觉测量 | LabelMe 曲线监督、TensorFlow U-Net 分割、逐图网格检测、Hc/Br/饱和端点测量。 |
| D. Web 教学与分析 | Streamlit 交互式上传、分割结果、关键点复核、回线和教学反馈展示。 |

## 快速开始

### Web 分析平台

```powershell
cd STM32-Hysteresis-AI-Vision-System
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

本地 U-Net 不需要云端密钥。可选的云端教学反馈使用 `DASHSCOPE_API_KEY` 环境变量，或只在本机 `.streamlit/secrets.toml` 配置；该文件不会被提交。

### Windows 上位机

```powershell
cd desktop_capture
python -m pip install -r requirements.txt
python main.py
```

上位机按 `ADB_PATH` 环境变量、系统 `PATH`、Android SDK 常规路径的顺序寻找 adb；仍未找到时可在界面中手动选择 `adb.exe`。详见 [desktop_capture/README.md](desktop_capture/README.md)。

### STM32 固件

Keil 工程为 `firmware/Projects/MDK-ARM/atk_f407.uvprojx`，发布镜像为 `release/firmware/hysteresis_v1.hex`。详见 [firmware/README.md](firmware/README.md)。

## AI 训练与数据集

原始 500 张 JPG 约 1 GB，不进入普通 Git 历史。将它们按 `sample_id` 放在本机 `dataset/images/`，再按 [ai_pipeline/README.md](ai_pipeline/README.md) 执行 LabelMe 转换、TensorFlow 训练和预测。仓库保留 metadata、人工标注、标定文件、训练脚本、部署模型和少量验证预览。

部署模型为 `models/hysteresis_unet_v1.keras`。V1.0 整理过程没有重新训练或改动权重。清洁留出集的 Dice 记录为 `0.880`（9 张验证图），仅是当前原型实验记录，不应解释为大规模泛化性能结论。

## 目录结构

```text
app.py                  # 唯一正式 Streamlit 入口
analyzer.py             # 兼容性保留的早期独立分析程序
ai_model/               # 部署侧 U-Net 推理与网格测量
ai_pipeline/            # 数据准备、TensorFlow 训练、评估脚本
desktop_capture/        # Windows 串口/ADB 自动采集程序
firmware/               # STM32 工程；Drivers/Middlewares 为第三方依赖
models/                 # 正式部署模型
data/                   # metadata、LabelMe 标注与数据说明
evaluation/             # 训练记录和少量预览
docs/                   # 架构、用户手册、协议、科学边界和软著材料
legacy/                 # 旧版 Web、视觉实验、PyTorch 训练和历史图片
release/firmware/       # 单一发布固件镜像
```

## 科学边界

- 静态图像不能推断 `LOOP_HZ`，必须来自 STM32 通信记录或视频时间信息。
- 没有真实线圈、电阻、电容、磁路、截面积等物理标定时，只报告可靠格数/通道电压，不能伪造 A/m、T。
- 部分固件参数被归一化到显示轨迹，`HMAX`、`BS` 等绝对量不能由未知单张静态图唯一恢复。
- `data/metadata/parameters.csv` 是采集真值与研究标签，不是未知图像推理输入。

详见 [docs/SCIENTIFIC_LIMITATIONS.md](docs/SCIENTIFIC_LIMITATIONS.md)。

## 第三方依赖、软著与许可

TensorFlow、OpenCV、Streamlit、STM32 HAL/CMSIS、ADB 和 LabelMe 等是依赖，不是本项目原创代码。原创范围包括实验控制、磁滞模型与协议、采集恢复、视觉测量、模型训练/部署衔接和交互系统。详见 [THIRD_PARTY.md](THIRD_PARTY.md) 与 [docs/soft_copyright/source_code_selection.md](docs/soft_copyright/source_code_selection.md)。

暂未授予开源许可。参见 [COPYRIGHT.md](COPYRIGHT.md)；正式 LICENSE 与著作权人姓名必须由三名共同著作权人确认后再定。
