// SPDX-License-Identifier: BSD-2-Clause
// raw_packet_qp: SQ -> MR -> DMA -> Ethernet -> CQ 的单在途原始包队列。
// 控制面仅在停用且空闲时重配；所有接口运行于 Corundum app clk。
`timescale 1ns / 1ps
`default_nettype none
module raw_packet_qp #(
    parameter DMA_ADDR_WIDTH = 64,
    parameter DMA_LEN_WIDTH = 16,
    parameter DMA_TAG_WIDTH = 16,
    parameter RAM_SEL_WIDTH = 4,
    parameter RAM_ADDR_WIDTH = 16,
    parameter RAM_SEG_COUNT = 2,
    parameter RAM_SEG_DATA_WIDTH = 512,
    parameter RAM_SEG_BE_WIDTH = RAM_SEG_DATA_WIDTH/8,
    parameter RAM_SEG_ADDR_WIDTH = RAM_ADDR_WIDTH-$clog2(RAM_SEG_COUNT*RAM_SEG_BE_WIDTH),
    parameter AXIL_APP_CTRL_ADDR_WIDTH = 24,
    parameter AXIL_APP_CTRL_DATA_WIDTH = 32,
    parameter AXIL_APP_CTRL_STRB_WIDTH = 4,
    parameter DMA_IMM_WIDTH = 32,
    parameter AXIS_DATA_WIDTH = 512,
    parameter AXIS_KEEP_WIDTH = AXIS_DATA_WIDTH/8,
    parameter MAX_FRAME_SIZE = 9214
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
    output wire [DMA_ADDR_WIDTH-1:0]                      m_axis_ctrl_dma_read_desc_dma_addr,
    output wire [RAM_SEL_WIDTH-1:0]                       m_axis_ctrl_dma_read_desc_ram_sel,
    output wire [RAM_ADDR_WIDTH-1:0]                      m_axis_ctrl_dma_read_desc_ram_addr,
    output wire [DMA_LEN_WIDTH-1:0]                       m_axis_ctrl_dma_read_desc_len,
    output wire [DMA_TAG_WIDTH-1:0]                       m_axis_ctrl_dma_read_desc_tag,
    output wire                                           m_axis_ctrl_dma_read_desc_valid,
    input  wire                                           m_axis_ctrl_dma_read_desc_ready,
    input  wire [DMA_TAG_WIDTH-1:0]                       s_axis_ctrl_dma_read_desc_status_tag,
    input  wire [3:0]                                     s_axis_ctrl_dma_read_desc_status_error,
    input  wire                                           s_axis_ctrl_dma_read_desc_status_valid,
    output wire [DMA_ADDR_WIDTH-1:0]                      m_axis_ctrl_dma_write_desc_dma_addr,
    output wire [RAM_SEL_WIDTH-1:0]                       m_axis_ctrl_dma_write_desc_ram_sel,
    output wire [RAM_ADDR_WIDTH-1:0]                      m_axis_ctrl_dma_write_desc_ram_addr,
    output wire [DMA_IMM_WIDTH-1:0]                       m_axis_ctrl_dma_write_desc_imm,
    output wire                                           m_axis_ctrl_dma_write_desc_imm_en,
    output wire [DMA_LEN_WIDTH-1:0]                       m_axis_ctrl_dma_write_desc_len,
    output wire [DMA_TAG_WIDTH-1:0]                       m_axis_ctrl_dma_write_desc_tag,
    output wire                                           m_axis_ctrl_dma_write_desc_valid,
    input  wire                                           m_axis_ctrl_dma_write_desc_ready,
    input  wire [DMA_TAG_WIDTH-1:0]                       s_axis_ctrl_dma_write_desc_status_tag,
    input  wire [3:0]                                     s_axis_ctrl_dma_write_desc_status_error,
    input  wire                                           s_axis_ctrl_dma_write_desc_status_valid,
    output wire [DMA_ADDR_WIDTH-1:0]                      m_axis_data_dma_read_desc_dma_addr,
    output wire [RAM_SEL_WIDTH-1:0]                       m_axis_data_dma_read_desc_ram_sel,
    output wire [RAM_ADDR_WIDTH-1:0]                      m_axis_data_dma_read_desc_ram_addr,
    output wire [DMA_LEN_WIDTH-1:0]                       m_axis_data_dma_read_desc_len,
    output wire [DMA_TAG_WIDTH-1:0]                       m_axis_data_dma_read_desc_tag,
    output wire                                           m_axis_data_dma_read_desc_valid,
    input  wire                                           m_axis_data_dma_read_desc_ready,
    input  wire [DMA_TAG_WIDTH-1:0]                       s_axis_data_dma_read_desc_status_tag,
    input  wire [3:0]                                     s_axis_data_dma_read_desc_status_error,
    input  wire                                           s_axis_data_dma_read_desc_status_valid,
    input  wire [RAM_SEG_COUNT*RAM_SEL_WIDTH-1:0]         ctrl_dma_ram_wr_cmd_sel,
    input  wire [RAM_SEG_COUNT*RAM_SEG_BE_WIDTH-1:0]      ctrl_dma_ram_wr_cmd_be,
    input  wire [RAM_SEG_COUNT*RAM_SEG_ADDR_WIDTH-1:0]    ctrl_dma_ram_wr_cmd_addr,
    input  wire [RAM_SEG_COUNT*RAM_SEG_DATA_WIDTH-1:0]    ctrl_dma_ram_wr_cmd_data,
    input  wire [RAM_SEG_COUNT-1:0]                       ctrl_dma_ram_wr_cmd_valid,
    output wire [RAM_SEG_COUNT-1:0]                       ctrl_dma_ram_wr_cmd_ready,
    output wire [RAM_SEG_COUNT-1:0]                       ctrl_dma_ram_wr_done,
    input  wire [RAM_SEG_COUNT*RAM_SEL_WIDTH-1:0]         ctrl_dma_ram_rd_cmd_sel,
    input  wire [RAM_SEG_COUNT*RAM_SEG_ADDR_WIDTH-1:0]    ctrl_dma_ram_rd_cmd_addr,
    input  wire [RAM_SEG_COUNT-1:0]                       ctrl_dma_ram_rd_cmd_valid,
    output wire [RAM_SEG_COUNT-1:0]                       ctrl_dma_ram_rd_cmd_ready,
    output wire [RAM_SEG_COUNT*RAM_SEG_DATA_WIDTH-1:0]    ctrl_dma_ram_rd_resp_data,
    output wire [RAM_SEG_COUNT-1:0]                       ctrl_dma_ram_rd_resp_valid,
    input  wire [RAM_SEG_COUNT-1:0]                       ctrl_dma_ram_rd_resp_ready,
    input  wire [RAM_SEG_COUNT*RAM_SEL_WIDTH-1:0]         data_dma_ram_wr_cmd_sel,
    input  wire [RAM_SEG_COUNT*RAM_SEG_BE_WIDTH-1:0]      data_dma_ram_wr_cmd_be,
    input  wire [RAM_SEG_COUNT*RAM_SEG_ADDR_WIDTH-1:0]    data_dma_ram_wr_cmd_addr,
    input  wire [RAM_SEG_COUNT*RAM_SEG_DATA_WIDTH-1:0]    data_dma_ram_wr_cmd_data,
    input  wire [RAM_SEG_COUNT-1:0]                       data_dma_ram_wr_cmd_valid,
    output wire [RAM_SEG_COUNT-1:0]                       data_dma_ram_wr_cmd_ready,
    output wire [RAM_SEG_COUNT-1:0]                       data_dma_ram_wr_done,
    output wire [AXIS_DATA_WIDTH-1:0] m_axis_tx_tdata,
    output wire [AXIS_KEEP_WIDTH-1:0] m_axis_tx_tkeep,
    output wire m_axis_tx_tvalid,
    input wire m_axis_tx_tready,
    output wire m_axis_tx_tlast,
    input wire tx_cpl_valid
);

