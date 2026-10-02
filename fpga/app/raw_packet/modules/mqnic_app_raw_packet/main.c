// SPDX-License-Identifier: BSD-2-Clause
// Trusted single-client experimental raw TX interface.  SQ and payload are
// coherent DMA memory; userspace chooses SQEs, never device physical addresses.
#include <linux/module.h>
#include <linux/auxiliary_bus.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/mm.h>
#include <linux/dma-mapping.h>
#include <linux/uaccess.h>
#include <linux/iopoll.h>
#include <linux/kref.h>
#include <linux/mutex.h>
#include "mqnic.h"
#include "raw_packet.h"

struct raw_app {
    struct miscdevice misc;
    struct device *dma_dev;
    void __iomem *regs;
    void *mem;
    dma_addr_t dma;
    struct mutex lock;
    struct kref ref;
    bool opened, dead, unsafe;
    u32 submitted, reaped;
};

static void raw_free(struct kref *ref)
{
    struct raw_app *a = container_of(ref, struct raw_app, ref);
    // A failed drain cannot prove that PCIe has stopped using this allocation.
    // Quarantine rather than free it; recovery requires a device reset/reboot.
    if (!a->unsafe)
        dma_free_coherent(a->dma_dev, RAW_MAP_SIZE, a->mem, a->dma);
    else
        dev_err(a->dma_dev, "raw TX drain failed; DMA allocation quarantined\n");
    put_device(a->dma_dev);
    kfree(a->misc.name);
    kfree(a);
}

static int raw_stop(struct raw_app *a)
{
    u32 status;
    int ret;
    iowrite32(0, a->regs+RAW_REG_ENABLE);
    ret = readl_poll_timeout(a->regs+RAW_REG_STATUS, status, !(status & 1), 10, 100000);
    if (ret)
        a->unsafe = true;
    return ret;
}

static void raw_write64(struct raw_app *a, unsigned int reg, u64 val)
{
    iowrite32(lower_32_bits(val), a->regs+reg);
    iowrite32(upper_32_bits(val), a->regs+reg+4);
}

static int raw_start(struct raw_app *a)
{
    if (a->unsafe)
        return -EIO;
    if (ioread32(a->regs+RAW_REG_ENABLE) || (ioread32(a->regs+RAW_REG_STATUS) & 1))
        return -EBUSY;
    memset(a->mem, 0, RAW_MAP_SIZE);
    // SQ consumer/published CQ counters are reset only after a completed drain.
    iowrite32(1, a->regs+RAW_REG_QUEUE_RESET);
    iowrite32(0, a->regs+RAW_REG_CONFIG_ERROR);
    raw_write64(a, RAW_REG_SQ_BASE_L, a->dma+RAW_SQ_OFFSET);
    raw_write64(a, RAW_REG_CQ_BASE_L, a->dma+RAW_CQ_OFFSET);
    iowrite32(RAW_RING_LOG, a->regs+RAW_REG_RING_LOG);
    iowrite32(RAW_PD, a->regs+RAW_REG_PD);
    iowrite32(RAW_LKEY & 15, a->regs+RAW_REG_MR_INDEX);
    iowrite32(RAW_LKEY, a->regs+RAW_REG_MR_KEY);
    iowrite32(RAW_PD, a->regs+RAW_REG_MR_PD);
    iowrite32(RAW_MR_ENABLE | RAW_MR_LOCAL_READ, a->regs+RAW_REG_MR_FLAGS);
    raw_write64(a, RAW_REG_MR_VA_L, RAW_VADDR);
    raw_write64(a, RAW_REG_MR_DMA_L, a->dma+RAW_DATA_OFFSET);
    raw_write64(a, RAW_REG_MR_LENGTH_L, RAW_MAP_SIZE-RAW_DATA_OFFSET);
    iowrite32(1, a->regs+RAW_REG_MR_COMMIT);
    dma_wmb();
    iowrite32(1, a->regs+RAW_REG_ENABLE);
    a->submitted = a->reaped = 0;
    return ioread32(a->regs+RAW_REG_CONFIG_ERROR) ? -EIO : 0;
}

static int raw_open(struct inode *inode, struct file *file)
{
    struct raw_app *a = container_of(file->private_data, struct raw_app, misc);
    int ret = 0;
    mutex_lock(&a->lock);
    if (a->dead || a->unsafe)
        ret = -ENODEV;
    else if (a->opened)
        ret = -EBUSY;
    else {
        a->opened = true;
        kref_get(&a->ref);
        file->private_data = a;
    }
    mutex_unlock(&a->lock);
    return ret;
}

static int raw_release(struct inode *inode, struct file *file)
{
    struct raw_app *a = file->private_data;
    mutex_lock(&a->lock);
    if (!a->dead)
        raw_stop(a);
    a->opened = false;
    mutex_unlock(&a->lock);
    kref_put(&a->ref, raw_free);
    return 0;
}

static int raw_mmap(struct file *file, struct vm_area_struct *vma)
{
    struct raw_app *a = file->private_data;
    int ret;
    mutex_lock(&a->lock);
    if (a->dead)
        ret = -ENODEV;
    else if (vma->vm_pgoff || vma->vm_end-vma->vm_start != RAW_MAP_SIZE)
        ret = -EINVAL;
    else
        // vm_file keeps this open file and its DMA allocation alive until all
        // mappings (including forked mappings) close.  Do not use devm memory.
        ret = dma_mmap_coherent(a->dma_dev, vma, a->mem, a->dma, RAW_MAP_SIZE);
    mutex_unlock(&a->lock);
    return ret;
}

