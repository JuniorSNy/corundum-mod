# SPDX-License-Identifier: BSD-2-Clause
PYTHON_BIN ?= python3
.PHONY: all test
all: test
test:
	$(PYTHON_BIN) -m pytest -q --tb=short test_raw_packet_qp.py
