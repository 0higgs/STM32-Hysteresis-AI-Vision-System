# PC 与 STM32 蓝牙串口协议

传输为 ASCII 行，命令和响应以换行结束。当前桌面端连接 JDY-34 时通常使用 9600 baud；实际串口号由 Windows 分配。

| 命令 | 含义 | 典型响应 |
| --- | --- | --- |
| `PING` | 通信探测 | `PONG` |
| `CAPS` | 查询能力 | `CAPS SETALL HYST-V2` |
| `GET STATUS` | 查询待应用/当前参数 | `STATUS HMAX=...` |
| `SET key value` | 修改单一参数 | `OK` 或 `ERR RANGE/PARAM` |
| `SETALL` + 12 参数 | 原子设置完整参数组 | `OK SETALL` 或 `ERR SETALL FORMAT/RANGE` |
| `APPLY` | 将待应用参数更新到输出 | `OK APPLY` |
| `PRESET SOFT/HARD/UNSAT` | 加载预置 | `OK PRESET` 或 `ERR PRESET` |

`SETALL` 的 12 个字段顺序不可改变：`HMAX HC BR BS LOOP_HZ X_GAIN Y_GAIN X_OFFSET Y_OFFSET XY_COUPLING ASYMMETRY AMPLITUDE`。旧固件没有 `SETALL` 时，桌面端会使用兼容的 `SET` 序列与 `APPLY`。

参数合法范围由 `firmware/User/bt_protocol.c` 和 `desktop_capture/main.py` 共同维护；任何改动必须同步两端并完成硬件验证。串口分段或状态回传截断时，上位机应继续等待完整状态而不是将片段误判为成功。