initial begin
    if (DMA_ADDR_WIDTH != 64 || AXIL_APP_CTRL_DATA_WIDTH != 32 ||
        AXIL_APP_CTRL_STRB_WIDTH != 4 || MAX_FRAME_SIZE > 16384 || DMA_LEN_WIDTH < 15) begin
        $error("Unsupported raw QP address, CSR, or frame width");
        $finish;
    end
end

// Fixed resources for this single-inflight queue; concurrency needs a tag/context pool.
localparam SQ_DMA_TAG = 1;
localparam CQ_DMA_TAG = 2;
localparam PAYLOAD_DMA_TAG = 3;
localparam ENTRY_SIZE = 32;
localparam [DMA_LEN_WIDTH-1:0] SQ_DMA_LENGTH = ENTRY_SIZE;
localparam SQE_WR_ID_OFFSET = 0;
localparam SQE_ADDR_OFFSET = 64;
localparam SQE_LENGTH_OFFSET = 128;
localparam SQE_LKEY_OFFSET = 160;
localparam SQE_FLAGS_OFFSET = 192;
localparam CQ_STATUS_SQ_DMA = 32'h10;
localparam CQ_STATUS_BAD_SQE = 32'h20;
localparam CQ_STATUS_MR = 32'h30;
localparam CQ_STATUS_PAYLOAD_DMA = 32'h40;
localparam CQ_FATAL_DMA = 32'h50;

