// SPDX-License-Identifier: BSD-2-Clause
#define _DEFAULT_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <endian.h>
#include <time.h>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include "raw_packet.h"
_Static_assert(sizeof(struct raw_sqe) == 32, "SQE ABI");
_Static_assert(sizeof(struct raw_cqe) == 32, "CQE ABI");
static double now(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec+t.tv_nsec*1e-9;
}
int main(int argc, char **argv)
{
    int fd = -1, ret = 1, started = 0;
    FILE *frame = NULL;
    unsigned char *map = MAP_FAILED, packet[RAW_MAX_FRAME+1];
    size_t len;
    uint32_t prod = 1, reaped = 1;
    struct raw_progress progress;
    struct raw_sqe *sqe;
    struct raw_cqe cqe;
    double deadline;
    if (argc != 3) {
        fprintf(stderr, "Usage: %s /dev/mqnic-raw-PCI_ADDRESS ethernet-frame.bin\n"
            "Frame includes Ethernet header, excludes preamble/FCS; 14..9214 bytes.\n", argv[0]);
        return 2;
    }
    frame = fopen(argv[2], "rb");
    if (!frame) { perror("frame"); goto out; }
    len = fread(packet, 1, sizeof(packet), frame);
    if (ferror(frame) || len < 14 || len > RAW_MAX_FRAME) {
        fprintf(stderr, "Invalid frame length/read error\n"); goto out;
    }
    fd = open(argv[1], O_RDWR | O_CLOEXEC);
    if (fd < 0) { perror("open"); goto out; }
    map = mmap(NULL, RAW_MAP_SIZE, PROT_READ|PROT_WRITE, MAP_SHARED, fd, 0);
    if (map == MAP_FAILED) { perror("mmap"); goto out; }
    // START initializes rings/MR and clears the mapping, so fill after START.
    if (ioctl(fd, RAW_IOCTL_START)) { perror("start"); goto out; }
    started = 1;
    memcpy(map+RAW_DATA_OFFSET, packet, len);
    sqe = (struct raw_sqe *)(map+RAW_SQ_OFFSET);
    sqe->wr_id = htole64(1);
    sqe->addr = htole64(RAW_VADDR);
    sqe->length = htole32(len);
    sqe->lkey = htole32(RAW_LKEY);
    sqe->flags = sqe->reserved = 0;
    // ioctl executes dma_wmb before publishing the producer to the FPGA.
    if (ioctl(fd, RAW_IOCTL_SUBMIT, &prod)) { perror("submit"); goto out; }
    deadline = now()+2;
    for (;;) {
        if (ioctl(fd, RAW_IOCTL_PROGRESS, &progress)) { perror("progress"); goto out; }
        if (progress.fatal || progress.config_error) {
            fprintf(stderr, "QP error: fatal=%x configuration=%x\n", progress.fatal, progress.config_error);
            goto out;
        }
        uint32_t commit = __atomic_load_n((uint32_t *)(map+RAW_CQ_OFFSET+28), __ATOMIC_ACQUIRE);
        memcpy(&cqe, map+RAW_CQ_OFFSET, sizeof(cqe));
        cqe.commit_sequence = commit;
        // Check payload identity too: FPGA DMA status means issued, and a
        // PCIe posted write can still be travelling to host memory.
        if (progress.cq_prod == 1 && le32toh(cqe.commit_sequence) == 1)
            break;
        if (now() > deadline) { fprintf(stderr, "Completion timeout\n"); goto out; }
        usleep(100);
    }
    if (le64toh(cqe.wr_id) != 1 || le32toh(cqe.status) || le32toh(cqe.length) != len || le32toh(cqe.sq_sequence)) {
        fprintf(stderr, "CQE error: status=%x length=%u sequence=%u\n",
            le32toh(cqe.status), le32toh(cqe.length), le32toh(cqe.sq_sequence));
        goto out;
    }
    if (ioctl(fd, RAW_IOCTL_REAP, &reaped)) { perror("reap"); goto out; }
    printf("Sent %zu-byte Ethernet frame; MAC completion received.\n", len);
    ret = 0;
out:
    if (started && ioctl(fd, RAW_IOCTL_STOP)) { perror("stop/drain"); ret = 1; }
    if (map != MAP_FAILED) munmap(map, RAW_MAP_SIZE);
    if (fd >= 0) close(fd);
    if (frame) fclose(frame);
    return ret;
}
