# SPDX-License-Identifier: BSD-2-Clause
"""White-box counter seeding, then real SQ/DMA/TX/CQ traffic across 32-bit wrap."""
from pathlib import Path
import struct
import cocotb
from cocotb.triggers import FallingEdge, Timer, with_timeout
from raw_qp_tb import init_pipeline, put_packet, CORUNDUM
from raw_app import wait_cqe
from sim_runner import run_simulation


@cocotb.test(timeout_time=500, timeout_unit='us')
async def counters_and_tag_wrap(dut):
    tb = await init_pipeline(dut, ring_log=4)
    start = 0xfffffff0
    # Accelerate the unreachable-in-a-short-test initial count only. All actual
    # WQEs, DMA transfers, completions and CQ publication use public interfaces.
    await FallingEdge(dut.clk)
    for name in ['fetch_ptr_reg', 'tx_ptr_reg', 'sq_cons_reg', 'cq_prod_reg', 'tag_counter_reg']:
        getattr(dut, name).value = start
    dut.csr_inst.sq_prod_reg.value = start
    dut.csr_inst.cq_cons_reg.value = start
    # Model historical CQ records, rather than a fresh zero-filled CQ (whose
    # commit zero would be ambiguous at wrap without a prior slot generation).
    for slot in range(16):
        previous_commit = (start+slot-16+1) & 0xffffffff
        tb.mem[0x4000+slot*32+28:0x4000+slot*32+32] = struct.pack('<I', previous_commit)
    await Timer(20, units='ns')
    tags = []
    for batch in range(6):
        first = start+batch*8
        packets = [struct.pack('<Q', first+i)+bytes((j+i) & 255 for j in range(57)) for i in range(8)]
        for i, packet in enumerate(packets):
            put_packet(tb, first+i, packet, ring_size=16)
        target = (first+8) & 0xffffffff
        await tb.write(0x38, target)
        for packet in packets:
            frame = await with_timeout(tb.tx.recv(), 20, 'us')
            assert bytes(frame) == packet
            tag = int(frame.tuser) >> 1
            assert 0 <= tag < 8
            tags.append(tag)
            await tb.complete_tx(tag)
        await tb.wait_reg(0x40, target)
        for i, packet in enumerate(packets):
            sequence = first+i
            commit = (sequence+1) & 0xffffffff
            assert await wait_cqe(tb.mem, 0x4000+(sequence % 16)*32, commit) == (
                0xfeed0000+sequence, 0, len(packet), sequence & 0xffffffff, 0, 0, commit)
        await tb.write(0x44, target)
    assert any(a > b for a, b in zip(tags, tags[1:])), 'TX generation never wrapped'
    assert await tb.read(0x54) == 0
    assert await tb.read(0x1c) == 0
    assert tb.tx.empty()


def test_qp_wrap():
    app = Path(__file__).resolve().parents[2]
    sources = list((app/'rtl').glob('raw_*.v'))
    sources += [CORUNDUM/'fpga/lib/pcie/rtl'/name for name in ['dma_psdpram.v', 'dma_client_axis_source.v']]
    sources += list((CORUNDUM/'fpga/lib/axi/rtl').glob('axil_reg_if*.v'))
    run_simulation(verilog_sources=[str(p) for p in sources], toplevel='raw_packet_qp',
                   module='test_raw_packet_qp_wrap', python_search=[str(Path(__file__).resolve().parent)],
                   parameters={'OP_TABLE_SIZE': 4, 'DMA_TAG_WIDTH': 3, 'TX_TAG_WIDTH': 4},
                   sim_build=str(app/'tb/sim_build/qp_wrap'))
