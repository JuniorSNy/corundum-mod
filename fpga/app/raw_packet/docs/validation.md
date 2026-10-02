# 验证记录

当前多在途实施记录见 [流水线验证](pipeline-validation.md)，此前单在途基线见
[2026-10-02 工程化重构](refactor-20261002.md)。
以下 2026-09-21 内容为历史证据；2026-09-22 审查已确认独立 pytest 进程
未彻底解决 runner 挂起，不应把历史 5 case 通过当作当前完整回归。

## 历史验证（2026-09-21）

基准：Corundum `6748aed1`，分支 `feature/au250-fec-off`。
2026-09-21，本机 Python 3.10 / cocotb 1.7.2 / Icarus。

## 已执行

- `iverilog -g2005 -Wall` 展开 app wrapper 及其依赖通过。
  只有 MR 数组完整加入 `always @*` 敏感列表的提示，无宽度或未连接驱动警告。
- MR cocotb：lkey、PD、权限、零长度、边界、虚拟/DMA 地址溢出、
  100 组随机边界查询、响应反压、失效及复位。
- QP cocotb，AXIS 256/512 两组：14/60/64/65/127/1514/4097/9214 字节，
  非对齐地址、descriptor/TX 反压、真实 segmented RAM 事务、SQ/CQ 多次绕环，
  MR/长度/flags 错误、payload DMA 错误、CQ 满、CQ DMA fatal、停用和清错。
  明确断言 MAC completion 前不发布成功 CQE。
- 真实 `mqnic_core_pcie_us`，PCIe/ETH/SYNC 512 位，1×1 与 1×2 端口配置：
  host SQ → PCIe read → app MR/DMA → MAC → CQ PCIe write；
  raw 和普通 NIC 流混合发送逐帧比较，错误 MR CQE，后续普通 TX/RX。
  第二端口配置验证 app 向量切片/展开；实际测试流量集中于 port 0。
- 用户工具 `-Wall -Wextra -Werror` 编译通过。
- 辅助驱动用本机 Linux 7.0.0-31 headers 构建 `.ko` 通过。
  工具链输出缺少 vmlinux 而跳过 BTF，不影响生成 ko。

入口 `tb/run_tests.sh`：5 个 case 分别调用 pytest。
本机曾出现同一 pytest 进程多次 simulator.run 后停在子进程退出/启动阶段，
当时尝试使用独立进程隔离，后续审查证明并未完整解决，保留完整断言；没有用退出码覆盖、跳过断言或只认 XML 来报通过。

## 风格检查的限制

额外运行了 erie Verilog formatter/AST strict deliverable gate。
其初次结果为 3167 errors / 219 strict warnings，**没有通过**。
主要要求包括自定义端口前缀、低有效复位、双语固定头、每 always 单寄存器、
禁止块注释；Corundum app 模板包含条件宏端口，formatter 也报告 normalization failure。

本实现保留 Corundum 的 app ABI、同步高有效复位、现有模块组织与代码风格，
未为满足另一套命名规则改写宿主接口或删除许可证。因此该检查不能作为本项目
已通过的交付门禁；功能证据是上述 Verilog 展开与 cocotb 测试。
不宣称该原型达到 Erie strict/ASIC signoff。若后续项目指定该风格，应单独迁移并回归。

## 尚未验证

没有运行 Vivado 综合/布局布线、资源/时序签核、物理 AU250、真实 Linux 驱动加载、
用户态程序实际发包、PCIe 热拔插或故障注入恢复。内核模块目前只有编译证据，
不能用 cocotb 的 Python 主机模型替代 Linux 驱动运行验证。

单 outstanding 设计用于打通路径；无吞吐/延迟指标承诺。没有完整 RoCE、
多 QP 调度、SG MR、pin_user_pages/IOMMU 页表、硬件超时重试或 raw RX。
