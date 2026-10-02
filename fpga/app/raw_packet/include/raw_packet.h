/* SPDX-License-Identifier: BSD-2-Clause */
#ifndef MQNIC_RAW_PACKET_H
#define MQNIC_RAW_PACKET_H
#include <linux/types.h>
#include <linux/ioctl.h>
#define RAW_APP_ID 0x12348010

/* BAR2 control ABI; offsets and entry layouts remain version 0x100. */
#define RAW_REG_RB_TYPE 0x00
#define RAW_REG_RB_VERSION 0x04
#define RAW_REG_RB_NEXT 0x08
#define RAW_REG_APP_ID 0x0c
#define RAW_REG_ENABLE 0x10
#define RAW_REG_STATUS 0x14
#define RAW_REG_CONFIG_ERROR 0x18
#define RAW_REG_FATAL 0x1c
#define RAW_REG_SQ_BASE_L 0x20
#define RAW_REG_SQ_BASE_H 0x24
#define RAW_REG_CQ_BASE_L 0x28
#define RAW_REG_CQ_BASE_H 0x2c
#define RAW_REG_RING_LOG 0x30
#define RAW_REG_PD 0x34
#define RAW_REG_SQ_PROD 0x38
#define RAW_REG_SQ_CONS 0x3c
#define RAW_REG_CQ_PROD 0x40
#define RAW_REG_CQ_CONS 0x44
#define RAW_REG_MAX_FRAME 0x48
#define RAW_REG_QUEUE_RESET 0x4c
#define RAW_REG_MR_INDEX 0x80
#define RAW_REG_MR_KEY 0x84
#define RAW_REG_MR_PD 0x88
#define RAW_REG_MR_FLAGS 0x8c
#define RAW_REG_MR_VA_L 0x90
#define RAW_REG_MR_VA_H 0x94
#define RAW_REG_MR_DMA_L 0x98
#define RAW_REG_MR_DMA_H 0x9c
#define RAW_REG_MR_LENGTH_L 0xa0
#define RAW_REG_MR_LENGTH_H 0xa4
#define RAW_REG_MR_COMMIT 0xa8
#define RAW_RB_TYPE 0x12348110
#define RAW_RB_VERSION 0x100
#define RAW_PD 7
#define RAW_MR_ENABLE (1U << 31)
#define RAW_MR_LOCAL_READ 1U

#define RAW_RING_LOG 8
#define RAW_RING_SIZE (1U << RAW_RING_LOG)
#define RAW_SQ_OFFSET 0
#define RAW_CQ_OFFSET 0x4000
#define RAW_DATA_OFFSET 0x8000
#define RAW_MAP_SIZE 0x100000
#define RAW_VADDR 0x10000000ULL
#define RAW_LKEY 0x1233
#define RAW_MAX_FRAME 9214
struct raw_sqe {
    __le64 wr_id;
    __le64 addr;
    __le32 length;
    __le32 lkey;
    __le32 flags;
    __le32 reserved;
};
struct raw_cqe {
    __le64 wr_id;
    __le32 status;
    __le32 length;
    __le32 sq_sequence;
    __le32 reserved;
    __le32 reserved2;
    __le32 commit_sequence;
};
struct raw_progress {
    __u32 sq_cons;
    __u32 cq_prod;
    __u32 fatal;
    __u32 config_error;
};
#define RAW_IOCTL_START _IO('R', 0)
#define RAW_IOCTL_SUBMIT _IOW('R', 1, __u32)
#define RAW_IOCTL_REAP _IOW('R', 2, __u32)
#define RAW_IOCTL_PROGRESS _IOR('R', 3, struct raw_progress)
#define RAW_IOCTL_STOP _IO('R', 4)
#endif
