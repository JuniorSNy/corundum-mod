# Raw TX FPGA 下一阶段设计研究（2026-10-02）

## 研究基线与结论

源码基线 `0784146c`，分支 `feature/au250-fec-off`。本研究阅读当前五个 app RTL、
MR/QP/core/Alveo 测试、辅助驱动、CQ 用户态轮询及 2026-09-22 审查；
以 Corundum `fpga/common/rtl/tx_engine.v` 的 descriptor table、阶段指针、
DMA/TX completion 对应关系作为并发结构参考。

建议下一步先建立可观测的单 QP 性能和故障基线，再实现单 QP 的多个在途 WQE，
随后引入多 QP。停止恢复是并发扩展的前置契约。MR 分页可以独立推进设计，
但普通用户内存注册必须与驱动生命周期一起实现。
当前仍是 raw Ethernet TX 原型；这些工作不等同于实现 RoCE 或可靠 RDMA。

本轮没有修改 RTL、驱动、测试行为或旧板级产物；本文件给出后续实现方案和验收条件。

## 当前结构与实际证据

| 路径 | 源码证据 | 推论/限制 |
|---|---|---|
| SQ→MR→payload→TX completion→CQ | `rtl/raw_packet_qp.v` 的 `ST_IDLE` 至 `ST_CQ_WAIT` | 单在途，CQ DMA status 成功后才启动下一条 |
| DMA staging→AXIS | `rtl/raw_dma_read.v` 的 `ST_DMA/ST_SOURCE/ST_STREAM` | 整帧 DMA 成功才发送，错误不会发送旧缓冲；固定 RAM 地址 0 |
| MR | `rtl/raw_mr_table.v` 的 `index/offset/translated/error_comb` | 16 项，全 key/PD/权限/范围/溢出检查；仅连续 DMA 区间 |
| TX 仲裁与完成分流 | `rtl/mqnic_app_block_raw_packet.v` 的 `tx_mux_inst/raw_tx_cpl` | port 0，raw tag 0，整帧 round-robin；普通 TX 不同命名空间 |
| CSR | `rtl/raw_packet_csr.v` 的 `config_open/reset_queues/mr_commit` | 禁用且 idle 时修改配置；可组合参数尚未从 QP 顶层透传和独立验证 |
| 停止 | `modules/mqnic_app_raw_packet/main.c` 的 `raw_stop/raw_free` | 100 ms app busy 轮询；超时 unsafe，最终泄漏 DMA，没有可回收隔离管理 |

已核对 `/tmp/raw-final-regression.log` 的 11 个 pytest case 正常结束记录，
并解析 `/tmp/raw-packet-final-20261002/` 的实际 XML：7 个功能 pytest case
对应 8 个无 failure/error/skipped 的 cocotb test，板级包括 raw 场景和原普通 NIC 回归。
另 4 个 pytest case 检查 runner 对 pass/fail/skip/空结果的处理，不能算作 4 个硬件场景。
本轮重新运行当前 MR 与 QP 256/512：**3 passed in 4.04s**，构建记录
`/tmp/raw-next-step-audit-20261002/`。本轮没有重新执行完整板级回归。

旧审查中的测试目录、runner 等待路径、2×1 拓扑、双端口普通 TX/RX、逐流顺序、
CQ commit 轮询已有正式实现，不能继续把它们列成未完成项。
但当前集成场景仅发送有限帧，不能据此声称有吞吐、长期公平性或故障恢复保证。
没有新增 Vivado 综合、布局布线、时序或物理 AU250 发包证据。

## A：可观测性、接口契约与故障测试

