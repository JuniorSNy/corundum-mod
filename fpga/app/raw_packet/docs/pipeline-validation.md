# 单 QP 多在途 raw TX：实现与 cocotb 验证

开始日期：2026-10-02；最终验收：2026-10-03（Asia/Shanghai）。目标见 [goal-cocotb-pipeline.md](goal-cocotb-pipeline.md)。
基线为 `0784146c`，流水线实现为 `dfbc3647`，fatal 排空修正为 `c1f6bb61`。
本阶段以 cocotb 验收，不上板、不运行 Vivado，也不把 raw TX 模块称为完整 RDMA 网卡。

**当前状态：`c1f6bb61` 完整 cocotb 回归与最终验收门禁通过，G0..G4 完成。**
64 pytest passed，2984.51 s；60 个功能仿真运行、74 个功能 cocotb 场景，另有四个 runner 合约。
机器可读证据见 [pipeline-results-20261002.json](pipeline-results-20261002.json)，记录实际 XML、源码哈希、
参数/seed、吞吐、延迟及阶段指标。旧版 PASS 没有代替修正版验收。

## 实现范围

- 一个 raw QP，支持 1/2/4 个活动 WQE；SQ/MR 前端与 payload DMA、TX、CQ 阶段分离。
- 每槽 16 KiB 独立帧 RAM 区间，复用 Corundum segmented RAM 和 AXIS source。
  多个 payload DMA 可在前一条 MAC/CQ 等待期间推进，发帧与 CQE 退休保持 SQ 顺序。
- 操作 generation 关联 SQ/payload/CQ DMA 和 MAC 完成；重复、错误和非活动 tag 不推进其它槽。
  raw TX tag 最高位为 0，普通 NIC 为 1；queue reset 保留 generation。
- 接受前预留操作槽和 CQ credit；每槽 CQ 数据保持到相应 DMA 读取完成。
- disable 禁止新接受，已接受操作排空；watchdog/CQ fatal 保留未可靠发布的上下文。
  idle 同时要求 TX 指针赶上 fetch 指针，避免迟到 DMA 与 queue reset 同周期释放待发帧。
- app custom parameters 经 PCIe/Alveo 顶层透传；单元默认深度 1，AU250 raw app 配置深度 4。
  APP_ID、BAR2、32-byte SQE/CQE、commit_sequence、旧寄存器/ioctl、连续 MR 与 raw port 0 保持。

## G0..G4 需求与证据

下表对应最终修正版的实际通过证据。测试文件的存在、收集数量和静态展开均不能代替实际通过的 XML。

| 关卡 | 必须证明 | 对应测试或产物 | 当前证据状态 |
|---|---|---|---|
| G0 基线 | 原行为、app-enabled 集成、可重复吞吐/延迟及源码标识 | 修改前完整运行；`tb/reference_benchmark` 从 `0784146c` 提取 RTL，两种 AXIS 各重复两次 | 完整基线 11 pytest passed、407.57 s，含 8 个功能 cocotb 场景；四次原单在途性能重复的 XML 均通过且指标完全相同 |
| G1 验证能力 | MR 保护、独立 CSR/DMA、AXIL/AXIS/descriptor 保持、独立 CQ RAM 段反压、拒绝空/失败/跳过 XML | `raw_mr_table`、`raw_packet_csr`、`raw_dma_read`、`test_raw_packet_qp_segments.py`、`test_sim_runner.py`、Host 协议监视器 | 修正版完整通过。runner fixture 的预期 fail/skip/empty 是拒绝合约，不计作功能 PASS |
| G2 深度 1 | 原 ABI、MR/格式/DMA 错误、CQ 满、公开退休计数、STOP/drain/resume 保持 | `test_raw_packet_qp.py` 的深度 1 × AXIS 256/512；MR/CSR/DMA 单元；原 NIC 回归 | 修正版深度 1 两种位宽及全部单元/错误/停止断言通过 |
| G3 深度 2/4 | 独立 buffer/tag、CQ credit、乱序完成仍顺序 TX/CQ、第一条 MAC/CQ 未完成时后续操作确实推进 | 六种深度/AXIS 组合，`pipeline_reorder_stop`、`pipeline_cq_credit`；每组合 seeds 11/29/101 × 1024 WQE | 修正版完整通过：18 组正式压力，共 18,432 条混合 WQE；相同 seed、断言及 600 s/进程截止 |
| G3 故障与停止 | 八阶段 STOP、真正帧中途 STOP、32-bit 指针/commit 与窄 tag 回绕；SQ/payload/MAC/CQ 丢失、旧 tag；fatal 保留多上下文并拒绝提前 reset | STOP/wrap/fault/missing/SQ-generation 测试；新增 `test_raw_packet_qp_stop_midframe.py` 与两项 `test_raw_packet_qp_drain.py` | 修正版全部通过。真正帧中途 STOP 实测 3 拍/192 B 已握手；两个 fatal drain 场景也在最终完整矩阵通过 |
| G4 集成与普通 NIC | PCIe 1×1/1×2/2×1；2×1 深度 1/2/4；Alveo 2×1 深度 1/4，app-enabled raw 与原 NIC；双端口持续 TX/RX 共存 | 五项 PCIe 核配置，两项 Alveo 配置各含两个 cocotb 场景；两项持续共存配置 | 修正版九项集成 pytest 全部通过。持续共存每配置 96 raw、每端口 96 普通 TX 和 96 RX，逐流顺序、完整字节和并发进展均通过 |
| G4 性能 | 同一固定模型比较深度 1/2/4，64 B 深度 4/1 至少 2×；报告 64/1514/9214 B 吞吐、字节率、commit 延迟及阶段等待周期 | `test_raw_packet_qp_stress.py`、`test_raw_packet_qp_phases.py`、`check_pipeline_metrics.py` | 修正版正式指标重算通过；六种参数均有 3 seed × 1024，以及三种长度的吞吐/延迟/阶段数据 |

