# SPDX-License-Identifier: BSD-2-Clause
"""Raw QP host, DMA and RAM models shared by independent cocotb scenarios."""
import itertools
import os
import struct
import sys
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer, Event, Lock, with_timeout
from cocotbext.axi import AxiLiteMaster, AxiLiteBus, AxiStreamSink, AxiStreamBus
from cocotbext.axi.stream import define_stream

CORUNDUM = Path(os.environ.get('CORUNDUM_ROOT', Path(__file__).resolve().parents[4]))
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
        self.hold_data_status = False
        self.data_statuses = []
        self.data_descriptors = []
        self.data_delays = {}
        self.cq_gate = Event()
        self.cq_gate.set()
        self.tx_completion_lock = Lock()
        self.cq_delay_ns = 32
        cocotb.start_soon(self.monitor_interfaces())
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

    async def monitor_interfaces(self):
        channels = [
            ('m_axis_tx', ['tdata', 'tkeep', 'tlast', 'tuser'], 'tvalid', 'tready'),
            ('m_axis_ctrl_dma_read_desc', ['dma_addr', 'ram_addr', 'len', 'tag'], 'valid', 'ready'),
            ('m_axis_data_dma_read_desc', ['dma_addr', 'ram_addr', 'len', 'tag'], 'valid', 'ready'),
            ('m_axis_ctrl_dma_write_desc', ['dma_addr', 'ram_addr', 'len', 'tag'], 'valid', 'ready'),
        ]
        held = {}
        while True:
            # Sample the values presented at the edge, before register updates.
            await RisingEdge(self.dut.clk)
            if int(self.dut.rst.value):
                held.clear()
                continue
            for prefix, fields, valid_name, ready_name in channels:
                valid = int(getattr(self.dut, prefix+'_'+valid_name).value)
                if not valid:
                    assert prefix not in held, f'{prefix} dropped valid under backpressure'
                    continue
                ready = int(getattr(self.dut, prefix+'_'+ready_name).value)
                if prefix in held or not ready:
                    value = tuple(int(getattr(self.dut, prefix+'_'+f).value) for f in fields)
                    if prefix in held:
                        assert value == held[prefix], f'{prefix} changed under backpressure'
                    if not ready:
                        held[prefix] = value
                if ready:
                    held.pop(prefix, None)

    async def read_dma(self, prefix, source, status, ram):
        while True:
            desc = await source.recv()
            address, length = int(desc.dma_addr), int(desc.len)
            self.requests.append((prefix, address, length))
            error = self.errors.pop((prefix, address), 0)
            if prefix == 'data':
                self.data_descriptors.append((address, length, int(desc.ram_addr), int(desc.tag)))
            if not error:
                off = address-self.base
                assert 0 <= off <= len(self.mem)-length
                await ram.write(int(desc.ram_addr), bytes(self.mem[off:off+length]))
            if prefix == 'data':
                cocotb.start_soon(self.return_data_status(status, desc, error))
            else:
                await Timer(20, units='ns')
                await status.send(StatusTransaction(tag=desc.tag, error=error))

    async def return_data_status(self, status, desc, error):
        await Timer(self.data_delays.get(int(desc.dma_addr), 20), units='ns')
        if self.hold_data_status:
            self.data_statuses.append((status, int(desc.tag), error))
        else:
            await status.send(StatusTransaction(tag=desc.tag, error=error))

    async def write_dma(self, source, status):
        while True:
            desc = await source.recv()
            address, length = int(desc.dma_addr), int(desc.len)
            error = self.errors.pop(('write', address), 0)
            await self.cq_gate.wait()
            data = bytes(await self.cq_ram.read(int(desc.ram_addr), length))
            if not error:
                off = address-self.base
                assert 0 <= off <= len(self.mem)-length
                self.mem[off:off+length-4] = data[:-4]
            await Timer(self.cq_delay_ns, units='ns')
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

    async def complete_tx(self, tag=0):
        await self.tx_completion_lock.acquire()
        try:
            await FallingEdge(self.dut.clk)
            self.dut.tx_cpl_tag.value = tag
            self.dut.tx_cpl_valid.value = 1
            await RisingEdge(self.dut.clk)
            await FallingEdge(self.dut.clk)
            self.dut.tx_cpl_valid.value = 0
        finally:
            self.tx_completion_lock.release()


async def init_pipeline(dut, ring_log=3):
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
    for addr, value in [(0x20, 0), (0x24, 1), (0x28, 0x4000), (0x2c, 1),
                        (0x30, ring_log), (0x34, 7), (0x80, 3), (0x84, 0x1233),
                        (0x88, 7), (0x8c, 0x80000001), (0x90, 0x1000),
                        (0x94, 0), (0x98, 0x10000), (0x9c, 1),
                        (0xa0, 0x80000), (0xa4, 0), (0xa8, 1)]:
        await tb.write(addr, value)
    await tb.write(0x10, 1)
    return tb


def put_packet(tb, sequence, packet, ring_size=8, key=0x1233):
    offset = (sequence % 32) * 16384 + 3
    tb.mem[0x10000+offset:0x10000+offset+len(packet)] = packet
    sqoff = (sequence % ring_size)*32
    tb.mem[sqoff:sqoff+32] = struct.pack('<QQIIII', 0xfeed0000+sequence,
                                      0x1000+offset, len(packet), key, 0, 0)


async def wait_pending(tb, count):
    async def wait():
        while len(tb.data_statuses) != count:
            await Timer(20, units='ns')
    await with_timeout(wait(), 20, 'us')


