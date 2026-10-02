# SPDX-License-Identifier: BSD-2-Clause
"""CSR protocol, configuration ownership and nonzero register-block relocation."""
from pathlib import Path
import itertools
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer
from cocotbext.axi import AxiLiteMaster, AxiLiteBus
from sim_runner import run_simulation
from raw_qp_tb import CORUNDUM


@cocotb.test(timeout_time=100, timeout_unit='us')
async def csr_ownership(dut):
    cocotb.start_soon(Clock(dut.clk, 4, units='ns').start())
    dut.rst.value = 1
    for name, value in {'idle': 1, 'queue_config_valid': 1, 'ring_size': 4,
                        'sq_cons': 0, 'cq_prod': 0, 'fatal': 0, 'op_table_size': 4,
                        'active_count': 0, 'fetch_ptr': 0, 'phase': 0,
                        'unexpected_count': 0, 'stall_count': 0}.items():
        getattr(dut, name).value = value
    master = AxiLiteMaster(AxiLiteBus.from_prefix(dut, 's_axil_app_ctrl'), dut.clk, dut.rst)
    master.write_if.aw_channel.set_pause_generator(itertools.cycle([1, 0, 0]))
    master.write_if.w_channel.set_pause_generator(itertools.cycle([0, 1, 1, 0]))
    master.write_if.b_channel.set_pause_generator(itertools.cycle([1, 1, 0, 0]))
    master.read_if.r_channel.set_pause_generator(itertools.cycle([1, 0, 1, 0]))
    await Timer(40, units='ns')
    dut.rst.value = 0
    await Timer(40, units='ns')
    base = 0x100
    async def rd(offset):
        return await master.read_dword(base+offset)
    async def wr(offset, value):
        await master.write_dword(base+offset, value)
    assert await rd(0) == 0x12348110
    assert await rd(8) == 0x200
    assert await master.read_dword(0) == 0, 'CSR block aliases address zero'
    await master.write(base+0x20, b'\x12')
    assert await rd(0x18) == 1
    assert await rd(0x20) == 0
    await wr(0x18, 0)
    await wr(0x20, 0x1000)
    assert await rd(0x20) == 0x1000
    await wr(0x30, 0)
    assert await rd(0x18) == 2
    await wr(0x30, 2)
    await wr(0x38, 4)
    await wr(0x38, 5)
    assert await rd(0x38) == 4
    assert await rd(0x18) == 3
    dut.cq_prod.value = 2
    await wr(0x44, 3)
    assert await rd(0x44) == 0
    assert await rd(0x18) == 4
    await wr(0x44, 2)
    assert await rd(0x44) == 2
    await wr(0x10, 1)
    dut.idle.value = 0
    await wr(0x20, 0x2000)
    assert await rd(0x20) == 0x1000
    assert await rd(0x18) == 5
    await wr(0x10, 0)
    await wr(0x4c, 1)
    assert await rd(0x38) == 4, 'reset while busy changed producer'
    dut.idle.value = 1
    await wr(0x4c, 1)
    assert await rd(0x38) == 0
    assert await rd(0x44) == 0
    dut.queue_config_valid.value = 0
    await wr(0x10, 1)
    assert await rd(0x10) == 0
    dut.queue_config_valid.value = 1
    dut.fatal.value = 0x60
    await wr(0x10, 1)
    assert await rd(0x10) == 0
    assert await rd(0x1c) == 0x60
    assert await rd(0x14) == 0x100
    assert await rd(0x50) == 4
    await wr(0x200, 1)
    assert await rd(0x18) == 6


def test_csr():
    app = Path(__file__).resolve().parents[2]
    sources = [app/'rtl/raw_packet_csr.v']+list((CORUNDUM/'fpga/lib/axi/rtl').glob('axil_reg_if*.v'))
    run_simulation(verilog_sources=[str(p) for p in sources], toplevel='raw_packet_csr',
                   module='test_raw_packet_csr', python_search=[str(Path(__file__).resolve().parent)],
                   parameters={'RB_BASE_ADDR': 0x100, 'RB_NEXT_PTR': 0x200},
                   sim_build=str(app/'tb/sim_build/csr'))
