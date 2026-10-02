"""Host-memory SQ/CQ test using Corundum's segmented RAM bus drivers."""
import itertools
import os
from pathlib import Path
import struct
import sys
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer, with_timeout
from cocotbext.axi import AxiLiteMaster, AxiLiteBus, AxiStreamSink, AxiStreamBus
from cocotbext.axi.stream import define_stream
from sim_runner import run_simulation
from raw_app import wait_cqe
import pytest

CORUNDUM = Path(os.environ.get('CORUNDUM_ROOT', Path(__file__).resolve().parents[5]))
sys.path.insert(0, str(CORUNDUM / 'fpga/lib/pcie/tb'))
from dma_psdp_ram import PsdpRamMasterWrite, PsdpRamWriteBus, PsdpRamMasterRead, PsdpRamReadBus
DescBus, _, _, DescSink, _ = define_stream('Desc', signals=['dma_addr', 'ram_addr', 'ram_sel', 'len', 'tag', 'valid', 'ready'])
StatusBus, StatusTransaction, StatusSource, _, _ = define_stream('Status', signals=['tag', 'error', 'valid'])


def pauses():
    return itertools.cycle([1, 1, 0, 0, 0, 1, 0])


class Host:
    """DMA descriptors cause actual segmented RAM transactions, not forced DUT internals."""
    def __init__(self, dut):
        self.dut = dut
        self.base = 0x100000000
        self.mem = bytearray(2**20)
        self.requests = []
        self.errors = {}
        self.axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, 's_axil_app_ctrl'), dut.clk, dut.rst)
        self.tx = AxiStreamSink(AxiStreamBus.from_prefix(dut, 'm_axis_tx'), dut.clk, dut.rst)
        self.tx.set_pause_generator(pauses())
        self.ctrl_ram = PsdpRamMasterWrite(PsdpRamWriteBus.from_prefix(dut, 'ctrl_dma_ram'), dut.clk, dut.rst)
        self.data_ram = PsdpRamMasterWrite(PsdpRamWriteBus.from_prefix(dut, 'data_dma_ram'), dut.clk, dut.rst)
        self.cq_ram = PsdpRamMasterRead(PsdpRamReadBus.from_prefix(dut, 'ctrl_dma_ram'), dut.clk, dut.rst)
        for prefix, ram in [('ctrl', self.ctrl_ram), ('data', self.data_ram)]:
            desc = DescSink(DescBus.from_prefix(dut, f'm_axis_{prefix}_dma_read_desc'), dut.clk, dut.rst)
            desc.set_pause_generator(pauses())
            status = StatusSource(StatusBus.from_prefix(dut, f's_axis_{prefix}_dma_read_desc_status'), dut.clk, dut.rst)
            cocotb.start_soon(self.read_dma(prefix, desc, status, ram))
        desc = DescSink(DescBus.from_prefix(dut, 'm_axis_ctrl_dma_write_desc'), dut.clk, dut.rst)
        desc.set_pause_generator(pauses())
        status = StatusSource(StatusBus.from_prefix(dut, 's_axis_ctrl_dma_write_desc_status'), dut.clk, dut.rst)
        cocotb.start_soon(self.write_dma(desc, status))

    async def read_dma(self, prefix, source, status, ram):
        while True:
            desc = await source.recv()
            address, length = int(desc.dma_addr), int(desc.len)
            self.requests.append((prefix, address, length))
            error = self.errors.pop((prefix, address), 0)
            if not error:
                off = address-self.base
                assert 0 <= off <= len(self.mem)-length
                await ram.write(int(desc.ram_addr), bytes(self.mem[off:off+length]))
            await Timer(20, units='ns')
            await status.send(StatusTransaction(tag=desc.tag, error=error))

    async def write_dma(self, source, status):
        while True:
            desc = await source.recv()
            address, length = int(desc.dma_addr), int(desc.len)
            error = self.errors.pop(('write', address), 0)
            data = bytes(await self.cq_ram.read(int(desc.ram_addr), length))
            if not error:
                off = address-self.base
                assert 0 <= off <= len(self.mem)-length
                self.mem[off:off+length-4] = data[:-4]
            await Timer(32, units='ns')
            await status.send(StatusTransaction(tag=desc.tag, error=error))
            # Model delayed posted writes: DMA status precedes publication in
            # host memory; only the last DWORD authorizes reading this CQE.
            if not error:
                await Timer(100, units='ns')
                self.mem[off+length-4:off+length] = data[-4:]

    async def write(self, address, value):
        await self.axil.write_dword(address, value)

    async def read(self, address):
        return await self.axil.read_dword(address)

    async def wait_reg(self, address, expected):
        for _ in range(1000):
            if await self.read(address) == expected:
                return
            await Timer(20, units='ns')
        raise AssertionError(f'register {address:#x} did not reach {expected}')

    async def complete_tx(self):
        await FallingEdge(self.dut.clk)
        self.dut.tx_cpl_valid.value = 1
        await RisingEdge(self.dut.clk)
        await FallingEdge(self.dut.clk)
        self.dut.tx_cpl_valid.value = 0


@cocotb.test(timeout_time=200, timeout_unit='us')
async def raw_sq_to_ethernet(dut):
    cocotb.start_soon(Clock(dut.clk, 4, units='ns').start())
    dut.rst.value = 1
    dut.tx_cpl_valid.value = 0
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
            await tb.complete_tx()
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


@pytest.mark.parametrize('axis_width', [256, 512])
def test_qp(axis_width):
    app = Path(__file__).resolve().parents[2]
    sources = list((app/'rtl').glob('raw_*.v'))
    sources += [CORUNDUM/'fpga/lib/pcie/rtl'/name for name in ['dma_psdpram.v', 'dma_client_axis_source.v']]
    sources += list((CORUNDUM/'fpga/lib/axi/rtl').glob('axil_reg_if*.v'))
    run_simulation(
        simulator='icarus', verilog_sources=[str(p) for p in sources],
        toplevel='raw_packet_qp', module='test_raw_packet_qp', python_search=[str(Path(__file__).resolve().parent)],
        parameters={'AXIS_DATA_WIDTH': axis_width, 'AXIS_KEEP_WIDTH': axis_width//8},
        sim_build=str(app/f'tb/sim_build/qp_{axis_width}'),
    )
