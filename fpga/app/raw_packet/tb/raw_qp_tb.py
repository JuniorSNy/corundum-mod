# SPDX-License-Identifier: BSD-2-Clause
"""Raw QP host, DMA and RAM models shared by independent cocotb scenarios."""
import itertools
import json
from collections import deque
import os
import struct
import sys
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer, Event, Lock, with_timeout
from cocotb.result import SimTimeoutError
from cocotb.utils import get_sim_time
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
        # Model events are diagnostic evidence, not additional wire assertions.
        # Keep a bounded history and inspect registers only on a slow timer or
        # failure, avoiding additional signal reads on every simulation clock.
        self.recent_events = deque(maxlen=24)
        self.last_progress_ns = get_sim_time(units='ns')
        names = ('front_state_reg', 'tx_state_reg', 'cq_state_reg',
                 'state_reg', 'fetch_ptr_reg', 'tx_ptr_reg', 'sq_cons_reg',
                 'cq_prod_reg', 'active_reg', 'fatal_reg', 'tag_counter_reg')
        self.diagnostic_regs = {
            name: getattr(dut, name) for name in names if hasattr(dut, name)
        }
        self.last_fatal = 0
        self.stall_reported_at = None
        cocotb.start_soon(self.monitor_progress())
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

    def record_event(self, kind, **fields):
        now = get_sim_time(units='ns')
        self.last_progress_ns = now
        self.recent_events.append({'time_ns': now, 'model_event': kind, **fields})

    @staticmethod
    def diagnostic_value(handle):
        # Inactive status tag/error pins may intentionally contain X. Preserve
        # them in diagnostic output instead of failing a background log task.
        value = handle.value
        try:
            return int(value)
        except ValueError:
            return str(value)

    def dump_diagnostics(self, reason):
        snapshot = {name: self.diagnostic_value(handle) for name, handle in self.diagnostic_regs.items()}
        if all(isinstance(snapshot.get(name), int)
               for name in ('front_state_reg', 'tx_state_reg', 'cq_state_reg')):
            snapshot['phase'] = (snapshot['front_state_reg'] |
                                 snapshot['tx_state_reg'] << 5 |
                                 snapshot['cq_state_reg'] << 6)
        # Include current status pins for statuses injected outside Host methods.
        # They are a failure-time snapshot, not a history of wire handshakes.
        pins = {}
        for prefix in ('s_axis_ctrl_dma_read_desc_status',
                       's_axis_data_dma_read_desc_status',
                       's_axis_ctrl_dma_write_desc_status', 'tx_cpl'):
            pins[prefix] = {field: self.diagnostic_value(getattr(self.dut, prefix+'_'+field))
                            for field in ('valid', 'tag', 'error')
                            if hasattr(self.dut, prefix+'_'+field)}
        self.dut._log.warning('RAW_QP_DIAGNOSTIC reason=%s time_ns=%s phase/registers=%s status_pins=%s',
                              reason, get_sim_time(units='ns'), json.dumps(snapshot, sort_keys=True),
                              json.dumps(pins, sort_keys=True))
        for event in self.recent_events:
            self.dut._log.warning('RAW_QP_RECENT_MODEL_EVENT %s', json.dumps(event, sort_keys=True))

    async def monitor_progress(self):
        while True:
            await Timer(1000, units='ns')
            fatal_handle = self.diagnostic_regs.get('fatal_reg')
            fatal = int(fatal_handle.value) if fatal_handle is not None else 0
            if fatal and fatal != self.last_fatal:
                self.dump_diagnostics(f'hardware fatal {fatal:#x}')
            self.last_fatal = fatal
            now = get_sim_time(units='ns')
            if now-self.last_progress_ns < 5000 or self.stall_reported_at == self.last_progress_ns:
                continue
            active_handle = self.diagnostic_regs.get('active_reg')
            if active_handle is not None and int(active_handle.value):
                self.dump_diagnostics('no model progress for at least 5000 ns while contexts active')
                self.stall_reported_at = self.last_progress_ns

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
            self.record_event(('sq' if prefix == 'ctrl' else 'payload')+'_read_descriptor_recv', dma_addr=address,
                              length=length, ram_addr=int(desc.ram_addr), tag=int(desc.tag))
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
                self.record_event('sq_status_enqueued', tag=int(desc.tag), error=error)

    async def return_data_status(self, status, desc, error):
        await Timer(self.data_delays.get(int(desc.dma_addr), 20), units='ns')
        if self.hold_data_status:
            self.data_statuses.append((status, int(desc.tag), error))
            self.record_event('payload_status_held', tag=int(desc.tag), error=error)
        else:
            await status.send(StatusTransaction(tag=desc.tag, error=error))
            self.record_event('payload_status_enqueued', tag=int(desc.tag), error=error)

    async def write_dma(self, source, status):
        while True:
            desc = await source.recv()
            address, length = int(desc.dma_addr), int(desc.len)
            self.record_event('cq_write_descriptor_recv', dma_addr=address,
                              length=length, ram_addr=int(desc.ram_addr), tag=int(desc.tag))
            error = self.errors.pop(('write', address), 0)
            await self.cq_gate.wait()
            data = bytes(await self.cq_ram.read(int(desc.ram_addr), length))
            if not error:
                off = address-self.base
                assert 0 <= off <= len(self.mem)-length
                self.mem[off:off+length-4] = data[:-4]
            await Timer(self.cq_delay_ns, units='ns')
            await status.send(StatusTransaction(tag=desc.tag, error=error))
            self.record_event('cq_status_enqueued', tag=int(desc.tag), error=error)
            # Model delayed posted writes: DMA status precedes publication in
            # host memory; only the last DWORD authorizes reading this CQE.
            if not error:
                await Timer(100, units='ns')
                self.mem[off+length-4:off+length] = data[-4:]
                self.record_event('cq_commit_published', tag=int(desc.tag), dma_addr=address,
                                  commit_sequence=int.from_bytes(data[-4:], 'little'))

    async def write(self, address, value):
        await self.axil.write_dword(address, value)

    async def read(self, address):
        return await self.axil.read_dword(address)

    async def wait_reg(self, address, expected):
        actual = None
        for _ in range(1000):
            actual = await self.read(address)
            if actual == expected:
                return
            await Timer(20, units='ns')
        self.dump_diagnostics(f'wait_reg {address:#x} expected={expected:#x} actual={actual:#x}')
        raise AssertionError(f'register {address:#x} did not reach {expected}; last value {actual:#x}')

    async def complete_tx(self, tag=0):
        await self.tx_completion_lock.acquire()
        try:
            await FallingEdge(self.dut.clk)
            self.dut.tx_cpl_tag.value = tag
            self.dut.tx_cpl_valid.value = 1
            await RisingEdge(self.dut.clk)
            self.record_event('mac_completion_pulse', tag=tag)
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
    try:
        await with_timeout(wait(), 20, 'us')
    except SimTimeoutError:
        tb.dump_diagnostics(f'wait_pending expected={count} actual={len(tb.data_statuses)}')
        raise


