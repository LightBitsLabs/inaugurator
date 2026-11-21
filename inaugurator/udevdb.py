import os
import traceback

_SYSFS_BLOCK = "/sys/class/block"
_UDEV_DATA = "/run/udev/data"


def markBlockDevicesInitialized(sysfsBlock=_SYSFS_BLOCK, udevData=_UDEV_DATA):
    """lvm asks udev whether a block device is initialized before it reads it, and waits
    10 seconds for each one that is not. No udev daemon runs in the inaugurator, so nothing
    would ever mark them: a machine with hundreds of partitions waits for hours. udev takes
    a device as initialized when its database entry exists, even an empty one.
    A device left unmarked costs lvm those 10 seconds and nothing else, so no failure in
    here reaches the caller: a drive that drops off the bus between the listing and the
    read must not stop the disk setup."""
    try:
        if not os.path.isdir(udevData):
            os.makedirs(udevData)
        names = os.listdir(sysfsBlock)
    except EnvironmentError:
        traceback.print_exc()
        return
    for name in names:
        try:
            _markInitialized(os.path.join(sysfsBlock, name, "dev"), udevData)
        except EnvironmentError:
            traceback.print_exc()


def _markInitialized(deviceNumberPath, udevData):
    if not os.path.exists(deviceNumberPath):
        # A hidden block device, such as one path of a multipath NVMe namespace, has no
        # device number. lvm cannot open it, so it needs no entry.
        return
    with open(deviceNumberPath) as f:
        deviceNumber = f.read().strip()
    open(os.path.join(udevData, "b" + deviceNumber), "a").close()
