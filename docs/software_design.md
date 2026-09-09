# 软件设计说明

## 模块职责

- `app.py`：正式 Streamlit 入口，组织上传、模式切换、人工点位、U-Net 结果与可选教学反馈。
- `ai_model/unet_measurement.py`：加载 `models/hysteresis_unet_v1.keras`，裁剪固定屏幕区域、分割回线、检测当前图网格和零轴、输出几何测量。
- `desktop_capture/main.py`：Tkinter 上位机，负责串口通信、参数表调度、状态确认、自动采集恢复。
- `desktop_capture/adb_camera.py`：ADB 命令、拍照、拉取图像与可取消操作封装。
- `desktop_capture/dataset_manifest.py`：成功采集记录和断点判断。
- `firmware/User/hyst_model.[ch]`：磁滞轨迹计算与双 DAC 缓冲。
- `firmware/User/bt_protocol.[ch]`：蓝牙命令解析、参数校验与状态反馈。
- `ai_pipeline/`：数据准备、TensorFlow 训练、预测、网格/参数评估工具。

## 设计约束

部署代码与训练代码分开：部署只读 `models/hysteresis_unet_v1.keras`，训练不作为 Web 在线行为。模型和数据都使用项目根目录相对路径。上位机的设备异常在工作线程中捕获并回传 UI 提示，不能因为手机/串口暂时缺失而使 UI 主线程崩溃。

## 版本兼容

固件支持 `SETALL`，桌面端在旧固件不支持时保留逐条 `SET` 与 `APPLY` 的兼容路径。旧 Web、旧 PyTorch 脚本和历史视觉结果保存在 `legacy/`，不再作为正式入口。
