# SPDX-License-Identifier: BSD-2-Clause
"""STOP after accepted TX beats must drain one intact frame before resuming."""
from pathlib import Path

import cocotb
from cocotb.triggers import Event, FallingEdge, RisingEdge, Timer, with_timeout

from raw_app import wait_cqe
from raw_qp_tb import CORUNDUM, init_pipeline, put_packet
from sim_runner import run_simulation


@cocotb.test(timeout_time=200, timeout_unit='us')
async def stop_inside_frame(dut):
    tb = await init_pipeline(dut)
    tb.tx.clear_pause_generator()
    tb.tx.pause = False
    packets = [bytes((j+31*i) & 255 for j in range(length))
               for i, length in enumerate((4097, 65, 1514, 127, 4097))]
    first_beat = Event()
    accepted_beats = 0
    accepted_bytes = 0
    accepted_frames = []
    wire_frame = bytearray()
    observing = True

    async def observe_handshakes():
        nonlocal accepted_beats, accepted_bytes
        while observing:
            # Capture the values presented at the edge, before RTL updates.
            await RisingEdge(dut.clk)
            if int(dut.m_axis_tx_tvalid.value) and int(dut.m_axis_tx_tready.value):
                accepted_beats += 1
                data = int(dut.m_axis_tx_tdata.value).to_bytes(len(dut.m_axis_tx_tkeep), 'little')
                keep = int(dut.m_axis_tx_tkeep.value)
                for lane, value in enumerate(data):
                    if keep & (1 << lane):
                        wire_frame.append(value)
                        accepted_bytes += 1
                if int(dut.m_axis_tx_tlast.value):
                    accepted_frames.append(bytes(wire_frame))
                    wire_frame.clear()
                if accepted_beats == 1:
                    first_beat.set()

    observer = cocotb.start_soon(observe_handshakes())
    for sequence, packet in enumerate(packets):
        put_packet(tb, sequence, packet)
    await tb.write(0x38, len(packets))
    await with_timeout(first_beat.wait(), 20, 'us')
    await FallingEdge(dut.clk)
    tb.tx.pause = True

    async def wait_for_stall():
        while True:
            await FallingEdge(dut.clk)
            if int(dut.m_axis_tx_tvalid.value) and not int(dut.m_axis_tx_tready.value):
                return

    await with_timeout(wait_for_stall(), 20, 'us')
    assert accepted_beats >= 1, 'STOP did not follow an actual AXIS handshake'
    assert not accepted_frames, 'the first TLAST was accepted before STOP'
    assert 0 < accepted_bytes < len(packets[0]), 'the frame was not partially accepted'
    held_beats, held_bytes = accepted_beats, accepted_bytes
    await tb.write(0x10, 0)
    assert await tb.read(0x10) == 0
    accepted = await tb.read(0x58)
    assert 1 <= accepted <= 4 < len(packets), 'no pending SQ work remains for restart'
    assert await tb.read(0x14) & 1
    await Timer(200, units='ns')
    assert (accepted_beats, accepted_bytes) == (held_beats, held_bytes)
    assert not accepted_frames and tb.tx.empty()
    assert await tb.read(0x58) == accepted, 'STOP accepted new WQEs'
    assert await tb.read(0x14) & 1, 'busy dropped during the partially accepted frame'
    assert await tb.read(0x3c) == await tb.read(0x40) == 0
    dut._log.info('STOP inside first frame after %d AXIS beats/%d bytes; %d WQEs accepted',
                  held_beats, held_bytes, accepted)

    tb.tx.pause = False
    first_tag = None
    for sequence in range(accepted):
        frame = await with_timeout(tb.tx.recv(), 20, 'us')
        assert bytes(frame) == packets[sequence]
        tag = int(frame.tuser) >> 1
        if first_tag is None:
            first_tag = tag
        await tb.complete_tx(tag)
        await tb.wait_reg(0x40, sequence+1)
        assert await wait_cqe(tb.mem, 0x4000+sequence*32, sequence+1) == (
            0xfeed0000+sequence, 0, len(packets[sequence]), sequence, 0, 0, sequence+1)
    await tb.wait_reg(0x14, 0)
    assert await tb.read(0x3c) == accepted
    assert await tb.read(0x58) == accepted
    assert len(tb.data_descriptors) == accepted
    assert accepted_frames == packets[:accepted]
    assert accepted_bytes == sum(map(len, packets[:accepted]))
    assert tb.tx.empty()

    # A duplicate MAC completion cannot turn the drained first frame into
    # another CQE or release the pending producer entry while disabled.
    await tb.complete_tx(first_tag)
    await Timer(100, units='ns')
    assert await tb.read(0x40) == await tb.read(0x3c) == accepted
    assert await tb.read(0x58) == accepted
    assert accepted_frames == packets[:accepted]

    await tb.write(0x44, accepted)
    await tb.write(0x10, 1)
    for sequence in range(accepted, len(packets)):
        frame = await with_timeout(tb.tx.recv(), 20, 'us')
        assert bytes(frame) == packets[sequence]
        await tb.complete_tx(int(frame.tuser) >> 1)
        await tb.wait_reg(0x40, sequence+1)
        assert await wait_cqe(tb.mem, 0x4000+sequence*32, sequence+1) == (
            0xfeed0000+sequence, 0, len(packets[sequence]), sequence, 0, 0, sequence+1)
    await tb.wait_reg(0x14, 0)
    assert await tb.read(0x58) == await tb.read(0x3c) == await tb.read(0x40) == len(packets)
    assert len(tb.data_descriptors) == len(packets)
    assert accepted_frames == packets
    assert accepted_bytes == sum(map(len, packets))
    assert not wire_frame and tb.tx.empty()
    assert await tb.read(0x1c) == 0
    observing = False
    await observer


def test_qp_stop_midframe():
    app = Path(__file__).resolve().parents[2]
    sources = list((app/'rtl').glob('raw_*.v'))
    sources += [CORUNDUM/'fpga/lib/pcie/rtl'/name
                for name in ('dma_psdpram.v', 'dma_client_axis_source.v')]
    sources += list((CORUNDUM/'fpga/lib/axi/rtl').glob('axil_reg_if*.v'))
    run_simulation(verilog_sources=[str(path) for path in sources], toplevel='raw_packet_qp',
                   module='test_raw_packet_qp_stop_midframe',
                   python_search=[str(Path(__file__).resolve().parent)],
                   parameters={'OP_TABLE_SIZE': 4, 'AXIS_DATA_WIDTH': 512, 'AXIS_KEEP_WIDTH': 64},
                   sim_build=str(app/'tb/sim_build/qp_stop_midframe'))
