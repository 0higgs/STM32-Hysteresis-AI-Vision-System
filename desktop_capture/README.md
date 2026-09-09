# Windows 自动采集控制端

正式入口是 `main.py`，用于将参数表逐行下发到 JDY-34/STM32，并在示波器稳定后通过有线 ADB 控制 Android 手机拍照。

## 安装与启动

```powershell
python -m pip install -r requirements.txt
python main.py
```

需要 Python、`pyserial`、`openpyxl` 以及 Android Platform Tools。ADB 查找顺序为：`ADB_PATH` 环境变量、系统 `PATH`、`%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe`，最后可用界面“浏览”手动选择。串口或 ADB 不可用时界面会显示失败原因；硬件不在场时程序不应因设备缺失崩溃。

## 使用流程

1. 将 JDY-34 连接为 Windows 串口并在界面刷新、连接；使用 `PING` 或“读取状态”确认通讯。
2. 手机开启开发者选项和 USB 调试，连接数据线，在手机上允许调试；点击“检测手机”。
3. 导入 `parameter_table_template.csv` 或等价 CSV/XLSX。每行应有唯一 `sample_id` 与固件参数列。
4. 选择输出目录、稳定等待时间、每组张数、重试次数和快门方式，开始自动拍照。
5. 程序执行 `SETALL`；旧固件不支持时回退到兼容的多条 `SET` 加 `APPLY`。成功图像按 sample_id 命名，并记录到 manifest。

## 断点续拍与重试

采集清单由 `dataset_manifest.py` 维护。启动同一输出目录时，程序读取已成功记录的 `sample_id`/序号并跳过，避免覆盖；拍摄、回传或短暂 ADB 异常按界面重试次数恢复。若设备状态持续不一致，应停止任务、保留 manifest，排除供电/蓝牙/USB 问题后从同一目录重新开始。

## 常见错误

- **未发现手机**：检查数据线、USB 调试和授权弹窗；运行 `adb devices` 查看状态。
- **unauthorized**：在手机撤销并重新允许 USB 调试授权。
- **ADB 找不到**：设置 `ADB_PATH` 或在界面选择 `adb.exe`。
- **串口读取状态不一致**：确认 JDY-34 连接、波特率和固件协议版本；优先 `SETALL`，必要时使用兼容 `SET` 路径。
- **停止按钮等待中**：当前 ADB 子操作完成后会响应停止；可保留 manifest 后再次启动续拍。
