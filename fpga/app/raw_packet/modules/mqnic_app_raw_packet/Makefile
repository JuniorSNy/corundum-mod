# SPDX-License-Identifier: BSD-2-Clause
ifneq ($(KERNELRELEASE),)
ccflags-y += -I$(CORUNDUM_ROOT)/modules/mqnic -I$(src)/../../include
obj-m += mqnic_app_raw_packet.o
mqnic_app_raw_packet-y := main.o
else
CORUNDUM_ROOT ?= $(abspath ../../../../..)
KDIR ?= /lib/modules/$(shell uname -r)/build
all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) CORUNDUM_ROOT=$(CORUNDUM_ROOT) modules
clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
endif