持续共存用测试头的 flow marker、port、sequence 分流，再按各流独立序列逐包比较；
不以数据主体的内容查找流。port 0 的 raw/普通 TX 在相同 sequence 和 64/1514/4097 B 长度下
具有相同数据主体，重复内容不会混淆身份。旧短集成场景仍有 `pkt in raw` 分类方式，
不能单独宣称覆盖重复内容；本项证据来自持续共存测试。

## 完整运行与当前验收入口

| 源码/运行 | 实际结果 | 日志与产物 |
|---|---|---|
| `0784146c` 完整基线 | 11 pytest passed，407.57 s；8 个功能 cocotb 场景 | `/tmp/raw-pipeline-baseline-20261002.log`、同名构建目录 |
| `dfbc3647` 完整回归 | 61 pytest passed，4759.21 s；57 个功能运行、71 个功能 cocotb 场景，加 4 个 runner 合约；正式指标门禁通过 | `/tmp/raw-pipeline-final-generation.log`、`/tmp/raw-pipeline-final-generation/`、`/tmp/raw-pipeline-generation-results.json` |
| `c1f6bb61` 四 worker 尝试 | seed 11 触及 600 s 截止；停止后为 1 failed、39 passed，726.55 s，退出 2；不计作完整通过 | `/tmp/raw-pipeline-final-acceptance.log`、同名产物目录 |
| `c1f6bb61` 两 worker 完整运行 | 64 pytest passed，2984.51 s；60 个功能运行、74 个功能 cocotb 场景，加 4 个 runner 合约；进程退出 0，最终矩阵/源码/性能门禁通过 | `/tmp/raw-pipeline-final-acceptance-two.log`、`/tmp/raw-pipeline-final-acceptance-two/` |

最终运行使用冻结的 `/tmp/raw-pipeline-acceptance-source/fpga/app/raw_packet/`，与晋升到主仓库的
`c1f6bb61` 对照。worker 数由 4 改为 2，减少 CPU 争用；WQE 数、断言、延迟参数和每进程截止均不变。
环境为本机 Python `/home/sj/miniforge3/envs/corundum-test/bin/python`、cocotb 1.7.2、Icarus
及 cocotbext-axi/pcie/eth。`tb/run_tests.sh` 自动纳入各 DUT 测试并执行正式压力/性能门禁。

