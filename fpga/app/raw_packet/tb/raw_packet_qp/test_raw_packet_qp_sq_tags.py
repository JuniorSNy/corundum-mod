# SPDX-License-Identifier: BSD-2-Clause
"""A repeated SQ status must not complete a later SQ read."""
from pathlib import Path
from unittest.mock import patch
import cocotb
from cocotb.triggers import Event, Timer, with_timeout
from raw_qp_tb import Host, init_pipeline, put_packet, StatusTransaction, CORUNDUM
from raw_app import wait_cqe
from sim_runner import run_simulation


@cocotb.test(timeout_time=200, timeout_unit='us')
async def sq_generation_isolation(dut):
    held = Event()
    release = Event()
    tags = []
    status_sources = []
    cq_held, cq_release = Event(), Event()
    cq_tags, cq_sources = [], []

    class StatusProxy:
        def __init__(self, source):
            self.source = source

        async def send(self, transaction):
            tags.append(int(transaction.tag))
            status_sources.append(self.source)
            if len(tags) == 2:
                held.set()
                await release.wait()
            await self.source.send(transaction)

    class CqStatusProxy:
        def __init__(self, source):
            self.source = source

        async def send(self, transaction):
            cq_tags.append(int(transaction.tag))
            cq_sources.append(self.source)
            if len(cq_tags) == 2:
                cq_held.set()
                await cq_release.wait()
            await self.source.send(transaction)

    class SqHost(Host):
        async def read_dma(self, prefix, source, status, ram):
            if prefix == 'ctrl':
                status = StatusProxy(status)
            await super().read_dma(prefix, source, status, ram)

        async def write_dma(self, source, status):
            await super().write_dma(source, CqStatusProxy(status))

    with patch('raw_qp_tb.Host', SqHost):
        tb = await init_pipeline(dut)
    packets = [bytes((j+i) & 255 for j in range(65)) for i in range(2)]
    for i, packet in enumerate(packets):
        put_packet(tb, i, packet)
    await tb.write(0x38, 2)
    await with_timeout(held.wait(), 20, 'us')
    frame = await with_timeout(tb.tx.recv(), 20, 'us')
    assert bytes(frame) == packets[0]
    assert len(tb.data_descriptors) == 1
    await status_sources[1].send(StatusTransaction(tag=tags[0], error=0))
    await Timer(200, units='ns')
    assert len(tb.data_descriptors) == 1, 'old SQ status advanced a later payload DMA'
    assert tags[0] != tags[1], 'SQ reads reuse a fixed tag across distinct operations'
    assert tb.tx.empty()
    assert await tb.read(0x60) == 1
    release.set()
    second = await with_timeout(tb.tx.recv(), 20, 'us')
    assert bytes(second) == packets[1]
    for frame in (frame, second):
        await tb.complete_tx(int(frame.tuser) >> 1)
    await with_timeout(cq_held.wait(), 20, 'us')
    await tb.wait_reg(0x40, 1)
    await cq_sources[1].send(StatusTransaction(tag=cq_tags[0], error=0))
    await Timer(200, units='ns')
    assert await tb.read(0x40) == 1, 'old CQ status retired a later completion'
    assert await tb.read(0x60) == 2
    cq_release.set()
    await tb.wait_reg(0x40, 2)
    for i, packet in enumerate(packets):
        assert await wait_cqe(tb.mem, 0x4000+i*32, i+1) == (0xfeed0000+i, 0, len(packet), i, 0, 0, i+1)
    await status_sources[1].send(StatusTransaction(tag=tags[1], error=0))
    await cq_sources[1].send(StatusTransaction(tag=cq_tags[1], error=0))
    await Timer(100, units='ns')
    assert await tb.read(0x60) == 4
    assert await tb.read(0x40) == 2
    assert tb.tx.empty()


def test_sq_generation():
    app = Path(__file__).resolve().parents[2]
    sources = list((app/'rtl').glob('raw_*.v'))
    sources += [CORUNDUM/'fpga/lib/pcie/rtl'/name for name in ['dma_psdpram.v', 'dma_client_axis_source.v']]
    sources += list((CORUNDUM/'fpga/lib/axi/rtl').glob('axil_reg_if*.v'))
    run_simulation(verilog_sources=[str(p) for p in sources], toplevel='raw_packet_qp',
                   module='test_raw_packet_qp_sq_tags', python_search=[str(Path(__file__).resolve().parent)],
                   parameters={'OP_TABLE_SIZE': 4}, sim_build=str(app/'tb/sim_build/sq_generation'))
