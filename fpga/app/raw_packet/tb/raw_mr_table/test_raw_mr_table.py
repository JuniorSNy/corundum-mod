"""MR 保护与翻译测试；预期值只使用软件整数运算，不复制 RTL 状态机。"""

import os
from pathlib import Path
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer
from sim_runner import run_simulation


@cocotb.test(timeout_time=200, timeout_unit='us')
async def mr_protection(dut):
    """检查完整 key、PD、权限、边界、溢出、输出反压和复位失效。"""
    cocotb.start_soon(Clock(dut.clk, 4, units="ns").start())
    dut.rst.value = 1
    dut.cfg_valid.value = 0
    dut.req_valid.value = 0
    dut.resp_ready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0

    async def configure(key=0x1233, pd=7, va=0x1000, dma=0x8000, length=4096,
                        permissions=1, enable=1):
        await FallingEdge(dut.clk)
        values = dict(index=key & 15, key=key, pd=pd, vaddr=va, dma_addr=dma,
                      length=length, permissions=permissions, enable=enable)
        for name, value in values.items():
            getattr(dut, "cfg_" + name).value = value
        dut.cfg_valid.value = 1
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.cfg_valid.value = 0

    async def query(address, length, expected_error=0, expected_addr=0,
                    key=0x1233, pd=7, permissions=1, stall=0):
        await FallingEdge(dut.clk)
        dut.req_key.value = key
        dut.req_pd.value = pd
        dut.req_vaddr.value = address
        dut.req_length.value = length
        dut.req_permissions.value = permissions
        dut.req_valid.value = 1
        assert dut.req_ready.value == 1
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.req_valid.value = 0
        assert dut.resp_valid.value == 1
        assert int(dut.resp_error.value) == expected_error
        assert int(dut.resp_dma_addr.value) == (expected_addr if not expected_error else 0)
        snapshot = (int(dut.resp_error.value), int(dut.resp_dma_addr.value))
        for _ in range(stall):
            await RisingEdge(dut.clk)
            await FallingEdge(dut.clk)
            assert dut.req_ready.value == 0
            assert dut.resp_valid.value == 1
            assert (int(dut.resp_error.value), int(dut.resp_dma_addr.value)) == snapshot
        dut.resp_ready.value = 1
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.resp_ready.value = 0

    await query(0x1000, 64, expected_error=1)
    await configure()
    await query(0x1003, 61, expected_addr=0x8003, stall=9)
    await query(0x1fff, 1, expected_addr=0x8fff)
    await query(0x2000, 1, expected_error=4)
    await query(0xfff, 1, expected_error=4)
    await query(0x1000, 0, expected_error=4)
    await query(0x1000, 1, key=0x2233, expected_error=1)
    await query(0x1000, 1, pd=8, expected_error=2)
    await query(0x1000, 1, permissions=2, expected_error=3)
    rng = random.Random(0x250)
    for _ in range(100):
        addr = rng.randrange(0x800, 0x2800)
        size = rng.randrange(1, 1024)
        valid = 0x1000 <= addr and addr + size <= 0x2000
        await query(addr, size, expected_error=0 if valid else 4,
                    expected_addr=0x8000+addr-0x1000, stall=rng.randrange(4))
    await configure(va=0, dma=(1 << 64)-16, length=4096)
    await query(0, 16, expected_addr=(1 << 64)-16)
    await query(0, 17, expected_error=5)
    await query(32, 1, expected_error=5)
    await configure(va=(1 << 64)-16, dma=0, length=4096)
    await query((1 << 64)-16, 17, expected_error=5)
    await configure(enable=0)
    await query(0x1000, 1, expected_error=1)
    await configure()
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    await query(0x1000, 64, expected_error=1)


def test_mr():
    """使用项目已有 cocotb/Icarus 环境执行单模块测试。"""
    root = Path(__file__).resolve().parents[2]
    run_simulation(
        simulator="icarus", verilog_sources=[str(root / "rtl/raw_mr_table.v")],
        toplevel="raw_mr_table", module="test_raw_mr_table", python_search=[str(Path(__file__).resolve().parent)],
        sim_build=os.environ.get("SIM_BUILD", str(root / "tb/sim_build/mr")),
    )
