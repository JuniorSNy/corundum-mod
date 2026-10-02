# AU250 Raw Packet QP / MR DMA 原型

新增逻辑位于 `mqnic_app_block` 内，目录布局参考 `app/dma_bench`。
这是后续 RDMA 的 SQ、MR、DMA、CQ 基础，不包含 RoCE 报文协议、重传或完整 verbs。

```text
用户态 SQE → ctrl DMA 取 SQE → MR 检查/地址转换 → data DMA → 本地整帧 RAM
                                                            ↓
普通 mqnic TX ──────────────────────────────────────────→ 整帧仲裁 → port 0 MAC
                                                                          ↓
用户态 CQ ← ctrl DMA 写 CQE ← raw TX completion ← 按 tag 分流 MAC completion
```

- 一个 raw TX QP，一个在途 WQE；16 个 MR 表项。目标是功能正确，没有线速吞吐承诺。
- 普通 NIC TX/RX 保留。raw 与普通 TX 用 Corundum `axis_arb_mux` 按 `tlast` 仲裁。
- raw 使用 port 0、TX tag 0；普通 `tx_engine` 使用 tag 最高位为 1 的空间。
- AXIS 使用 app 的同步时钟；其他端口透传。保留主工程 PCIe/DMA/MAC，不新增 CDC。
- MR 映射连续的设备 DMA 地址区间，检查完整 lkey、PD、权限、边界及 64 位溢出。
  尚不支持任意用户页注册、页表或 scatter-gather MR。
- 首版只有 raw TX，没有 RQ/raw RX、RDMA READ/WRITE/SEND、ACK 或重传。

## 文件与边界

| 文件 | 职责 |
|---|---|
| `rtl/raw_mr_table.v` | 16 项 MR、权限校验、地址转换、保持至握手的响应 |
| `rtl/raw_dma_read.v` | DMA descriptor → segmented RAM → AXIS；失败不输出残帧 |
| `rtl/raw_packet_csr.v` | AXI-Lite CSR bank、主机 doorbell、MR 配置 staging |
| `rtl/raw_packet_qp.v` | SQ 消费、MR 查询、payload DMA、TX 完成及 CQ；单在途调度 |
| `rtl/mqnic_app_block_raw_packet.v` | Corundum app ABI、整帧仲裁、完成分流、未使用接口处理 |
| `include/raw_packet.h` | 共享的 SQE/CQE/ioctl ABI |
| `modules/mqnic_app_raw_packet/` | mqnic auxiliary driver，分配/映射 coherent DMA 内存 |
| `utils/raw_packet_send.c` | 用户态填写 SQE，发送一个完整 Ethernet 帧 |
| `tb/` | MR/QP 单元测试及真实 `mqnic_core_pcie_us` 集成仿真 |

AU250 构建入口：`fpga/mqnic/Alveo/fpga_100g/fpga_AU250_app_raw_packet`。
目标器件 `xcu250-figd2104-2-e`，APP_ID `0x12348010`，使用 app DMA 与 sync AXIS，DDR 关闭。
应用控制 BAR 为 BAR2；app 的 AXI-Lite master 未使用。详见 [寄存器表](docs/registers.md)。

## SQ/CQ 与所有权

两种 entry 都为 32 字节、小端序；布局见头文件。SQE：

```c
u64 wr_id, address;
u32 length, lkey, flags, reserved;
```

`flags/reserved` 必须为零。数据包含完整 Ethernet L2 header，长度 14..9214，
不含 preamble/FCS；MAC 负责 padding/FCS。地址是 MR 虚拟地址，不是主机物理地址。

CQE：

```c
u64 wr_id;
u32 status, length, sq_sequence, reserved, reserved2, commit_sequence;
```

`commit_sequence = sq_sequence + 1`（32 位回绕），放在最后一个 DWORD。
环指针为单调递增 32 位计数，只有计算槽位时对环大小取模。SQ/CQ 大小相同，
硬件支持 2..1024 项；示例驱动固定 256 项。CQ 满时停止取新 SQE。