localparam ST_IDLE=0, ST_SQ_REQ=1, ST_SQ_DATA=2, ST_SQ_DONE=3,
    ST_CHECK=4, ST_MR_REQ=5, ST_MR_RESP=6, ST_DATA_REQ=7,
    ST_DATA=8, ST_TX_WAIT=9, ST_CQ_DESC=10, ST_CQ_WAIT=11;
reg [3:0] state_reg = ST_IDLE;
reg [3:0] state_next;
reg [31:0] sq_cons_reg = 0;
reg [31:0] sq_cons_next;
reg [31:0] cq_prod_reg = 0;
reg [31:0] cq_prod_next;
reg [31:0] fatal_reg = 0;
reg [31:0] fatal_next;
reg [255:0] sqe_reg = 0;
reg [255:0] sqe_next;
reg [31:0] result_reg = 0;
reg [31:0] result_next;
reg [63:0] payload_addr_reg = 0;
reg [63:0] payload_addr_next;
reg tx_done_reg = 0;
reg tx_done_next;

wire enable;
wire [63:0] sq_base;
wire [63:0] cq_base;
wire [3:0] ring_log;
wire [23:0] pd;
wire [31:0] sq_prod;
wire [31:0] cq_cons;
wire [31:0] config_error;
wire [3:0] mr_index;
wire [31:0] mr_key;
wire [31:0] mr_flags;
wire [23:0] mr_pd;
wire [63:0] mr_va;
wire [63:0] mr_dma;
wire [63:0] mr_len;
wire reset_queues;
wire mr_commit;

wire [31:0] ring_size = 32'd1 << ring_log;
wire [31:0] ring_mask = ring_size-1;
wire [31:0] sq_pending = sq_prod-sq_cons_reg;
wire [31:0] cq_pending = cq_prod_reg-cq_cons;
wire [64:0] sq_limit = {1'b0, sq_base} + ({33'd0, ring_size} << 5)-1'b1;
wire [64:0] cq_limit = {1'b0, cq_base} + ({33'd0, ring_size} << 5)-1'b1;
wire queue_config_valid = ring_log >= 1 && ring_log <= 10 &&
    sq_base[4:0] == 0 && cq_base[4:0] == 0 && !sq_limit[64] && !cq_limit[64];
