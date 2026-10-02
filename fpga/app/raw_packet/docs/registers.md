# BAR2 CSR（32 位）

未实现的读取返回 0；写操作要求完整 4 字节 strobe、4 字节对齐。
无效写不返回 AXI SLVERR，而记录 `config_error`；软件应检查该寄存器。
MR 和基础配置只能在 `enable=0 && busy=0` 时改变。

| 偏移 | 寄存器 | 说明 |
|---|---|---|
| 00/04/08 | block type/version/next | 12348110 / 00000100 / 0 |
| 0c | app id | 12348010 |
| 10 | enable | 写 0 停取新 SQE；在途继续排空 |
| 14 | status | bit 0 busy，bit 8 fatal |
| 18 | config_error | 写任意完整 DWORD 清除 |
| 1c | fatal | CQ DMA 失败 0x50\|error；诊断 watchdog 超时 0x60 |
| 20/24 | SQ DMA base | 64 位，32 字节对齐 |
| 28/2c | CQ DMA base | 64 位，32 字节对齐 |
| 30 | ring_log | log2(entries)，1..10 |
| 34 | QP PD | 24 位 |
| 38 | SQ producer | 软件发布；单调推进，不能越过可用容量 |
| 3c | SQ consumer | 只读 |
| 40 | CQ producer | 只读；软件同时检查 CQE commit_sequence |
| 44 | CQ consumer | 软件确认已处理的 CQE |
| 48 | max frame | 只读，默认 9214 |
| 4c | reset queues | 停用且空闲时写 1，清环计数和 fatal |
| 50 | op table size | 只读，配置的最大在途 WQE 数（1/2/4） |
| 54 | active count | 只读，已取 SQE、尚未成功退休的操作数，含隔离上下文 |
| 58 | fetch pointer | 只读，内部 SQ fetch 指针，32 位回绕 |
| 5c | phase | bits 3:0 SQ/MR 前端，bit 5 TX stream，bits 7:6 CQ writer（bit 4 保留） |
| 60 | unexpected count | 只读，忽略的 SQ/payload/CQ DMA status 和 MAC completion 数，32 位回绕 |
| 64 | stall count | 只读，无进展周期计数；watchdog 故障时保持，queue reset 清零 |
| 80 | MR shadow index | 0..15 |
| 84 | MR lkey | 完整 32 位，低 4 位必须等于 index |
| 88 | MR PD | 24 位 |
| 8c | MR flags | bit 31 enable；bit 0 local read，bit 1 local write |
| 90/94 | MR virtual base | 64 位 |
| 98/9c | MR DMA base | 64 位 |
| a0/a4 | MR length | 64 位 |
| a8 | MR commit | 写 1 原子提交 shadow 表项 |

config_error：1 非完整/未对齐写；2 无效 QP 参数或启用失败；
3 SQ producer 越界；4 CQ consumer 越界；5 活动期间改配置；6 未定义写。

配置顺序：停用 → 等 busy=0 → reset queues → 设置 bases/ring/PD → 配 MR shadow
并 commit → enable。MR 失效也是 shadow enable=0 后 commit，不能在线修改在用 MR。
MR local write 权限为后续扩展保留，当前 raw TX 只请求 local read。

`RAW_TX_WATCHDOG_CYCLES=0` 默认关闭自动超时；非零时连续无阶段进展达到配置周期
锁存 fatal=0x60。它停止接收新 WQE，保留 DMA/缓冲所有权，不取消父 PCIe DMA。
迟到 status 可以使已接受的工作排空，但不推进硬件退休计数或释放隔离上下文。
父 DMA 已接受的 CQ 写入仍可能晚到主机；软件需要结合 fatal 和资源归属处理它。
故障时 busy 仍反映未结束的前端、DMA、AXIS、MAC 和 CQ DMA 事务；
已接受但尚未启动 TX 的上下文同样保持 busy，不能借最后一条迟到 DMA status 提前复位。
排空后 busy 可以为 0，而 active count 仍保留失败/未发布上下文，等待显式 queue reset。
busy=0 不证明主机 posted writes 已排空，系统级资源回收仍需父设备协调。
tag generation 跨 queue reset 保留，完整 rst 前必须静默父 DMA；有限 tag 回绕
不能防御无限迟到的旧完成。phase 编码供诊断，见 `raw_packet_qp.v` 的状态常量。
SQ DMA 对外使用操作 generation；串行 SQ reader 内部的固定 tag 仅在外部 tag、
已发 descriptor 和首个有效 status 均匹配后转换。重复 SQ/CQ status 不推进后续操作。
