// SPDX-License-Identifier: BSD-2-Clause
// Raw QP control registers. Configuration is writable only while disabled/idle.
// Queue ownership stays in raw_packet_qp; this bank owns host doorbells and MR staging.
`timescale 1ns / 1ps
`default_nettype none

module raw_packet_csr #(
    parameter AXIL_APP_CTRL_ADDR_WIDTH = 24,
    parameter AXIL_APP_CTRL_DATA_WIDTH = 32,
    parameter AXIL_APP_CTRL_STRB_WIDTH = 4,
    parameter MAX_FRAME_SIZE = 9214,
    parameter RB_BASE_ADDR = 0,
    parameter RB_NEXT_PTR = 0
)(
    input wire clk,
    input wire rst,
    input  wire [AXIL_APP_CTRL_ADDR_WIDTH-1:0]            s_axil_app_ctrl_awaddr,
    input  wire [2:0]                                     s_axil_app_ctrl_awprot,
    input  wire                                           s_axil_app_ctrl_awvalid,
    output wire                                           s_axil_app_ctrl_awready,
    input  wire [AXIL_APP_CTRL_DATA_WIDTH-1:0]            s_axil_app_ctrl_wdata,
    input  wire [AXIL_APP_CTRL_STRB_WIDTH-1:0]            s_axil_app_ctrl_wstrb,
    input  wire                                           s_axil_app_ctrl_wvalid,
    output wire                                           s_axil_app_ctrl_wready,
    output wire [1:0]                                     s_axil_app_ctrl_bresp,
    output wire                                           s_axil_app_ctrl_bvalid,
    input  wire                                           s_axil_app_ctrl_bready,
    input  wire [AXIL_APP_CTRL_ADDR_WIDTH-1:0]            s_axil_app_ctrl_araddr,
    input  wire [2:0]                                     s_axil_app_ctrl_arprot,
    input  wire                                           s_axil_app_ctrl_arvalid,
    output wire                                           s_axil_app_ctrl_arready,
    output wire [AXIL_APP_CTRL_DATA_WIDTH-1:0]            s_axil_app_ctrl_rdata,
    output wire [1:0]                                     s_axil_app_ctrl_rresp,
    output wire                                           s_axil_app_ctrl_rvalid,
    input  wire                                           s_axil_app_ctrl_rready,
    input wire idle,
    input wire queue_config_valid,
    input wire [31:0] ring_size,
    input wire [31:0] sq_cons,
    input wire [31:0] cq_prod,
    input wire [31:0] fatal,
    input wire [31:0] op_table_size,
    input wire [31:0] active_count,
    input wire [31:0] fetch_ptr,
    input wire [31:0] phase,
    input wire [31:0] unexpected_count,
    input wire [31:0] stall_count,
    output wire reset_queues,
    output wire mr_commit,
    output wire enable,
    output wire [63:0] sq_base,
    output wire [63:0] cq_base,
    output wire [3:0] ring_log,
    output wire [23:0] pd,
    output wire [31:0] sq_prod,
    output wire [31:0] cq_cons,
    output wire [31:0] config_error,
    output wire [3:0] mr_index,
    output wire [31:0] mr_key,
    output wire [31:0] mr_flags,
    output wire [23:0] mr_pd,
    output wire [63:0] mr_va,
    output wire [63:0] mr_dma,
    output wire [63:0] mr_len
);

