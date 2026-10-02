# 目标：单 QP 多在途 raw TX，并通过 Corundum cocotb 验证

## 目标定义

以 `0784146c` 的 raw Ethernet TX app 为基线，把一个在途 WQE 的串行路径改进为
**可配置 1/2/4 个在途 WQE 的单 QP 流水线**。下一条 SQE 获取、MR 校验、payload DMA
能够与前一条 MAC completion/CQ DMA 等待重叠，同时保持 SQ 顺序发帧和发布 CQE。
参考 Corundum 原有 RTL 和验证方式，建立可重复、有截止、自动断言的 cocotb 回归。

本阶段以 RTL 功能仿真和 PCIe/Alveo 核集成仿真验收，**不进行上板测试**。
Vivado 综合、实现和时序签核属于后续阶段，不是本目标的完成条件。
完成后仍称为 raw TX RDMA 基础模块，不称为完整 RDMA 网卡。

## 边界与兼容要求

- 新硬件放在 `mqnic_app_block` 内，继续复用 Corundum DMA、segmented RAM、AXIS、MAC 接口。
- 保持 APP_ID、BAR2、32 字节 SQE/CQE、commit_sequence、现有寄存器和 ioctl 语义。
- 保持 16 项连续 DMA MR、完整 lkey/PD/权限/范围/溢出校验；帧长仍为 14..9214。
- 保持一个 raw QP、port 0；其它端口普通 NIC TX/RX 继续工作。
- 参数建议命名 `OP_TABLE_SIZE`，支持 1/2/4；顶层透传到 app，测试不能只改底层参数。
- 遵循同步高有效复位、`*_reg/*_next` 和 Corundum 原接口命名。
- 多 QP、分页 MTT、任意用户页注册、raw RX、RoCE、重传、verbs 不纳入本阶段。
- 系统级父 DMA 静默和真实 Linux 恢复不能由 cocotb 模型证明，本阶段不宣称完成。

## 硬件改进内容

| 改进 | 设计要求 | Corundum 参考 |
|---|---|---|
| 操作上下文表 | 每槽保存 SQ sequence、wr_id、length、转换地址、错误、阶段完成位、buffer/tag | `fpga/common/rtl/tx_engine.v` 的 descriptor table 和阶段指针 |
| 流水线阶段 | SQ fetch、MR、payload DMA、TX、CQ writer 分别推进，通过槽索引关联 | `tx_engine.v`，结合当前 `raw_packet_qp.v` |
| 帧缓冲池 | 每槽独立 RAM 区间，DMA 成功后才发整帧；地址不再全部固定为 0 | `dma_psdpram`、`dma_client_axis_source` |
| tag 对应 | 多个 DMA/TX 完成精确回到对应槽，保留普通 TX tag 最高位为 1 的约定 | `mqnic_core.v` 的 DMA mux 与 `tx_engine.v` TX tag |
| CQ writer | 每个在途 CQE 独立存储，不能共用变化中的组合 CQE；按 SQ 顺序写回 | `cpl_write.v` 的操作管理方式，保持 raw CQE ABI |
| 停止和诊断 | disable 后停止接收新 WQE；排空已接受操作；故障保留状态用于诊断 | 当前 CSR/STOP 契约，新增状态/计数块不移动旧布局 |

必须明确以下资源不变量：

1. `active_operations <= OP_TABLE_SIZE`，每个活动槽最多对应一条 WQE。
2. 启动前预留 CQ 槽：`cq_prod - cq_cons + reserved_completions <= ring_size`。
3. 活动缓冲区不重叠；payload buffer 仅在 AXIS source 读完且没有遗留 RAM 访问后复用。
4. CQE 存储保持到相应 DMA 读取结束；操作上下文保持到完成流程结束。
5. MR/格式校验失败不发起 payload DMA；payload DMA 失败不输出帧。
6. 成功 CQE 必须对应本操作的 MAC TX completion；错误完成不能挪用其它槽的结果。
7. 内部 fetch/issue/retire 指针分离，公开 SQ consumer/CQ producer 保持现有含义。
8. DMA tag 以 app 实际接口位宽为准，预留 mux 使用的位；不足时 elaboration 明确失败。

