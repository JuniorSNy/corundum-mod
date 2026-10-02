# SPDX-License-Identifier: BSD-2-Clause
"""Require full stress evidence and compare fixed-latency depth 1/2/4 runs."""
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET


def check_metrics(root):
    records = {}
    for path in root.rglob('pipeline_metrics.json'):
        record = json.loads(path.read_text())
        key = (record['axis_width'], record['depth'], record['stress_seed'])
        if key in records:
            raise AssertionError(f'Duplicate metrics for {key}: {path}')
        assert record['stress_count_per_seed'] >= 1024, f'Only development stress: {path}'
        assert record['stress_seed'] in (11, 29, 101) and record['seeds'] == [record['stress_seed']], path
        assert (record['data_status_delay_ns'], record['mac_completion_delay_ns'],
                record['cq_status_delay_ns']) == (400, 1000, 128), path
        xml = list(path.parent.glob('*results.xml'))
        assert len(xml) == 1, f'Use a fresh build directory: {path.parent}'
        cases = list(ET.parse(xml[0]).iter('testcase'))
        assert len(cases) == 1 and not any(list(c.iter(tag)) for c in cases
                                           for tag in ('failure', 'error', 'skipped')), xml
        assert cases[0].get('name') == 'stress_and_latency', xml
        for length in (('64', '1514', '9214') if record['stress_seed'] == 11 else ()):
            metrics = record['frames'][length]
            assert metrics['wqe_per_second'] > 0 and metrics['steady_interval_ns'] > 0, path
            assert metrics['commit_latency_ns']['max'] >= metrics['commit_latency_ns']['min'] > 0, path
        records[key] = record
    assert set(records) == {(w, d, seed) for w in (256, 512) for d in (1, 2, 4) for seed in (11, 29, 101)}, 'Missing stress matrix'
    summary = []
    for width in (256, 512):
        for length in ('64', '1514', '9214'):
            values = {d: records[(width, d, 11)]['frames'][length]['wqe_per_second'] for d in (1, 2, 4)}
            ratio = values[4]/values[1]
            if length == '64':
                assert ratio >= 2, f'Controlled latency improvement failed: width={width}, ratio={ratio}'
            row = {'axis_width': width, 'length': int(length), 'wqe_per_second': values,
                   'depth_4_over_1': ratio}
            summary.append(row)
            print(f'AXIS {width}, {length} bytes: depth 4 / depth 1 = {ratio:.3f}x')
    (root/'pipeline_metrics_summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    return summary


if __name__ == '__main__':
    check_metrics(Path(os.environ.get('RAW_SIM_BUILD_ROOT', Path(__file__).resolve().parent/'sim_build')))
