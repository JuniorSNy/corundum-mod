# SPDX-License-Identifier: BSD-2-Clause
"""Ordered raw TX/CQ verification using Corundum segmented RAM interfaces."""
from pathlib import Path
import struct
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, with_timeout
from sim_runner import run_simulation
from raw_app import wait_cqe
from raw_qp_tb import Host, init_pipeline, put_packet, wait_pending, CORUNDUM, StatusTransaction
import pytest


@cocotb.test(timeout_time=200, timeout_unit='us')
async def raw_sq_to_ethernet(dut):
    cocotb.start_soon(Clock(dut.clk, 4, units='ns').start())
    dut.rst.value = 1
    dut.tx_cpl_valid.value = 0
    dut.tx_cpl_tag.value = 0
    dut.ctrl_dma_ram_wr_cmd_sel.value = 0
    dut.ctrl_dma_ram_rd_cmd_sel.value = 0
    dut.data_dma_ram_wr_cmd_sel.value = 0
    tb = Host(dut)
    await Timer(40, units='ns')
    dut.rst.value = 0
    await Timer(40, units='ns')
    assert await tb.read(0) == 0x12348110
    for addr, value in [(0x20, 0), (0x24, 1), (0x28, 0x4000), (0x2c, 1),
                        (0x30, 2), (0x34, 7), (0x80, 3), (0x84, 0x1233),
                        (0x88, 7), (0x8c, 0x80000001), (0x90, 0x1000),
                        (0x94, 0), (0x98, 0x10000), (0x9c, 1),
                        (0xa0, 0x10000), (0xa4, 0), (0xa8, 1)]:
        await tb.write(addr, value)
    await tb.write(0x10, 1)
    seq = 0

    async def submit(length=65, key=0x1233, address=0x1003, expected=0, flags=0, dma_error=0, stop=False):
        nonlocal seq
        packet = bytes((i+seq) % 256 for i in range(length))
        off = 0x10000+address-0x1000
        if 0 <= off <= len(tb.mem)-length:
            tb.mem[off:off+length] = packet
        sqoff = (seq % 4)*32
        wr_id = 0x123400000000+seq
        tb.mem[sqoff:sqoff+32] = struct.pack('<QQIIII', wr_id, address, length, key, flags, 0)
        before = len([r for r in tb.requests if r[0] == 'data'])
        if dma_error:
            tb.errors[('data', tb.base+off)] = dma_error
        await tb.write(0x38, seq+1)
        if expected == 0:
            frame = await with_timeout(tb.tx.recv(), 100, 'us')
            assert bytes(frame) == packet
            await Timer(80, units='ns')
            assert await tb.read(0x40) == seq
            if stop:
                await tb.write(0x10, 0)
                assert await tb.read(0x14) & 1
                await Timer(100, units='ns')
                assert await tb.read(0x40) == seq
                assert await tb.read(0x3c) == seq
            await tb.complete_tx(int(frame.tuser) >> 1)
        await tb.wait_reg(0x40, seq+1)
        cqoff = 0x4000+(seq % 4)*32
        cqe = await wait_cqe(tb.mem, cqoff, seq+1)
        assert cqe == (wr_id, expected, length, seq, 0, 0, seq+1)
        assert await tb.read(0x3c) == seq+1
        if expected:
            assert tb.tx.empty()
            if not dma_error:
                assert len([r for r in tb.requests if r[0] == 'data']) == before
        seq += 1
        await tb.write(0x44, seq)
        if stop:
            await tb.wait_reg(0x14, 0)
            assert await tb.read(0x10) == 0
            await tb.write(0x10, 1)

    for length in [14, 60, 64, 65, 127, 1514, 4097, 9214]:
        await submit(length)
    await submit(length=1514, stop=True)
    await submit(length=65)
    # SQ fetch failure cannot publish an untrusted wr_id or payload DMA.
    tb.errors[('ctrl', tb.base+(seq % 4)*32)] = 2
    before = len([r for r in tb.requests if r[0] == 'data'])
    await tb.write(0x38, seq+1)
    await tb.wait_reg(0x40, seq+1)
    cqoff = 0x4000+(seq % 4)*32
    assert await wait_cqe(tb.mem, cqoff, seq+1) == (0, 0x12, 0, seq, 0, 0, seq+1)
    assert len([r for r in tb.requests if r[0] == 'data']) == before
    assert tb.tx.empty()
    seq += 1
    await tb.write(0x44, seq)
    await submit()
    await submit(key=0x2233, expected=0x31)
    await submit(address=0xfff, expected=0x34)
    await submit(address=0x10ff0, length=65, expected=0x34)
    await submit(length=13, expected=0x20)
    await submit(flags=1, expected=0x20)
    await submit(expected=0x42, dma_error=2)
    await tb.write(0x84, 0xdead)
    assert await tb.read(0x18) == 5
    await submit()
    await tb.write(0x38, seq+5)
    assert await tb.read(0x38) == seq
    assert await tb.read(0x18) == 3
    start = seq
    for i in range(4):
        off = ((seq+i) % 4)*32
        tb.mem[off:off+32] = struct.pack('<QQIIII', seq+i, 0x1003, 13, 0x1233, 0, 0)
    await tb.write(0x38, seq+4)
    await tb.wait_reg(0x40, seq+4)
    seq += 4
    off = (seq % 4)*32
    tb.mem[off:off+32] = struct.pack('<QQIIII', seq, 0x1003, 13, 0x1233, 0, 0)
    await tb.write(0x38, seq+1)
    request_count = len(tb.requests)
    await Timer(200, units='ns')
    assert len(tb.requests) == request_count
    assert await tb.read(0x3c) == seq
    await tb.write(0x44, start+1)
    await tb.wait_reg(0x40, seq+1)
    seq += 1
    await tb.write(0x44, seq)
    tb.errors[('write', tb.base+0x4000+(seq % 4)*32)] = 1
    tb.mem[(seq % 4)*32:(seq % 4)*32+32] = struct.pack('<QQIIII', seq, 0x1003, 13, 0x1233, 0, 0)
    await tb.write(0x38, seq+1)
    await tb.wait_reg(0x1c, 0x51)
    assert await tb.read(0x40) == seq
    assert await tb.read(0x3c) == seq
    await tb.write(0x10, 0)
    await tb.write(0x4c, 1)
    assert await tb.read(0x1c) == 0
    assert await tb.read(0x38) == 0
    assert await tb.read(0x40) == 0
    seq = 0
    await tb.write(0x10, 1)
    await submit()



