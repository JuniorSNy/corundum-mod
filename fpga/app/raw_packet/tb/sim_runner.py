# SPDX-License-Identifier: BSD-2-Clause
"""Icarus configuration from cocotb-test, synchronous process supervision.

The local Python 3.10 asyncio subprocess transport can wait forever after child
exit (also reproducible with /usr/bin/true, without cocotb). Keep logs in files
and wait directly on the child; a timeout is always a failure, even with PASS XML.
"""
import hashlib
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import xml.etree.ElementTree as ET

from cocotb_test.simulator import Icarus

# Cocotb 1.7 logs assertion tracebacks at INFO. Keep regression diagnostics
# visible even when packet/DMA models run at WARNING to limit log volume.
logging.getLogger('cocotb.regression').setLevel(logging.INFO)


class FileLoggedIcarus(Icarus):
    def execute(self, commands):
        for index, command in enumerate(commands):
            log = Path(self.sim_dir) / f'process-{index}.log'
            self.logger.info('Running command: %s (log: %s)', command, log)
            with log.open('wb') as output:
                self.process = subprocess.Popen(
                    command, cwd=self.work_dir, env=self.env,
                    stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
                )
                try:
                    self.process.wait(timeout=self.process_timeout)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait()
                    raise RuntimeError(f'Simulator process timeout: {command}; log: {log}')
                if self.process.returncode:
                    raise RuntimeError(f'Process exited {self.process.returncode}: {command}; log: {log}')
                self.process = None

    def exit_gracefully(self, signum, frame):
        if self.process is not None:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait()
        raise RuntimeError(f'Simulation interrupted by signal {signum}')


def run_simulation(**kwargs):
    timeout = float(os.environ.get('RAW_SIM_TIMEOUT', kwargs.pop('timeout_seconds', 180)))
    expected_tests = kwargs.pop('expected_tests', 1)
    simulator = kwargs.pop('simulator', 'icarus')
    if simulator != 'icarus':
        raise ValueError('The raw app regression currently requires Icarus')
    # Include common Python helpers both in pytest and in the embedded simulator.
    kwargs.setdefault('python_search', []).append(str(Path(__file__).resolve().parent))
    # Parameters are not dependencies in cocotb-test's timestamp cache.
    build_root = os.environ.get('RAW_SIM_BUILD_ROOT')
    if build_root:
        kwargs['sim_build'] = str(Path(build_root) / kwargs['module'] / Path(kwargs['sim_build']).name)
    kwargs.setdefault('force_compile', True)
    kwargs.setdefault('extra_env', {}).setdefault('COCOTB_LOG_LEVEL', os.environ.get('COCOTB_LOG_LEVEL', 'WARNING'))
    runner = FileLoggedIcarus(**kwargs)
    runner.process_timeout = timeout
    try:
        sources = [Path(p) for p in kwargs.get('verilog_sources', [])]
        sources += [p for directory in kwargs.get('includes', []) for p in Path(directory).glob('*.vh')]
        python_sources = {p for directory in kwargs.get('python_search', [])
                          for p in Path(directory).glob('*.py')}
        manifest = {
            'source_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
            'python_source_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in sorted(python_sources)},
            'parameters': kwargs.get('parameters', {}), 'defines': kwargs.get('defines', []),
            'toplevel': kwargs.get('toplevel'), 'module': kwargs.get('module'),
            'expected_tests': expected_tests, 'process_timeout_seconds': timeout,
            'scenario': {k: v for k, v in kwargs.get('extra_env', {}).items()
                         if k in ('RAW_STRESS_SEED', 'RAW_STRESS_COUNT', 'RAW_STOP_STAGE', 'RAW_MISSING_STAGE', 'RAW_DRAIN_SCENARIO')},
        }
        (Path(runner.sim_dir)/'source_manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
        results = runner.run()
        if not runner.compile_only:
            cases = list(ET.parse(results).iter('testcase'))
            if len(cases) != expected_tests or any(list(c.iter('failure')) or list(c.iter('error')) or
                                list(c.iter('skipped')) for c in cases):
                raise AssertionError(f'Empty, failed, or skipped simulation results: {results}')
        return results
    finally:
        signal.signal(signal.SIGINT, runner.old_sigint_h)
        signal.signal(signal.SIGTERM, runner.old_sigterm_h)