localparam REG_RB_TYPE = 'h00;
localparam REG_RB_VERSION = 'h04;
localparam REG_RB_NEXT = 'h08;
localparam REG_APP_ID = 'h0c;
localparam REG_ENABLE = 'h10;
localparam REG_STATUS = 'h14;
localparam REG_CONFIG_ERROR = 'h18;
localparam REG_FATAL = 'h1c;
localparam REG_SQ_BASE_L = 'h20;
localparam REG_SQ_BASE_H = 'h24;
localparam REG_CQ_BASE_L = 'h28;
localparam REG_CQ_BASE_H = 'h2c;
localparam REG_RING_LOG = 'h30;
localparam REG_PD = 'h34;
localparam REG_SQ_PROD = 'h38;
localparam REG_SQ_CONS = 'h3c;
localparam REG_CQ_PROD = 'h40;
localparam REG_CQ_CONS = 'h44;
localparam REG_MAX_FRAME = 'h48;
localparam REG_QUEUE_RESET = 'h4c;
localparam REG_OP_TABLE_SIZE = 'h50;
localparam REG_ACTIVE_COUNT = 'h54;
localparam REG_FETCH_PTR = 'h58;
localparam REG_PHASE = 'h5c;
localparam REG_UNEXPECTED_COUNT = 'h60;
localparam REG_STALL_COUNT = 'h64;
localparam REG_MR_INDEX = 'h80;
localparam REG_MR_KEY = 'h84;
localparam REG_MR_PD = 'h88;
localparam REG_MR_FLAGS = 'h8c;
localparam REG_MR_VA_L = 'h90;
localparam REG_MR_VA_H = 'h94;
localparam REG_MR_DMA_L = 'h98;
localparam REG_MR_DMA_H = 'h9c;
localparam REG_MR_LENGTH_L = 'ha0;
localparam REG_MR_LENGTH_H = 'ha4;
localparam REG_MR_COMMIT = 'ha8;

reg enable_reg = 0;
reg [63:0] sq_base_reg = 0;
reg [63:0] cq_base_reg = 0;
reg [3:0] ring_log_reg = 4;
reg [23:0] pd_reg = 0;
reg [31:0] sq_prod_reg = 0;
reg [31:0] cq_cons_reg = 0;
reg [31:0] config_error_reg = 0;
reg [3:0] mr_index_reg = 0;
reg [31:0] mr_key_reg = 0;
reg [31:0] mr_flags_reg = 0;
reg [23:0] mr_pd_reg = 0;
reg [63:0] mr_va_reg = 0;
reg [63:0] mr_dma_reg = 0;
reg [63:0] mr_len_reg = 0;
wire [AXIL_APP_CTRL_ADDR_WIDTH-1:0] wr_addr, rd_addr;
wire [AXIL_APP_CTRL_ADDR_WIDTH-1:0] wr_offset = wr_addr - RB_BASE_ADDR;
wire [AXIL_APP_CTRL_ADDR_WIDTH-1:0] rd_offset = rd_addr - RB_BASE_ADDR;
wire [31:0] wr_data;
wire [3:0] wr_strb;
wire wr_en, rd_en;
reg [31:0] rd_data;
wire config_open = !enable_reg && idle;
wire wr_full = wr_strb == 4'hf;
assign reset_queues = wr_en && wr_full && wr_offset == REG_QUEUE_RESET && config_open && wr_data == 1;
assign mr_commit = wr_en && wr_full && wr_offset == REG_MR_COMMIT && config_open && wr_data == 1;

assign enable = enable_reg;
assign sq_base = sq_base_reg;
assign cq_base = cq_base_reg;
assign ring_log = ring_log_reg;
assign pd = pd_reg;
assign sq_prod = sq_prod_reg;
assign cq_cons = cq_cons_reg;
assign config_error = config_error_reg;
assign mr_index = mr_index_reg;
assign mr_key = mr_key_reg;
assign mr_flags = mr_flags_reg;
assign mr_pd = mr_pd_reg;
assign mr_va = mr_va_reg;
assign mr_dma = mr_dma_reg;
assign mr_len = mr_len_reg;