@cocotb.test(timeout_time=200, timeout_unit='us')
async def pipeline_reorder_stop(dut):
    """Hold all DMA status, reorder returns, stop, and delay first MAC/CQ completion."""
    tb = await init_pipeline(dut)
    depth = int(dut.OP_TABLE_SIZE.value)
    tb.hold_data_status = True
    packets = [bytes((j+37*i) & 255 for j in range([65, 1514, 4097, 9214, 127][i]))
               for i in range(depth+1)]
    for i, packet in enumerate(packets):
        put_packet(tb, i, packet)
    await tb.write(0x38, depth+1)
    await wait_pending(tb, depth)
    assert len(tb.data_descriptors) == depth
    assert len({d[2] for d in tb.data_descriptors}) == depth, 'overlapping payload buffers'
    assert len({d[3] for d in tb.data_descriptors}) == depth, 'duplicate active DMA tags'
    # A wrong tag must not complete any slot or release unvalidated data.
    status = tb.data_statuses[0][0]
    await status.send(StatusTransaction(tag=0xffff, error=0))
    await Timer(100, units='ns')
    assert tb.tx.empty()
    await tb.write(0x10, 0)
    assert await tb.read(0x14) & 1
    # Every later status arrives before the first. Nothing may pass the TX head.
    for source, tag, error in reversed(tb.data_statuses[1:]):
        await source.send(StatusTransaction(tag=tag, error=error))
    await Timer(100, units='ns')
    assert tb.tx.empty()
    source, tag, error = tb.data_statuses[0]
    await source.send(StatusTransaction(tag=tag, error=error))
    frames = [await with_timeout(tb.tx.recv(), 20, 'us') for _ in range(depth)]
    assert [bytes(f) for f in frames] == packets[:depth]
    tags = [int(f.tuser) >> 1 for f in frames]
    assert len(set(tags)) == depth
    assert await tb.read(0x40) == 0, 'CQ success before matching MAC completion'
    assert len(tb.data_descriptors) == depth, 'STOP accepted another WQE'
    # Later completions and duplicate DMA status cannot retire the head.
    await source.send(StatusTransaction(tag=tag, error=2))
    await tb.complete_tx(0xffff)
    for tx_tag in reversed(tags[1:]):
        await tb.complete_tx(tx_tag)
    await Timer(100, units='ns')
    assert await tb.read(0x40) == 0
    tb.cq_gate.clear()
    await tb.complete_tx(tags[0])
    await Timer(200, units='ns')
    assert await tb.read(0x40) == 0, 'CQ counter advanced with RAM read held'
    assert await tb.read(0x14) & 1
    tb.cq_gate.set()
    await tb.wait_reg(0x40, depth)
    for i, packet in enumerate(packets[:depth]):
        assert await wait_cqe(tb.mem, 0x4000+i*32, i+1) == (
            0xfeed0000+i, 0, len(packet), i, 0, 0, i+1)
    await tb.wait_reg(0x14, 0)
    assert await tb.read(0x3c) == depth
    # Pending producer entry survives STOP; enable resumes it without queue reset.
    tb.hold_data_status = False
    await tb.write(0x44, depth)
    await tb.write(0x10, 1)
    frame = await with_timeout(tb.tx.recv(), 20, 'us')
    assert bytes(frame) == packets[depth]
    await tb.complete_tx(int(frame.tuser) >> 1)
    await tb.wait_reg(0x40, depth+1)
    assert await wait_cqe(tb.mem, 0x4000+depth*32, depth+1) == (
        0xfeed0000+depth, 0, len(packets[depth]), depth, 0, 0, depth+1)


