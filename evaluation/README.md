# U-Net 部署模型验证记录（2026-09-19）

- 数据源：136 份人工标注，源数据指纹见 `validation_summary.json`。
- 固定划分：110 张训练、26 张验证，随机种子 `20260814`，纳入全部 9 类拍摄条件。
- 部署模型：`../models/hysteresis_unet_v1.keras`。
- 原图 ROI：`(1927, 307, 3878, 2191)`；模型输入：`640 x 600`。
- 验证结果：平均 Dice `0.8952`、中位 Dice `0.9035`、最低单图 Dice `0.8141`、平均 IoU `0.8117`。
- CPU 单图推理耗时中位数：约 `0.205 s`（TensorFlow 2.20.0，本机记录）。
- 模型 SHA-256：`60d8e72c81b1121454ae80741041a2be3b10c53a11c0c1b4ca6a59b5948b960e`。

`history.csv` 和 `run_config.json` 记录训练过程；`per_image_metrics.csv` 为逐图指标；`validation_previews/` 中红色为人工标注、蓝色为模型预测。该验证集来自同一固定采集装置，不是跨设备独立测试。
