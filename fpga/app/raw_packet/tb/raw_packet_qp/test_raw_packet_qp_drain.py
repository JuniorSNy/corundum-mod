# SPDX-License-Identifier: BSD-2-Clause
"""Fatal drain owns ready, unsent frames until TX and MAC work finish."""
import os
from pathlib import Path
from unittest.mock import patch

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge, Timer, with_timeout
import pytest

from raw_qp_tb import Host, init_pipeline, put_packet, wait_pending, StatusTransaction, CORUNDUM
from sim_runner import run_simulation


async def aligned_reset_and_payload_status(tb, tag, error=0):
    """A legal late status and an AXI-Lite reset request arrive at one edge.

    No payload status is queued in the otherwise idle StatusSource in this
    scenario. Drive its public DUT interface once, after its RAM write finished.
    The CSR master owns AW/W/B throughout; no internal DUT state is forced.
    """
    dut = tb.dut
    transaction = cocotb.start_soon(tb.write(0x4c, 1))

    async def align():
        while True:
            await FallingEdge(dut.clk)
            if all(int(getattr(dut, name).value) for name in (
                    's_axil_app_ctrl_awvalid', 's_axil_app_ctrl_awready',
                    's_axil_app_ctrl_wvalid', 's_axil_app_ctrl_wready')):
                assert int(dut.s_axil_app_ctrl_awaddr.value) == 0x4c
                assert int(dut.s_axil_app_ctrl_wdata.value) == 1
                assert int(dut.s_axil_app_ctrl_wstrb.value) == 15
                assert not int(dut.s_axis_data_dma_read_desc_status_valid.value)
                dut.s_axis_data_dma_read_desc_status_tag.value = tag
                dut.s_axis_data_dma_read_desc_status_error.value = error
                dut.s_axis_data_dma_read_desc_status_valid.value = 1
                await RisingEdge(dut.clk)
                await FallingEdge(dut.clk)
                dut.s_axis_data_dma_read_desc_status_valid.value = 0
                return

    await with_timeout(align(), 20, 'us')
    await with_timeout(transaction, 20, 'us')


async def late_status_reset_race(dut):
    tb = await init_pipeline(dut)
    tb.hold_data_status = True
    packet = bytes(j & 255 for j in range(1514))
    put_packet(tb, 0, packet)
    await tb.write(0x38, 1)
    await wait_pending(tb, 1)
    await tb.wait_reg(0x1c, 0x60)
    await tb.write(0x10, 0)
    await tb.write(0x18, 0)
    assert await tb.read(0x54) == 1
    assert await tb.read(0x14) & 1
    _, tag, error = tb.data_statuses[0]
    await aligned_reset_and_payload_status(tb, tag, error)
    observed = tuple([await tb.read(addr) for addr in (0x18, 0x1c, 0x58, 0x54)])
    dut._log.warning('aligned watchdog reset: config_error=%#x fatal=%#x fetch=%d active=%d', *observed)
    assert observed[0] == 5, 'reset accepted while late DMA enabled an unstarted TX'
    assert observed[1:] == (0x60, 1, 1)
    frame = await with_timeout(tb.tx.recv(), 20, 'us')
    assert bytes(frame) == packet
    assert await tb.read(0x14) & 1, 'busy dropped before the retained MAC completion'
    assert await tb.read(0x40) == 0
    assert await tb.read(0x3c) == 0
    await tb.complete_tx(int(frame.tuser) >> 1)
    await tb.wait_reg(0x14, 0x100)
    assert await tb.read(0x54) == 1
    assert await tb.read(0x40) == 0
    assert tb.tx.empty()
    # Issued model DMA, stream and MAC work are accounted for before reset.
    await tb.write(0x4c, 1)
    assert await tb.read(0x54) == 0
    assert await tb.read(0x58) == 0
    assert await tb.read(0x1c) == 0


