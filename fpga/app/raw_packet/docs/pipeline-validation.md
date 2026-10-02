# 多在途 raw TX 实施与验证记录

日期：2026-10-02。起始源码 `0784146c`；目标文档已提交 `a10a3fa7`，实现仍在工作树。
目标见 [cocotb 改进目标](goal-cocotb-pipeline.md)。本阶段不上板、不运行 Vivado。

## 已实施

- 单 QP 可配置 1/2/4 个操作槽；顺序 SQ/MR 前端与并发 payload DMA 解耦。
- 每槽 16 KiB，共享 Corundum segmented RAM；DMA 完整成功后按 SQ 顺序发送。
- 按分配 generation 关联 DMA/MAC 完成；TX tag 高位 0，与普通 NIC 命名空间分离。
- 接受前同时预留操作槽和 CQ credit；TX 与 CQ 的内部指针分开，公开 consumer/prod
  保留原退休语义。每槽 CQ 内容保持到其 DMA 读取结束。
- STOP 禁止新接受，已接受操作继续排空；CQ fatal 保留上下文。
- 可选无进展 watchdog 与只读诊断寄存器，默认不启用超时；不伪造 DMA abort。
- Corundum custom app parameter hooks 透传，Alveo 顶层/核心/测试顶层补可选宏通路。
  默认未启用宏的其它 app 参数和端口接口保持原样。
- SQE/CQE、APP_ID、BAR2、ioctl、连续 MR 和 raw port 0 不变。

## 已完成的运行

| 运行 | 结果 | 日志/产物 |
|---|---|---|
| 修改前完整基线 | 11 pytest passed，407.57 s；核对 8 个功能 cocotb XML | `/tmp/raw-pipeline-baseline-20261002.log` 和同名构建目录 |
| 第一版兼容 QP | 6 passed，深度 1/2/4 × AXIS 256/512 | `/tmp/raw-pipeline-second-20261002.log` |
| 并发定向 QP | 6 passed；每组合 3 cocotb 场景 | `/tmp/raw-pipeline-directed-20261002.log` |
| 诊断故障与定向回归 | 7 passed，20.05 s | `/tmp/raw-pipeline-fault-20261002.log` |
| 加接口保持监视器后的定向/故障 | 7 passed，19.04 s | `/tmp/raw-pipeline-monitors.log` |
| 独立 CSR/DMA、故障 | 3 passed，1.39 s | `/tmp/raw-pipeline-units.log` |
| 独立 CQ RAM 段反压 | 1 passed，1.00 s；两个 16-byte 段均实际暂停 | `/tmp/raw-pipeline-segments-retry.log` |
| 八阶段 STOP/drain/resume | 8 passed，10.10 s | `/tmp/raw-pipeline-stop-matrix.log` |
| 32 位计数器与窄 tag 回绕 | 1 passed，3.22 s；仅初始计数为白盒加速，后续均真实接口 | `/tmp/raw-pipeline-wrap.log` |
| 第一版 AU250 2×1 PCIe 核，深度 4 | 1 passed，46.33 s | `/tmp/raw-pipeline-core-first.log` |
| 第一版 Alveo 2×1，深度 4 | 1 pytest passed，304.95 s，含 raw 与原 NIC 两个 cocotb test | `/tmp/raw-pipeline-alveo-first.log` |
| 当前最终功能矩阵 | 22 pytest passed，1094.01 s；18 个功能 XML、32 cocotb 场景全部通过；另含 4 个 runner 合约测试 | `/tmp/raw-pipeline-final-functional.log` 与 `/tmp/raw-pipeline-final-functional/` |
| SQ/MAC/CQ 完成丢失 | 3 passed，1.51 s；watchdog、拒绝未排空 reset、迟到完成仍保留上下文 | `/tmp/raw-pipeline-missing.log` 与 `/tmp/raw-pipeline-missing/` |
| 阶段等待周期指标 | 6 passed，412.09 s；各深度/AXIS 运行 64/1514/9214 B，每长度 96 WQE | `/tmp/raw-pipeline-phases-retry.log` 与 `/tmp/raw-pipeline-phases/` |
| 两端口持续共存 | 2 passed，446.67 s；2×1 深度 1/4，96 raw + 每端口 96 普通 TX/RX，并发与逐流顺序断言 | `/tmp/raw-pipeline-coexist-batched.log` 与 `/tmp/raw-pipeline-coexist-batched/` |
| 修正前正式压力 | 18 passed，3207.53 s；3 seed × 1024 × 六种参数；实际 XML 和性能门禁均通过 | `/tmp/raw-pipeline-stress-seeds.log` 与 `/tmp/raw-pipeline-stress-seeds/` |
| 原单在途性能重复 | 从 `0784146c` 提取源码，AXIS 256/512 各重复两次，四份 XML 通过且指标完全相同 | `/tmp/raw-reference-reproducible.log` 与 `/tmp/raw-reference-reproducible/` |
| SQ/CQ generation 修正定向回归 | 20 passed，24.07 s；包含新隔离场景、六种 QP、丢失完成、STOP、32 位/窄 tag 回绕 | `/tmp/raw-pipeline-sq-generation-fixed.log` 与 `/tmp/raw-pipeline-sq-generation-fixed/` |

上述功能矩阵使用新增诊断之后、SQ generation 修正之前的 RTL，包含五个 PCIe 核配置和 Alveo 深度 1/4，
每个 Alveo 配置均运行 raw 场景及原普通 NIC 回归。runner 的失败、跳过、空 XML
fixture 是预期拒绝的合约测试，不能当作功能通过的 XML。

