// SPDX-License-Identifier: BSD-2-Clause
// raw_packet_qp: SQ -> MR -> DMA -> Ethernet -> CQ 的多在途原始包队列。
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
    parameter MAX_FRAME_SIZE = 9214,
    parameter OP_TABLE_SIZE = 1,
    parameter TX_TAG_WIDTH = 16,
    parameter WATCHDOG_CYCLES = 0
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
    output wire [TX_TAG_WIDTH:0] m_axis_tx_tuser,
    input wire [TX_TAG_WIDTH-1:0] tx_cpl_tag,
    input wire tx_cpl_valid
);


localparam SLOT_WIDTH = OP_TABLE_SIZE > 1 ? $clog2(OP_TABLE_SIZE) : 1;
localparam SLOT_MASK = OP_TABLE_SIZE-1;
localparam FRAME_BUFFER_SIZE = 16384;
localparam RAM_WORD_BYTES = RAM_SEG_COUNT*RAM_SEG_BE_WIDTH;
localparam [DMA_TAG_WIDTH-1:0] SQ_DMA_TAG = 1;
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
    ST_CHECK=4, ST_MR_REQ=5, ST_MR_RESP=6, ST_DATA_REQ=7;
localparam TX_IDLE=0, TX_STREAM=1;
localparam CQ_IDLE=0, CQ_DESC=1, CQ_WAIT=2;

initial begin
    if (DMA_ADDR_WIDTH != 64 || AXIL_APP_CTRL_DATA_WIDTH != 32 ||
        AXIL_APP_CTRL_STRB_WIDTH != 4 || MAX_FRAME_SIZE > FRAME_BUFFER_SIZE || DMA_LEN_WIDTH < 15 ||
        (OP_TABLE_SIZE != 1 && OP_TABLE_SIZE != 2 && OP_TABLE_SIZE != 4) ||
        RAM_ADDR_WIDTH < 14+$clog2(OP_TABLE_SIZE) ||
        DMA_TAG_WIDTH < $clog2(OP_TABLE_SIZE)+1 || TX_TAG_WIDTH < $clog2(OP_TABLE_SIZE)+2 ||
        DMA_TAG_WIDTH > 32 || TX_TAG_WIDTH > 32 || RAM_WORD_BYTES < ENTRY_SIZE) begin
        $error("Unsupported raw QP configuration");
        $finish;
    end
end

reg [3:0] front_state_reg = ST_IDLE, front_state_next;
reg tx_state_reg = TX_IDLE, tx_state_next;
reg [1:0] cq_state_reg = CQ_IDLE, cq_state_next;
reg [31:0] fetch_ptr_reg = 0, fetch_ptr_next;
reg [31:0] tx_ptr_reg = 0, tx_ptr_next;
reg [31:0] sq_cons_reg = 0, sq_cons_next;
reg [31:0] cq_prod_reg = 0, cq_prod_next;
reg [31:0] fatal_reg = 0, fatal_next;
reg [31:0] tag_counter_reg = 0, tag_counter_next;
reg [31:0] stall_count_reg = 0, stall_count_next;
reg [31:0] unexpected_count_reg = 0, unexpected_count_next;
reg [2:0] unexpected_events;
reg sq_dma_desc_issued_reg = 0, sq_dma_desc_issued_next;
reg sq_dma_status_done_reg = 0, sq_dma_status_done_next;
reg [31:0] front_sequence_reg = 0, front_sequence_next;
reg [SLOT_WIDTH-1:0] front_slot_reg = 0, front_slot_next;
reg [255:0] sqe_reg = 0, sqe_next;
reg [OP_TABLE_SIZE-1:0] active_reg = 0, active_next;
reg [OP_TABLE_SIZE-1:0] ready_reg = 0, ready_next;
reg [OP_TABLE_SIZE-1:0] dma_issued_reg = 0, dma_issued_next;
reg [OP_TABLE_SIZE-1:0] dma_done_reg = 0, dma_done_next;
reg [OP_TABLE_SIZE-1:0] tx_started_reg = 0, tx_started_next;
reg [OP_TABLE_SIZE-1:0] stream_done_reg = 0, stream_done_next;
reg [OP_TABLE_SIZE-1:0] tx_done_reg = 0, tx_done_next;
reg [63:0] wr_id_mem [0:OP_TABLE_SIZE-1];
reg [63:0] wr_id_next [0:OP_TABLE_SIZE-1];
reg [63:0] payload_mem [0:OP_TABLE_SIZE-1];
reg [63:0] payload_next [0:OP_TABLE_SIZE-1];
reg [31:0] length_mem [0:OP_TABLE_SIZE-1];
reg [31:0] length_next [0:OP_TABLE_SIZE-1];
reg [31:0] sequence_mem [0:OP_TABLE_SIZE-1];
reg [31:0] sequence_next [0:OP_TABLE_SIZE-1];
reg [31:0] tag_mem [0:OP_TABLE_SIZE-1];
reg [31:0] tag_next [0:OP_TABLE_SIZE-1];
reg [31:0] result_mem [0:OP_TABLE_SIZE-1];
reg [31:0] result_next [0:OP_TABLE_SIZE-1];

