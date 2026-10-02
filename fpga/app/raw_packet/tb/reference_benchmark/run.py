# SPDX-License-Identifier: BSD-2-Clause
"""Extract immutable baseline with git show; adapt only the added tag interface."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

APP = Path(__file__).resolve().parents[2]
REPO = APP.parents[2]
ROOT = Path(os.environ.get('RAW_SIM_BUILD_ROOT', APP/'tb/sim_build/reference_benchmark'))
REFERENCE = '0784146c'


def main():
    snapshot = ROOT/'reference_sources'
    snapshot.mkdir(parents=True, exist_ok=True)
    names = ['raw_packet_qp.v', 'raw_packet_csr.v', 'raw_dma_read.v', 'raw_mr_table.v']
    for name in names:
        source = subprocess.check_output(['git', 'show', REFERENCE+':fpga/app/raw_packet/rtl/'+name], cwd=REPO).decode()
        (snapshot/name).write_text(source)
    original = (snapshot/'raw_packet_qp.v').read_text()
    old_header = original.split(');', 1)[0]
    parameters = re.findall(r'parameter\s+(\w+)\s*=', old_header)
    ports = re.findall(r'(?:input|output)\s+(?:wire|reg)\s+(?:\[[^]]+\]\s*)?(\w+)', old_header)
    assert len(ports) == 80 and ports[-1] == 'tx_cpl_valid', ports
    (snapshot/'raw_packet_qp_reference.v').write_text(original.replace('module raw_packet_qp #(', 'module raw_packet_qp_reference #(', 1))
    current = (APP/'rtl/raw_packet_qp.v').read_text().split(');', 1)[0]+');\n'
    current_ports = re.findall(r'(?:input|output)\s+(?:wire|reg)\s+(?:\[[^]]+\]\s*)?(\w+)', current)
    assert set(current_ports)-set(ports) == {'m_axis_tx_tuser', 'tx_cpl_tag'}
    assert set(ports) <= set(current_ports)
    adapter = current+'assign m_axis_tx_tuser = 0;\nraw_packet_qp_reference #(\n'
    adapter += ',\n'.join('    .'+name+'('+name+')' for name in parameters)+'\n) reference_inst (\n'
    adapter += ',\n'.join('    .'+name+'('+name+')' for name in ports)+'\n);\nendmodule\n'
    (snapshot/'adapter.v').write_text(adapter)
    sys.path.insert(0, str(APP/'tb'))
    from sim_runner import run_simulation
    sources = [snapshot/'adapter.v', snapshot/'raw_packet_qp_reference.v']+[snapshot/name for name in names[1:]]
    sources += [REPO/'fpga/lib/pcie/rtl'/name for name in ['dma_psdpram.v', 'dma_client_axis_source.v']]
    sources += list((REPO/'fpga/lib/axi/rtl').glob('axil_reg_if*.v'))
    records = []
    for width in (256, 512):
        repeated = []
        for repeat in (1, 2):
            xml = run_simulation(verilog_sources=[str(p) for p in sources], toplevel='raw_packet_qp',
                                 module='raw_reference_benchmark',
                                 python_search=[str(Path(__file__).parent), str(APP/'tb/raw_packet_qp')],
                                 parameters={'AXIS_DATA_WIDTH': width, 'AXIS_KEEP_WIDTH': width//8},
                                 sim_build=str(ROOT/f'{width}_{repeat}'))
            record = json.loads((Path(xml).parent/'reference_metrics.json').read_text())
            assert record['reference_revision'] == REFERENCE and record['axis_width'] == width
            repeated.append(record)
            records.append(record)
        assert repeated[0] == repeated[1], f'Baseline timing was not repeatable for AXIS {width}'
    (ROOT/'reference_metrics_summary.json').write_text(json.dumps(records, indent=2)+'\n')
    print('Four archived baseline runs passed; metrics repeat exactly at both widths.')


if __name__ == '__main__':
    main()
