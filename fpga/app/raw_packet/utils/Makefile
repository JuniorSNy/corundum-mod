# SPDX-License-Identifier: BSD-2-Clause
CC ?= cc
CFLAGS ?= -O2 -g -Wall -Wextra -Werror
CPPFLAGS += -I../include
all: raw_packet_send
raw_packet_send: raw_packet_send.c ../include/raw_packet.h
	$(CC) $(CPPFLAGS) $(CFLAGS) -o $@ $<
clean:
	$(RM) raw_packet_send
.PHONY: all clean
