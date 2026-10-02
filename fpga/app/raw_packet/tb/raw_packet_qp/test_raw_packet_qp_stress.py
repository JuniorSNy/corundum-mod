# SPDX-License-Identifier: BSD-2-Clause
"""Continuous publication, randomized errors and controlled latency measurements."""
import json
import os
from pathlib import Path
import random
import struct
import cocotb
from cocotb.triggers import Timer, with_timeout
from cocotb.utils import get_sim_time
import pytest
from raw_qp_tb import init_pipeline, put_packet, CORUNDUM
from raw_app import wait_cqe
from sim_runner import run_simulation

SEEDS = [11, 29, 101]
DATA_STATUS_DELAY_NS = 400
MAC_COMPLETION_DELAY_NS = 1000
CQ_STATUS_DELAY_NS = 128


async def continuous_run(tb, specs, start, *, varied_delay=False):
    """Keep a 16-entry SQ window occupied; retire only committed CQ records."""
    ring_size = 16
    completions = []
    payload_before = len(tb.data_descriptors)
    expected_payload_count = 0
    published = start
    publication_times = {}
    latencies = []

    def publish(sequence):
        nonlocal expected_payload_count
        publication_times[sequence] = float(get_sim_time(units='ns'))
        packet, status, flags = specs[sequence-start]
        key = 0x2233 if status == 0x31 else 0x1233
        put_packet(tb, sequence, packet, ring_size=ring_size, key=key)
        sqoff = (sequence % ring_size)*32
        if flags:
            tb.mem[sqoff+24:sqoff+28] = struct.pack('<I', flags)
        dma_addr = tb.base+0x10000+(sequence % 32)*16384+3
        if status == 0x42:
            tb.errors[('data', dma_addr)] = 2
        if status == 0x12:
            tb.errors[('ctrl', tb.base+sqoff)] = 2
        if status in (0, 0x42):
            expected_payload_count += 1
        tb.data_delays[dma_addr] = ((sequence % 3)*300+20 if varied_delay else DATA_STATUS_DELAY_NS)

    async def return_mac(tag):
        await Timer(MAC_COMPLETION_DELAY_NS, units='ns')
        await tb.complete_tx(tag)

    async def receive():
        for packet, status, _ in specs:
            if status == 0:
                frame = await with_timeout(tb.tx.recv(), 20, 'us')
                assert bytes(frame) == packet, 'TX payload or per-QP order mismatch'
                completions.append(cocotb.start_soon(return_mac(int(frame.tuser) >> 1)))

    receiver = cocotb.start_soon(receive())
    for sequence in range(start, min(start+ring_size, start+len(specs))):
        publish(sequence)
        published += 1
    await tb.write(0x38, published)
    commit_times = []
    for i, (packet, status, _) in enumerate(specs):
        sequence = start+i
        if i and i % 256 == 0:
            tb.dut._log.warning('Committed %d/%d WQEs at sequence %d', i, len(specs), sequence)
        cqe = await wait_cqe(tb.mem, 0x4000+(sequence % ring_size)*32, (sequence+1) & 0xffffffff)
        expected = (0 if status == 0x12 else 0xfeed0000+sequence,
                    status, 0 if status == 0x12 else len(packet), sequence, 0, 0, sequence+1)
        assert cqe == expected
        commit_times.append(float(get_sim_time(units='ns')))
        latencies.append(commit_times[-1]-publication_times[sequence])
        await tb.write(0x44, sequence+1)
        if published < start+len(specs):
            publish(published)
            published += 1
            await tb.write(0x38, published)
    await with_timeout(receiver, 20, 'us')
    for completion in completions:
        await completion
    await tb.wait_reg(0x40, start+len(specs))
    assert tb.tx.empty(), 'unexpected extra frame'
    assert len(tb.data_descriptors)-payload_before == expected_payload_count
    assert await tb.read(0x54) == 0
    assert await tb.read(0x1c) == 0
    return commit_times, latencies