每次仿真保存 RTL/header、测试/helper Python SHA256、参数、seed/scenario、预期场景数与截止。
最终执行 `tb/validate_pipeline_results.py`，先重算性能门禁，再逐一匹配明确的模块/参数/scenario
矩阵、每目录唯一 XML、命名场景和四类 runner fixture，随后核对正常 pytest 退出及源码与提交哈希。
报告补录原 Alveo TB、`mqnic.py`、`dma_psdp_ram.py` 的当前 versioned SHA，明确它们没有在每次
仿真启动时捕获，不能把验收时补录哈希说成全部运行输入都已被记录。

验收工具已用真实产物副本验证：删除一份压力 metric 会拒绝 `Missing stress matrix`，
同目录复制实际 XML 会拒绝两份 XML。负例目录 `/tmp/raw-pipeline-validator-negative-c5rar8gr/`。
这些是工具拒绝行为证据，不替代新源码的功能通过。

## 性能：最终修正版正式结果

以下取自最终 `c1f6bb61` 的 [机器可读报告](pipeline-results-20261002.json)，由正式 XML 与指标门禁核对。
payload status 延迟固定 400 ns、MAC completion 1000 ns、CQ status 128 ns；CQ 最后 DWORD
另延迟 100 ns 发布。每帧长 96 WQE，舍弃前 16 个 commit 后按仿真时间计算稳态吞吐；
commit 延迟从 producer 发布开始计。随机压力每参数组合为 3 seed × 1024，未用开发 32-WQE 结果替代。

| AXIS 位宽 | 64 B 深度 4/1 | 1514 B 深度 4/1 | 9214 B 深度 4/1 |
|---|---|---|---|
| 256 | 4.000× | 4.000× | 1.961× |
| 512 | 4.000× | 4.000× | 2.902× |

修正版 64 B 的深度 1/4 分别为 585480/2341920 WQE/s，两种位宽相同。完整 WQE/s、数据字节率、
commit 延迟分布及阶段等待周期均保存在该报告中。阶段计数记录存在等待条件的周期，条件可以重叠，
不能相加作为总延迟。256-bit、9214 B 时深度 2/4 吞吐相同，说明增加完成并发已不能继续提升该模型
的数据传输速率；结合长帧 AXIS 反压观察，可推断限制转向 RAM/AXIS 传输。此为模型推断，
不是 PCIe/MAC 物理性能或 100G 线速证明。此处已使用修正版实测数据；原单在途 RTL 的四次重复结果另外保存在同一报告。

| AXIS | 帧长 | 深度 1 WQE/s | 深度 2 WQE/s | 深度 4 WQE/s |
|---|---|---:|---:|---:|
| 256 | 64 | 585,480 | 1,170,960 | 2,341,920 |
| 256 | 1514 | 482,625 | 965,251 | 1,930,502 |
| 256 | 9214 | 250,344 | 490,918 | 490,918 |
| 512 | 64 | 585,480 | 1,170,960 | 2,341,920 |
| 512 | 1514 | 525,210 | 1,050,420 | 2,100,840 |
| 512 | 9214 | 334,840 | 669,680 | 971,817 |

| AXIS | 帧长 | commit 中位数，深度 1/2/4（µs） | p99，深度 1/4（µs） |
|---|---|---|---|
| 256 | 64 | 27.316/13.656/6.816 | 27.456/7.656 |
| 256 | 1514 | 33.136/16.556/8.276 | 33.276/9.476 |
| 256 | 9214 | 63.896/32.576/32.576 | 64.036/34.656 |
| 512 | 64 | 27.316/13.656/6.816 | 27.436/7.656 |
| 512 | 1514 | 30.456/15.216/7.596 | 30.596/8.456 |
| 512 | 9214 | 47.776/23.876/16.456 | 47.916/18.536 |

完整 payload 字节率、min/median/p99/max commit 延迟和各阶段等待条件周期见 JSON。
64 B 阶段观测的总周期：深度 1 为 41039，深度 4 在 AXIS 256/512 分别为 10474/10469；
这些是独立 96-WQE 阶段观测，不能冒充 1024-WQE 随机压力。

## 复现过的失败及处理

- 原 asyncio runner 的 child-exit 等待挂起可用无 RTL 的 `tb/runner_diagnostic.py` 复现。
  当前使用同步进程监督、文件日志、明确截止和 XML 合约；超时、空 XML 或 skip 一律不算功能通过。