wire enable;
wire [63:0] sq_base, cq_base;
wire [3:0] ring_log;
wire [23:0] pd;
wire [31:0] sq_prod, cq_cons, config_error;
wire [3:0] mr_index;
wire [31:0] mr_key, mr_flags;
wire [23:0] mr_pd;
wire [63:0] mr_va, mr_dma, mr_len;
wire reset_queues, mr_commit;
wire [31:0] ring_size = 32'd1 << ring_log;
wire [31:0] ring_mask = ring_size-1;
wire [31:0] active_count = fetch_ptr_reg-sq_cons_reg;
// Fetching reserves both an operation slot and a CQ credit, including errors.
wire [31:0] reserved_cq_count = fetch_ptr_reg-cq_cons;
wire [64:0] sq_limit = {1'b0, sq_base} + ({33'd0, ring_size} << 5)-1'b1;
wire [64:0] cq_limit = {1'b0, cq_base} + ({33'd0, ring_size} << 5)-1'b1;
wire queue_config_valid = ring_log >= 1 && ring_log <= 10 &&
    sq_base[4:0] == 0 && cq_base[4:0] == 0 && !sq_limit[64] && !cq_limit[64];
wire [SLOT_WIDTH-1:0] fetch_slot = fetch_ptr_reg & SLOT_MASK;
wire [SLOT_WIDTH-1:0] tx_slot = tx_ptr_reg & SLOT_MASK;
wire [SLOT_WIDTH-1:0] cq_slot = sq_cons_reg & SLOT_MASK;
wire [63:0] sq_address = sq_base + ({32'd0, front_sequence_reg & ring_mask} << 5);
wire [63:0] cq_address = cq_base + ({32'd0, cq_prod_reg & ring_mask} << 5);
wire [31:0] sq_length = sqe_reg[SQE_LENGTH_OFFSET +: 32];
wire sq_ready, sq_done, sq_valid, sq_last;
// The serial SQ reader has a local fixed tag. At the app DMA boundary use
// allocation generation, and translate only the first matching issued status.
wire sq_status_match = s_axis_ctrl_dma_read_desc_status_valid &&
    sq_dma_desc_issued_reg && !sq_dma_status_done_reg && active_reg[front_slot_reg] &&
    (front_state_reg == ST_SQ_DATA || front_state_reg == ST_SQ_DONE) &&
    s_axis_ctrl_dma_read_desc_status_tag == tag_mem[front_slot_reg][DMA_TAG_WIDTH-1:0];
wire cq_status_match = s_axis_ctrl_dma_write_desc_status_valid &&
    cq_state_reg == CQ_WAIT && active_reg[cq_slot] &&
    s_axis_ctrl_dma_write_desc_status_tag == tag_mem[cq_slot][DMA_TAG_WIDTH-1:0];
wire [3:0] sq_error;
wire [255:0] sq_data;
wire [31:0] sq_keep;
wire mr_ready, mr_valid;
wire [63:0] mr_result_addr;
wire [3:0] mr_error;
wire source_ready;
wire tx_launch = tx_state_reg == TX_IDLE && tx_ptr_reg != fetch_ptr_reg &&
    active_reg[tx_slot] && ready_reg[tx_slot] && dma_done_reg[tx_slot] && result_mem[tx_slot] == 0;
// Fatal CQ errors retain contexts. Only a drained datapath may be reset/reconfigured.
wire pending_dma = |(dma_issued_reg & ~dma_done_reg);
wire pending_tx = |(tx_started_reg & ~tx_done_reg);
wire idle = front_state_reg == ST_IDLE && tx_state_reg == TX_IDLE && cq_state_reg == CQ_IDLE &&
    !pending_dma && !pending_tx && (fatal_reg != 0 || active_count == 0);
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
    .idle(idle),
    .queue_config_valid(queue_config_valid),
    .ring_size(ring_size),
    .sq_cons(sq_cons_reg),
    .cq_prod(cq_prod_reg),
    .fatal(fatal_reg),
    .op_table_size(OP_TABLE_SIZE),
    .active_count(active_count),
    .fetch_ptr(fetch_ptr_reg),
    .phase({24'd0, cq_state_reg, tx_state_reg, 1'b0, front_state_reg}),
    .unexpected_count(unexpected_count_reg),
    .stall_count(stall_count_reg),
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
    .req_valid(front_state_reg == ST_MR_REQ), .req_ready(mr_ready),
    .req_key(sqe_reg[SQE_LKEY_OFFSET +: 32]), .req_pd(pd), .req_vaddr(sqe_reg[SQE_ADDR_OFFSET +: 64]),
    .req_length(sq_length), .req_permissions(2'b01),
    .resp_valid(mr_valid), .resp_ready(front_state_reg == ST_MR_RESP),
    .resp_dma_addr(mr_result_addr), .resp_error(mr_error)
);


integer k;
always @* begin
    front_state_next = front_state_reg;
    tx_state_next = tx_state_reg;
    cq_state_next = cq_state_reg;
    fetch_ptr_next = fetch_ptr_reg;
    tx_ptr_next = tx_ptr_reg;
    sq_cons_next = sq_cons_reg;
    cq_prod_next = cq_prod_reg;
    fatal_next = fatal_reg;
    tag_counter_next = tag_counter_reg;
    stall_count_next = stall_count_reg;
    unexpected_count_next = unexpected_count_reg;
    unexpected_events = {2'b0, s_axis_ctrl_dma_read_desc_status_valid} +
        {2'b0, s_axis_data_dma_read_desc_status_valid} +
        {2'b0, s_axis_ctrl_dma_write_desc_status_valid} + {2'b0, tx_cpl_valid};
    sq_dma_desc_issued_next = sq_dma_desc_issued_reg;
    sq_dma_status_done_next = sq_dma_status_done_reg;
    if (m_axis_ctrl_dma_read_desc_valid && m_axis_ctrl_dma_read_desc_ready)
        sq_dma_desc_issued_next = 1;
    if (sq_status_match) begin
        sq_dma_status_done_next = 1;
        unexpected_events = unexpected_events-1;
    end
    if (cq_status_match) unexpected_events = unexpected_events-1;
    front_sequence_next = front_sequence_reg;
    front_slot_next = front_slot_reg;
    sqe_next = sqe_reg;
    active_next = active_reg;
    ready_next = ready_reg;
    dma_issued_next = dma_issued_reg;
    dma_done_next = dma_done_reg;
    tx_started_next = tx_started_reg;
    stream_done_next = stream_done_reg;
    tx_done_next = tx_done_reg;
    for (k=0; k<OP_TABLE_SIZE; k=k+1) begin
        wr_id_next[k] = wr_id_mem[k];
        payload_next[k] = payload_mem[k];
        length_next[k] = length_mem[k];
        sequence_next[k] = sequence_mem[k];
        tag_next[k] = tag_mem[k];
        result_next[k] = result_mem[k];
    end

    case (front_state_reg)
        ST_IDLE: if (enable && fatal_reg == 0 && fetch_ptr_reg != sq_prod &&
                active_count < OP_TABLE_SIZE && reserved_cq_count < ring_size) begin
            front_slot_next = fetch_slot;
            front_sequence_next = fetch_ptr_reg;
            sq_dma_desc_issued_next = 0;
            sq_dma_status_done_next = 0;
            fetch_ptr_next = fetch_ptr_reg+1;
            tag_counter_next = tag_counter_reg+1;
            sqe_next = 0;
            active_next[fetch_slot] = 1;
            ready_next[fetch_slot] = 0;
            dma_issued_next[fetch_slot] = 0;
            dma_done_next[fetch_slot] = 0;
            tx_started_next[fetch_slot] = 0;
            stream_done_next[fetch_slot] = 0;
            tx_done_next[fetch_slot] = 0;
            wr_id_next[fetch_slot] = 0;
            length_next[fetch_slot] = 0;
            result_next[fetch_slot] = 0;
            sequence_next[fetch_slot] = fetch_ptr_reg;
            tag_next[fetch_slot] = tag_counter_reg;
            front_state_next = ST_SQ_REQ;
        end
        ST_SQ_REQ: if (sq_ready) front_state_next = ST_SQ_DATA;
        ST_SQ_DATA: begin
            if (sq_valid) begin
                sqe_next = sq_data;
                front_state_next = ST_SQ_DONE;
            end else if (sq_done) begin
                result_next[front_slot_reg] = CQ_STATUS_SQ_DMA | sq_error;
                ready_next[front_slot_reg] = 1;
                dma_done_next[front_slot_reg] = 1;
                front_state_next = ST_IDLE;
            end
        end
        ST_SQ_DONE: if (sq_done) front_state_next = ST_CHECK;
        ST_CHECK: begin
            wr_id_next[front_slot_reg] = sqe_reg[SQE_WR_ID_OFFSET +: 64];
            length_next[front_slot_reg] = sq_length;
            if (sq_length < 14 || sq_length > MAX_FRAME_SIZE || sqe_reg[SQE_FLAGS_OFFSET +: 64] != 0) begin
                result_next[front_slot_reg] = CQ_STATUS_BAD_SQE;
                ready_next[front_slot_reg] = 1;
                dma_done_next[front_slot_reg] = 1;
                front_state_next = ST_IDLE;
            end else front_state_next = ST_MR_REQ;
        end
        ST_MR_REQ: if (mr_ready) front_state_next = ST_MR_RESP;
        ST_MR_RESP: if (mr_valid) begin
            if (mr_error != 0) begin
                result_next[front_slot_reg] = CQ_STATUS_MR | mr_error;
                ready_next[front_slot_reg] = 1;
                dma_done_next[front_slot_reg] = 1;
                front_state_next = ST_IDLE;
            end else begin
                payload_next[front_slot_reg] = mr_result_addr;
                front_state_next = ST_DATA_REQ;
            end
        end
        ST_DATA_REQ: if (m_axis_data_dma_read_desc_ready) begin
            dma_issued_next[front_slot_reg] = 1;
            ready_next[front_slot_reg] = 1;
            front_state_next = ST_IDLE;
        end
        default: front_state_next = ST_IDLE;
    endcase

    // Status channels may return in any order; tags include allocation generation.
    for (k=0; k<OP_TABLE_SIZE; k=k+1) begin
        if (s_axis_data_dma_read_desc_status_valid && active_reg[k] && dma_issued_reg[k] &&
                !dma_done_reg[k] && s_axis_data_dma_read_desc_status_tag == tag_mem[k][DMA_TAG_WIDTH-1:0]) begin
            unexpected_events = unexpected_events-1;
            dma_done_next[k] = 1;
            if (s_axis_data_dma_read_desc_status_error != 0)
                result_next[k] = CQ_STATUS_PAYLOAD_DMA | s_axis_data_dma_read_desc_status_error;
        end
        if (tx_cpl_valid && active_reg[k] && tx_started_reg[k] && !tx_done_reg[k] &&
                tx_cpl_tag == {1'b0, tag_mem[k][TX_TAG_WIDTH-2:0]}) begin
            unexpected_events = unexpected_events-1;
            tx_done_next[k] = 1;
        end
    end

    case (tx_state_reg)
        TX_IDLE: if (tx_ptr_reg != fetch_ptr_reg && active_reg[tx_slot] &&
                ready_reg[tx_slot] && dma_done_reg[tx_slot]) begin
            if (result_mem[tx_slot] != 0) begin
                tx_ptr_next = tx_ptr_reg+1;
                stream_done_next[tx_slot] = 1;
                tx_done_next[tx_slot] = 1;
            end else if (source_ready) begin
                tx_started_next[tx_slot] = 1;
                tx_state_next = TX_STREAM;
            end
        end
        TX_STREAM: if (m_axis_tx_tvalid && m_axis_tx_tready && m_axis_tx_tlast) begin
            stream_done_next[tx_slot] = 1;
            tx_ptr_next = tx_ptr_reg+1;
            tx_state_next = TX_IDLE;
        end
    endcase

    case (cq_state_reg)
        CQ_IDLE: if (fatal_reg == 0 && sq_cons_reg != tx_ptr_reg && active_reg[cq_slot] &&
                stream_done_reg[cq_slot] && tx_done_reg[cq_slot]) cq_state_next = CQ_DESC;
        CQ_DESC: if (m_axis_ctrl_dma_write_desc_ready) cq_state_next = CQ_WAIT;
        CQ_WAIT: if (cq_status_match) begin
            if (fatal_reg != 0) begin
                // A watchdog has quarantined this operation; a late status may
                // end drain but must not publish success or release its context.
            end else if (s_axis_ctrl_dma_write_desc_status_error != 0) begin
                fatal_next = CQ_FATAL_DMA | s_axis_ctrl_dma_write_desc_status_error;
            end else begin
                active_next[cq_slot] = 0;
                sq_cons_next = sq_cons_reg+1;
                cq_prod_next = cq_prod_reg+1;
            end
            cq_state_next = CQ_IDLE;
        end
    endcase

    unexpected_count_next = unexpected_count_reg + unexpected_events;
    // A diagnostic timeout freezes acceptance, retaining all DMA/slot ownership.
    // It is not an abort of parent PCIe DMA, nor permission to free host memory.
    if (active_count != 0 && fatal_reg == 0) begin
        if (front_state_next != front_state_reg || tx_state_next != tx_state_reg ||
                cq_state_next != cq_state_reg || dma_done_next != dma_done_reg ||
                tx_done_next != tx_done_reg || sq_dma_status_done_next != sq_dma_status_done_reg ||
                sq_dma_desc_issued_next != sq_dma_desc_issued_reg ||
                (m_axis_tx_tvalid && m_axis_tx_tready)) begin
            stall_count_next = 0;
        end else if (WATCHDOG_CYCLES != 0 && stall_count_reg >= WATCHDOG_CYCLES-1) begin
            fatal_next = 32'h60;
        end else begin
            stall_count_next = stall_count_reg+1;
        end
    end else if (fatal_reg == 0) begin
        stall_count_next = 0;
    end

    if (reset_queues) begin
        fetch_ptr_next = 0;
        tx_ptr_next = 0;
        sq_cons_next = 0;
        cq_prod_next = 0;
        fatal_next = 0;
        stall_count_next = 0;
        unexpected_count_next = 0;
        sq_dma_desc_issued_next = 0;
        sq_dma_status_done_next = 0;
        active_next = 0;
        ready_next = 0;
        dma_issued_next = 0;
        dma_done_next = 0;
        tx_started_next = 0;
        stream_done_next = 0;
        tx_done_next = 0;
        // Keep allocation generation across queue resets; rst requires parent drain.
    end
end

integer n;
always @(posedge clk) begin
    front_state_reg <= front_state_next;
    tx_state_reg <= tx_state_next;
    cq_state_reg <= cq_state_next;
    fetch_ptr_reg <= fetch_ptr_next;
    tx_ptr_reg <= tx_ptr_next;
    sq_cons_reg <= sq_cons_next;
    cq_prod_reg <= cq_prod_next;
    fatal_reg <= fatal_next;
    tag_counter_reg <= tag_counter_next;
    stall_count_reg <= stall_count_next;
    unexpected_count_reg <= unexpected_count_next;
    sq_dma_desc_issued_reg <= sq_dma_desc_issued_next;
    sq_dma_status_done_reg <= sq_dma_status_done_next;
    front_sequence_reg <= front_sequence_next;
    front_slot_reg <= front_slot_next;
    sqe_reg <= sqe_next;
    active_reg <= active_next;
    ready_reg <= ready_next;
    dma_issued_reg <= dma_issued_next;
    dma_done_reg <= dma_done_next;
    tx_started_reg <= tx_started_next;
    stream_done_reg <= stream_done_next;
    tx_done_reg <= tx_done_next;
    for (n=0; n<OP_TABLE_SIZE; n=n+1) begin
        wr_id_mem[n] <= wr_id_next[n];
        payload_mem[n] <= payload_next[n];
        length_mem[n] <= length_next[n];
        sequence_mem[n] <= sequence_next[n];
        tag_mem[n] <= tag_next[n];
        result_mem[n] <= result_next[n];
    end
    if (rst) begin
        front_state_reg <= ST_IDLE;
        tx_state_reg <= TX_IDLE;
        cq_state_reg <= CQ_IDLE;
        fetch_ptr_reg <= 0;
        tx_ptr_reg <= 0;
        sq_cons_reg <= 0;
        cq_prod_reg <= 0;
        fatal_reg <= 0;
        tag_counter_reg <= 0;
        stall_count_reg <= 0;
        unexpected_count_reg <= 0;
        sq_dma_desc_issued_reg <= 0;
        sq_dma_status_done_reg <= 0;
        front_sequence_reg <= 0;
        front_slot_reg <= 0;
        sqe_reg <= 0;
        active_reg <= 0;
        ready_reg <= 0;
        dma_issued_reg <= 0;
        dma_done_reg <= 0;
        tx_started_reg <= 0;
        stream_done_reg <= 0;
        tx_done_reg <= 0;
        for (n=0; n<OP_TABLE_SIZE; n=n+1) begin
            wr_id_mem[n] <= 0;
            payload_mem[n] <= 0;
            length_mem[n] <= 0;
            sequence_mem[n] <= 0;
            tag_mem[n] <= 0;
            result_mem[n] <= 0;
        end
    end
end

assign m_axis_ctrl_dma_read_desc_ram_sel = 0;
assign m_axis_ctrl_dma_read_desc_tag = tag_mem[front_slot_reg][DMA_TAG_WIDTH-1:0];
assign m_axis_data_dma_read_desc_ram_sel = 0;
assign m_axis_data_dma_read_desc_dma_addr = payload_mem[front_slot_reg];
assign m_axis_data_dma_read_desc_ram_addr = front_slot_reg * FRAME_BUFFER_SIZE;
assign m_axis_data_dma_read_desc_len = length_mem[front_slot_reg];
assign m_axis_data_dma_read_desc_tag = tag_mem[front_slot_reg];
assign m_axis_data_dma_read_desc_valid = front_state_reg == ST_DATA_REQ;
assign m_axis_ctrl_dma_write_desc_dma_addr = cq_address;
assign m_axis_ctrl_dma_write_desc_ram_sel = 0;
assign m_axis_ctrl_dma_write_desc_ram_addr = cq_slot * RAM_WORD_BYTES;
assign m_axis_ctrl_dma_write_desc_len = ENTRY_SIZE;
assign m_axis_ctrl_dma_write_desc_tag = tag_mem[cq_slot];
assign m_axis_ctrl_dma_write_desc_imm = 0;
assign m_axis_ctrl_dma_write_desc_imm_en = 0;
assign m_axis_ctrl_dma_write_desc_valid = cq_state_reg == CQ_DESC;

// Each CQE occupies a full segmented word so independently stalled segments
// continue to select the same operation until its DMA descriptor completes.
genvar seg;
generate
    for (seg=0; seg<RAM_SEG_COUNT; seg=seg+1) begin : cq_ram_segment
        reg valid_reg = 0;
        reg [RAM_SEG_DATA_WIDTH-1:0] data_reg = 0;
        wire [RAM_SEG_ADDR_WIDTH-1:0] addr = ctrl_dma_ram_rd_cmd_addr[seg*RAM_SEG_ADDR_WIDTH +: RAM_SEG_ADDR_WIDTH];
        wire [SLOT_WIDTH-1:0] slot = addr & SLOT_MASK;
        wire [31:0] commit_sequence = sequence_mem[slot]+32'd1;
        wire [255:0] cqe = {commit_sequence, 64'd0, sequence_mem[slot], length_mem[slot], result_mem[slot], wr_id_mem[slot]};
        assign ctrl_dma_ram_rd_cmd_ready[seg] = !valid_reg || ctrl_dma_ram_rd_resp_ready[seg];
        assign ctrl_dma_ram_rd_resp_valid[seg] = valid_reg;
        assign ctrl_dma_ram_rd_resp_data[seg*RAM_SEG_DATA_WIDTH +: RAM_SEG_DATA_WIDTH] = data_reg;
        always @(posedge clk) begin
            if (rst) begin
                valid_reg <= 0;
                data_reg <= 0;
            end else if (ctrl_dma_ram_rd_cmd_ready[seg]) begin
                valid_reg <= ctrl_dma_ram_rd_cmd_valid[seg];
                if (ctrl_dma_ram_rd_cmd_valid[seg])
                    data_reg <= addr < OP_TABLE_SIZE ? (cqe >> (seg*RAM_SEG_DATA_WIDTH)) : 0;
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
    .req_valid(front_state_reg == ST_SQ_REQ), .req_ready(sq_ready),
    .done_valid(sq_done), .done_ready(1'b1), .done_error(sq_error),
    .dma_desc_addr(m_axis_ctrl_dma_read_desc_dma_addr),
    .dma_desc_ram_addr(m_axis_ctrl_dma_read_desc_ram_addr),
    .dma_desc_len(m_axis_ctrl_dma_read_desc_len),
    .dma_desc_tag(),
    .dma_desc_valid(m_axis_ctrl_dma_read_desc_valid),
    .dma_desc_ready(m_axis_ctrl_dma_read_desc_ready),
    .dma_status_tag(SQ_DMA_TAG),
    .dma_status_error(s_axis_ctrl_dma_read_desc_status_error),
    .dma_status_valid(sq_status_match),
    .ram_wr_cmd_be(ctrl_dma_ram_wr_cmd_be),
    .ram_wr_cmd_addr(ctrl_dma_ram_wr_cmd_addr),
    .ram_wr_cmd_data(ctrl_dma_ram_wr_cmd_data),
    .ram_wr_cmd_valid(ctrl_dma_ram_wr_cmd_valid),
    .ram_wr_cmd_ready(ctrl_dma_ram_wr_cmd_ready),
    .ram_wr_done(ctrl_dma_ram_wr_done),
    .m_axis_tdata(sq_data),
    .m_axis_tkeep(sq_keep),
    .m_axis_tvalid(sq_valid),
    .m_axis_tready(front_state_reg == ST_SQ_DATA),
    .m_axis_tlast(sq_last)
);


wire [RAM_ADDR_WIDTH-1:0] tx_ram_address = tx_slot * FRAME_BUFFER_SIZE;
wire [DMA_LEN_WIDTH-1:0] tx_length = length_mem[tx_slot];
wire [RAM_SEG_COUNT*RAM_SEG_ADDR_WIDTH-1:0] payload_rd_addr;
wire [RAM_SEG_COUNT-1:0] payload_rd_valid, payload_rd_ready;
wire [RAM_SEG_COUNT*RAM_SEG_DATA_WIDTH-1:0] payload_rd_data;
wire [RAM_SEG_COUNT-1:0] payload_rd_resp_valid, payload_rd_resp_ready;

dma_psdpram #(
    .SIZE(OP_TABLE_SIZE*FRAME_BUFFER_SIZE), .SEG_COUNT(RAM_SEG_COUNT),
    .SEG_DATA_WIDTH(RAM_SEG_DATA_WIDTH), .SEG_BE_WIDTH(RAM_SEG_BE_WIDTH),
    .SEG_ADDR_WIDTH(RAM_SEG_ADDR_WIDTH), .PIPELINE(2)
) payload_ram_inst (
    .clk(clk), .rst(rst), .wr_cmd_be(data_dma_ram_wr_cmd_be),
    .wr_cmd_addr(data_dma_ram_wr_cmd_addr), .wr_cmd_data(data_dma_ram_wr_cmd_data),
    .wr_cmd_valid(data_dma_ram_wr_cmd_valid), .wr_cmd_ready(data_dma_ram_wr_cmd_ready),
    .wr_done(data_dma_ram_wr_done), .rd_cmd_addr(payload_rd_addr),
    .rd_cmd_valid(payload_rd_valid), .rd_cmd_ready(payload_rd_ready),
    .rd_resp_data(payload_rd_data), .rd_resp_valid(payload_rd_resp_valid),
    .rd_resp_ready(payload_rd_resp_ready)
);

dma_client_axis_source #(
    .RAM_ADDR_WIDTH(RAM_ADDR_WIDTH), .SEG_COUNT(RAM_SEG_COUNT),
    .SEG_DATA_WIDTH(RAM_SEG_DATA_WIDTH), .SEG_BE_WIDTH(RAM_SEG_BE_WIDTH),
    .SEG_ADDR_WIDTH(RAM_SEG_ADDR_WIDTH), .AXIS_DATA_WIDTH(AXIS_DATA_WIDTH),
    .AXIS_KEEP_WIDTH(AXIS_KEEP_WIDTH), .AXIS_USER_ENABLE(1), .AXIS_USER_WIDTH(TX_TAG_WIDTH+1),
    .AXIS_ID_WIDTH(1), .AXIS_DEST_WIDTH(1), .LEN_WIDTH(DMA_LEN_WIDTH), .TAG_WIDTH(DMA_TAG_WIDTH)
) payload_source_inst (
    .clk(clk), .rst(rst), .enable(1'b1),
    .s_axis_read_desc_ram_addr(tx_ram_address),
    .s_axis_read_desc_len(tx_length),
    .s_axis_read_desc_tag({DMA_TAG_WIDTH{1'b0}}),
    .s_axis_read_desc_id(1'b0), .s_axis_read_desc_dest(1'b0),
    .s_axis_read_desc_user({1'b0, tag_mem[tx_slot][TX_TAG_WIDTH-2:0], 1'b0}),
    .s_axis_read_desc_valid(tx_launch), .s_axis_read_desc_ready(source_ready),
    .m_axis_read_desc_status_tag(), .m_axis_read_desc_status_error(), .m_axis_read_desc_status_valid(),
    .m_axis_read_data_tdata(m_axis_tx_tdata), .m_axis_read_data_tkeep(m_axis_tx_tkeep),
    .m_axis_read_data_tvalid(m_axis_tx_tvalid), .m_axis_read_data_tready(m_axis_tx_tready),
    .m_axis_read_data_tlast(m_axis_tx_tlast), .m_axis_read_data_tid(),
    .m_axis_read_data_tdest(), .m_axis_read_data_tuser(m_axis_tx_tuser),
    .ram_rd_cmd_addr(payload_rd_addr), .ram_rd_cmd_valid(payload_rd_valid),
    .ram_rd_cmd_ready(payload_rd_ready), .ram_rd_resp_data(payload_rd_data),
    .ram_rd_resp_valid(payload_rd_resp_valid), .ram_rd_resp_ready(payload_rd_resp_ready)
);

endmodule
`resetall