@cocotb.test(timeout_time=200, timeout_unit='us')
async def pipeline_cq_credit(dut):
    """A two-entry CQ limits all depths, including valid long-frame operations."""
    tb = await init_pipeline(dut, ring_log=1)
    packets = [bytes((j+13*i) & 255 for j in range(4097)) for i in range(3)]
    for i in range(2):
        put_packet(tb, i, packets[i], ring_size=2)
    await tb.write(0x38, 2)
    for i in range(2):
        frame = await with_timeout(tb.tx.recv(), 20, 'us')
        assert bytes(frame) == packets[i]
        await tb.complete_tx(int(frame.tuser) >> 1)
    await tb.wait_reg(0x40, 2)
    for i in range(2):
        assert await wait_cqe(tb.mem, 0x4000+i*32, i+1) == (
            0xfeed0000+i, 0, len(packets[i]), i, 0, 0, i+1)
    put_packet(tb, 2, packets[2], ring_size=2)
    await tb.write(0x38, 3)
    before = len(tb.requests)
    await Timer(1000, units='ns')
    assert len(tb.requests) == before, 'fetch without CQ credit'
    assert tb.tx.empty()
    await tb.write(0x44, 1)
    frame = await with_timeout(tb.tx.recv(), 20, 'us')
    assert bytes(frame) == packets[2]
    await tb.complete_tx(int(frame.tuser) >> 1)
    await tb.wait_reg(0x40, 3)
    assert await wait_cqe(tb.mem, 0x4000, 3) == (0xfeed0002, 0, len(packets[2]), 2, 0, 0, 3)


@pytest.mark.parametrize('axis_width', [256, 512])
@pytest.mark.parametrize('op_table_size', [1, 2, 4])
def test_qp(axis_width, op_table_size):
    app = Path(__file__).resolve().parents[2]
    sources = list((app/'rtl').glob('raw_*.v'))
    sources += [CORUNDUM/'fpga/lib/pcie/rtl'/name for name in ['dma_psdpram.v', 'dma_client_axis_source.v']]
    sources += list((CORUNDUM/'fpga/lib/axi/rtl').glob('axil_reg_if*.v'))
    run_simulation(
        simulator='icarus', verilog_sources=[str(p) for p in sources],
        toplevel='raw_packet_qp', module='test_raw_packet_qp', python_search=[str(Path(__file__).resolve().parent)],
        parameters={'AXIS_DATA_WIDTH': axis_width, 'AXIS_KEEP_WIDTH': axis_width//8, 'OP_TABLE_SIZE': op_table_size},
        sim_build=str(app/f'tb/sim_build/qp_{axis_width}_{op_table_size}'),
        expected_tests=3,
    )
