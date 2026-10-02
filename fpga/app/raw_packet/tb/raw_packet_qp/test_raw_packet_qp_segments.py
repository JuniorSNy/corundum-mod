# SPDX-License-Identifier: BSD-2-Clause
"""CQ records span both RAM segments, independently backpressured."""
from pathlib import Path
from unittest.mock import patch
import cocotb
from cocotb.triggers import with_timeout
from raw_qp_tb import init_pipeline, put_packet, CORUNDUM
from independent_ram import IndependentSegmentRead
from raw_app import wait_cqe
from sim_runner import run_simulation


@cocotb.test(timeout_time=200, timeout_unit='us')
async def independent_cq_segments(dut):
    with patch('raw_qp_tb.PsdpRamMasterRead', IndependentSegmentRead):
        tb = await init_pipeline(dut)
    packets = [bytes((j+23*i) & 255 for j in range(n)) for i, n in enumerate([65, 4097, 127, 9214])]
    for i, packet in enumerate(packets):
        put_packet(tb, i, packet)
    await tb.write(0x38, 4)
    for packet in packets:
        frame = await with_timeout(tb.tx.recv(), 20, 'us')
        assert bytes(frame) == packet
        await tb.complete_tx(int(frame.tuser) >> 1)
    await tb.wait_reg(0x40, 4)
    for i, packet in enumerate(packets):
        assert await wait_cqe(tb.mem, 0x4000+i*32, i+1) == (
            0xfeed0000+i, 0, len(packet), i, 0, 0, i+1)
    assert all(tb.cq_ram.stall_counts), f'Segment stalls not exercised: {tb.cq_ram.stall_counts}'


def test_qp_segments():
    app = Path(__file__).resolve().parents[2]
    sources = list((app/'rtl').glob('raw_*.v'))
    sources += [CORUNDUM/'fpga/lib/pcie/rtl'/name for name in ['dma_psdpram.v', 'dma_client_axis_source.v']]
    sources += list((CORUNDUM/'fpga/lib/axi/rtl').glob('axil_reg_if*.v'))
    run_simulation(verilog_sources=[str(p) for p in sources], toplevel='raw_packet_qp',
                   module='test_raw_packet_qp_segments', python_search=[str(Path(__file__).resolve().parent)],
                   parameters={'OP_TABLE_SIZE': 4, 'AXIS_DATA_WIDTH': 256, 'AXIS_KEEP_WIDTH': 32,
                               'RAM_SEG_DATA_WIDTH': 128}, sim_build=str(app/'tb/sim_build/qp_segments'))
