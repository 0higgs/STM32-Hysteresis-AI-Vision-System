# 数据集管理

## 版本与范围

当前数据资产对应 V1.0 采集/标注流程。原始 500 张 JPG 约 1 GB，不进入 Git，以避免仓库膨胀、复制困难和意外发布。原图仅保存在经授权的本地或发布附件中。

## 目录约定

| 路径 | 内容 |
| --- | --- |
| `metadata/manifest.csv` | 自动采集时记录的图像、sample_id、状态及关联信息。 |
| `metadata/parameters.csv` | 每个采集样本的 STM32 控制参数真值。 |
| `labelme_annotations/labels.txt` | 标签定义，当前主标签为 `hysteresis_loop`。 |
| `labelme_annotations/annotations/` | 与图片同名的 LabelMe JSON。 |
| `../dataset/images/` | 本机原图位置，不纳入 Git。 |

`sample_id` 与图片基名、LabelMe JSON 基名必须一一对应，例如 `IMG_0001.jpg` 与 `IMG_0001.json`。标注表达的是图像中可见的荧光磁滞轨迹；不要擅自改变标签语义或把不可见的曲线延伸补成标签。

## metadata 字段与复现

`parameters.csv` 保存 HMAX、HC、BR、BS、LOOP_HZ、增益、偏置、耦合、不对称和 DAC 幅度等采集控制量。它用于实验追溯、监督和可识别性评估；未知图像推理不能把它作为输入。完成原图定位和 JSON 对应后，按 [../ai_pipeline/README.md](../ai_pipeline/README.md) 重建训练数据集。