async def first_cq_error_retains_contexts(dut):
    class RecordedSink:
        def __init__(self, source, records):
            self.source, self.records = source, records

        async def recv(self):
            desc = await self.source.recv()
            self.records.append((int(desc.dma_addr), int(desc.tag)))
            return desc

    class FaultHost(Host):
        def __init__(self, dut):
            self.cq_descriptors = []
            super().__init__(dut)

        async def return_data_status(self, status, desc, error):
            await Timer(20, units='ns')
            if int(desc.dma_addr) == self.base+0x10003:
                await status.send(StatusTransaction(tag=desc.tag, error=error))
            else:
                self.data_statuses.append((status, int(desc.tag), error))

        async def write_dma(self, source, status):
            await super().write_dma(RecordedSink(source, self.cq_descriptors), status)

    with patch('raw_qp_tb.Host', FaultHost):
        tb = await init_pipeline(dut)
    packets = [bytes((j+17*i) & 255 for j in range(n))
               for i, n in enumerate((65, 1514, 127, 4097))]
    for i, packet in enumerate(packets):
        put_packet(tb, i, packet)
    # Slot 2 fails payload DMA; slot 3 fails format and must never issue payload.
    tb.errors[('data', tb.base+0x10000+2*16384+3)] = 2
    tb.mem[3*32+24:3*32+28] = (1).to_bytes(4, 'little')
    tb.errors[('write', tb.base+0x4000)] = 2
    await tb.write(0x38, 4)
    await wait_pending(tb, 2)
    await tb.wait_reg(0x58, 4)
    first = await with_timeout(tb.tx.recv(), 20, 'us')
    assert bytes(first) == packets[0]
    await tb.complete_tx(int(first.tuser) >> 1)
    await tb.wait_reg(0x1c, 0x52)
    await tb.write(0x10, 0)
    assert await tb.read(0x54) == 4
    assert await tb.read(0x14) & 1
    assert await tb.read(0x3c) == 0
    assert await tb.read(0x40) == 0
    assert len(tb.data_descriptors) == 3
    assert len(tb.cq_descriptors) == 1
    assert tb.mem[0x4000:0x4080] == bytes(128)
    await tb.write(0x4c, 1)
    assert await tb.read(0x18) == 5, 'CQ fatal reset released unfinished payload ownership'
    # The later payload error can finish first but cannot pass the good TX head.
    source, tag, error = tb.data_statuses[1]
    assert error == 2
    await source.send(StatusTransaction(tag=tag, error=error))
    await Timer(100, units='ns')
    assert tb.tx.empty()
    assert await tb.read(0x14) & 1
    await tb.write(0x18, 0)
    _, tag, error = tb.data_statuses[0]
    assert error == 0
    await aligned_reset_and_payload_status(tb, tag, error)
    observed = tuple([await tb.read(addr) for addr in (0x18, 0x1c, 0x58, 0x54)])
    dut._log.warning('aligned CQ fatal reset: config_error=%#x fatal=%#x fetch=%d active=%d', *observed)
    assert observed[0] == 5, 'CQ fatal reset raced a ready retained frame'
    assert observed[1:] == (0x52, 4, 4)
    second = await with_timeout(tb.tx.recv(), 20, 'us')
    assert bytes(second) == packets[1]
    assert await tb.read(0x14) & 1
    await tb.complete_tx(int(second.tuser) >> 1)
    await tb.wait_reg(0x14, 0x100)
    # Payload/format errors must advance TX retirement without needing MAC tags.
    # No context or public counter retires after the unreliable first CQ write.
    assert await tb.read(0x54) == 4
    assert await tb.read(0x58) == 4
    assert await tb.read(0x3c) == 0
    assert await tb.read(0x40) == 0
    assert len(tb.data_descriptors) == 3
    assert len(tb.cq_descriptors) == 1
    assert tb.tx.empty()
    assert tb.mem[0x4000:0x4080] == bytes(128)
    await tb.write(0x4c, 1)
    assert await tb.read(0x54) == 0
    assert await tb.read(0x58) == 0
    assert await tb.read(0x1c) == 0


@cocotb.test(timeout_time=200, timeout_unit='us')
async def fatal_drain_ownership(dut):
    if os.environ['RAW_DRAIN_SCENARIO'] == 'late_reset':
        await late_status_reset_race(dut)
    else:
        await first_cq_error_retains_contexts(dut)


@pytest.mark.parametrize('scenario,depth,watchdog', [('late_reset', 2, 128), ('cq_error', 4, 0)])
def test_fatal_drain(scenario, depth, watchdog):
    app = Path(__file__).resolve().parents[2]
    sources = list((app/'rtl').glob('raw_*.v'))
    sources += [CORUNDUM/'fpga/lib/pcie/rtl'/name for name in ['dma_psdpram.v', 'dma_client_axis_source.v']]
    sources += list((CORUNDUM/'fpga/lib/axi/rtl').glob('axil_reg_if*.v'))
    run_simulation(verilog_sources=[str(p) for p in sources], toplevel='raw_packet_qp',
                   module='test_raw_packet_qp_drain', python_search=[str(Path(__file__).resolve().parent)],
                   parameters={'OP_TABLE_SIZE': depth, 'WATCHDOG_CYCLES': watchdog},
                   extra_env={'RAW_DRAIN_SCENARIO': scenario},
                   sim_build=str(app/f'tb/sim_build/qp_drain_{scenario}'))
