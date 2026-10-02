# SPDX-License-Identifier: BSD-2-Clause
"""DMA descriptor stability, status tags, segmented RAM and held done response."""
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer, with_timeout
from cocotbext.axi import AxiStreamSink, AxiStreamBus
from raw_qp_tb import CORUNDUM, pauses, PsdpRamMasterWrite, PsdpRamWriteBus
from sim_runner import run_simulation


async def wait_signal(signal, value=1):
    async def poll():
        while int(signal.value) != value:
            await Timer(4, units='ns')
    await with_timeout(poll(), 20, 'us')


@cocotb.test(timeout_time=200, timeout_unit='us')
async def dma_protocol(dut):
    cocotb.start_soon(Clock(dut.clk, 4, units='ns').start())
    dut.rst.value = 1
    dut.req_valid.value = 0
    dut.req_addr.value = 0
    dut.req_len.value = 0
    dut.done_ready.value = 0
    dut.dma_desc_ready.value = 0
    dut.dma_status_tag.value = 0
    dut.dma_status_error.value = 0
    dut.dma_status_valid.value = 0
    ram = PsdpRamMasterWrite(PsdpRamWriteBus.from_prefix(dut, 'ram'), dut.clk, dut.rst)
    ram.set_pause_generator(pauses())
    sink = AxiStreamSink(AxiStreamBus.from_prefix(dut, 'm_axis'), dut.clk, dut.rst)
    sink.set_pause_generator(pauses())
    await Timer(40, units='ns')
    dut.rst.value = 0
    await Timer(40, units='ns')

    async def request(length):
        await wait_signal(dut.req_ready)
        await FallingEdge(dut.clk)
        dut.req_addr.value = 0x100000003
        dut.req_len.value = length
        dut.req_valid.value = 1
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.req_valid.value = 0

    async def status(tag, error=0):
        await FallingEdge(dut.clk)
        dut.dma_status_tag.value = tag
        dut.dma_status_error.value = error
        dut.dma_status_valid.value = 1
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.dma_status_valid.value = 0

    async def consume_done(error):
        await wait_signal(dut.done_valid)
        for _ in range(8):
            await Timer(4, units='ns')
            assert int(dut.done_valid.value) and int(dut.done_error.value) == error
            assert not int(dut.req_ready.value)
        await FallingEdge(dut.clk)
        dut.done_ready.value = 1
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.done_ready.value = 0

    for length in [1, 31, 32, 63, 64, 65, 9214]:
        await request(length)
        await wait_signal(dut.dma_desc_valid)
        for _ in range(8):
            await Timer(4, units='ns')
            assert int(dut.dma_desc_valid.value)
            assert int(dut.dma_desc_addr.value) == 0x100000003
            assert int(dut.dma_desc_len.value) == length
        await FallingEdge(dut.clk)
        dut.dma_desc_ready.value = 1
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.dma_desc_ready.value = 0
        await status(2)
        await Timer(20, units='ns')
        assert not int(dut.done_valid.value) and sink.empty()
        packet = bytes((j+length) & 255 for j in range(length))
        await ram.write(0, packet)
        await status(1)
        assert bytes(await with_timeout(sink.recv(), 20, 'us')) == packet
        await consume_done(0)
    for length in [0, 16385]:
        await request(length)
        assert not int(dut.dma_desc_valid.value)
        await consume_done(15)
        assert sink.empty()
    await request(65)
    await wait_signal(dut.dma_desc_valid)
    await FallingEdge(dut.clk)
    dut.dma_desc_ready.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.dma_desc_ready.value = 0
    await status(1, 2)
    await consume_done(2)
    assert sink.empty(), 'failed DMA streamed old RAM contents'


def test_dma():
    app = Path(__file__).resolve().parents[2]
    sources = [app/'rtl/raw_dma_read.v']+[CORUNDUM/'fpga/lib/pcie/rtl'/name for name in ['dma_psdpram.v', 'dma_client_axis_source.v']]
    run_simulation(verilog_sources=[str(p) for p in sources], toplevel='raw_dma_read',
                   module='test_raw_dma_read', python_search=[str(Path(__file__).resolve().parent)],
                   sim_build=str(app/'tb/sim_build/dma'))
