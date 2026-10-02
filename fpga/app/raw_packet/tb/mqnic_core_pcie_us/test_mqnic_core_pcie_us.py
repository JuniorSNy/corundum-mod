# SPDX-License-Identifier: BSD-2-Clause-Views
# Integration harness/source configuration derived from Corundum dma_bench.
# Copyright (c) 2021-2023 The Regents of the University of California
import os
import struct
from pathlib import Path
import pytest
import cocotb
from sim_runner import run_simulation
from cocotb.triggers import Timer, with_timeout
from core_tb import TB, CORUNDUM
from raw_scenario import exercise_raw_and_normal

APP = Path(__file__).resolve().parents[2]

@cocotb.test(timeout_time=2, timeout_unit='ms')
async def raw_and_normal_nic(dut):
    tb = TB(dut, msix_count=2**len(dut.core_pcie_inst.irq_index))
    await exercise_raw_and_normal(tb)

# cocotb-test

tests_dir = os.path.dirname(__file__)
rtl_dir = str(APP / 'rtl')
lib_dir = str(CORUNDUM / 'fpga/lib')
axi_rtl_dir = os.path.abspath(os.path.join(lib_dir, 'axi', 'rtl'))
axis_rtl_dir = os.path.abspath(os.path.join(lib_dir, 'axis', 'rtl'))
eth_rtl_dir = os.path.abspath(os.path.join(lib_dir, 'eth', 'rtl'))
pcie_rtl_dir = os.path.abspath(os.path.join(lib_dir, 'pcie', 'rtl'))