## 压力与性能验收状态

开发检查：每组合 3 seed × 32 WQE 加固定延迟性能场景，6 passed，389.70 s，
日志 `/tmp/raw-pipeline-stress-smoke.log`。固定模型参数为 payload status 400 ns、
MAC completion 1000 ns、CQ status 128 ns；CQ 另模拟最后 DWORD 晚于 status 发布。
此开发结果不能替代正式的每 seed 1024 条压力要求。

开发性能比值（深度 4 / 深度 1）：

| AXIS | 64 B | 1514 B | 9214 B |
|---|---|---|---|
| 256 | 4.000 | 4.000 | 1.961 |
| 512 | 4.000 | 4.000 | 2.903 |

数据来自 `/tmp/raw-pipeline-stress-smoke/`，是受控仿真模型的吞吐对比，不是 PCIe 或 100G
物理性能。完整验收须取得 18 组正式压力 XML/metrics，运行 `tb/check_pipeline_metrics.py`，
确认 3 seed × 1024、无失败/跳过、相同模型参数、延迟统计以及短帧至少 2 倍提升。

正式压力首轮 `/tmp/raw-pipeline-stress-full/` 已推进到第二个 seed，但接口监视器逐周期
读取闲置信号开销较大；优化为只在 valid 反压/保持检查时读取数据后，中止并重新运行。
被中止轮退出 130，不算通过，没有用增加截止或空 XML 掩盖结果。

随后 `/tmp/raw-pipeline-stress-final.log` 的首个参数组合触及 600 s 进程截止，明确判为
失败并保留日志。原因是把三个 1024-WQE seed 和性能场景合在单个进程中，累计工作量
超出截止。现拆为每 seed 一个 pytest case，仍保留每参数 3 seed × 1024、全部断言和
600 s/进程截止；旧失败和中止的运行不计入验收。

修正前压力与共存结果（已收齐，但不能代替 generation 修正后的验收）：

- `/tmp/raw-pipeline-stress-seeds.log`：18 组，每组 1 seed × 1024；600 s/进程、30 ms 仿真截止，已通过。
- 八阶段 STOP 与 counter/tag wrap 为独立新增测试，统一入口会自动纳入。
- 两端口持续共存：PCIe 核 2×1，深度 1/4，
  96 raw + 每端口 96 普通 TX + 每端口 96 普通 RX 并发。首轮测试误将 9214 B
  传给要求 `len < max_tx_mtu` 的普通 NIC Python 驱动，已保留失败，改普通大帧为
  9014 B 后重新运行；raw 的 9214 B 覆盖及逐包断言保留。串行每包等待 RX 中断的
  `/tmp/raw-pipeline-coexist-final.log` 首组又触及 600 s（另组中止，退出 130）。日志显示
  TX/CQ 持续推进，RX 的 interrupt moderation 延迟逐包累积。随后复用 Corundum 的
  批量发送/逐包接收方式，每批 8 包且 <32 KiB，保持总 96 包和全部断言；
  `/tmp/raw-pipeline-coexist-batched.log` 两组均通过，没有扩大截止或缩减覆盖。

末轮 SQ tag 检查复现了真实关联缺口：固定 SQ tag 的旧 status 能错误启动下一条
payload DMA。失败见 `/tmp/raw-pipeline-sq-generation-repro.log`（明确断言 2 != 1）。
已将 SQ 对外 tag 关联操作 generation，并门控首个已发 descriptor 的 matching status；
SQ reader 内部固定 tag 只在关联成功后转换。异常计数同时覆盖 SQ/payload/CQ/MAC。
新场景还注入 CQ 旧 status 与排空后的重复 status，断言公开指针不推进。定向 20 项已通过，
完整矩阵需重新运行；此前 18 组压力通过不作为修正后源码的验收。

阶段指标记录每个仿真周期是否存在 descriptor ready 等待、SQ/MR 等待、payload status
未回、AXIS 反压、MAC completion 未回、CQ status 未回。它们可以重叠，不能相加成总延迟。
深度 1 的 96×64 B 总观测周期为 41039；深度 4 的 AXIS 256/512 分别为 10474/10469。
这批是独立性能观测场景，不冒充 1024-WQE 随机压力结果。

## 剩余工作与证据边界

已完成 AU250 2×1 深度 4 的 `iverilog -g2005 -Wall` 静态展开；日志位于
`/tmp/raw-pipeline-static/test_mqnic_core_pcie_us/static_2x1_depth4/process-0.log`。
软件工具与 auxiliary 模块编译通过；模块使用 Linux 7.0.0-34 头文件，未加载运行。
Erie 严格格式门禁未通过（4440 errors、287 strict warnings），产物为
`/tmp/raw-pipeline-deliverable-gate.{json,md,log}`；其中有与用户明确要求的 Corundum
命名/复位风格冲突的规则。此门禁不能宣称通过，也不作为功能仿真的替代。

尚需重新完成 generation 修正后的完整矩阵与性能门禁，补齐当前源码与回归产物清单。
因此目标暂未完成。测试进程正常退出、XML 和指标覆盖均需核对，不能仅凭 stdout 点数。
当前无 Vivado、时序、GTY/CMAC 硬 IP、真实 Linux 驱动或上板证据；Python 模型不证明
父 DMA 静默、posted write 排空或真实故障恢复。DMA 地址仍由连续 MR 映射，非用户页注册。