先增加独立统计/诊断寄存器块，透传 `RB_BASE_ADDR/RB_NEXT_PTR` 并验证链式发现，
保持现有 SQE/CQE/ioctl 和现有块布局。统计建议包含：SQ accepted、MR reject、
payload DMA error、TX completion、CQ published-to-DMA、CQ full stall cycles、
DMA descriptor/status wait cycles、TX backpressure、当前阶段和 outstanding 数量。
“CQ published-to-DMA”不得命名为“主机已收到 CQE”。明确计数器位宽、回绕和快照语义。
软件 ABI 的寄存器/字段常量可以从一个小型描述表生成 C/Python/Verilog 文件，
或先增加跨语言一致性检查；QP 单测仍有字面量，不能认为 ABI 重复表达已消除。

当前一条 WQE 的间隔由 SQ DMA、MR、payload DMA、AXIS、MAC completion 和 CQ DMA
串行组成。增加 AXIS 位宽不会消除这些等待。先测 64/1514/9214 字节的 WQE/s、
payload 字节率、各阶段等待周期、从 producer 发布到 CQ commit 的延迟分布，
再决定并发深度。不从功能仿真时间推导 PCIe 或 100G 线速承诺。

| 新测试 | 当前覆盖及缺口 | 验收 |
|---|---|---|
| CSR 独立测试 | 已有忙时写和部分 pointer 错误；无独立 CSR DUT | 分离 AW/W、B/R 反压、partial strobe、地址/长度非法、非零块偏移及 next pointer |
| DMA 独立测试 | QP 间接覆盖；descriptor/TX 有固定周期暂停 | 每段 RAM 独立暂停、done 反压、错误 tag、状态迟到、无 status、边界长度；协议有效字段在反压期间稳定 |
| CQ 满和发布 | 已有满 CQ，但用 malformed SQE；人为延迟 commit | 满 CQ 加合法长帧，不提前消耗未预留资源；不同 posted-write 延迟仍仅在正确 commit 后读取 |
| 停止矩阵 | 目前 stop 位于等待 MAC completion 阶段 | 在 SQ descriptor/status、payload descriptor/status、TX 中间、CQ descriptor/status 各阶段 disable；不启动新 WQE，在途正确排空 |
| 故障矩阵 | 已有 SQ/payload/CQ DMA 错误和清错重启 | status 丢失/错误 tag/重复/迟到均不得假完成；故障上下文可诊断；超时不能被算作通过 |
| 计数器回绕 | 已有 ring slot 多次绕环；不是 32 位 counter 回绕 | 单独测试近 `0xffffffff` 的 modular arithmetic 和 commit 0；helper sequence 应明确取模，必要时用标注的白盒初始化辅助测试 |
| 两端口共存 | 有限每流顺序和后续 RX | raw/normal 持续同时有数据、MAC 反压、不同帧长；验证帧不交织、每流顺序和无饥饿 |

测试应记录接口握手和 descriptor/tag/地址，不以修改 DUT 内部变量代替正常业务。
协议监视器按 AXIL、AXIS、segmented RAM 分开，故障注入和预期结果由独立 scoreboard 管理。
集成测试目前使用 `pkt in raw` 区分流；新增测试使用显式流 ID/序号，允许不同流携带相同内容。
随机测试固定 seed 并记录 seed，保留可重复定向边界用例。

## B：明确 stop/drain/reset 的资源安全边界

`enable=0` 当前只阻止下一次 `ST_IDLE` 启动，不取消已发给父 DMA 的请求。
DMA status 和 MAC completion 没有返回时，FSM 可以无限等待。这是现状，不应把
增加一个本地 timeout 并直接释放缓冲当作修复。

建议定义状态：RUNNING→DRAINING→STOPPED；排空超时进入 FAULTED，保留缓冲和 MR 引用，
禁止新提交。只有父设备协调的 DMA 静默/复位、posted-write 排空及旧完成处理得到证明后，
才能进入 RECOVERING 并重新创建队列。app-only reset 会丢失上下文，不能证明父 DMA 已取消。
父设备级恢复可能影响普通 NIC，需定义通知和恢复顺序，不能藏在 app 私有 STOP 中。

