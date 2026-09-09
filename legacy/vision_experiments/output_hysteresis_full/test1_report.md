# 磁滞回线图像智能分析报告
## 1. 分析模式
当前为归一化分析模式，仅输出 $H^*$、$B^*$ 等相对参数。
## 2. 主要结果
- star_Hm: 0.911458
- star_Bm: 1.14121
- star_Br_abs: 0.189961
- star_Hc_abs: 0.144685
- star_LoopArea: 0.172154

## 3. 实验状态诊断
- 回线提取和分支重建正常，可用于后续参数分析。

## 4. 参数说明
- $B_r$：剩磁，对应 $H=0$ 时的磁感应强度。
- $H_c$：矫顽力，对应 $B=0$ 时的磁场强度。
- LoopArea：磁滞回线面积，可用于表征磁滞损耗。
- 若未输入样品平均磁路长度 $l$ 与截面积 $S$，结果仅作为相对比较，不应写成真实物理单位。

## 5. 输入设置
- image: test1.jpg
- outdir: output_hysteresis_full
- roi: None
- origin: None
- threshold: auto
- min_area: 80
- max_width: 1800
- x_vdiv: None
- y_vdiv: None
- x_divs: 10.0
- y_divs: 8.0
- R1: None
- U: None
- n: 150.0
- N: 50.0
- R2: 10000.0
- C2: 1e-05
- l: None
- S: None
- bins: 140
- min_bin_points: 3
- q_low: 0.18
- q_high: 0.82
- smooth_window: 17
