// SPDX-License-Identifier: BSD-2-Clause
// Module Name / 模块名称: raw_mr_table
// Description / 模块说明: 注册内存查找、保护域校验和 DMA 地址转换。
// 一次查询产生一个保持至握手的结果；更新接口由上层在 QP 停用时使用。
`timescale 1ns / 1ps
`default_nettype none

module raw_mr_table #(
    parameter INDEX_WIDTH = 4
)(
    input  wire                     clk,
    input  wire                     rst,
    // 配置完整表项；key 的低 INDEX_WIDTH 位必须与索引一致。
    input  wire                     cfg_valid,
    input  wire [INDEX_WIDTH-1:0]   cfg_index,
    input  wire                     cfg_enable,
    input  wire [31:0]              cfg_key,
    input  wire [23:0]              cfg_pd,
    input  wire [63:0]              cfg_vaddr,
    input  wire [63:0]              cfg_dma_addr,
    input  wire [63:0]              cfg_length,
    input  wire [1:0]               cfg_permissions,
    // 查询权限 bit 0 为 local read，bit 1 为 local write。
    input  wire                     req_valid,
    output wire                     req_ready,
    input  wire [31:0]              req_key,
    input  wire [23:0]              req_pd,
    input  wire [63:0]              req_vaddr,
    input  wire [31:0]              req_length,
    input  wire [1:0]               req_permissions,
    output wire                     resp_valid,
    input  wire                     resp_ready,
    output wire [63:0]              resp_dma_addr,
    output wire [3:0]               resp_error
);

localparam ENTRY_COUNT = 2**INDEX_WIDTH;
reg [ENTRY_COUNT-1:0] enabled_reg = 0;
reg [31:0] key_mem [0:ENTRY_COUNT-1];
reg [23:0] pd_mem [0:ENTRY_COUNT-1];
reg [63:0] vaddr_mem [0:ENTRY_COUNT-1];
reg [63:0] dma_mem [0:ENTRY_COUNT-1];
reg [63:0] length_mem [0:ENTRY_COUNT-1];
reg [1:0] permissions_mem [0:ENTRY_COUNT-1];

wire [INDEX_WIDTH-1:0] index = req_key[INDEX_WIDTH-1:0];
wire [63:0] offset = req_vaddr - vaddr_mem[index];
wire [64:0] translated = {1'b0, dma_mem[index]} + {1'b0, offset};
wire [64:0] last_dma = translated + {33'd0, req_length} - 1'b1;
wire [64:0] last_virtual = {1'b0, req_vaddr} + {33'd0, req_length} - 1'b1;
reg [3:0] error_comb;
reg valid_reg = 0;
reg [63:0] dma_addr_reg = 0;
reg [3:0] error_reg = 0;

assign req_ready = !rst && (!valid_reg || resp_ready);
assign resp_valid = valid_reg;
assign resp_dma_addr = dma_addr_reg;
assign resp_error = error_reg;

// 减法边界判断避免 base+length 溢出让越界请求误通过。
always @* begin
    error_comb = 0;
    if (!enabled_reg[index] || key_mem[index] != req_key) begin
        error_comb = 1;
    end else if (pd_mem[index] != req_pd) begin
        error_comb = 2;
    end else if ((permissions_mem[index] & req_permissions) != req_permissions) begin
        error_comb = 3;
    end else if (req_length == 0 || req_vaddr < vaddr_mem[index] ||
            offset > length_mem[index] || req_length > length_mem[index]-offset) begin
        error_comb = 4;
    end else if (translated[64] || last_dma[64] || last_virtual[64]) begin
        error_comb = 5;
    end
end

// 只有 valid 位需要复位；未启用表项的其余内容不会参与有效转换。
always @(posedge clk) begin
    if (rst) begin
        enabled_reg <= 0;
    end else if (cfg_valid) begin
        enabled_reg[cfg_index] <= cfg_enable && cfg_key[INDEX_WIDTH-1:0] == cfg_index;
        key_mem[cfg_index] <= cfg_key;
        pd_mem[cfg_index] <= cfg_pd;
        vaddr_mem[cfg_index] <= cfg_vaddr;
        dma_mem[cfg_index] <= cfg_dma_addr;
        length_mem[cfg_index] <= cfg_length;
        permissions_mem[cfg_index] <= cfg_permissions;
    end
end

// 反压时结果保持；消费结果的同一周期允许接收下一次查询。
always @(posedge clk) begin
    if (rst) begin
        valid_reg <= 0;
        dma_addr_reg <= 0;
        error_reg <= 0;
    end else if (req_ready) begin
        valid_reg <= req_valid;
        if (req_valid) begin
            dma_addr_reg <= error_comb == 0 ? translated[63:0] : 64'd0;
            error_reg <= error_comb;
        end
    end
end

endmodule
`resetall
