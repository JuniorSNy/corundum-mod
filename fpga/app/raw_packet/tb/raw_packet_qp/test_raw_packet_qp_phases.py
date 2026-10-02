# SPDX-License-Identifier: BSD-2-Clause
"""Observe stage waiting cycles in the fixed latency benchmark, without forcing RTL."""
import json
from pathlib import Path
import cocotb
from cocotb.triggers import RisingEdge
import pytest
from raw_qp_tb import init_pipeline, CORUNDUM
from sim_runner import run_simulation


@cocotb.test(timeout_time=5, timeout_unit='ms')
async def phase_wait_metrics(dut):
    from test_raw_packet_qp_stress import continuous_run, CQ_STATUS_DELAY_NS
    tb = await init_pipeline(dut, ring_log=4)
    tb.cq_delay_ns = CQ_STATUS_DELAY_NS
    counts = {}
    running = True

    async def observe():
        while running:
            await RisingEdge(dut.clk)
            front = int(dut.front_state_reg.value)
            cq = int(dut.cq_state_reg.value)
            tests = {
                'sq_descriptor_ready': front == 1 and not int(dut.m_axis_ctrl_dma_read_desc_ready.value),
                'sq_data_or_status': front in (2, 3),
                'mr_response': front == 6,
                'payload_descriptor_ready': front == 7 and not int(dut.m_axis_data_dma_read_desc_ready.value),
                'payload_status_pending': bool(int(dut.dma_issued_reg.value) & ~int(dut.dma_done_reg.value)),
                'axis_ready': bool(int(dut.m_axis_tx_tvalid.value) and not int(dut.m_axis_tx_tready.value)),
                'mac_completion_pending': bool(int(dut.tx_started_reg.value) & ~int(dut.tx_done_reg.value)),
                'cq_descriptor_ready': cq == 1 and not int(dut.m_axis_ctrl_dma_write_desc_ready.value),
                'cq_status_pending': cq == 2,
            }
            counts['observed_cycles'] = counts.get('observed_cycles', 0)+1
            for name, value in tests.items():
                counts[name] = counts.get(name, 0)+int(value)

    task = cocotb.start_soon(observe())
    records = {}
    sequence = 0
    for length in (64, 1514, 9214):
        counts.clear()
        specs = [(bytes((j+i) & 255 for j in range(length)), 0, 0) for i in range(96)]
        await continuous_run(tb, specs, sequence)
        records[str(length)] = dict(counts)
        assert counts['payload_status_pending'] > 0
        assert counts['mac_completion_pending'] > 0
        assert counts['cq_status_pending'] > 0
        assert counts['axis_ready'] > 0
        sequence += len(specs)
    running = False
    await task
    Path('phase_wait_metrics.json').write_text(json.dumps({
        'depth': int(dut.OP_TABLE_SIZE.value), 'axis_width': len(dut.m_axis_tx_tdata),
        'clock_period_ns': 4, 'wqe_per_length': 96,
        'note': 'Per-cycle occupancy of wait conditions; overlapping conditions are not additive.',
        'frames': records}, indent=2)+'\n')


@pytest.mark.parametrize('axis_width', [256, 512])
@pytest.mark.parametrize('op_table_size', [1, 2, 4])
def test_qp_phases(axis_width, op_table_size):
    app = Path(__file__).resolve().parents[2]
    sources = list((app/'rtl').glob('raw_*.v'))
    sources += [CORUNDUM/'fpga/lib/pcie/rtl'/name for name in ['dma_psdpram.v', 'dma_client_axis_source.v']]
    sources += list((CORUNDUM/'fpga/lib/axi/rtl').glob('axil_reg_if*.v'))
    run_simulation(verilog_sources=[str(p) for p in sources], toplevel='raw_packet_qp',
                   module='test_raw_packet_qp_phases', python_search=[str(Path(__file__).resolve().parent)],
                   parameters={'AXIS_DATA_WIDTH': axis_width, 'AXIS_KEEP_WIDTH': axis_width//8,
                               'OP_TABLE_SIZE': op_table_size},
                   sim_build=str(app/f'tb/sim_build/phases_{axis_width}_{op_table_size}'))
