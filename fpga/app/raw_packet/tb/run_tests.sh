#!/usr/bin/env bash
# SPDX-License-Identifier: BSD-2-Clause
set -euo pipefail
cd "$(dirname "$0")"
PYTHON_BIN="${PYTHON_BIN:-python3}"
# One process deliberately exercises repeated simulator startup and shutdown.
exec "$PYTHON_BIN" -m pytest -q --tb=short test_sim_runner.py raw_mr_table raw_packet_qp mqnic_core_pcie_us fpga_core "$@"