@pytest.mark.parametrize("if_count,ports_per_if,op_table_size", [(1, 1, 1), (1, 2, 1), (2, 1, 1), (2, 1, 2), (2, 1, 4)])
def test_mqnic_core_pcie_us(request, if_count, ports_per_if, op_table_size):
    axis_pcie_data_width = axis_eth_data_width = axis_eth_sync_data_width = 512
    ptp_ts_enable = ptp_ts_fmt_tod = 1
    dut = "mqnic_core_pcie_us"
    module = os.path.splitext(os.path.basename(__file__))[0]
    toplevel = dut

    verilog_sources = [
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), f"{dut}.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "mqnic_core.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "mqnic_core_pcie.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "mqnic_dram_if.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "mqnic_interface.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "mqnic_interface_tx.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "mqnic_interface_rx.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "mqnic_port.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "mqnic_port_tx.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "mqnic_port_rx.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "mqnic_egress.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "mqnic_ingress.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "mqnic_l2_egress.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "mqnic_l2_ingress.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "mqnic_rx_queue_map.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "mqnic_ptp.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "mqnic_ptp_clock.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "mqnic_ptp_perout.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "mqnic_rb_clk_info.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "cpl_write.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "cpl_op_mux.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "desc_fetch.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "desc_op_mux.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "queue_manager.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "cpl_queue_manager.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "tx_fifo.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "rx_fifo.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "tx_req_mux.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "tx_engine.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "rx_engine.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "tx_checksum.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "rx_hash.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "rx_checksum.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "stats_counter.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "stats_collect.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "stats_pcie_if.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "stats_pcie_tlp.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "stats_dma_if_pcie.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "stats_dma_latency.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "mqnic_tx_scheduler_block_rr.v"),
        os.path.join(str(CORUNDUM / "fpga/common/rtl"), "tx_scheduler_rr.v"),
        os.path.join(rtl_dir, "mqnic_app_block_raw_packet.v"),
        os.path.join(rtl_dir, "raw_packet_qp.v"),
        os.path.join(rtl_dir, "raw_mr_table.v"),
        os.path.join(eth_rtl_dir, "mac_ctrl_rx.v"),
        os.path.join(eth_rtl_dir, "mac_ctrl_tx.v"),
        os.path.join(eth_rtl_dir, "mac_pause_ctrl_rx.v"),
        os.path.join(eth_rtl_dir, "mac_pause_ctrl_tx.v"),
        os.path.join(eth_rtl_dir, "ptp_td_phc.v"),
        os.path.join(eth_rtl_dir, "ptp_td_leaf.v"),
        os.path.join(eth_rtl_dir, "ptp_td_rel2tod.v"),
        os.path.join(eth_rtl_dir, "ptp_perout.v"),
        os.path.join(eth_rtl_dir, "lfsr.v"),
        os.path.join(axi_rtl_dir, "axi_vfifo_raw.v"),
        os.path.join(axi_rtl_dir, "axi_vfifo_raw_rd.v"),
        os.path.join(axi_rtl_dir, "axi_vfifo_raw_wr.v"),
        os.path.join(axi_rtl_dir, "axil_crossbar.v"),
        os.path.join(axi_rtl_dir, "axil_crossbar_addr.v"),
        os.path.join(axi_rtl_dir, "axil_crossbar_rd.v"),
        os.path.join(axi_rtl_dir, "axil_crossbar_wr.v"),
        os.path.join(axi_rtl_dir, "axil_reg_if.v"),
        os.path.join(axi_rtl_dir, "axil_reg_if_rd.v"),
        os.path.join(axi_rtl_dir, "axil_reg_if_wr.v"),
        os.path.join(axi_rtl_dir, "axil_register_rd.v"),
        os.path.join(axi_rtl_dir, "axil_register_wr.v"),
        os.path.join(axi_rtl_dir, "arbiter.v"),
        os.path.join(axi_rtl_dir, "priority_encoder.v"),
        os.path.join(axis_rtl_dir, "axis_adapter.v"),
        os.path.join(axis_rtl_dir, "axis_arb_mux.v"),
        os.path.join(axis_rtl_dir, "axis_async_fifo.v"),
        os.path.join(axis_rtl_dir, "axis_async_fifo_adapter.v"),
        os.path.join(axis_rtl_dir, "axis_demux.v"),
        os.path.join(axis_rtl_dir, "axis_fifo.v"),
        os.path.join(axis_rtl_dir, "axis_fifo_adapter.v"),
        os.path.join(axis_rtl_dir, "axis_pipeline_fifo.v"),
        os.path.join(axis_rtl_dir, "axis_register.v"),
        os.path.join(pcie_rtl_dir, "pcie_axil_master.v"),
        os.path.join(pcie_rtl_dir, "pcie_tlp_demux.v"),
        os.path.join(pcie_rtl_dir, "pcie_tlp_demux_bar.v"),
        os.path.join(pcie_rtl_dir, "pcie_tlp_mux.v"),
        os.path.join(pcie_rtl_dir, "pcie_tlp_fifo.v"),
        os.path.join(pcie_rtl_dir, "pcie_tlp_fifo_raw.v"),
        os.path.join(pcie_rtl_dir, "pcie_msix.v"),
        os.path.join(pcie_rtl_dir, "irq_rate_limit.v"),
        os.path.join(pcie_rtl_dir, "dma_if_pcie.v"),
        os.path.join(pcie_rtl_dir, "dma_if_pcie_rd.v"),
        os.path.join(pcie_rtl_dir, "dma_if_pcie_wr.v"),
        os.path.join(pcie_rtl_dir, "dma_if_mux.v"),
        os.path.join(pcie_rtl_dir, "dma_if_mux_rd.v"),
        os.path.join(pcie_rtl_dir, "dma_if_mux_wr.v"),
        os.path.join(pcie_rtl_dir, "dma_if_desc_mux.v"),
        os.path.join(pcie_rtl_dir, "dma_ram_demux_rd.v"),
        os.path.join(pcie_rtl_dir, "dma_ram_demux_wr.v"),
        os.path.join(pcie_rtl_dir, "dma_psdpram.v"),
        os.path.join(pcie_rtl_dir, "dma_client_axis_sink.v"),
        os.path.join(pcie_rtl_dir, "dma_client_axis_source.v"),
        os.path.join(pcie_rtl_dir, "pcie_us_if.v"),
        os.path.join(pcie_rtl_dir, "pcie_us_if_rc.v"),
        os.path.join(pcie_rtl_dir, "pcie_us_if_rq.v"),
        os.path.join(pcie_rtl_dir, "pcie_us_if_cc.v"),
        os.path.join(pcie_rtl_dir, "pcie_us_if_cq.v"),
        os.path.join(pcie_rtl_dir, "pcie_us_cfg.v"),
        os.path.join(pcie_rtl_dir, "pulse_merge.v"),
    ]

    verilog_sources.extend(str(APP / "rtl" / name) for name in ["raw_dma_read.v", "raw_packet_csr.v"])

    parameters = {}

    # Structural configuration
    parameters['IF_COUNT'] = if_count
    parameters['PORTS_PER_IF'] = ports_per_if
    parameters['SCHED_PER_IF'] = ports_per_if

    # Clock configuration
    parameters['CLK_PERIOD_NS_NUM'] = 4
    parameters['CLK_PERIOD_NS_DENOM'] = 1

    # PTP configuration
    parameters['PTP_CLK_PERIOD_NS_NUM'] = 32
    parameters['PTP_CLK_PERIOD_NS_DENOM'] = 5
    parameters['PTP_CLOCK_PIPELINE'] = 0
    parameters['PTP_CLOCK_CDC_PIPELINE'] = 0
    parameters['PTP_SEPARATE_TX_CLOCK'] = 0
    parameters['PTP_SEPARATE_RX_CLOCK'] = 0
    parameters['PTP_PORT_CDC_PIPELINE'] = 0
    parameters['PTP_PEROUT_ENABLE'] = 0
    parameters['PTP_PEROUT_COUNT'] = 1

    # Queue manager configuration
    parameters['EVENT_QUEUE_OP_TABLE_SIZE'] = 32
    parameters['TX_QUEUE_OP_TABLE_SIZE'] = 32
    parameters['RX_QUEUE_OP_TABLE_SIZE'] = 32
    parameters['CQ_OP_TABLE_SIZE'] = 32
    parameters['EQN_WIDTH'] = 6
    parameters['TX_QUEUE_INDEX_WIDTH'] = 13
    parameters['RX_QUEUE_INDEX_WIDTH'] = 8
    parameters['CQN_WIDTH'] = max(parameters['TX_QUEUE_INDEX_WIDTH'], parameters['RX_QUEUE_INDEX_WIDTH']) + 1
    parameters['EQ_PIPELINE'] = 3
    parameters['TX_QUEUE_PIPELINE'] = 3 + max(parameters['TX_QUEUE_INDEX_WIDTH']-12, 0)
    parameters['RX_QUEUE_PIPELINE'] = 3 + max(parameters['RX_QUEUE_INDEX_WIDTH']-12, 0)
    parameters['CQ_PIPELINE'] = 3 + max(parameters['CQN_WIDTH']-12, 0)

    # TX and RX engine configuration
    parameters['TX_DESC_TABLE_SIZE'] = 32
    parameters['RX_DESC_TABLE_SIZE'] = 32
    parameters['RX_INDIR_TBL_ADDR_WIDTH'] = min(parameters['RX_QUEUE_INDEX_WIDTH'], 8)

    # Scheduler configuration
    parameters['TX_SCHEDULER_OP_TABLE_SIZE'] = parameters['TX_DESC_TABLE_SIZE']
    parameters['TX_SCHEDULER_PIPELINE'] = parameters['TX_QUEUE_PIPELINE']
    parameters['TDMA_INDEX_WIDTH'] = 6

    # Interface configuration
    parameters['PTP_TS_ENABLE'] = ptp_ts_enable
    parameters['PTP_TS_FMT_TOD'] = ptp_ts_fmt_tod
    parameters['PTP_TS_WIDTH'] = 96 if parameters['PTP_TS_FMT_TOD'] else 48
    parameters['TX_CPL_ENABLE'] = parameters['PTP_TS_ENABLE']
    parameters['TX_CPL_FIFO_DEPTH'] = 32
    parameters['TX_TAG_WIDTH'] = 16
    parameters['TX_CHECKSUM_ENABLE'] = 1
    parameters['RX_HASH_ENABLE'] = 1
    parameters['RX_CHECKSUM_ENABLE'] = 1
    parameters['LFC_ENABLE'] = 1
    parameters['PFC_ENABLE'] = parameters['LFC_ENABLE']
    parameters['MAC_CTRL_ENABLE'] = 1
    parameters['TX_FIFO_DEPTH'] = 32768
    parameters['RX_FIFO_DEPTH'] = 131072
    parameters['MAX_TX_SIZE'] = 9214
    parameters['MAX_RX_SIZE'] = 9214
    parameters['TX_RAM_SIZE'] = 131072
    parameters['RX_RAM_SIZE'] = 131072

    # RAM configuration
    parameters['DDR_CH'] = 2
    parameters['DDR_ENABLE'] = 0
    parameters['DDR_GROUP_SIZE'] = 1
    parameters['AXI_DDR_DATA_WIDTH'] = 512
    parameters['AXI_DDR_ADDR_WIDTH'] = 34
    parameters['AXI_DDR_ID_WIDTH'] = 8
    parameters['AXI_DDR_MAX_BURST_LEN'] = 256
    parameters['HBM_CH'] = 2
    parameters['HBM_ENABLE'] = 0
    parameters['HBM_GROUP_SIZE'] = parameters['HBM_CH']
    parameters['AXI_HBM_DATA_WIDTH'] = 256
    parameters['AXI_HBM_ADDR_WIDTH'] = 33
    parameters['AXI_HBM_ID_WIDTH'] = 6
    parameters['AXI_HBM_MAX_BURST_LEN'] = 16

    # Application block configuration
    parameters['APP_ID'] = 0x12348010
    parameters['APP_ENABLE'] = 1
    parameters['APP_CTRL_ENABLE'] = 1
    parameters['APP_DMA_ENABLE'] = 1
    parameters['APP_AXIS_DIRECT_ENABLE'] = 0
    parameters['APP_AXIS_SYNC_ENABLE'] = 1
    parameters['APP_AXIS_IF_ENABLE'] = 0
    parameters['APP_STAT_ENABLE'] = 0

    # DMA interface configuration
    parameters['DMA_IMM_ENABLE'] = 1
    parameters['DMA_IMM_WIDTH'] = 32
    parameters['DMA_LEN_WIDTH'] = 16
    parameters['DMA_TAG_WIDTH'] = 16
    parameters['RAM_ADDR_WIDTH'] = (max(parameters['TX_RAM_SIZE'], parameters['RX_RAM_SIZE'])-1).bit_length()
    parameters['RAM_PIPELINE'] = 2

    # PCIe interface configuration
    parameters['AXIS_PCIE_DATA_WIDTH'] = axis_pcie_data_width
    parameters['PF_COUNT'] = 1
    parameters['VF_COUNT'] = 0

    # Interrupt configuration
    parameters['IRQ_INDEX_WIDTH'] = parameters['EQN_WIDTH']

    # AXI lite interface configuration (control)
    parameters['AXIL_CTRL_DATA_WIDTH'] = 32
    parameters['AXIL_CTRL_ADDR_WIDTH'] = 24
    parameters['AXIL_CSR_PASSTHROUGH_ENABLE'] = 0

    # AXI lite interface configuration (application control)
    parameters['AXIL_APP_CTRL_DATA_WIDTH'] = parameters['AXIL_CTRL_DATA_WIDTH']
    parameters['AXIL_APP_CTRL_ADDR_WIDTH'] = 24

    # Ethernet interface configuration
    parameters['AXIS_ETH_DATA_WIDTH'] = axis_eth_data_width
    parameters['AXIS_ETH_SYNC_DATA_WIDTH'] = axis_eth_sync_data_width
    parameters['AXIS_ETH_RX_USE_READY'] = 0
    parameters['AXIS_ETH_TX_PIPELINE'] = 0
    parameters['AXIS_ETH_TX_FIFO_PIPELINE'] = 2
    parameters['AXIS_ETH_TX_TS_PIPELINE'] = 0
    parameters['AXIS_ETH_RX_PIPELINE'] = 0
    parameters['AXIS_ETH_RX_FIFO_PIPELINE'] = 2

    # Statistics counter subsystem
    parameters['STAT_ENABLE'] = 1
    parameters['STAT_DMA_ENABLE'] = 1
    parameters['STAT_PCIE_ENABLE'] = 1
    parameters['STAT_INC_WIDTH'] = 24
    parameters['STAT_ID_WIDTH'] = 12

    parameters['RAW_TX_OP_TABLE_SIZE'] = op_table_size

    extra_env = {f'PARAM_{k}': str(v) for k, v in parameters.items()}

    sim_build = os.path.join(tests_dir, "sim_build",
        request.node.name.replace('[', '-').replace(']', ''))

    run_simulation(
        python_search=[tests_dir],
        includes=[str(APP/'rtl')],
        defines=['APP_CUSTOM_PARAMS_ENABLE'],
        verilog_sources=verilog_sources,
        toplevel=toplevel,
        module=module,
        parameters=parameters,
        sim_build=sim_build,
        extra_env=extra_env,
    )
