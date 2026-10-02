# SPDX-License-Identifier: BSD-2-Clause
"""Lost SQ/MAC/CQ completions quarantine ownership until accounted drain."""
import os
from pathlib import Path
from unittest.mock import patch
import cocotb
from cocotb.triggers import Event, Timer, with_timeout
import pytest
from raw_qp_tb import Host, init_pipeline, put_packet, CORUNDUM
from sim_runner import run_simulation


@cocotb.test(timeout_time=200, timeout_unit='us')
async def missing_completion(dut):
    stage = os.environ['RAW_MISSING_STAGE']
    seen, release = Event(), Event()

    class HeldStatus:
        def __init__(self, source):
            self.source = source

        async def send(self, transaction):
            seen.set()
            await release.wait()
            await self.source.send(transaction)

    class FaultHost(Host):
        async def read_dma(self, prefix, source, status, ram):
            if stage == 'sq' and prefix == 'ctrl':
                status = HeldStatus(status)
            await super().read_dma(prefix, source, status, ram)

        async def write_dma(self, source, status):
            if stage == 'cq':
                status = HeldStatus(status)
            await super().write_dma(source, status)

    with patch('raw_qp_tb.Host', FaultHost):
        tb = await init_pipeline(dut)
    packets = [bytes((j+i*17) & 255 for j in range(65)) for i in range(3)]
    for i, packet in enumerate(packets):
        put_packet(tb, i, packet)
    await tb.write(0x38, 3)
    tags = []
    if stage == 'sq':
        await with_timeout(seen.wait(), 20, 'us')
        assert tb.tx.empty()
    else:
        for packet in packets[:2]:
            frame = await with_timeout(tb.tx.recv(), 20, 'us')
            assert bytes(frame) == packet
            tags.append(int(frame.tuser) >> 1)
        if stage == 'cq':
            for tag in tags:
                await tb.complete_tx(tag)
            await with_timeout(seen.wait(), 20, 'us')
    await tb.wait_reg(0x1c, 0x60)
    accepted = await tb.read(0x58)
    assert accepted == (1 if stage == 'sq' else 2)
    assert await tb.read(0x54) == accepted
    assert await tb.read(0x40) == 0
    assert await tb.read(0x3c) == 0
    assert await tb.read(0x14) & 1
    await tb.write(0x10, 0)
    await tb.write(0x4c, 1)
    assert await tb.read(0x18) == 5, 'reset released outstanding completion ownership'
    release.set()
    if stage == 'sq':
        frame = await with_timeout(tb.tx.recv(), 20, 'us')
        assert bytes(frame) == packets[0]
        await tb.complete_tx(int(frame.tuser) >> 1)
    elif stage == 'mac':
        for tag in reversed(tags):
            await tb.complete_tx(tag)
    await tb.wait_reg(0x14, 0x100)
    await Timer(200, units='ns')
    assert await tb.read(0x58) == accepted
    assert await tb.read(0x54) == accepted
    assert await tb.read(0x40) == 0
    assert await tb.read(0x3c) == 0
    assert tb.tx.empty()
    # A CQ already accepted by parent DMA can still reach host memory late.
    # Quarantine is checked through fatal/ownership, not by pretending to abort it.
    if stage == 'cq':
        assert int.from_bytes(tb.mem[0x401c:0x4020], 'little') == 1
    # All modeled issued work has now been accounted for. Explicit queue reset
    # may clear quarantined contexts; this is not an app-only parent DMA abort.
    await tb.write(0x4c, 1)
    assert await tb.read(0x54) == 0
    assert await tb.read(0x1c) == 0


@pytest.mark.parametrize('stage', ['sq', 'mac', 'cq'])
def test_missing_completion(stage):
    app = Path(__file__).resolve().parents[2]
    sources = list((app/'rtl').glob('raw_*.v'))
    sources += [CORUNDUM/'fpga/lib/pcie/rtl'/name for name in ['dma_psdpram.v', 'dma_client_axis_source.v']]
    sources += list((CORUNDUM/'fpga/lib/axi/rtl').glob('axil_reg_if*.v'))
    run_simulation(verilog_sources=[str(p) for p in sources], toplevel='raw_packet_qp',
                   module='test_raw_packet_qp_missing', python_search=[str(Path(__file__).resolve().parent)],
                   parameters={'OP_TABLE_SIZE': 2, 'WATCHDOG_CYCLES': 128},
                   extra_env={'RAW_MISSING_STAGE': stage},
                   sim_build=str(app/f'tb/sim_build/qp_missing_{stage}'))
