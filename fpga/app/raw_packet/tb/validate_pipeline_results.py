# SPDX-License-Identifier: BSD-2-Clause
"""Validate the complete 64-case raw TX acceptance run before collecting it.

This is an acceptance tool, not a simulator input. It deliberately leaves the
collector and the captured testbench sources unchanged. Integration identities
include topology/depth and require the app configuration; unrelated Corundum
parameters are retained by the collector and versioned testbench manifests.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from check_pipeline_metrics import check_metrics
from collect_pipeline_results import collect


FUNCTIONAL_RUNS = 60
FUNCTIONAL_CASES = 74
INTEGRATION_MODULES = {
    'test_mqnic_core_pcie_us', 'test_raw_packet_coexist', 'test_fpga_core_raw_packet',
}
APP_PARAMETERS = {
    'APP_ID': 0x12348010, 'APP_ENABLE': 1, 'APP_CTRL_ENABLE': 1,
    'APP_DMA_ENABLE': 1, 'APP_AXIS_DIRECT_ENABLE': 0, 'APP_AXIS_SYNC_ENABLE': 1,
    'APP_AXIS_IF_ENABLE': 0, 'APP_STAT_ENABLE': 0,
}
EXTRA_MODELS = (
    'fpga/mqnic/Alveo/fpga_100g/tb/fpga_core/test_fpga_core.py',
    'fpga/common/tb/mqnic.py',
    'fpga/lib/pcie/tb/dma_psdp_ram.py',
)


def identity(module, parameters, scenario):
    if module in INTEGRATION_MODULES:
        parameters = {name: parameters[name]
                      for name in ('IF_COUNT', 'PORTS_PER_IF', 'RAW_TX_OP_TABLE_SIZE')}
    return module, tuple(sorted(parameters.items())), tuple(sorted(scenario.items()))


def expected_matrix():
    expected = {}

    def add(module, cases, parameters=None, scenario=None):
        key = identity(module, parameters or {}, scenario or {})
        assert key not in expected
        expected[key] = tuple(cases)

    add('test_raw_mr_table', ['mr_protection'])
    add('test_raw_dma_read', ['dma_protocol'])
    add('test_raw_packet_csr', ['csr_ownership'], {'RB_BASE_ADDR': 0x100, 'RB_NEXT_PTR': 0x200})
    for depth in (1, 2, 4):
        for width in (256, 512):
            parameters = {'OP_TABLE_SIZE': depth, 'AXIS_DATA_WIDTH': width, 'AXIS_KEEP_WIDTH': width//8}
            add('test_raw_packet_qp', ['raw_sq_to_ethernet', 'pipeline_reorder_stop', 'pipeline_cq_credit'],
                parameters)
            add('test_raw_packet_qp_phases', ['phase_wait_metrics'], parameters)
            for seed in (11, 29, 101):
                add('test_raw_packet_qp_stress', ['stress_and_latency'], parameters,
                    {'RAW_STRESS_COUNT': '1024', 'RAW_STRESS_SEED': str(seed)})
    add('test_raw_packet_qp_fault', ['missing_status_quarantine'],
        {'OP_TABLE_SIZE': 2, 'WATCHDOG_CYCLES': 128})
    for stage in ('sq', 'mac', 'cq'):
        add('test_raw_packet_qp_missing', ['missing_completion'],
            {'OP_TABLE_SIZE': 2, 'WATCHDOG_CYCLES': 128}, {'RAW_MISSING_STAGE': stage})
    add('test_raw_packet_qp_segments', ['independent_cq_segments'],
        {'OP_TABLE_SIZE': 4, 'AXIS_DATA_WIDTH': 256, 'AXIS_KEEP_WIDTH': 32, 'RAM_SEG_DATA_WIDTH': 128})
    add('test_raw_packet_qp_sq_tags', ['sq_generation_isolation'], {'OP_TABLE_SIZE': 4})
    for stage in ('sq_desc', 'sq_status', 'payload_desc', 'payload_status',
                  'tx_stream', 'mac_wait', 'cq_desc', 'cq_status'):
        add('test_raw_packet_qp_stop', ['stop_at_boundary'], {'OP_TABLE_SIZE': 4}, {'RAW_STOP_STAGE': stage})
    add('test_raw_packet_qp_stop_midframe', ['stop_inside_frame'],
        {'OP_TABLE_SIZE': 4, 'AXIS_DATA_WIDTH': 512, 'AXIS_KEEP_WIDTH': 64})
    for scenario, depth, watchdog in (('late_reset', 2, 128), ('cq_error', 4, 0)):
        add('test_raw_packet_qp_drain', ['fatal_drain_ownership'],
            {'OP_TABLE_SIZE': depth, 'WATCHDOG_CYCLES': watchdog}, {'RAW_DRAIN_SCENARIO': scenario})
    add('test_raw_packet_qp_wrap', ['counters_and_tag_wrap'],
        {'OP_TABLE_SIZE': 4, 'DMA_TAG_WIDTH': 3, 'TX_TAG_WIDTH': 4})
    for interfaces, ports, depth in ((1, 1, 1), (1, 2, 1), (2, 1, 1), (2, 1, 2), (2, 1, 4)):
        add('test_mqnic_core_pcie_us', ['raw_and_normal_nic'],
            {'IF_COUNT': interfaces, 'PORTS_PER_IF': ports, 'RAW_TX_OP_TABLE_SIZE': depth})
    for depth in (1, 4):
        parameters = {'IF_COUNT': 2, 'PORTS_PER_IF': 1, 'RAW_TX_OP_TABLE_SIZE': depth}
        add('test_raw_packet_coexist', ['both_ports_coexist'], parameters)
        add('test_fpga_core_raw_packet', ['raw_and_normal_board', 'ordinary_nic_regression'], parameters)
    assert len(expected) == FUNCTIONAL_RUNS
    assert sum(map(len, expected.values())) == FUNCTIONAL_CASES
    return expected


def validate_matrix(root):
    """Reject duplicate/missing runs and check actual named, passed XML cases."""
    expected = expected_matrix()
    seen = {}
    fixtures = set()
    checked_xml = set()
    for path in sorted(root.rglob('source_manifest.json')):
        manifest = json.loads(path.read_text())
        module = manifest['module']
        xmls = list(path.parent.glob('*results.xml'))
        assert len(xmls) == 1, f'Expected exactly one XML beside {path}; found {len(xmls)}'
        xml = xmls[0]
        checked_xml.add(xml)
        cases = list(ET.parse(xml).iter('testcase'))
        if module.startswith('runner_fixture_'):
            outcome = module.removeprefix('runner_fixture_')
            assert outcome in ('pass', 'fail', 'skip', 'empty') and outcome not in fixtures, module
            if outcome == 'empty':
                assert not cases, xml
            else:
                assert len(cases) == 1 and cases[0].get('name') == 'fixture', xml
                failures = bool(list(cases[0].iter('failure')) or list(cases[0].iter('error')))
                skipped = bool(list(cases[0].iter('skipped')))
                assert failures == (outcome == 'fail') and skipped == (outcome == 'skip'), xml
            fixtures.add(outcome)
            continue
        key = identity(module, manifest['parameters'], manifest['scenario'])
        assert key in expected, f'Unexpected functional run: {key}'
        assert key not in seen, f'Duplicate functional run: {key}; {seen.get(key)} and {path}'
        assert manifest['expected_tests'] == len(expected[key]), path
        assert Counter(case.get('name') for case in cases) == Counter(expected[key]), xml
        assert all(case.get('classname') == module for case in cases), xml
        assert not any(list(case.iter(tag)) for case in cases
                       for tag in ('failure', 'error', 'skipped')), xml
        if module in INTEGRATION_MODULES:
            for name, value in APP_PARAMETERS.items():
                assert manifest['parameters'][name] == value, (path, name)
            assert 'APP_CUSTOM_PARAMS_ENABLE' in manifest['defines'], path
            if 'DDR_ENABLE' in manifest['parameters']:
                assert manifest['parameters']['DDR_ENABLE'] == 0, path
        seen[key] = str(path)
    assert checked_xml == set(root.rglob('*results.xml')), 'Orphan XML without a matching manifest'
    assert fixtures == {'pass', 'fail', 'skip', 'empty'}, f'Missing runner fixtures: {fixtures}'
    missing = set(expected)-set(seen)
    assert not missing, f'Missing required functional runs: {sorted(missing)}'
    return len(seen), sum(len(expected[key]) for key in seen)


def extra_model_hashes(repo, revision):
    """Supplement per-run hashes without claiming retrospective capture."""
    records = {}
    for relative in EXTRA_MODELS:
        current = hashlib.sha256((repo/relative).read_bytes()).hexdigest()
        versioned = hashlib.sha256(subprocess.check_output(
            ['git', 'show', f'{revision}:{relative}'], cwd=repo)).hexdigest()
        assert current == versioned, (relative, 'extra model differs from implementation revision')
        records[relative] = current
    return records


def validate(args):
    assert (args.functional_runs, args.functional_cases) == (FUNCTIONAL_RUNS, FUNCTIONAL_CASES)
    root = args.build_root.resolve()
    # Recompute the existing performance gate rather than trust a stale summary.
    check_metrics(root)
    runs, cases = validate_matrix(root)
    repo = Path(__file__).resolve().parents[4]
    revision = subprocess.check_output(['git', 'rev-parse', args.revision], cwd=repo, text=True).strip()
    models = extra_model_hashes(repo, revision)
    # The original collector also checks normal pytest completion and all
    # captured RTL/header/app-Python hashes against this revision and worktree.
    collect(args)
    report = json.loads(args.output.read_text())
    report['explicit_matrix_validation'] = {
        'functional_runs': runs, 'functional_cocotb_cases': cases,
        'pytest_cases_including_runner_contracts': runs+4,
        'unique_xml_per_manifest': True, 'named_module_parameter_scenario_matrix': True,
        'performance_gate_recomputed': True,
    }
    report['additional_python_models'] = {
        'source_sha256': models,
        'checked_against_revision': revision,
        'capture_scope': 'Captured at final acceptance; not captured in each simulation source manifest.',
        'limitation': 'These hashes identify current versioned external models, not their contents at every simulator startup.',
    }
    report['acceptance_validator_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print('Complete module/parameter/scenario matrix and recomputed performance gate validated.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root', type=Path, required=True)
    parser.add_argument('--pytest-log', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--staged-app', type=Path)
    parser.add_argument('--functional-cases', type=int, default=FUNCTIONAL_CASES, choices=[FUNCTIONAL_CASES])
    parser.add_argument('--functional-runs', type=int, default=FUNCTIONAL_RUNS, choices=[FUNCTIONAL_RUNS])
    validate(parser.parse_args())
