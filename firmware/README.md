# STM32F407 磁滞回线发生固件

## 工程与硬件

- MCU：STM32F407（Keil MDK-ARM 工程）。
- 工程入口：`Projects/MDK-ARM/atk_f407.uvprojx`。
- DAC 映射：`PA5 / DAC2 -> 示波器 X`；`PA4 / DAC1 -> 示波器 Y`。
- 无线串口：JDY-34，经 USART2（PA2/PA3）与上位机通讯；当前实验界面使用 9600 baud。
- 发布镜像：`../release/firmware/hysteresis_v1.hex`。

## 原创与依赖边界

项目自研的核心实现集中在 `User/`，尤其是 `main.c`、`bt_protocol.[ch]`、`hyst_model.[ch]` 及其实际调用模块。`Drivers/`、`Middlewares/`、CMSIS、HAL、启动文件以及由 Keil/ST 工具生成的工程配置均为第三方框架或工具依赖；它们必须保留以便构建，但不应列为软著原创源码。

## 构建方法

1. 用 Keil MDK-ARM 打开 `Projects/MDK-ARM/atk_f407.uvprojx`。
2. 确认目标芯片、调试器和板级时钟配置与实验硬件一致。
3. Build 工程并下载到开发板。构建产生的 `Output/` 目录已被 Git 忽略；若需发布固件，只更新经过验证的 `release/firmware/hysteresis_v1.hex`。

## 通信与参数

PC 与固件的协议定义在 `User/bt_protocol.c`。支持 `PING`、`CAPS`、`GET STATUS`、`SET`、`SETALL`、`APPLY` 与 `PRESET`；完整格式、响应和错误见 [../docs/protocol.md](../docs/protocol.md)。不要在未同步修改桌面端与固件端的情况下改变字段顺序、范围或语义。

磁滞回线计算由 `User/hyst_model.c` 实现。它输出显示/实验控制轨迹，部分参数存在归一化，不能把图像测得格数直接等同于未经标定的物理量。
