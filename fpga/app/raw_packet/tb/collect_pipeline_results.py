# SPDX-License-Identifier: BSD-2-Clause
"""Collect passed XML, metrics and versioned source hashes after a full run."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(args):
    repo = Path(__file__).resolve().parents[4]
    revision = subprocess.check_output(
        ['git', 'rev-parse', args.revision], cwd=repo, text=True).strip()
    root = args.build_root.resolve()
    report = {
        'implementation_revision': revision, 'build_root': str(root),
        'pytest_log_sha256': digest(args.pytest_log), 'functional_runs': [],
        'runner_contracts': [], 'source_sha256': {}, 'python_source_sha256': {},
        'stress_metrics': [], 'phase_wait_metrics': [], 'reference_metrics': [],
    }
    versioned = {}

    def check_sources(manifest, field):
        assert manifest.get(field), f'Missing {field}'
        for original, expected in manifest[field].items():
            path = Path(original).resolve()
            if args.staged_app and path.is_relative_to(args.staged_app.resolve()):
                path = repo/'fpga/app/raw_packet'/path.relative_to(args.staged_app.resolve())
            relative = str(path.relative_to(repo))
            if relative not in versioned:
                data = subprocess.check_output(['git', 'show', f'{revision}:{relative}'], cwd=repo)
                versioned[relative] = hashlib.sha256(data).hexdigest()
            assert versioned[relative] == expected, (relative, 'revision differs from tested source')
            assert digest(path) == expected, (relative, 'working copy differs from tested source')
            report[field][relative] = expected

    for xml in sorted(root.rglob('*results.xml')):
        cases = list(ET.parse(xml).iter('testcase'))
        fixture = next((v for v in ('pass', 'fail', 'skip', 'empty')
                        if 'runner_fixture_'+v in str(xml)), None)
        if fixture:
            if fixture == 'empty':
                assert not cases, xml
            else:
                assert len(cases) == 1, xml
                bad = any(cases[0].find(k) is not None for k in ('failure', 'error', 'skipped'))
                assert bad == (fixture != 'pass'), xml
            report['runner_contracts'].append({
                'expected_outcome': fixture, 'xml': str(xml), 'xml_sha256': digest(xml)})
            continue
        manifest = json.loads((xml.parent/'source_manifest.json').read_text())
        assert cases and len(cases) == manifest['expected_tests'], xml
        assert not any(c.find(k) is not None for c in cases
                       for k in ('failure', 'error', 'skipped')), xml
        check_sources(manifest, 'source_sha256')
        check_sources(manifest, 'python_source_sha256')
        report['functional_runs'].append({
            'xml': str(xml), 'xml_sha256': digest(xml), 'cases': [c.attrib for c in cases],
            'parameters': manifest['parameters'], 'scenario': manifest['scenario'],
            'process_timeout_seconds': manifest['process_timeout_seconds'],
        })

    count = sum(len(r['cases']) for r in report['functional_runs'])
    assert count == args.functional_cases, (count, args.functional_cases)
    assert len(report['functional_runs']) == args.functional_runs
    assert len(report['runner_contracts']) == 4
    assert {r['expected_outcome'] for r in report['runner_contracts']} == {'pass', 'fail', 'skip', 'empty'}
    pytest_count = args.functional_runs+4
    log = args.pytest_log.read_text()
    assert re.search(rf'\b{pytest_count} passed in ', log), 'Missing normal pytest completion'
    assert not re.search(r'\b\d+ (?:failed|error|errors)\b', log), 'Failed pytest result'
    report['pytest_cases'] = pytest_count
    report['functional_cocotb_count'] = count
    for path in sorted(root.rglob('pipeline_metrics.json')):
        report['stress_metrics'].append(json.loads(path.read_text()))
    assert len(report['stress_metrics']) == 18
    report['performance_summary'] = json.loads((root/'pipeline_metrics_summary.json').read_text())
    for path in sorted(root.rglob('phase_wait_metrics.json')):
        report['phase_wait_metrics'].append(json.loads(path.read_text()))
    assert len(report['phase_wait_metrics']) == 6
    for path in sorted(args.reference_root.rglob('reference_metrics.json')):
        xmls = list(path.parent.glob('*results.xml'))
        assert len(xmls) == 1
        cases = list(ET.parse(xmls[0]).iter('testcase'))
        assert len(cases) == 1 and not any(cases[0].find(k) is not None
                                         for k in ('failure', 'error', 'skipped'))
        report['reference_metrics'].append(json.loads(path.read_text()))
    assert len(report['reference_metrics']) == 4
    for width in (256, 512):
        rows = [r for r in report['reference_metrics'] if r['axis_width'] == width]
        assert len(rows) == 2 and rows[0] == rows[1]
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(f'Validated {pytest_count} pytest cases, {count} functional cocotb cases; source hashes match {revision}.')
    print(args.output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root', type=Path, required=True)
    parser.add_argument('--pytest-log', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--staged-app', type=Path)
    parser.add_argument('--functional-cases', type=int, required=True)
    parser.add_argument('--functional-runs', type=int, required=True)
    collect(parser.parse_args())