watchdog 第一版用于锁存 stage/tag/address/sequence 和诊断，不伪造 MAC 成功 CQE，
不自动重用 tag、MR 或 RAM。恢复时需防迟到 status/completion 关联到新操作：
采用可传递的 generation tag 或确保完整排空；generation 回绕也必须有重用约束。
当前 raw tag 0 在 `ST_DATA/ST_TX_WAIT` 接收 completion，正常路径已验证；
跨复位的旧 completion 场景没有验证，不声称已经发现正常路径误完成。

驱动将 unsafe 分配改为由父设备恢复管理器持有的显式隔离对象，保存 device/mapping 引用，
提供安全回收和错误报告。验收须包括真实用户进程异常退出、保留 mmap/fork、
驱动 remove、DMA status 丢失、复位后重开；Python RootComplex 不能替代这些 Linux 测试。

## C：单 QP 多在途流水线

保留 app ABI 和整帧 staging。先做可参数化的 2/4/8 个操作槽，默认可继续为 1，
使现有回归作为兼容基线。取 SQE、MR、payload DMA、TX 和 CQ 分别通过槽索引交接，
允许下一条 SQE/payload 与上一条 MAC/CQ 等待重叠。参考 `tx_engine.v` 的
`desc_table_active/data_fetched/tx_done/cpl_write_done` 和阶段指针，
复用管理方式，不直接搬普通 NIC 的 descriptor/CQ ABI。

每个操作上下文至少保存 sequence、wr_id、length、lkey/PD、translated address、
result、阶段完成位、buffer slot 和关联 tag。单 QP 第一版按 SQ 顺序发送和发布 CQ，
允许 DMA 返回乱序；错误 WQE 也必须占据自己的完成顺序。延后乱序 CQ 设计。

实现必须同时满足：

1. **CQ credit**：启动 WQE 前预留一个 CQ 槽；约束
   `cq_prod - cq_cons + reserved_completions <= ring_size`。
   不能沿用单在途的仅检查 `cq_pending < ring_size` 后任意启动多个操作。
2. **tag**：区分操作槽/阶段；按 app 实际暴露宽度制定 DMA 编码。
   `mqnic_core.v` 会扣除接口/控制数据 mux 位，不能假设父 DMA 的全部 tag 位可用。
   普通 TX 在 `tx_engine.v` 设置 TX tag 最高位 1；raw 可使用其余命名空间，
   wrapper 必须从“等于 0”改为按 raw 命名空间识别并传递槽索引。
3. **RAM**：`raw_dma_read` 接收 RAM 起始地址，划分不重叠帧槽。
   8×16 KiB 的简单起步方案需要 128 KiB payload 逻辑容量；
   这只是容量估算，实际 BRAM/URAM 映射及时序由综合决定。
   保持 DMA 成功前不发帧；单个连续 AXIS source 可先按 SQ 顺序读各槽。
4. **生命周期**：payload buffer 在 AXIS source 已读完且无未完成 RAM 访问后才能复用；
   操作上下文继续等待 MAC/CQ。CQE 每槽保存到对应 DMA 读取完成，
   不能让多笔 CQ DMA 共用当前组合 `cqe` 和 RAM 地址 0。
5. **计数器**：分离内部 fetch/issue/retire 指针；公开 SQ consumer、CQ producer
   仍保持当前 ABI 语义。只有 CQ DMA 成功才推进原公开计数器。

验收：乱序 DMA status、MAC completion 延迟、CQ DMA 反压、CQ credit 耗尽、
buffer/tag wrap、混合成功/错误、正常 NIC 共存，以及所有槽的 stop/drain。
同条件对比单在途与多在途吞吐和延迟，测量资源变化；不预先承诺 100G 线速。

## D：动态连续 MR，随后分页 MR

现有 MR 保护检查应保留。16 项异步索引数组加 64/65 位算术适合小表，
扩大成数千项前先综合查看关键路径和 RAM 推断；必要时采用同步表读取、
流水化保护检查/地址转换，并通过 ready/valid 关联上下文。

