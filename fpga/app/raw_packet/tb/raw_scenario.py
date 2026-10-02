# SPDX-License-Identifier: BSD-2-Clause
import cocotb
from cocotb.triggers import with_timeout
from raw_app import (
    APP_ID, ENABLE, STATUS, CONFIG_ERROR, SQ_BASE, CQ_BASE, RING_LOG, PD,
    SQ_PROD, CQ_PROD, CQ_CONS, MR_INDEX, MR_KEY, MR_PD, MR_FLAGS, MR_VA,
    MR_DMA, MR_LENGTH, MR_COMMIT, SQE, wait_cqe, wait_register,
)


async def exercise_raw_and_normal(tb):
    await tb.init()
    await tb.driver.init_pcie_dev(tb.rc.find_device(tb.dev.functions[0].pcie_id))
    for interface in tb.driver.interfaces:
        for ndev in interface.ndevs:
            await ndev.open()
    regs = tb.driver.app_hw_regs
    assert await regs.read_dword(0x0c) == APP_ID
    mem = tb.rc.mem_pool.alloc_region(0x20000)
    base = mem.get_absolute_address(0)
    async def wr64(offset, value):
        await regs.write_dword(offset, value & 0xffffffff)
        await regs.write_dword(offset+4, value >> 32)
    await wr64(SQ_BASE, base)
    await wr64(CQ_BASE, base+0x4000)
    await regs.write_dword(RING_LOG, 4)
    await regs.write_dword(PD, 7)
    await regs.write_dword(MR_INDEX, 3)
    await regs.write_dword(MR_KEY, 0x1233)
    await regs.write_dword(MR_PD, 7)
    await regs.write_dword(MR_FLAGS, 0x80000001)
    await wr64(MR_VA, 0x1000)
    await wr64(MR_DMA, base+0x8000)
    await wr64(MR_LENGTH, 0x10000)
    await regs.write_dword(MR_COMMIT, 1)
    await regs.write_dword(ENABLE, 1)
    assert await regs.read_dword(CONFIG_ERROR) == 0

    # One normal stream per physical port; payload markers distinguish streams.
    endpoints = [ndev for interface in tb.driver.interfaces for ndev in interface.ndevs]
    assert len(endpoints) == len(tb.port_mac)
    normal = [[bytes((j+0x80+i+16*p) & 255 for j in range(n))
               for i, n in enumerate([64, 1514, 4097, 9014])]
              for p in range(len(endpoints))]
    raw = [bytes((j+i) & 255 for j in range(n)) for i,n in enumerate([64, 65, 1514, 4097, 9214])]
    offset = 3
    for i,pkt in enumerate(raw):
        mem[0x8000+offset:0x8000+offset+len(pkt)] = pkt
        mem[i*32:(i+1)*32] = SQE.pack(i+100, 0x1000+offset, len(pkt), 0x1233, 0, 0)
        offset += len(pkt)+11
    # Publish all raw SQEs, and concurrently exercise the normal NIC TX DMA path.
    async def normal_tx(ndev, packets):
        for pkt in packets:
            await ndev.start_xmit(pkt, 0)
    tasks = [cocotb.start_soon(normal_tx(ndev, normal[p]))
             for p, ndev in enumerate(endpoints)]
    await regs.write_dword(SQ_PROD, len(raw))

    async def check_port(p):
        raw_seen, normal_seen = [], []
        for _ in range(len(normal[p]) + (len(raw) if p == 0 else 0)):
            pkt = bytes(await with_timeout(tb.port_mac[p].tx.recv(), 100, 'us'))
            if p == 0 and pkt in raw:
                raw_seen.append(pkt)
            else:
                normal_seen.append(pkt)
        assert normal_seen == normal[p], f'port {p} normal TX order/content'
        assert raw_seen == (raw if p == 0 else []), f'port {p} raw TX order/content'
    checks = [cocotb.start_soon(check_port(p)) for p in range(len(endpoints))]
    for task in tasks + checks:
        await task
    for i, pkt in enumerate(raw):
        cqe = await wait_cqe(mem, 0x4000+i*32, i+1)
        assert cqe == (i+100, 0, len(pkt), i, 0, 0, i+1)
    await wait_register(regs, CQ_PROD, len(raw))
    await regs.write_dword(CQ_CONS, len(raw))

    # Invalid MR generates a CQE through real PCIe DMA, with no Ethernet frame.
    i=len(raw)
    mem[i*32:(i+1)*32] = SQE.pack(999, 0x1000, 64, 0x2233, 0, 0)
    await regs.write_dword(SQ_PROD, i+1)
    cqe = await wait_cqe(mem, 0x4000+i*32, i+1)
    assert cqe == (999, 0x31, 64, i, 0, 0, i+1)
    await wait_register(regs, CQ_PROD, i+1)
    assert all(mac.tx.empty() for mac in tb.port_mac)
    # RX and subsequent normal TX on every port after the raw queue drained.
    for p, ndev in enumerate(endpoints):
        await tb.port_mac[p].rx.send(normal[p][0])
        pkt = await with_timeout(ndev.recv(), 100, 'us')
        assert bytes(pkt.data) == normal[p][0]
        await ndev.start_xmit(normal[p][1], 0)
        assert bytes(await with_timeout(tb.port_mac[p].tx.recv(), 100, 'us')) == normal[p][1]
    await regs.write_dword(ENABLE, 0)
    await wait_register(regs, STATUS, 0)