wire [63:0] sq_address = sq_base + ({32'd0, sq_cons_reg & ring_mask} << 5);
wire [63:0] cq_address = cq_base + ({32'd0, cq_prod_reg & ring_mask} << 5);
wire [31:0] sq_length = sqe_reg[SQE_LENGTH_OFFSET +: 32];
wire sq_ready, sq_done, sq_valid, sq_last;
wire [3:0] sq_error;
wire [255:0] sq_data;
wire [31:0] sq_keep;
wire data_ready, data_done;
wire [3:0] data_error;
wire mr_ready, mr_valid;
wire [63:0] mr_result_addr;
wire [3:0] mr_error;

raw_packet_csr #(
    .AXIL_APP_CTRL_ADDR_WIDTH(AXIL_APP_CTRL_ADDR_WIDTH),
    .AXIL_APP_CTRL_DATA_WIDTH(AXIL_APP_CTRL_DATA_WIDTH),
    .AXIL_APP_CTRL_STRB_WIDTH(AXIL_APP_CTRL_STRB_WIDTH),
    .MAX_FRAME_SIZE(MAX_FRAME_SIZE)
) csr_inst (
    .clk(clk),
    .rst(rst),
    .s_axil_app_ctrl_awaddr(s_axil_app_ctrl_awaddr),
    .s_axil_app_ctrl_awprot(s_axil_app_ctrl_awprot),
    .s_axil_app_ctrl_awvalid(s_axil_app_ctrl_awvalid),
    .s_axil_app_ctrl_awready(s_axil_app_ctrl_awready),
    .s_axil_app_ctrl_wdata(s_axil_app_ctrl_wdata),
    .s_axil_app_ctrl_wstrb(s_axil_app_ctrl_wstrb),
    .s_axil_app_ctrl_wvalid(s_axil_app_ctrl_wvalid),
    .s_axil_app_ctrl_wready(s_axil_app_ctrl_wready),
    .s_axil_app_ctrl_bresp(s_axil_app_ctrl_bresp),
    .s_axil_app_ctrl_bvalid(s_axil_app_ctrl_bvalid),
    .s_axil_app_ctrl_bready(s_axil_app_ctrl_bready),
    .s_axil_app_ctrl_araddr(s_axil_app_ctrl_araddr),
    .s_axil_app_ctrl_arprot(s_axil_app_ctrl_arprot),
    .s_axil_app_ctrl_arvalid(s_axil_app_ctrl_arvalid),
    .s_axil_app_ctrl_arready(s_axil_app_ctrl_arready),
    .s_axil_app_ctrl_rdata(s_axil_app_ctrl_rdata),
    .s_axil_app_ctrl_rresp(s_axil_app_ctrl_rresp),
    .s_axil_app_ctrl_rvalid(s_axil_app_ctrl_rvalid),
    .s_axil_app_ctrl_rready(s_axil_app_ctrl_rready),
    .idle(state_reg == ST_IDLE),
    .queue_config_valid(queue_config_valid),
    .ring_size(ring_size),
    .sq_cons(sq_cons_reg),
    .cq_prod(cq_prod_reg),
    .fatal(fatal_reg),
    .reset_queues(reset_queues),
    .mr_commit(mr_commit),
    .enable(enable),
    .sq_base(sq_base),
    .cq_base(cq_base),
    .ring_log(ring_log),
    .pd(pd),
    .sq_prod(sq_prod),
    .cq_cons(cq_cons),
    .config_error(config_error),
    .mr_index(mr_index),
    .mr_key(mr_key),
    .mr_flags(mr_flags),
    .mr_pd(mr_pd),
    .mr_va(mr_va),
    .mr_dma(mr_dma),
    .mr_len(mr_len)
);

raw_mr_table mr_table_inst (
    .clk(clk), .rst(rst), .cfg_valid(mr_commit), .cfg_index(mr_index),
    .cfg_enable(mr_flags[31]), .cfg_key(mr_key), .cfg_pd(mr_pd),
    .cfg_vaddr(mr_va), .cfg_dma_addr(mr_dma), .cfg_length(mr_len),
    .cfg_permissions(mr_flags[1:0]),
    .req_valid(state_reg == ST_MR_REQ), .req_ready(mr_ready),
    .req_key(sqe_reg[SQE_LKEY_OFFSET +: 32]), .req_pd(pd), .req_vaddr(sqe_reg[SQE_ADDR_OFFSET +: 64]),
    .req_length(sq_length), .req_permissions(2'b01),
    .resp_valid(mr_valid), .resp_ready(state_reg == ST_MR_RESP),
    .resp_dma_addr(mr_result_addr), .resp_error(mr_error)
);

// SQE 的头、payload 和 CQE 生命周期串行化，缓冲复用不依赖 PCIe 返回顺序。
always @* begin
    state_next = state_reg;
    sq_cons_next = sq_cons_reg;
    cq_prod_next = cq_prod_reg;
    sqe_next = sqe_reg;
    result_next = result_reg;
    payload_addr_next = payload_addr_reg;
    fatal_next = fatal_reg;
    tx_done_next = tx_done_reg;

    if (tx_cpl_valid && (state_reg == ST_DATA || state_reg == ST_TX_WAIT)) begin
        tx_done_next = 1;
    end
    if (reset_queues) begin
        sq_cons_next = 0;
        cq_prod_next = 0;
        fatal_next = 0;
    end
    case (state_reg)
        ST_IDLE: if (enable && fatal_reg == 0 && sq_pending != 0 && cq_pending < ring_size) begin
            sqe_next = 0;
            result_next = 0;
            tx_done_next = 0;
            state_next = ST_SQ_REQ;
        end
        ST_SQ_REQ: if (sq_ready) begin
            state_next = ST_SQ_DATA;
        end
        ST_SQ_DATA: begin
            if (sq_valid) begin
                sqe_next = sq_data;
                state_next = ST_SQ_DONE;
            end else if (sq_done) begin
                result_next = CQ_STATUS_SQ_DMA | sq_error;
                state_next = ST_CQ_DESC;
            end
        end
        ST_SQ_DONE: if (sq_done) begin
            state_next = ST_CHECK;
        end
        ST_CHECK: begin
            if (sq_length < 14 || sq_length > MAX_FRAME_SIZE || sqe_reg[SQE_FLAGS_OFFSET +: 64] != 0) begin
                result_next = CQ_STATUS_BAD_SQE;
                state_next = ST_CQ_DESC;
            end else begin
                state_next = ST_MR_REQ;
            end
        end
        ST_MR_REQ: if (mr_ready) begin
            state_next = ST_MR_RESP;
        end
        ST_MR_RESP: if (mr_valid) begin
            if (mr_error != 0) begin
                result_next = CQ_STATUS_MR | mr_error;
                state_next = ST_CQ_DESC;
            end else begin
                payload_addr_next = mr_result_addr;
                state_next = ST_DATA_REQ;
            end
        end
        ST_DATA_REQ: if (data_ready) begin
            state_next = ST_DATA;
        end
        ST_DATA: if (data_done) begin
            if (data_error != 0) begin
                result_next = CQ_STATUS_PAYLOAD_DMA | data_error;
                state_next = ST_CQ_DESC;
            end else begin
                state_next = ST_TX_WAIT;
            end
        end
        ST_TX_WAIT: if (tx_done_reg) begin
            state_next = ST_CQ_DESC;
        end
        ST_CQ_DESC: if (m_axis_ctrl_dma_write_desc_ready) begin
            state_next = ST_CQ_WAIT;
        end
        ST_CQ_WAIT: if (s_axis_ctrl_dma_write_desc_status_valid && s_axis_ctrl_dma_write_desc_status_tag == CQ_DMA_TAG) begin
            if (s_axis_ctrl_dma_write_desc_status_error != 0) begin
                // 无法可靠发布 CQE 时停队列，绝不发布虚假的 consumer/prod。
                fatal_next = CQ_FATAL_DMA | s_axis_ctrl_dma_write_desc_status_error;
            end else begin
                sq_cons_next = sq_cons_reg+1;
                cq_prod_next = cq_prod_reg+1;
            end
            state_next = ST_IDLE;
        end
        default: state_next = ST_IDLE;
    endcase
end

always @(posedge clk) begin
    state_reg <= state_next;
    sq_cons_reg <= sq_cons_next;
    cq_prod_reg <= cq_prod_next;
    sqe_reg <= sqe_next;
    result_reg <= result_next;
    payload_addr_reg <= payload_addr_next;
    fatal_reg <= fatal_next;
    tx_done_reg <= tx_done_next;

    if (rst) begin
        state_reg <= ST_IDLE;
        sq_cons_reg <= 0;
        cq_prod_reg <= 0;
        sqe_reg <= 0;
        result_reg <= 0;
        payload_addr_reg <= 0;
        fatal_reg <= 0;
        tx_done_reg <= 0;
    end
end

assign m_axis_ctrl_dma_read_desc_ram_sel = 0;
assign m_axis_data_dma_read_desc_ram_sel = 0;
assign m_axis_ctrl_dma_write_desc_dma_addr = cq_address;
assign m_axis_ctrl_dma_write_desc_ram_sel = 0;
assign m_axis_ctrl_dma_write_desc_ram_addr = 0;
assign m_axis_ctrl_dma_write_desc_len = ENTRY_SIZE;
assign m_axis_ctrl_dma_write_desc_tag = CQ_DMA_TAG;
assign m_axis_ctrl_dma_write_desc_imm = 0;
assign m_axis_ctrl_dma_write_desc_imm_en = 0;
assign m_axis_ctrl_dma_write_desc_valid = state_reg == ST_CQ_DESC;

// CQE 保持到 DMA 写完成。每段可以独立反压，不假设所有段同周期取数。
// Last DWORD is the publication sequence; software observes it before payload.
wire [31:0] cqe_commit = sq_cons_reg + 32'd1;
wire [255:0] cqe = {cqe_commit, 64'd0, sq_cons_reg, sq_length, result_reg, sqe_reg[SQE_WR_ID_OFFSET +: 64]};
genvar seg;
generate
    for (seg=0; seg<RAM_SEG_COUNT; seg=seg+1) begin : cq_ram_segment
        reg valid_reg = 0;
        reg [RAM_SEG_DATA_WIDTH-1:0] data_reg = 0;
        wire [RAM_SEG_ADDR_WIDTH-1:0] addr = ctrl_dma_ram_rd_cmd_addr[seg*RAM_SEG_ADDR_WIDTH +: RAM_SEG_ADDR_WIDTH];
        assign ctrl_dma_ram_rd_cmd_ready[seg] = !valid_reg || ctrl_dma_ram_rd_resp_ready[seg];
        assign ctrl_dma_ram_rd_resp_valid[seg] = valid_reg;
        assign ctrl_dma_ram_rd_resp_data[seg*RAM_SEG_DATA_WIDTH +: RAM_SEG_DATA_WIDTH] = data_reg;
        always @(posedge clk) begin
            if (rst) begin
                valid_reg <= 0;
                data_reg <= 0;
            end else if (ctrl_dma_ram_rd_cmd_ready[seg]) begin
                valid_reg <= ctrl_dma_ram_rd_cmd_valid[seg];
                if (ctrl_dma_ram_rd_cmd_valid[seg]) begin
                    data_reg <= addr == 0 ? (cqe >> (seg*RAM_SEG_DATA_WIDTH)) : 0;
                end
            end
        end
    end
endgenerate

raw_dma_read #(
    .DMA_ADDR_WIDTH(DMA_ADDR_WIDTH), .DMA_LEN_WIDTH(DMA_LEN_WIDTH), .DMA_TAG_WIDTH(DMA_TAG_WIDTH),
    .RAM_ADDR_WIDTH(RAM_ADDR_WIDTH), .RAM_SEG_COUNT(RAM_SEG_COUNT),
    .RAM_SEG_DATA_WIDTH(RAM_SEG_DATA_WIDTH), .RAM_SEG_BE_WIDTH(RAM_SEG_BE_WIDTH),
    .RAM_SEG_ADDR_WIDTH(RAM_SEG_ADDR_WIDTH), .AXIS_DATA_WIDTH(256),
    .AXIS_KEEP_WIDTH(256/8), .RAM_SIZE(1024), .TAG(SQ_DMA_TAG)
) sq_dma_inst (
    .clk(clk), .rst(rst), .req_addr(sq_address), .req_len(SQ_DMA_LENGTH),
    .req_valid(state_reg == ST_SQ_REQ), .req_ready(sq_ready),
    .done_valid(sq_done), .done_ready(1'b1), .done_error(sq_error),
    .dma_desc_addr(m_axis_ctrl_dma_read_desc_dma_addr),
    .dma_desc_ram_addr(m_axis_ctrl_dma_read_desc_ram_addr),
    .dma_desc_len(m_axis_ctrl_dma_read_desc_len),
    .dma_desc_tag(m_axis_ctrl_dma_read_desc_tag),
    .dma_desc_valid(m_axis_ctrl_dma_read_desc_valid),
    .dma_desc_ready(m_axis_ctrl_dma_read_desc_ready),
    .dma_status_tag(s_axis_ctrl_dma_read_desc_status_tag),
    .dma_status_error(s_axis_ctrl_dma_read_desc_status_error),
    .dma_status_valid(s_axis_ctrl_dma_read_desc_status_valid),
    .ram_wr_cmd_be(ctrl_dma_ram_wr_cmd_be),
    .ram_wr_cmd_addr(ctrl_dma_ram_wr_cmd_addr),
    .ram_wr_cmd_data(ctrl_dma_ram_wr_cmd_data),
    .ram_wr_cmd_valid(ctrl_dma_ram_wr_cmd_valid),
    .ram_wr_cmd_ready(ctrl_dma_ram_wr_cmd_ready),
    .ram_wr_done(ctrl_dma_ram_wr_done),
    .m_axis_tdata(sq_data),
    .m_axis_tkeep(sq_keep),
    .m_axis_tvalid(sq_valid),
    .m_axis_tready(state_reg == ST_SQ_DATA),
    .m_axis_tlast(sq_last)
);

raw_dma_read #(
    .DMA_ADDR_WIDTH(DMA_ADDR_WIDTH), .DMA_LEN_WIDTH(DMA_LEN_WIDTH), .DMA_TAG_WIDTH(DMA_TAG_WIDTH),
    .RAM_ADDR_WIDTH(RAM_ADDR_WIDTH), .RAM_SEG_COUNT(RAM_SEG_COUNT),
    .RAM_SEG_DATA_WIDTH(RAM_SEG_DATA_WIDTH), .RAM_SEG_BE_WIDTH(RAM_SEG_BE_WIDTH),
    .RAM_SEG_ADDR_WIDTH(RAM_SEG_ADDR_WIDTH), .AXIS_DATA_WIDTH(AXIS_DATA_WIDTH),
    .AXIS_KEEP_WIDTH(AXIS_DATA_WIDTH/8), .RAM_SIZE(16384), .TAG(PAYLOAD_DMA_TAG)
) payload_dma_inst (
    .clk(clk), .rst(rst), .req_addr(payload_addr_reg), .req_len(sq_length[DMA_LEN_WIDTH-1:0]),
    .req_valid(state_reg == ST_DATA_REQ), .req_ready(data_ready),
    .done_valid(data_done), .done_ready(1'b1), .done_error(data_error),
    .dma_desc_addr(m_axis_data_dma_read_desc_dma_addr),
    .dma_desc_ram_addr(m_axis_data_dma_read_desc_ram_addr),
    .dma_desc_len(m_axis_data_dma_read_desc_len),
    .dma_desc_tag(m_axis_data_dma_read_desc_tag),
    .dma_desc_valid(m_axis_data_dma_read_desc_valid),
    .dma_desc_ready(m_axis_data_dma_read_desc_ready),
    .dma_status_tag(s_axis_data_dma_read_desc_status_tag),
    .dma_status_error(s_axis_data_dma_read_desc_status_error),
    .dma_status_valid(s_axis_data_dma_read_desc_status_valid),
    .ram_wr_cmd_be(data_dma_ram_wr_cmd_be),
    .ram_wr_cmd_addr(data_dma_ram_wr_cmd_addr),
    .ram_wr_cmd_data(data_dma_ram_wr_cmd_data),
    .ram_wr_cmd_valid(data_dma_ram_wr_cmd_valid),
    .ram_wr_cmd_ready(data_dma_ram_wr_cmd_ready),
    .ram_wr_done(data_dma_ram_wr_done),
    .m_axis_tdata(m_axis_tx_tdata),
    .m_axis_tkeep(m_axis_tx_tkeep),
    .m_axis_tvalid(m_axis_tx_tvalid),
    .m_axis_tready(m_axis_tx_tready),
    .m_axis_tlast(m_axis_tx_tlast)
);

endmodule
`resetall
