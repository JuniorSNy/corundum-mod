# SPDX-License-Identifier: BSD-2-Clause
"""Disable/drain/resume at externally observable SQ, DMA, TX and CQ boundaries."""
import os
from pathlib import Path
from unittest.mock import patch
import cocotb
from cocotb.triggers import Event, Timer, with_timeout
import pytest
from raw_qp_tb import Host, DescSink, init_pipeline, put_packet, CORUNDUM
from raw_app import wait_cqe
from sim_runner import run_simulation

STAGES = ['sq_desc', 'sq_status', 'payload_desc', 'payload_status',
          'tx_stream', 'mac_wait', 'cq_desc', 'cq_status']


@cocotb.test(timeout_time=200, timeout_unit='us')
async def stop_at_boundary(dut):
    stage = os.environ['RAW_STOP_STAGE']
    status_gate = Event()
    status_seen = Event()
    sinks = {}
    target = {'sq_desc': 'm_axis_ctrl_dma_read_desc_valid',
              'payload_desc': 'm_axis_data_dma_read_desc_valid',
              'cq_desc': 'm_axis_ctrl_dma_write_desc_valid'}.get(stage)

    def make_sink(bus, *args, **kwargs):
        sink = DescSink(bus, *args, **kwargs)
        if bus.valid._name == target:
            sinks[target] = sink
            original = sink.set_pause_generator
            def hold(_):
                original(None)
                sink.pause = True
            sink.set_pause_generator = hold
        return sink

    class GatedStatus:
        def __init__(self, source):
            self.source = source
        async def send(self, transaction):
            status_seen.set()
            await status_gate.wait()
            await self.source.send(transaction)

    class GatedHost(Host):
        async def read_dma(self, prefix, source, status, ram):
            if (stage == 'sq_status' and prefix == 'ctrl') or (stage == 'payload_status' and prefix == 'data'):
                status = GatedStatus(status)
            await super().read_dma(prefix, source, status, ram)

    with patch.multiple('raw_qp_tb', Host=GatedHost, DescSink=make_sink):
        tb = await init_pipeline(dut)
    if stage == 'tx_stream':
        tb.tx.clear_pause_generator()
        tb.tx.pause = True
    if stage == 'cq_status':
        tb.cq_gate.clear()
    packets = [bytes((j+23*i) & 255 for j in range(n)) for i, n in enumerate([65, 127, 1514, 4097])]
    for i, packet in enumerate(packets):
        put_packet(tb, i, packet)
    await tb.write(0x38, 4)

    async def wait_valid(signal):
        while not int(signal.value):
            await Timer(4, units='ns')
    frames = []
    first_completed = False
    if stage in ('sq_desc', 'payload_desc'):
        await with_timeout(wait_valid(getattr(dut, target)), 20, 'us')
    elif stage in ('sq_status', 'payload_status'):
        await with_timeout(status_seen.wait(), 20, 'us')
    elif stage == 'tx_stream':
        await with_timeout(wait_valid(dut.m_axis_tx_tvalid), 20, 'us')
    else:
        frames.append(await with_timeout(tb.tx.recv(), 20, 'us'))
        if stage in ('cq_desc', 'cq_status'):
            await tb.complete_tx(int(frames[0].tuser) >> 1)
            first_completed = True
            if stage == 'cq_desc':
                await with_timeout(wait_valid(getattr(dut, target)), 20, 'us')
            else:
                async def cq_wait():
                    while (await tb.read(0x5c) >> 6) != 2:
                        await Timer(4, units='ns')
                await with_timeout(cq_wait(), 20, 'us')
    await tb.write(0x10, 0)
    assert await tb.read(0x10) == 0
    accepted = await tb.read(0x58)
    assert 1 <= accepted <= 4
    await Timer(200, units='ns')
    assert await tb.read(0x58) == accepted, f'{stage}: fetch after disable'
    assert await tb.read(0x14) & 1, f'{stage}: busy dropped before drain'
    status_gate.set()
    for sink in sinks.values():
        sink.pause = False
    tb.tx.pause = False
    tb.cq_gate.set()
    while len(frames) < accepted:
        frames.append(await with_timeout(tb.tx.recv(), 20, 'us'))
    assert [bytes(frame) for frame in frames] == packets[:accepted]
    for i, frame in enumerate(frames):
        if i or not first_completed:
            await tb.complete_tx(int(frame.tuser) >> 1)
    await tb.wait_reg(0x40, accepted)
    await tb.wait_reg(0x14, 0)
    for i, packet in enumerate(packets[:accepted]):
        assert await wait_cqe(tb.mem, 0x4000+i*32, i+1) == (0xfeed0000+i, 0, len(packet), i, 0, 0, i+1)
    assert await tb.read(0x3c) == accepted
    # Re-enable consumes exactly the remaining published SQEs.
    await tb.write(0x10, 1)
    for i in range(accepted, 4):
        frame = await with_timeout(tb.tx.recv(), 20, 'us')
        assert bytes(frame) == packets[i]
        await tb.complete_tx(int(frame.tuser) >> 1)
    await tb.wait_reg(0x40, 4)
    assert tb.tx.empty()


@pytest.mark.parametrize('stage', STAGES)
def test_qp_stop(stage):
    app = Path(__file__).resolve().parents[2]
    sources = list((app/'rtl').glob('raw_*.v'))
    sources += [CORUNDUM/'fpga/lib/pcie/rtl'/name for name in ['dma_psdpram.v', 'dma_client_axis_source.v']]
    sources += list((CORUNDUM/'fpga/lib/axi/rtl').glob('axil_reg_if*.v'))
    run_simulation(verilog_sources=[str(p) for p in sources], toplevel='raw_packet_qp',
                   module='test_raw_packet_qp_stop', python_search=[str(Path(__file__).resolve().parent)],
                   parameters={'OP_TABLE_SIZE': 4}, extra_env={'RAW_STOP_STAGE': stage},
                   sim_build=str(app/f'tb/sim_build/qp_stop_{stage}'))