// AXI-Lite 的 AW/W 分离握手由 Corundum 已有寄存器桥处理。
axil_reg_if #(.DATA_WIDTH(32), .ADDR_WIDTH(AXIL_APP_CTRL_ADDR_WIDTH), .STRB_WIDTH(4))
csr_bus_inst (
    .clk(clk), .rst(rst),
    .s_axil_awaddr(s_axil_app_ctrl_awaddr), .s_axil_awprot(s_axil_app_ctrl_awprot),
    .s_axil_awvalid(s_axil_app_ctrl_awvalid), .s_axil_awready(s_axil_app_ctrl_awready),
    .s_axil_wdata(s_axil_app_ctrl_wdata), .s_axil_wstrb(s_axil_app_ctrl_wstrb),
    .s_axil_wvalid(s_axil_app_ctrl_wvalid), .s_axil_wready(s_axil_app_ctrl_wready),
    .s_axil_bresp(s_axil_app_ctrl_bresp), .s_axil_bvalid(s_axil_app_ctrl_bvalid),
    .s_axil_bready(s_axil_app_ctrl_bready),
    .s_axil_araddr(s_axil_app_ctrl_araddr), .s_axil_arprot(s_axil_app_ctrl_arprot),
    .s_axil_arvalid(s_axil_app_ctrl_arvalid), .s_axil_arready(s_axil_app_ctrl_arready),
    .s_axil_rdata(s_axil_app_ctrl_rdata), .s_axil_rresp(s_axil_app_ctrl_rresp),
    .s_axil_rvalid(s_axil_app_ctrl_rvalid), .s_axil_rready(s_axil_app_ctrl_rready),
    .reg_wr_addr(wr_addr), .reg_wr_data(wr_data), .reg_wr_strb(wr_strb),
    .reg_wr_en(wr_en), .reg_wr_wait(1'b0), .reg_wr_ack(wr_en),
    .reg_rd_addr(rd_addr), .reg_rd_en(rd_en), .reg_rd_data(rd_data),
    .reg_rd_wait(1'b0), .reg_rd_ack(rd_en)
);

// CSR 使用完整 32 位写；非法/忙时写被拒绝并记录，不破坏正在运行的 QP。
always @(posedge clk) begin
    if (rst) begin
        enable_reg <= 0;
        sq_base_reg <= 0;
        cq_base_reg <= 0;
        ring_log_reg <= 4;
        pd_reg <= 0;
        sq_prod_reg <= 0;
        cq_cons_reg <= 0;
        config_error_reg <= 0;
        mr_index_reg <= 0;
        mr_key_reg <= 0;
        mr_flags_reg <= 0;
        mr_pd_reg <= 0;
        mr_va_reg <= 0;
        mr_dma_reg <= 0;
        mr_len_reg <= 0;
    end else if (wr_en) begin
        if (!wr_full || wr_offset[1:0] != 0) begin
            config_error_reg <= 1;
        end else begin
            case (wr_offset)
                REG_ENABLE: begin
                    if (!wr_data[0]) begin
                        enable_reg <= 0;
                    end else if (queue_config_valid && fatal == 0) begin
                        enable_reg <= 1;
                    end else begin
                        config_error_reg <= 2;
                    end
                end
                REG_CONFIG_ERROR: config_error_reg <= 0;
                REG_SQ_PROD: begin
                    // 只接受前进的生产者指针，差值限制同时防止覆盖未消费 SQE。
                    if (wr_data-sq_prod_reg <= ring_size && wr_data-sq_cons <= ring_size) begin
                        sq_prod_reg <= wr_data;
                    end else begin
                        config_error_reg <= 3;
                    end
                end
                REG_CQ_CONS: begin
                    if (wr_data-cq_cons_reg <= cq_prod-cq_cons_reg) begin
                        cq_cons_reg <= wr_data;
                    end else begin
                        config_error_reg <= 4;
                    end
                end
                default: begin
                    if (!config_open) begin
                        config_error_reg <= 5;
                    end else begin
                        case (wr_offset)
                            REG_SQ_BASE_L: sq_base_reg[31:0] <= wr_data;
                            REG_SQ_BASE_H: sq_base_reg[63:32] <= wr_data;
                            REG_CQ_BASE_L: cq_base_reg[31:0] <= wr_data;
                            REG_CQ_BASE_H: cq_base_reg[63:32] <= wr_data;
                            REG_RING_LOG: begin
                                if (wr_data >= 1 && wr_data <= 10) begin
                                    ring_log_reg <= wr_data[3:0];
                                end else begin
                                    config_error_reg <= 2;
                                end
                            end
                            REG_PD: pd_reg <= wr_data[23:0];
                            REG_QUEUE_RESET: if (wr_data == 1) begin
                                sq_prod_reg <= 0;
                                cq_cons_reg <= 0;
                            end
                            REG_MR_INDEX: mr_index_reg <= wr_data[3:0];
                            REG_MR_KEY: mr_key_reg <= wr_data;
                            REG_MR_PD: mr_pd_reg <= wr_data[23:0];
                            REG_MR_FLAGS: mr_flags_reg <= wr_data;
                            REG_MR_VA_L: mr_va_reg[31:0] <= wr_data;
                            REG_MR_VA_H: mr_va_reg[63:32] <= wr_data;
                            REG_MR_DMA_L: mr_dma_reg[31:0] <= wr_data;
                            REG_MR_DMA_H: mr_dma_reg[63:32] <= wr_data;
                            REG_MR_LENGTH_L: mr_len_reg[31:0] <= wr_data;
                            REG_MR_LENGTH_H: mr_len_reg[63:32] <= wr_data;
                            REG_MR_COMMIT: begin end
                            default: config_error_reg <= 6;
                        endcase
                    end
                end
            endcase
        end
    end
end

always @* begin
    rd_data = 0;
    case (rd_offset)
        REG_RB_TYPE: rd_data = 32'h12348110;
        REG_RB_VERSION: rd_data = 32'h00000100;
        REG_RB_NEXT: rd_data = RB_NEXT_PTR;
        REG_APP_ID: rd_data = 32'h12348010;
        REG_ENABLE: rd_data = {31'd0, enable_reg};
        REG_STATUS: rd_data = {23'd0, fatal != 0, 7'd0, !idle};
        REG_CONFIG_ERROR: rd_data = config_error_reg;
        REG_FATAL: rd_data = fatal;
        REG_SQ_BASE_L: rd_data = sq_base_reg[31:0];
        REG_SQ_BASE_H: rd_data = sq_base_reg[63:32];
        REG_CQ_BASE_L: rd_data = cq_base_reg[31:0];
        REG_CQ_BASE_H: rd_data = cq_base_reg[63:32];
        REG_RING_LOG: rd_data = {28'd0, ring_log_reg};
        REG_PD: rd_data = {8'd0, pd_reg};
        REG_SQ_PROD: rd_data = sq_prod_reg;
        REG_SQ_CONS: rd_data = sq_cons;
        REG_CQ_PROD: rd_data = cq_prod;
        REG_CQ_CONS: rd_data = cq_cons_reg;
        REG_MAX_FRAME: rd_data = MAX_FRAME_SIZE;
        REG_OP_TABLE_SIZE: rd_data = op_table_size;
        REG_ACTIVE_COUNT: rd_data = active_count;
        REG_FETCH_PTR: rd_data = fetch_ptr;
        REG_PHASE: rd_data = phase;
        REG_UNEXPECTED_COUNT: rd_data = unexpected_count;
        REG_STALL_COUNT: rd_data = stall_count;
        REG_MR_INDEX: rd_data = {28'd0, mr_index_reg};
        REG_MR_KEY: rd_data = mr_key_reg;
        REG_MR_PD: rd_data = {8'd0, mr_pd_reg};
        REG_MR_FLAGS: rd_data = mr_flags_reg;
        REG_MR_VA_L: rd_data = mr_va_reg[31:0];
        REG_MR_VA_H: rd_data = mr_va_reg[63:32];
        REG_MR_DMA_L: rd_data = mr_dma_reg[31:0];
        REG_MR_DMA_H: rd_data = mr_dma_reg[63:32];
        REG_MR_LENGTH_L: rd_data = mr_len_reg[31:0];
        REG_MR_LENGTH_H: rd_data = mr_len_reg[63:32];
        default: rd_data = 0;
    endcase
end

endmodule
`resetall