第一步做受驱动管理的动态连续 DMA MR：分配 key generation、PD、权限、引用计数，
注销先阻止新查询，再等待引用清零后撤销映射。CSR shadow→commit 原子更新继续保留；
现有配置只有 disabled/idle 可更新，应明确第一版沿用此限制还是新增受控在线更新协议。

普通用户内存需要 pin、DMA 映射、失败回滚、unmap/unpin 和退出/复位生命周期。
硬件使用 DMA API 返回的设备地址，而不是用户虚拟地址或从 pagemap 得到的 PFN。
IOMMU 存在不等于 `dma_map_sg` 必定返回一个连续段；不能仅把 coherent 分配改成 1 GiB
就声称支持用户页注册。
依据：[Linux DMA API](https://docs.kernel.org/core-api/dma-api-howto.html)、
[pin_user_pages](https://docs.kernel.org/core-api/pin_user_pages.html)。

分页方案为 MR 元数据→MTT/page translation→一个或多个 payload DMA descriptor。
拆分跨页请求，聚合每段 status，全部成功后发送整帧；任何段错误仅产生一条错误 CQE。
选择 4 KiB/大页混合、页表位置和 translation cache 之前，测算容量与 miss 延迟。
验收包括不连续 DMA 段、页边界短尾、第二段错误、旧 key 重用、注销与在途 DMA 竞争。

## E：多 QP、板级签核与对端证据

多 QP 应复用共享 MR、DMA/缓冲池、TX 仲裁和 CQ writer，新增 QP context 表和调度，
不按 QP 数量复制整套 staging RAM。每 QP 保存 SQ/CQ 指针、PD、enable/error、credits、
port 及可运行状态；公平调度跳过 CQ 满/故障 QP，保持每 QP 顺序。
现有 port/flags 字段不应悄悄换义；新 capability/版本化配置描述多 QP/多端口能力。
验收一条 QP 满 CQ/故障不阻塞其它 QP，PD 隔离、端口选择、独立停止和共享池回收。

Vivado 基线可以在 A/B 期间单独推进：为 raw app 构建生成独立输出目录，记录完整
参数和源码 revision，检查综合 RAM 推断、资源、关键路径、CDC 和实现后时序。
原有 AU250 bitstream、报告和 rev/ 不能作为此 app 的签核证据，也不能覆盖。
性能流水线应根据实际关键路径调整，而不是凭 RTL 外观断定 Fmax。

物理板阶段先加载父 mqnic 与 auxiliary driver，确认 BAR2/普通双端口业务，再执行
raw 发包、错误 MR、CQ 满、STOP/reopen。对端用 DPDK 或 XDP+AF_XDP 按测试批次、
流 ID、序号、有效长度和可重复 payload 校验内容/丢包/重复/乱序；
记录接收端自身队列丢包，处理短帧 padding 和 jumbo frame 配置。
MAC CQE 与对端接收统计分别报告，成功 CQE 不是远端收到的证明。
RoCE header、raw RX、可靠传输和 verbs provider 均作为后续独立规格，不并入本轮重构。

## 建议可审查的变更顺序

1. 单独提交 CSR/诊断与缺口测试，建立性能基线；不修改 SQE/CQE ABI。
2. 单独提交停止/故障契约和驱动隔离恢复；需要父驱动支持的部分明确记录依赖。
3. 单独提交单 QP 操作表、tag/credit/buffer 管理和乱序 DMA 回归；然后实测并发收益。
4. 分开提交动态连续 MR、分页 translator 与 Linux 用户页注册；测试硬件和软件各自边界。
5. 最后增加多 QP 调度/端口配置；物理签核与对端结果始终按对应 revision 单列。

每个阶段保留 MR/QP/core/Alveo 原回归；测试覆盖范围随接口变化扩大。
研究完成不代表上述未来阶段已实施或通过验收。
