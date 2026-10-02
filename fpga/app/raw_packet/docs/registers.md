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
| 1c | fatal | CQ DMA 失败原因 |
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