- 三个 1024-WQE seed 合并在一个进程时触及 600 s；`/tmp/raw-pipeline-stress-final.log` 保留失败。
  改为每 seed 独立 case，仍为六种参数 × 三个 seed × 1024，保留原断言和 600 s 截止。
  更早监视器优化前的中止运行退出 130，同样不计通过。
- 普通 NIC Python 驱动要求 `len < max_tx_mtu`，共存测试首轮误用 9214 B，改为普通 9014 B、raw
  仍覆盖 9214 B。RX 逐包等中断又触及 600 s，随后沿用 Corundum 批量方式，每批 8 包、总量 96
  与逐包断言不变；失败/中止记录保留在 `/tmp/raw-pipeline-coexist-final.log` 等日志。
- 固定 SQ tag 的迟到 status 曾推进下一条 payload，复现见 `/tmp/raw-pipeline-sq-generation-repro.log`。
  generation 对外关联、issued/matching/first-status 门控修正后，旧 status 和重复 SQ/CQ 完成被隔离。
- fatal 排空竞态由同周期迟到 payload status 与 AXIL queue reset 复现，旧版两项失败见
  `/tmp/raw-pipeline-drain-race/old-final.log`。修正 idle 的 TX 排空条件，并测试四槽首 CQ error，
  包含后续好帧、payload error、format error；保留上下文和公开计数，未排空 reset 拒绝。
- 本次四 worker 完整尝试的真实 timeout 如上表所示，不把其已完成 case 拼成完整验收。
  两 worker 重跑使用全新产物目录，正常退出并通过最终检查。

## 复现最终验收

```bash
cd /home/sj/corundum/fpga/app/raw_packet
PYTHON_BIN=/home/sj/miniforge3/envs/corundum-test/bin/python \
RAW_SIM_BUILD_ROOT=/tmp/raw-tx-regression-new \
bash tb/run_tests.sh -n 2 > /tmp/raw-tx-regression-new.log 2>&1
```

使用一个尚不存在的构建目录，避免重复 XML；`-n 2` 需要 pytest-xdist，省略它可串行执行。
完整退出后运行 `tb/validate_pipeline_results.py --help` 中的入口，提供实际构建根、pytest 日志、
实现 revision、归档基线根和报告输出。此次还使用 `--staged-app` 将冻结快照路径对应到主仓库。
默认单独运行 collector 只收集报告；完整验收入口是 validator，它会重算性能并核对确切矩阵。

本次包版本：Python 3.10.20，pytest 7.2.1，xdist 3.1.0，cocotb 1.7.2，cocotb-test 0.2.4，
cocotbext-axi 0.1.24、pcie 0.2.14、eth 0.1.22，Icarus 12.0；完整环境记录在 JSON。

## 证据边界

AU250 2×1、深度 4 的修正版 Icarus Verilog-2005 模式 `iverilog -g2005 -Wall` 静态展开通过，见
`/tmp/raw-pipeline-static-acceptance/compile.log`。它只证明静态展开，不是综合或物理时序签核。
用户工具与 auxiliary 模块编译通过，模块使用 Linux 7.0.0-34 头文件，未加载运行。
Erie 严格格式门禁未通过：初轮 4440 errors/287 strict warnings，generation 轮 4510/294，
报告为 `/tmp/raw-pipeline-deliverable-gate.*` 和 `/tmp/raw-pipeline-generation-deliverable-gate.*`。
其中有与用户要求的 Corundum 命名/复位风格冲突的规则；没有把未通过说成通过，也不以该门禁代替功能仿真。

没有 Vivado 综合、布局布线、时序、GTY/CMAC 硬 IP、真实 Linux 驱动或上板发包证据。
RootComplex/PCIe/EthMac 和原 Alveo TB 是模型，不证明父 PCIe DMA 静默、posted write 排空或真实系统恢复。
app-only reset 不能作为 DMA abort 或释放仍有父 DMA 访问的内存的依据；有限 tag generation 无法防御无限迟到。
成功 CQE 对应 MAC TX completion，不代表远端收到。MR 仍是连续 DMA 地址映射，没有分页 MTT、任意用户页注册、
多 QP、raw RX、RoCE、重传或 verbs。旧 AU250 bitstream、报告和 `rev/` 不纳入本实现验收，也未修改或清理。

最终完成条件已由 G0..G4 所需组合的实际通过结果满足，并经独立的参数矩阵、源码与性能门禁核对。