@cocotb.test(timeout_time=30, timeout_unit='ms')
async def stress_and_latency(dut):
    tb = await init_pipeline(dut, ring_log=4)
    tb.cq_delay_ns = CQ_STATUS_DELAY_NS
    depth = int(dut.OP_TABLE_SIZE.value)
    axis_width = len(dut.m_axis_tx_tdata)
    stress_count = int(os.environ.get('RAW_STRESS_COUNT', 1024))
    sequence = 0
    seed = int(os.environ['RAW_STRESS_SEED'])
    for seed in [seed]:
        rng = random.Random(seed)
        specs = []
        for i in range(stress_count):
            length = rng.choice([14, 60, 64, 65, 127, 1514, 4097, 9214])
            flags = 0
            status = 0
            if i % 43 == 0:
                status = 0x12
            elif i % 31 == 0:
                flags, status = 1, 0x20
            elif i % 19 == 0:
                status = 0x31
            elif i % 29 == 0:
                status = 0x42
            packet = struct.pack('<QI', sequence+i, seed)+bytes((j+seed) & 255 for j in range(length-12))
            specs.append((packet, status, flags))
        dut._log.warning('Stress depth=%d width=%d seed=%d count=%d', depth, axis_width, seed, stress_count)
        await continuous_run(tb, specs, sequence, varied_delay=True)
        sequence += len(specs)
    metrics = {'depth': depth, 'axis_width': axis_width, 'seeds': [seed], 'stress_seed': seed,
               'stress_count_per_seed': stress_count, 'data_status_delay_ns': DATA_STATUS_DELAY_NS,
               'mac_completion_delay_ns': MAC_COMPLETION_DELAY_NS, 'cq_status_delay_ns': CQ_STATUS_DELAY_NS,
               'frames': {}}
    for length in ([64, 1514, 9214] if seed == SEEDS[0] else []):
        specs = [(bytes((j+i) & 255 for j in range(length)), 0, 0) for i in range(96)]
        times, latencies = await continuous_run(tb, specs, sequence)
        # Ignore the first 16 completions, but keep the continuous window full.
        interval = times[-1]-times[15]
        metrics['frames'][str(length)] = {'wqe_per_second': 80e9/interval,
                                          'payload_bytes_per_second': 80e9*length/interval,
                                          'steady_interval_ns': interval,
                                          'commit_latency_ns': {'min': min(latencies),
                                                                'median': sorted(latencies)[len(latencies)//2],
                                                                'p99': sorted(latencies)[int(len(latencies)*0.99)],
                                                                'max': max(latencies)}}
        sequence += len(specs)
    Path('pipeline_metrics.json').write_text(json.dumps(metrics, indent=2)+'\n')


@pytest.mark.parametrize('seed', SEEDS)
@pytest.mark.parametrize('axis_width', [256, 512])
@pytest.mark.parametrize('op_table_size', [1, 2, 4])
def test_qp_stress(axis_width, op_table_size, seed):
    app = Path(__file__).resolve().parents[2]
    sources = list((app/'rtl').glob('raw_*.v'))
    sources += [CORUNDUM/'fpga/lib/pcie/rtl'/name for name in ['dma_psdpram.v', 'dma_client_axis_source.v']]
    sources += list((CORUNDUM/'fpga/lib/axi/rtl').glob('axil_reg_if*.v'))
    run_simulation(verilog_sources=[str(p) for p in sources], toplevel='raw_packet_qp',
                   module='test_raw_packet_qp_stress', python_search=[str(Path(__file__).resolve().parent)],
                   parameters={'AXIS_DATA_WIDTH': axis_width, 'AXIS_KEEP_WIDTH': axis_width//8,
                               'OP_TABLE_SIZE': op_table_size},
                   extra_env={'RAW_STRESS_COUNT': os.environ.get('RAW_STRESS_COUNT', '1024'),
                              'RAW_STRESS_SEED': str(seed)},
                   timeout_seconds=600, sim_build=str(app/f'tb/sim_build/stress_{axis_width}_{op_table_size}_{seed}'))