1. 驱动 START 清空缓冲、配置 MR 和环，然后用户填写数据与 SQE。
2. 用户调用 SUBMIT；驱动在 MMIO producer 写入前执行 `dma_wmb()`。
3. 保持该 SQE、payload 不变，直到对应 CQE 到达。
4. 等待期望的 `commit_sequence`，以 acquire/DMA read barrier 读取其他字段。
   CSR CQ producer 表示 DMA 引擎已接受完成，不能单凭该数值假设 posted write 已到主机内存。
5. 处理 CQE 后 REAP 发布 CQ consumer，才可复用相关槽位和数据。

成功 CQE 表示收到 MAC TX completion，不代表远端收到包。错误请求不发送 payload。
SQ DMA 失败时无法可信读取 wr_id，此时 CQE 的 wr_id 为 0。

| status | 含义 |
|---|---|
| `0` | 成功 |
| `0x10 | dma_error` | SQE DMA 读取失败 |
| `0x20` | 长度或 flags/reserved 非法 |
| `0x31..0x35` | lkey、PD、权限、边界、地址溢出 |
| `0x40 | dma_error` | payload DMA 失败 |
| fatal `0x50 | dma_error` | CQ DMA 失败；不推进消费者/生产者，停止新工作 |

## 本地测试

依赖 Icarus、pytest、cocotb 1.7.2、cocotb-test、cocotbext-axi/pcie/eth。
复用 Corundum 的 DMA RAM 总线模型、PCIe root complex、mqnic Python 驱动和 Ethernet MAC 模型。

```bash
cd fpga/app/raw_packet
PYTHON_BIN=/home/sj/miniforge3/envs/corundum-test/bin/python bash tb/run_tests.sh
```

默认从安装目录定位 Corundum；在其他位置运行可设置 `CORUNDUM_ROOT=/path/to/corundum`。
统一入口在同一 pytest 进程执行全部 case，按 `tb/<dut>/` 分目录，也可在 DUT 目录运行 `make test`。
进程执行保留 cocotb-test 的 Icarus 配置，改用同步子进程等待和文件日志，
修复当前环境可独立复现的 asyncio 子进程退出挂起；超时、空结果、跳过或失败均不能算通过。
完整板级普通 NIC 回归较慢，单独采用 600 秒进程上限，其余 case 为 180 秒；
`RAW_SIM_TIMEOUT` 可调整进程上限，`RAW_SIM_BUILD_ROOT` 可隔离不同运行的构建目录。
`tb/core_tb.py` 与 integration source/parameter list 从 dma_bench 测试改编，保留原许可证。
具体覆盖和限制见 [验证记录](docs/validation.md)，基线与分阶段计划见 [重构记录](docs/refactor-20261002.md)。

## 软件构建与使用

```bash
cd fpga/app/raw_packet
make -C utils
make -C modules/mqnic_app_raw_packet
```

非当前内核可指定 `KDIR=/lib/modules/<version>/build`。
需要该固件已经运行、父 `mqnic` 驱动已经绑定设备，之后才加载辅助模块：

```bash
sudo insmod modules/mqnic_app_raw_packet/mqnic_app_raw_packet.ko
sudo utils/raw_packet_send /dev/mqnic-raw-0000:01:00.0 frame.bin
```

替换真实 PCI 地址；设备名由驱动生成。设备默认权限 0600，单客户端独占。
`frame.bin` 是实际要发送的 Ethernet 帧，不是 PCAP 文件。
程序通过 mmap 自己填写 SQE，ioctl 只承担初始化、发布指针、读取进度和停用。
Coherent 映射不包含 BAR，不允许用户自行设置 DMA 物理地址。

STOP 停止获取新 WQE 并等待当前 WQE 排空。VMA 保持文件和 DMA 缓冲存活，
关闭 fd 后仍存在的映射也不能被提前释放。100 ms 排空超时会隔离 DMA 分配，
禁止复用；需要设备复位/重启恢复。此版不实现硬件 DMA/MAC 超时自动恢复。
app-only reset 不能取消父 DMA 已接受的事务，复位前必须由整个设备流程静默 DMA。

## Vivado 构建

```bash
cd fpga/mqnic/Alveo/fpga_100g/fpga_AU250_app_raw_packet
make
```

该入口沿用 AU250 的板级文件/IP/约束，包含当前 Corundum checkout 的板级改动。
本次没有执行 Vivado 综合、布局布线或上板测试；仿真通过不等于 timing closure。
