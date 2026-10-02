// SPDX-License-Identifier: BSD-2-Clause
// raw_dma_read: 主机 DMA 到分段 RAM，再以 AXIS 输出完整有效负载。
// 只允许一个在途操作；DMA 错误时不输出任何帧字节。
`timescale 1ns / 1ps
`default_nettype none

module raw_dma_read #(
    parameter DMA_ADDR_WIDTH = 64,
    parameter DMA_LEN_WIDTH = 16,
    parameter DMA_TAG_WIDTH = 16,
    parameter RAM_ADDR_WIDTH = 16,
    parameter RAM_SEG_COUNT = 2,
    parameter RAM_SEG_DATA_WIDTH = 512,
    parameter RAM_SEG_BE_WIDTH = RAM_SEG_DATA_WIDTH/8,
    parameter RAM_SEG_ADDR_WIDTH = RAM_ADDR_WIDTH-$clog2(RAM_SEG_COUNT*RAM_SEG_BE_WIDTH),
    parameter AXIS_DATA_WIDTH = 512,
    parameter AXIS_KEEP_WIDTH = AXIS_DATA_WIDTH/8,
    parameter RAM_SIZE = 16384,
    parameter TAG = 1
)(
    input wire clk,
    input wire rst,
    input wire [DMA_ADDR_WIDTH-1:0] req_addr,
    input wire [DMA_LEN_WIDTH-1:0] req_len,
    input wire req_valid,
    output wire req_ready,
    output wire done_valid,
    input wire done_ready,
    output wire [3:0] done_error,
    output wire [DMA_ADDR_WIDTH-1:0] dma_desc_addr,
    output wire [RAM_ADDR_WIDTH-1:0] dma_desc_ram_addr,
    output wire [DMA_LEN_WIDTH-1:0] dma_desc_len,
    output wire [DMA_TAG_WIDTH-1:0] dma_desc_tag,
    output wire dma_desc_valid,
    input wire dma_desc_ready,
    input wire [DMA_TAG_WIDTH-1:0] dma_status_tag,
    input wire [3:0] dma_status_error,
    input wire dma_status_valid,
    input wire [RAM_SEG_COUNT*RAM_SEG_BE_WIDTH-1:0] ram_wr_cmd_be,
    input wire [RAM_SEG_COUNT*RAM_SEG_ADDR_WIDTH-1:0] ram_wr_cmd_addr,
    input wire [RAM_SEG_COUNT*RAM_SEG_DATA_WIDTH-1:0] ram_wr_cmd_data,
    input wire [RAM_SEG_COUNT-1:0] ram_wr_cmd_valid,
    output wire [RAM_SEG_COUNT-1:0] ram_wr_cmd_ready,
    output wire [RAM_SEG_COUNT-1:0] ram_wr_done,
    output wire [AXIS_DATA_WIDTH-1:0] m_axis_tdata,
    output wire [AXIS_KEEP_WIDTH-1:0] m_axis_tkeep,
    output wire m_axis_tvalid,
    input wire m_axis_tready,
    output wire m_axis_tlast
);

localparam ST_IDLE=0, ST_DESC=1, ST_DMA=2, ST_SOURCE=3, ST_STREAM=4, ST_DONE=5;
reg [2:0] state_reg = ST_IDLE;
reg [2:0] state_next;
reg [DMA_ADDR_WIDTH-1:0] addr_reg = 0;
reg [DMA_ADDR_WIDTH-1:0] addr_next;
reg [DMA_LEN_WIDTH-1:0] len_reg = 0;
reg [DMA_LEN_WIDTH-1:0] len_next;
reg [3:0] error_reg = 0;
reg [3:0] error_next;
wire source_ready;
wire [RAM_SEG_COUNT*RAM_SEG_ADDR_WIDTH-1:0] ram_rd_addr;
wire [RAM_SEG_COUNT-1:0] ram_rd_valid;
wire [RAM_SEG_COUNT-1:0] ram_rd_ready;
wire [RAM_SEG_COUNT*RAM_SEG_DATA_WIDTH-1:0] ram_rd_data;
wire [RAM_SEG_COUNT-1:0] ram_rd_resp_valid;
wire [RAM_SEG_COUNT-1:0] ram_rd_resp_ready;

assign req_ready = !rst && state_reg == ST_IDLE;
assign done_valid = state_reg == ST_DONE;
assign done_error = error_reg;
assign dma_desc_addr = addr_reg;
assign dma_desc_ram_addr = 0;
assign dma_desc_len = len_reg;
assign dma_desc_tag = TAG;
assign dma_desc_valid = state_reg == ST_DESC;

