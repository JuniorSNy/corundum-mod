"""A missing status faults acceptance without releasing DMA ownership."""
from pathlib import Path
import cocotb
from cocotb.triggers import Timer, with_timeout
from raw_qp_tb import init_pipeline, put_packet, wait_pending, CORUNDUM, StatusTransaction
from raw_app import wait_cqe
from sim_runner import run_simulation


@cocotb.test(timeout_time=200, timeout_unit='us')
async def missing_status_quarantine(dut):
    tb = await init_pipeline(dut)
    tb.hold_data_status = True
    packets = [bytes((j+7*i) & 255 for j in range(65+i)) for i in range(3)]
    for i, packet in enumerate(packets):
        put_packet(tb, i, packet)
    await tb.write(0x38, 3)
    await wait_pending(tb, 2)
    await tb.wait_reg(0x1c, 0x60)
    assert await tb.read(0x54) == 2
    assert await tb.read(0x58) == 2
    assert await tb.read(0x14) & 1
    assert tb.tx.empty()
    await tb.write(0x10, 0)
    await tb.write(0x4c, 1)
    assert await tb.read(0x18) == 5, 'reset accepted before DMA drain'
    assert await tb.read(0x58) == 2
    # Late statuses allow the accepted datapath to drain, without publishing
    # or recycling quarantined contexts. No third descriptor is accepted.
    for source, tag, error in reversed(tb.data_statuses):
        await source.send(StatusTransaction(tag=tag, error=error))
    old_tags = []
    for packet in packets[:2]:
        frame = await with_timeout(tb.tx.recv(), 20, 'us')
        assert bytes(frame) == packet
        tag = int(frame.tuser) >> 1
        old_tags.append(tag)
        await tb.complete_tx(tag)
    await tb.wait_reg(0x14, 0x100)
    assert await tb.read(0x40) == 0
    assert await tb.read(0x3c) == 0
    assert await tb.read(0x54) == 2
    assert len(tb.data_descriptors) == 2
    # In this model all issued DMA and MAC work is now accounted for.
    await tb.write(0x4c, 1)
    await tb.write(0x18, 0)
    assert await tb.read(0x1c) == 0
    tb.hold_data_status = False
    put_packet(tb, 0, packets[2])
    await tb.write(0x10, 1)
    await tb.write(0x38, 1)
    frame = await with_timeout(tb.tx.recv(), 20, 'us')
    new_tag = int(frame.tuser) >> 1
    assert new_tag not in old_tags, 'allocation generation reset with queue counters'
    await tb.complete_tx(old_tags[0])
    await Timer(40, units='ns')
    assert await tb.read(0x40) == 0
    await tb.complete_tx(new_tag)
    await tb.wait_reg(0x40, 1)
    assert await wait_cqe(tb.mem, 0x4000, 1) == (0xfeed0000, 0, len(packets[2]), 0, 0, 0, 1)


def test_qp_fault():
    app = Path(__file__).resolve().parents[2]
    sources = list((app/'rtl').glob('raw_*.v'))
    sources += [CORUNDUM/'fpga/lib/pcie/rtl'/name for name in ['dma_psdpram.v', 'dma_client_axis_source.v']]
    sources += list((CORUNDUM/'fpga/lib/axi/rtl').glob('axil_reg_if*.v'))
    run_simulation(verilog_sources=[str(p) for p in sources], toplevel='raw_packet_qp',
                   module='test_raw_packet_qp_fault', python_search=[str(Path(__file__).resolve().parent)],
                   parameters={'OP_TABLE_SIZE': 2, 'WATCHDOG_CYCLES': 128},
                   sim_build=str(app/'tb/sim_build/qp_fault'))
