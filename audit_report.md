# V1.0 软件著作权发布前工程审计

审计对象：本仓库 V1.0 整理前后文件；审计原则是保留实验可复现性、归档旧实现、排除缓存/构建产物、明确自研与第三方边界。

| 分类 | 主要路径 | 结论 |
| --- | --- | --- |
| 自研核心源代码 | `app.py`、`analyzer.py`、`ai_model/`、`desktop_capture/`、`firmware/User/` | KEEP；正式业务实现。 |
| 第三方代码 | `firmware/Drivers/`、`firmware/Middlewares/`、CMSIS、HAL、启动文件 | THIRD_PARTY；保留以编译，不作原创源码。 |
| 自动生成代码 | Keil `.uvoptx/.uvguix`、DebugConfig、HAL 配置及构建文件 | KEEP（工程所需）或 IGNORE（构建输出）；不列软著主体。 |
| 数据文件 | `data/metadata/`、`data/labelme_annotations/`、`ai_pipeline/calibration/` | KEEP；原始 500 JPG 不入库。 |
| 模型文件 | `models/hysteresis_unet_v1.keras` | KEEP；只读部署资产，不修改数值。 |
| 训练/评估代码 | `ai_pipeline/*.py`、`evaluation/` | KEEP；TensorFlow 脚本为正式流程。 |
| Web 应用 | `app.py` | KEEP；唯一正式入口。 |
| Windows 上位机 | `desktop_capture/main.py`、`adb_camera.py`、`dataset_manifest.py` | KEEP；唯一正式入口为 `main.py`。 |
| 测试代码 | `desktop_capture/test_capture_support.py` | KEEP；不依赖真实硬件的辅助测试。 |
| 缓存/临时文件 | `__pycache__/`、`*.pyc`、`*.inspect.ndjson` | DELETE/IGNORE；已清除本地缓存与 xlsx 检查残留。 |
| 编译产物 | 原 `firmware/Output/` | DELETE/IGNORE；仅发布 HEX 移至 `release/firmware/`。 |
| 历史旧版 | 原 `old/`、旧 `app.py`、历史图片、PyTorch 训练/旧推理 | ARCHIVE 至 `legacy/`，不永久删除。 |

## 重点文件判定

| 路径 | 判定 | 原因 |
| --- | --- | --- |
| `app.py` | KEEP | 原 `app_fixed.py`，包含当前完整 U-Net 和网格标定功能。 |
| `app_fixed.py` | RENAME | 已更名为正式 `app.py`。 |
| 原 `app.py` | ARCHIVE | 早期轻量云端版，已为 `legacy/app_legacy.py`。 |
| `analyzer.py` | KEEP | 兼容研究记录的独立辅助分析代码；非正式 Web 入口。 |
| `ai_model/unet_measurement.py` | KEEP | 正式部署推理，使用项目根目录相对模型路径。 |
| 原 `ai_pipeline/unet_measurement.py` | ARCHIVE | 早期 pipeline 推理，模型路径指向被忽略的 runs，且与部署实现重复。 |
| `ai_pipeline/train_unet_tensorflow.py` | KEEP | 正式 TensorFlow 训练。 |
| 原 `ai_pipeline/train_unet.py` | ARCHIVE | PyTorch 版本，已重命名 `legacy/ai_pipeline/train_unet_pytorch.py`。 |
| `desktop_capture/main.py` | KEEP | 正式桌面入口；ADB 解析已改为环境变量/PATH/常规 SDK/界面选择。 |
| `firmware/User/` | KEEP | 自研 STM32 业务、模型、协议及项目模块。 |
| `firmware/Drivers/`、`Middlewares/` | THIRD_PARTY | HAL/CMSIS/SDK 依赖。 |
| `firmware/Output/` | DELETE/IGNORE | 编译输出；经核验 HEX 已移动为发布资产。 |
| `models/` | KEEP | 已训练模型，V1.0 未改动。 |
| `evaluation/` | KEEP | 仅保留有限实验记录和预览。 |
| `data/` | KEEP | metadata/标注/标定，不含原始大图。 |

## 软著源码选择

优先选择上位机控制、固件协议与模型、数据转换与 TensorFlow 训练、部署量测、Web 交互。完整顺序见 `docs/soft_copyright/source_code_selection.md`。不要将 HAL/CMSIS、模型二进制、CSV、JPG、缓存或构建产物作为原创源码主体。

## 风险与结论

- **权属风险**：三名共同著作权人的姓名、顺序、单位/学校职务成果和授权范围尚未在仓库中确认；冻结前必须书面确认。
- **敏感信息风险**：当前工作树未发现硬编码密钥；云端密钥仅从本机 secret/环境变量读取。历史 Git 记录若曾暴露密钥，应在服务端撤销并重新生成。
- **硬件风险**：未在本次整理中进行 STM32、JDY-34 和手机硬件联调；文档和 Python 导入检查不能替代实机验证。
- **科学风险**：静态图像的参数解释受 `docs/SCIENTIFIC_LIMITATIONS.md` 约束。

除权属确认、API 密钥历史轮换和最终实机回归外，工程结构已适合作为 V1.0 发布/软著材料的基础版本。