// 接收 status 后才启动 RAM 到 AXIS，错误读不会泄露旧缓冲内容。
always @* begin
    state_next = state_reg;
    addr_next = addr_reg;
    len_next = len_reg;
    error_next = error_reg;

    case (state_reg)
        ST_IDLE: if (req_valid) begin
            addr_next = req_addr;
            len_next = req_len;
            error_next = 0;
            if (req_len == 0 || req_len > RAM_SIZE) begin
                error_next = 4'hf;
                state_next = ST_DONE;
            end else begin
                state_next = ST_DESC;
            end
        end
        ST_DESC: if (dma_desc_ready) begin
            state_next = ST_DMA;
        end
        ST_DMA: if (dma_status_valid && dma_status_tag == TAG) begin
            error_next = dma_status_error;
            state_next = dma_status_error == 0 ? ST_SOURCE : ST_DONE;
        end
        ST_SOURCE: if (source_ready) begin
            state_next = ST_STREAM;
        end
        ST_STREAM: if (m_axis_tvalid && m_axis_tready && m_axis_tlast) begin
            state_next = ST_DONE;
        end
        ST_DONE: if (done_ready) begin
            state_next = ST_IDLE;
        end
        default: state_next = ST_IDLE;
    endcase
end

always @(posedge clk) begin
    state_reg <= state_next;
    addr_reg <= addr_next;
    len_reg <= len_next;
    error_reg <= error_next;

    if (rst) begin
        state_reg <= ST_IDLE;
        addr_reg <= 0;
        len_reg <= 0;
        error_reg <= 0;
    end
end

// 复用 Corundum 的分段 RAM，保留每段独立握手与 byte enable。
dma_psdpram #(
    .SIZE(RAM_SIZE), .SEG_COUNT(RAM_SEG_COUNT),
    .SEG_DATA_WIDTH(RAM_SEG_DATA_WIDTH), .SEG_BE_WIDTH(RAM_SEG_BE_WIDTH),
    .SEG_ADDR_WIDTH(RAM_SEG_ADDR_WIDTH), .PIPELINE(2)
)
staging_ram_inst (
    .clk(clk), .rst(rst),
    .wr_cmd_be(ram_wr_cmd_be), .wr_cmd_addr(ram_wr_cmd_addr),
    .wr_cmd_data(ram_wr_cmd_data), .wr_cmd_valid(ram_wr_cmd_valid),
    .wr_cmd_ready(ram_wr_cmd_ready), .wr_done(ram_wr_done),
    .rd_cmd_addr(ram_rd_addr), .rd_cmd_valid(ram_rd_valid),
    .rd_cmd_ready(ram_rd_ready), .rd_resp_data(ram_rd_data),
    .rd_resp_valid(ram_rd_resp_valid), .rd_resp_ready(ram_rd_resp_ready)
);

// source 依据字节长度生成 tkeep/tlast，并在下游反压时保持输出。
dma_client_axis_source #(
    .RAM_ADDR_WIDTH(RAM_ADDR_WIDTH), .SEG_COUNT(RAM_SEG_COUNT),
    .SEG_DATA_WIDTH(RAM_SEG_DATA_WIDTH), .SEG_BE_WIDTH(RAM_SEG_BE_WIDTH),
    .SEG_ADDR_WIDTH(RAM_SEG_ADDR_WIDTH), .AXIS_DATA_WIDTH(AXIS_DATA_WIDTH),
    .AXIS_KEEP_WIDTH(AXIS_KEEP_WIDTH), .AXIS_USER_ENABLE(0),
    .AXIS_ID_WIDTH(1), .AXIS_DEST_WIDTH(1), .LEN_WIDTH(DMA_LEN_WIDTH),
    .TAG_WIDTH(DMA_TAG_WIDTH)
)
stream_source_inst (
    .clk(clk), .rst(rst), .enable(1'b1),
    .s_axis_read_desc_ram_addr({RAM_ADDR_WIDTH{1'b0}}),
    .s_axis_read_desc_len(len_reg), .s_axis_read_desc_tag({DMA_TAG_WIDTH{1'b0}}),
    .s_axis_read_desc_id(1'b0), .s_axis_read_desc_dest(1'b0),
    .s_axis_read_desc_user(1'b0), .s_axis_read_desc_valid(state_reg == ST_SOURCE),
    .s_axis_read_desc_ready(source_ready),
    .m_axis_read_desc_status_tag(), .m_axis_read_desc_status_error(),
    .m_axis_read_desc_status_valid(),
    .m_axis_read_data_tdata(m_axis_tdata), .m_axis_read_data_tkeep(m_axis_tkeep),
    .m_axis_read_data_tvalid(m_axis_tvalid), .m_axis_read_data_tready(m_axis_tready),
    .m_axis_read_data_tlast(m_axis_tlast), .m_axis_read_data_tid(),
    .m_axis_read_data_tdest(), .m_axis_read_data_tuser(),
    .ram_rd_cmd_addr(ram_rd_addr), .ram_rd_cmd_valid(ram_rd_valid),
    .ram_rd_cmd_ready(ram_rd_ready), .ram_rd_resp_data(ram_rd_data),
    .ram_rd_resp_valid(ram_rd_resp_valid), .ram_rd_resp_ready(ram_rd_resp_ready)
);

endmodule
`resetall
