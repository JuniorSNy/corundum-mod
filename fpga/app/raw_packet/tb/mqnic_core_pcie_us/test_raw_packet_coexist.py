# SPDX-License-Identifier: BSD-2-Clause
"""Sustained raw TX and ordinary TX/RX on both AU250 interfaces."""
import importlib.util
import logging
from pathlib import Path
import struct
from unittest.mock import patch
import cocotb
from cocotb.triggers import with_timeout
import pytest
from core_tb import TB
from raw_app import SQE, wait_cqe, wait_register
from sim_runner import run_simulation


@cocotb.test(timeout_time=2, timeout_unit='ms')
async def both_ports_coexist(dut):
    logging.getLogger('cocotb.regression').setLevel(logging.INFO)
    tb = TB(dut, msix_count=2**len(dut.core_pcie_inst.irq_index))
    await tb.init()
    await tb.driver.init_pcie_dev(tb.rc.find_device(tb.dev.functions[0].pcie_id))
    endpoints = [ndev for interface in tb.driver.interfaces for ndev in interface.ndevs]
    assert len(endpoints) == len(tb.port_mac) == 2
    for ndev in endpoints:
        await ndev.open()
    regs = tb.driver.app_hw_regs
    mem = tb.rc.mem_pool.alloc_region(0x100000)
    base = mem.get_absolute_address(0)

    async def wr64(offset, value):
        await regs.write_dword(offset, value & 0xffffffff)
        await regs.write_dword(offset+4, value >> 32)

    await wr64(0x20, base)
    await wr64(0x28, base+0x4000)
    for addr, value in [(0x30, 4), (0x34, 7), (0x80, 3), (0x84, 0x1233),
                        (0x88, 7), (0x8c, 0x80000001)]:
        await regs.write_dword(addr, value)
    await wr64(0x90, 0x1000)
    await wr64(0x98, base+0x10000)
    await wr64(0xa0, 0x80000)
    await regs.write_dword(0xa8, 1)
    await regs.write_dword(0x10, 1)

    count = 96

    def packet(marker, port, sequence):
        # The ordinary mqnic Python driver requires len(data) < max_tx_mtu.
        length = (64, 1514, 4097, 9214 if marker == b'RAW!' else 9014)[sequence % 4]
        return marker+struct.pack('<II', port, sequence)+bytes((j+port+sequence) & 255 for j in range(length-12))

    raw = [packet(b'RAW!', 0, i) for i in range(count)]
    normal = [[packet(b'NIC!', p, i) for i in range(count)] for p in range(2)]
    overlap = False

    async def normal_tx(p):
        for pkt in normal[p]:
            await endpoints[p].start_xmit(pkt, 0)

    async def normal_rx(p):
        # Batch like the reference NIC regression: waiting for an interrupt
        # after every injected frame serializes interrupt moderation latency.
        # Eight mixed frames occupy <32 KiB, within the 128 KiB RX FIFO.
        for first in range(0, count, 8):
            packets = [packet(b'RX!!', p, i) for i in range(first, min(first+8, count))]
            for pkt in packets:
                await tb.port_mac[p].rx.send(pkt)
            for pkt in packets:
                received = await with_timeout(endpoints[p].recv(), 100, 'us')
                assert bytes(received.data) == pkt, f'port {p} RX order/content'
            if (first+len(packets)) % 16 == 0:
                dut._log.warning('Coexist port %d RX %d/%d', p, first+len(packets), count)

    async def check_tx(p):
        nonlocal overlap
        raw_seen = normal_seen = 0
        for _ in range(count*(2 if p == 0 else 1)):
            pkt = bytes(await with_timeout(tb.port_mac[p].tx.recv(), 100, 'us'))
            if pkt[:4] == b'RAW!':
                assert p == 0 and raw_seen < count
                assert pkt == raw[raw_seen]
                raw_seen += 1
            else:
                assert normal_seen < count and pkt == normal[p][normal_seen]
                normal_seen += 1
            if p == 0 and 0 < raw_seen < count and 0 < normal_seen < count:
                overlap = True
            if (_+1) % 32 == 0:
                dut._log.warning('Coexist port %d TX raw=%d normal=%d', p, raw_seen, normal_seen)
        assert normal_seen == count and raw_seen == (count if p == 0 else 0)

    def publish(sequence):
        offset = (sequence % 32)*16384+3
        pkt = raw[sequence]
        mem[0x10000+offset:0x10000+offset+len(pkt)] = pkt
        sqoff = (sequence % 16)*32
        mem[sqoff:sqoff+32] = SQE.pack(sequence+100, 0x1000+offset, len(pkt), 0x1233, 0, 0)

    tasks = [cocotb.start_soon(coro(p)) for p in range(2) for coro in (normal_tx, normal_rx, check_tx)]
    published = 16
    for i in range(published):
        publish(i)
    await regs.write_dword(0x38, published)
    for i, pkt in enumerate(raw):
        assert await wait_cqe(mem, 0x4000+(i % 16)*32, i+1) == (i+100, 0, len(pkt), i, 0, 0, i+1)
        if (i+1) % 16 == 0:
            dut._log.warning('Coexist raw CQ %d/%d', i+1, count)
        await regs.write_dword(0x44, i+1)
        if published < count:
            publish(published)
            published += 1
            await regs.write_dword(0x38, published)
    for task in tasks:
        await task
    assert overlap, 'raw and ordinary port 0 TX streams never made concurrent progress'
    assert all(mac.tx.empty() for mac in tb.port_mac)
    await regs.write_dword(0x10, 0)
    await wait_register(regs, 0x14, 0)
    assert await regs.read_dword(0x1c) == 0


@pytest.mark.parametrize('op_table_size', [1, 4])
def test_coexist(request, op_table_size):
    path = Path(__file__).with_name('test_mqnic_core_pcie_us.py')
    spec = importlib.util.spec_from_file_location('raw_core_configuration', path)
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)

    def variant(**kwargs):
        kwargs.update(module='test_raw_packet_coexist', timeout_seconds=600,
                      sim_build=str(Path(__file__).parent/'sim_build'/f'coexist_2x1_{op_table_size}'))
        return run_simulation(**kwargs)

    with patch.object(reference, 'run_simulation', variant):
        reference.test_mqnic_core_pcie_us(request, 2, 1, op_table_size)