static long raw_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
    struct raw_app *a = file->private_data;
    struct raw_progress p;
    u32 value, cons, prod;
    int ret = 0;
    mutex_lock(&a->lock);
    if (a->dead) {
        ret = -ENODEV;
        goto out;
    }
    switch (cmd) {
    case RAW_IOCTL_START:
        ret = raw_start(a);
        break;
    case RAW_IOCTL_STOP:
        ret = raw_stop(a);
        break;
    case RAW_IOCTL_PROGRESS:
        p.sq_cons = ioread32(a->regs+RAW_REG_SQ_CONS);
        p.cq_prod = ioread32(a->regs+RAW_REG_CQ_PROD);
        p.fatal = ioread32(a->regs+RAW_REG_FATAL);
        p.config_error = ioread32(a->regs+RAW_REG_CONFIG_ERROR);
        dma_rmb();
        if (copy_to_user((void __user *)arg, &p, sizeof(p)))
            ret = -EFAULT;
        break;
    case RAW_IOCTL_SUBMIT:
    case RAW_IOCTL_REAP:
        if (copy_from_user(&value, (void __user *)arg, sizeof(value))) {
            ret = -EFAULT;
            break;
        }
        if (cmd == RAW_IOCTL_SUBMIT) {
            cons = ioread32(a->regs+RAW_REG_SQ_CONS);
            if (!ioread32(a->regs+RAW_REG_ENABLE) || a->unsafe ||
                value-a->submitted > RAW_RING_SIZE || value-cons > RAW_RING_SIZE) {
                ret = -EINVAL;
                break;
            }
            dma_wmb();
            iowrite32(value, a->regs+RAW_REG_SQ_PROD);
            a->submitted = value;
        } else {
            prod = ioread32(a->regs+RAW_REG_CQ_PROD);
            if (value-a->reaped > prod-a->reaped) {
                ret = -EINVAL;
                break;
            }
            dma_mb();
            iowrite32(value, a->regs+RAW_REG_CQ_CONS);
            a->reaped = value;
        }
        // Flush posted MMIO doorbell before returning to the producer.
        if (ioread32(a->regs+RAW_REG_CONFIG_ERROR))
            ret = -EIO;
        break;
    default:
        ret = -ENOTTY;
    }
out:
    mutex_unlock(&a->lock);
    return ret;
}

static const struct file_operations raw_fops = {
    .owner = THIS_MODULE, .open = raw_open, .release = raw_release,
    .mmap = raw_mmap, .unlocked_ioctl = raw_ioctl,
    .compat_ioctl = compat_ptr_ioctl,
};

static int raw_probe(struct auxiliary_device *adev, const struct auxiliary_device_id *id)
{
    struct mqnic_dev *mdev = container_of(adev, struct mqnic_adev, adev)->mdev;
    struct raw_app *a;
    int ret;
    if (!mdev->app_hw_addr || mdev->app_hw_regs_size < RAW_REG_MR_COMMIT+4 ||
        ioread32(mdev->app_hw_addr) != RAW_RB_TYPE ||
        ioread32(mdev->app_hw_addr+4) != RAW_RB_VERSION)
        return -ENODEV;
    a = kzalloc(sizeof(*a), GFP_KERNEL);
    if (!a)
        return -ENOMEM;
    a->dma_dev = get_device(mdev->dev);
    a->regs = mdev->app_hw_addr;
    mutex_init(&a->lock);
    kref_init(&a->ref);
    a->mem = dma_alloc_coherent(a->dma_dev, RAW_MAP_SIZE, &a->dma, GFP_KERNEL);
    if (!a->mem) {
        put_device(a->dma_dev);
        kfree(a);
        return -ENOMEM;
    }
    // Never overwrite an active queue left by another driver/session.
    ret = raw_stop(a);
    if (ret)
        goto fail;
    a->misc.minor = MISC_DYNAMIC_MINOR;
    a->misc.name = kasprintf(GFP_KERNEL, "mqnic-raw-%s", dev_name(mdev->dev));
    if (!a->misc.name) {
        ret = -ENOMEM;
        goto fail;
    }
    a->misc.fops = &raw_fops;
    a->misc.parent = &adev->dev;
    a->misc.mode = 0600;
    ret = misc_register(&a->misc);
    if (ret)
        goto fail;
    dev_set_drvdata(&adev->dev, a);
    return 0;
fail:
    kref_put(&a->ref, raw_free);
    return ret;
}

static void raw_remove(struct auxiliary_device *adev)
{
    struct raw_app *a = dev_get_drvdata(&adev->dev);
    misc_deregister(&a->misc);
    mutex_lock(&a->lock);
    raw_stop(a);
    a->dead = true;
    mutex_unlock(&a->lock);
    kref_put(&a->ref, raw_free);
}

static const struct auxiliary_device_id raw_ids[] = {
    { .name = "mqnic.app_12348010" }, {},
};
MODULE_DEVICE_TABLE(auxiliary, raw_ids);
static struct auxiliary_driver raw_driver = {
    .name = "mqnic_app_raw_packet", .probe = raw_probe, .remove = raw_remove,
    .id_table = raw_ids,
};
module_auxiliary_driver(raw_driver);
MODULE_LICENSE("Dual BSD/GPL");
MODULE_DESCRIPTION("Corundum single-QP raw Ethernet TX application");
