# SPDX-License-Identifier: BSD-2-Clause
"""Host-side raw app ABI helpers; these do not model RTL queue state."""
import struct
from cocotb.triggers import Timer, with_timeout

SQE = struct.Struct('<QQIIII')
CQE = struct.Struct('<QIIIIII')
ENTRY_SIZE = 32
APP_ID = 0x12348010
ENABLE = 0x10
STATUS = 0x14
CONFIG_ERROR = 0x18
FATAL = 0x1c
SQ_BASE = 0x20
CQ_BASE = 0x28
RING_LOG = 0x30
PD = 0x34
SQ_PROD = 0x38
SQ_CONS = 0x3c
CQ_PROD = 0x40
CQ_CONS = 0x44
QUEUE_RESET = 0x4c
MR_INDEX = 0x80
MR_KEY = 0x84
MR_PD = 0x88
MR_FLAGS = 0x8c
MR_VA = 0x90
MR_DMA = 0x98
MR_LENGTH = 0xa0
MR_COMMIT = 0xa8


async def wait_cqe(mem, offset, sequence, timeout_us=100):
    """Poll publication first, then read the record; producer MMIO is insufficient."""
    async def poll():
        while int.from_bytes(bytes(mem[offset+28:offset+32]), 'little') != sequence:
            await Timer(20, units='ns')
        record = CQE.unpack(bytes(mem[offset:offset+ENTRY_SIZE]))
        assert record[-1] == sequence
        return record
    return await with_timeout(poll(), timeout_us, 'us')


async def wait_register(regs, offset, value, timeout_us=100):
    async def poll():
        while await regs.read_dword(offset) != value:
            await Timer(20, units='ns')
    await with_timeout(poll(), timeout_us, 'us')