错误 tag、非活动槽完成或已完成槽的重复完成不得推进其它操作；记录诊断事件。
tag 重用、generation 位和正常排空后的重用条件必须在实现前写成接口契约。
有限 generation 不能解决无限迟到完成；故障后不得仅 reset app 就重用旧资源。

## 验证工具链与组织

使用本机已有 Python/cocotb 1.7.2、cocotb-test、Icarus 和 cocotbext-axi/pcie/eth。
沿用 `tb/<dut>/Makefile` 与 pytest，复用本项目同步 `sim_runner.py`，避免退回已经复现挂起的
asyncio runner。正常子进程退出、预期数量 XML、无 failure/error/skipped 缺一不可。
新增 cocotb test 后同步更新 expected_tests，不固定沿用当前 11 个 pytest case 数量。

| 验证层 | 入口/模型 | 本阶段必须证明 |
|---|---|---|
| MR 单元 | `tb/raw_mr_table` | 原保护与边界行为保持 |
| DMA/CSR 单元 | 新增 `tb/raw_dma_read`、`tb/raw_packet_csr` | 每段 RAM、AXIL/AXIS 反压、稳定性、错误 tag、配置锁定 |
| QP 单元 | `tb/raw_packet_qp`，Host 与 PsdpRam 模型 | OP_TABLE_SIZE=1/2/4 × AXIS=256/512，独立 scoreboard |
| PCIe 核集成 | `tb/mqnic_core_pcie_us`，RootComplex/PCIe/EthMac | 原 1×1/1×2/2×1 保留，2×1 必测三个操作深度 |
| Alveo 核集成 | `tb/fpga_core/test_fpga_core_raw_packet.py` | 启用 app，AU250 2×1；深度 1 和 4，raw 场景及原普通 NIC 回归 |

Alveo 测试继续复用原 `fpga_core` 测试环境，只用单独变体启用 app。
它是板级核心 RTL 仿真，没有 GTY/CMAC 硬 IP 或 Linux 驱动运行。
形式验证可另行开展；本阶段的 cocotb 不变量断言不称为形式证明。

## 定向场景与验收数据

### 功能与并发

- 长度 14/60/64/65/127/1514/4097/9214，未对齐地址、RAM 槽首尾、MR 边界。
- 连续提交多个 WQE，按不同顺序返回 payload DMA status，验证 TX/CQ 顺序。
- 延迟第一条 MAC completion，至少第二条 payload DMA 已被接收；
  第一条 CQ commit 未发布时，后续帧能够发送。这两项必须由外部接口事件证明。
- 延迟 CQ DMA，继续其它操作直到 CQ credit 耗尽；耗尽后不多取 SQE/覆盖 CQ。
- 混合好/坏 lkey、PD、权限、长度、flags，以及 SQ/payload/CQ DMA 错误。
- 环槽、操作槽、buffer/tag 多次复用；另测 32 位指针/commit 回绕，不能用环槽绕回代替。
- 同一流按 sequence 对比，完整字节比较；流 ID 独立于 payload，支持重复内容。

### 反压、停止与故障

- descriptor ready、AXIS ready、CQ RAM 各段响应和 AXIL B/R 独立反压；
  协议监视器检查 valid 未被接受时有效字段保持。
- 在 SQ/payload descriptor 与 status 等待、TX 中间、MAC completion、CQ DMA 等待阶段 STOP。
- STOP 后不接受新 WQE；正常返回条件下，在途操作恰好排空一次，停止后可重启。
- status 丢失不产生虚假完成；在明确的诊断截止内识别停滞，锁存故障上下文、禁止新接受，
  保留资源。迟到 status 不得让已隔离资源自动复用。
- CQ DMA fatal 时停止新接受；保留所有未可靠发布的完成上下文，不能假推进公开计数器。
- reset 故障测试只在明确建模的父 DMA 同步复位/排空条件下测试重建；
  app-only reset 后仍有父 DMA 写入的情况必须被标为不支持的使用方式。
- 普通 TX completion 独立分流；两端口正常 TX/RX 与 raw 持续共存，不交织帧、不丢内容。

### 随机与性能

QP 单元每种参数组合运行至少 1024 条混合 WQE，固定并记录至少 3 个随机 seed。
每条最终结果独立核对 wr_id/status/length/sequence/commit，无丢失、重复、错槽。
有意注入无法完成的故障应由测试明确判定为预期故障状态，而不是跳过断言或忽略 timeout。
每个接口等待有截止，总测试截止按工作量设置；超时输出最近 descriptor/tag/phase。

