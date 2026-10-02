# SPDX-License-Identifier: BSD-2-Clause
"""Fixed latency benchmark for the archived single-inflight RTL."""
import json
from pathlib import Path
import cocotb
from raw_qp_tb import init_pipeline
from test_raw_packet_qp_stress import continuous_run
from sim_runner import run_simulation


@cocotb.test(timeout_time=5, timeout_unit='ms')
async def reference_latency(dut):
    tb = await init_pipeline(dut, ring_log=4)
    tb.cq_delay_ns = 128
    result = {'reference_revision': '0784146c', 'axis_width': len(dut.m_axis_tx_tdata), 'frames': {}}
    sequence = 0
    for length in (64, 1514, 9214):
        specs = [(bytes((j+i) & 255 for j in range(length)), 0, 0) for i in range(96)]
        times, latencies = await continuous_run(tb, specs, sequence)
        result['frames'][str(length)] = {'wqe_per_second': 80e9/(times[-1]-times[15]),
                                       'commit_latency_ns': {'min': min(latencies), 'max': max(latencies)}}
        sequence += len(specs)
    Path('reference_metrics.json').write_text(json.dumps(result, indent=2)+'\n')
