# 智眼识磁 V1.0 用户操作说明书

## 1. 启动 Web 分析

安装根目录 `requirements.txt` 后，运行 `python -m streamlit run app.py`。选择固定相机与示波器位置拍摄的照片，优先点击“已训练 U-Net 自动标定（推荐）”。页面会显示轨迹掩膜、网格测量和关键点；若分割与实际荧光轨迹不一致，可使用人工复核或传统视觉回退。

白色点表示原点/标尺，红色点表示 Hc 交点，蓝色点表示 Br 交点，紫色点表示可见的正负饱和端点。它们是图像坐标或格数测量结果，不能在缺少物理标定时被误写成绝对磁学单位。

## 2. 自动采集

启动 `desktop_capture/main.py`，连接 JDY-34 串口，使用 PING/状态读取确认通信。连接开启 USB 调试的 Android 手机，检测设备后导入参数表，设置输出目录与稳定时间，开始自动拍照。任务会记录 manifest，意外中止后使用相同目录再次开始即可识别已完成样本。

## 3. 固件部署

Keil 打开 `firmware/Projects/MDK-ARM/atk_f407.uvprojx` 编译下载，或经核验后使用 `release/firmware/hysteresis_v1.hex`。确认 DAC 通道和示波器 X/Y 接线与项目约定一致。

## 4. AI 训练

准备本地原图、LabelMe JSON 和 metadata 后，按 `ai_pipeline/README.md` 的顺序转换数据、训练 TensorFlow U-Net、批量预测与评估。训练输出应保存为新的版本和运行记录；不得覆盖 V1.0 已训练模型。

## 5. 故障处理

设备缺失、串口授权或 ADB 授权错误应按界面提示处理。自动化任务出现失败时保留 manifest 和日志，先检查供电、蓝牙、USB 授权和固件协议，不要删除已采集图像后重新开始。