性能仿真采用相同帧长、DMA/status 延迟、MAC completion 延迟和随机 seed，比较深度 1/2/4。
输出稳态 WQE/s、payload 字节率、CQ commit 延迟和阶段等待周期，计时使用仿真时间。
必达条件是外部事件证明存在流水线重叠；另设受控延迟场景的改进目标：
深度 4 的稳态 WQE/s 至少为深度 1 的 2 倍。
该场景的延迟参数在改动前固定，不能为达标临时调整；不从该指标推导 100G 线速。
至少报告 64/1514/9214 三种帧长的结果，即使某种没有提升也须解释瓶颈。

## 实施顺序与关卡

| 阶段 | 交付 | 进入下一阶段的证据 |
|---|---|---|
| G0 当前基线 | 当前源码 revision/dirty diff、环境版本、完整回归、基线计时 | 全回归正常退出，核对 app 已启用；原吞吐和延迟可重复 |
| G1 测试能力 | 独立 CSR/DMA 测试、tag/credit/RAM 监视器、乱序与故障注入 | 现有行为无回归，新单在途契约通过；未来并发预期明确标为尚未满足 |
| G2 深度 1 重构 | 拆操作上下文、CQ 存储和内部阶段，仍单在途 | 原行为和所有单在途错误/STOP 场景通过 |
| G3 深度 2/4 | 多槽 RAM、tag、CQ credit、调度和诊断 | QP 六种参数组合、随机/故障矩阵和重叠证据通过 |
| G4 集成验收 | PCIe 三种拓扑、AU250 2×1 app-enabled、普通 NIC 回归、性能对比 | 全部明确必测组合通过；剩余限制如实记录 |

提交粒度按 G1/G2/G3/G4 划分，每个实现提交附对应验证记录。
G0 不把文档或旧 PASS 记录代替当前回归；G2 不靠删减测试实现兼容。
不修改或清理已有 AU250 bitstream、报告和 rev/。

## 已有命令与后续入口

当前完整基线：

```bash
cd /home/sj/corundum/fpga/app/raw_packet
PYTHON_BIN=/home/sj/miniforge3/envs/corundum-test/bin/python \
RAW_SIM_BUILD_ROOT=/tmp/raw-tx-goal-baseline \
bash tb/run_tests.sh
```

按层运行：

```bash
cd /home/sj/corundum/fpga/app/raw_packet
make -C tb/raw_mr_table PYTHON_BIN=/home/sj/miniforge3/envs/corundum-test/bin/python
make -C tb/raw_packet_qp PYTHON_BIN=/home/sj/miniforge3/envs/corundum-test/bin/python
make -C tb/mqnic_core_pcie_us PYTHON_BIN=/home/sj/miniforge3/envs/corundum-test/bin/python
make -C tb/fpga_core PYTHON_BIN=/home/sj/miniforge3/envs/corundum-test/bin/python
```

实施时把新增单元和参数矩阵纳入统一入口，不依赖维护者记住额外命令。
失败产物保留 seed、pytest 结果、真实 XML、进程日志、最后接口事件和必要的波形。
每次验收记录源码 hash 和工作树 diff，不能只写分支名；统计性能时注明模型参数。

## 完成条件与当前状态

目标完成要求 G0..G4 全部通过，保持 ABI、MR 保护和普通 NIC 行为，具备深度 1/2/4
的功能证据、故障/STOP 证据、流水线重叠和固定场景性能改进证据。
缺任一必测组合或只有 compile/空 XML 时不得宣布完成。
没有综合、物理时序或上板证据不妨碍本仿真目标完成，但必须继续明确这些限制。

2026-10-02 目标设计时（实施前）：已检查实际源码、Makefile 和 pytest 参数入口；
`pytest --collect-only` 确认当前 11 项收集成功，没有把收集结果算作功能通过。
既有验证记录见 `refactor-20261002.md`；最近 MR/QP 3 项通过见 `next-steps-20261002.md`。
本轮未重新执行 G0 完整回归，尚未实现多在途，也未执行 Vivado 或上板。

随后开始实施；当前进度与运行记录见 `pipeline-validation.md`。以上为目标设计时的历史状态。
