# SPDX-License-Identifier: BSD-2-Clause
"""AU250 app-enabled variant of the existing Alveo board-core test.

Reuse its Verilog top, PCIe/MAC environment and ordinary NIC regression. No
GTY/CMAC hard IP or Linux driver executes in this simulation.
"""
import importlib.util
from pathlib import Path
from unittest.mock import patch

import cocotb
from cocotb.triggers import with_timeout
from core_tb import CORUNDUM
from raw_scenario import exercise_raw_and_normal
from sim_runner import run_simulation

APP = Path(__file__).resolve().parents[2]
REFERENCE = CORUNDUM / 'fpga/mqnic/Alveo/fpga_100g/tb/fpga_core/test_fpga_core.py'
spec = importlib.util.spec_from_file_location('alveo_reference', REFERENCE)
board = importlib.util.module_from_spec(spec)
# Scapy 2.5 enumerates host routes while importing its packet serializers.
# This offline simulation has no dependency on the host routing table.
with patch('scapy.arch.read_routes', return_value=[]), patch('scapy.arch.read_routes6', return_value=[]):
    spec.loader.exec_module(board)


@cocotb.test(timeout_time=2, timeout_unit='ms')
async def raw_and_normal_board(dut):
    tb = board.TB(dut, msix_count=2**len(dut.uut.core_inst.core_pcie_inst.irq_index))
    tb.port_mac = tb.qsfp_mac
    await exercise_raw_and_normal(tb)


@cocotb.test(timeout_time=10, timeout_unit='ms')
async def ordinary_nic_regression(dut):
    await board.run_test_nic(dut)


def test_fpga_core_raw_packet(request):
    def run_variant(**kwargs):
        parameters = kwargs['parameters']
        parameters.update(APP_ID=0x12348010, APP_ENABLE=1, APP_CTRL_ENABLE=1,
                          APP_DMA_ENABLE=1, APP_AXIS_DIRECT_ENABLE=0,
                          APP_AXIS_SYNC_ENABLE=1, APP_AXIS_IF_ENABLE=0, APP_STAT_ENABLE=0)
        sources = kwargs['verilog_sources']
        sources.extend(str(p) for p in (APP/'rtl').glob('*.v'))
        for name in ['mac_ctrl_tx.v', 'mac_ctrl_rx.v', 'mac_pause_ctrl_tx.v',
                     'mac_pause_ctrl_rx.v', 'lfsr.v']:
            path = str(CORUNDUM/'fpga/lib/eth/rtl'/name)
            if path not in sources:
                sources.append(path)
        kwargs.update(module='test_fpga_core_raw_packet', timeout_seconds=600, expected_tests=2,
                      python_search=[str(Path(__file__).resolve().parent)],
                      extra_env={**{f'PARAM_{k}': str(v) for k, v in parameters.items()},
                                 'COCOTB_LOG_LEVEL': 'WARNING'},
                      sim_build=str(Path(__file__).resolve().parent/'sim_build/au250_2x1'))
        return run_simulation(**kwargs)
    # The reference owns the source list and board parameters; replace only its
    # final runner call while building this separate app-enabled variant.
    with patch.object(board.cocotb_test.simulator, 'run', run_variant):
        board.test_fpga_core(request, 2, 2, 1, 1)
