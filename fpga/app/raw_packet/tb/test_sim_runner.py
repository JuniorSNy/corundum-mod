# SPDX-License-Identifier: BSD-2-Clause
"""Reject false-positive results using actual simulator processes and reports."""
import pytest
from sim_runner import run_simulation


@pytest.mark.parametrize('outcome', ['pass', 'fail', 'skip', 'empty'])
def test_result_contract(tmp_path, outcome):
    rtl = tmp_path / 'runner_fixture.v'
    rtl.write_text('`timescale 1ns/1ps\nmodule runner_fixture; endmodule\n')
    module = f'runner_fixture_{outcome}'
    source = 'import cocotb\nfrom cocotb.triggers import Timer\n'
    if outcome != 'empty':
        source += f"@cocotb.test(skip={outcome == 'skip'})\nasync def fixture(dut):\n"
        source += "    await Timer(1, units='ns')\n"
        if outcome == 'fail':
            source += "    assert False, 'intentional runner contract failure'\n"
    (tmp_path / f'{module}.py').write_text(source)
    kwargs = dict(verilog_sources=[str(rtl)], toplevel='runner_fixture',
                  module=module, python_search=[str(tmp_path)], sim_build=str(tmp_path/'build'))
    if outcome == 'pass':
        run_simulation(**kwargs)
    elif outcome == 'fail':
        with pytest.raises(SystemExit, match='FAILED 1 tests'):
            run_simulation(**kwargs)
    else:
        with pytest.raises(AssertionError, match='Empty, failed, or skipped'):
            run_simulation(**kwargs)
