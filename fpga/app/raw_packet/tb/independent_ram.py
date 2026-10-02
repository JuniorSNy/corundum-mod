"""

Copyright (c) 2020-2023 Alex Forencich

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

"""

# Segment loop derived from Corundum dma_psdp_ram.py. Change only per-segment
# command/response pauses; retain its queues and transaction reconstruction.
import logging
from cocotb.triggers import RisingEdge
from dma_psdp_ram import PsdpRamMasterRead


class IndependentSegmentRead(PsdpRamMasterRead):
    async def _run(self):
        cmd_valid = 0
        cmd_addr = 0
        resp_ready = 0
        cycle = 0
        self.stall_counts = [0]*self.seg_count

        clock_edge_event = RisingEdge(self.clock)

        while True:
            await clock_edge_event

            cmd_ready_sample = self.bus.rd_cmd_ready.value
            resp_valid_sample = self.bus.rd_resp_valid.value

            if resp_valid_sample:
                resp_data_sample = self.bus.rd_resp_data.value

            if self.reset is not None and self.reset.value:
                self.bus.rd_cmd_valid.setimmediatevalue(0)
                self.bus.rd_resp_ready.setimmediatevalue(0)
                cmd_valid = 0
                resp_ready = 0
                continue

            cycle += 1
            # process segments
            for seg in range(self.seg_count):
                seg_mask = 1 << seg
                if resp_valid_sample & seg_mask and not resp_ready & seg_mask:
                    self.stall_counts[seg] += 1

                if (cmd_ready_sample & seg_mask) or not (cmd_valid & seg_mask):
                    if not self.seg_read_queue[seg].empty() and not self.pause and (cycle+2*seg) % 7 == 0:
                        op = await self.seg_read_queue[seg].get()
                        cmd_addr &= ~(self.seg_addr_mask << self.seg_addr_width*seg)
                        cmd_addr |= ((op.addr & self.seg_addr_mask) << self.seg_addr_width*seg)
                        cmd_valid |= seg_mask

                        if self.log.isEnabledFor(logging.INFO):
                            self.log.info("Read word seg: %d addr: 0x%08x", seg, op.addr)
                    else:
                        cmd_valid &= ~seg_mask

                if resp_ready & resp_valid_sample & (1 << seg):
                    seg_data = (resp_data_sample >> self.seg_data_width*seg) & self.seg_data_mask

                    await self.seg_read_resp_queue[seg].put(seg_data)

            resp_ready = sum(1 << seg for seg in range(self.seg_count) if (cycle+2*seg) % 7 >= 4)

            if self.pause:
                resp_ready = 0

            self.bus.rd_cmd_valid.value = cmd_valid
            self.bus.rd_cmd_addr.value = cmd_addr

            self.bus.rd_resp_ready.value = resp_ready

