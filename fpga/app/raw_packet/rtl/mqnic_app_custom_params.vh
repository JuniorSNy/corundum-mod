// SPDX-License-Identifier: BSD-2-Clause
// Propagate raw app parameters through the existing Corundum custom hooks.
`define APP_CUSTOM_PARAMS(X_PARAM) \
    X_PARAM(RAW_TX_OP_TABLE_SIZE, 1) \
    X_PARAM(RAW_TX_WATCHDOG_CYCLES, 0)

`define X_PARAM_DECL(NAME, DEFAULT) \
    parameter NAME = DEFAULT,

`define X_PARAM_MAP(NAME, DEFAULT) \
    .NAME(NAME),

`define APP_CUSTOM_PARAMS_DECL `APP_CUSTOM_PARAMS(`X_PARAM_DECL)
`define APP_CUSTOM_PARAMS_MAP `APP_CUSTOM_PARAMS(`X_PARAM_MAP)
