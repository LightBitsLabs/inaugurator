import os
import re
import logging
import struct
import traceback
from inaugurator import grubconfparser
from inaugurator import sh

_MLX5_DRIVER_DIRECTORY = "/sys/bus/pci/drivers/mlx5_core"
_PCI_ADDRESS = re.compile(r"^[0-9a-f]{4,}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]$")
_MSR_DEVICES = "/dev/cpu"
_CPUINFO = "/proc/cpuinfo"
_MSR_TEST_CTRL = 0x33
_SPLIT_LOCK_DETECT = 1 << 29


def _unbind(driverDirectory, address):
    with open(os.path.join(driverDirectory, "unbind"), "w") as f:
        f.write(address)


def _unbindMlx5Devices(driverDirectory):
    """In kernel 5.11 the shutdown hook of mlx5_core reads the driver of each of its auxiliary
    devices without checking that there is one, and no RDMA driver is loaded here. An adapter
    whose firmware has no fast teardown takes that path, and kexec dies in a kernel oops.
    Unbinding takes the remove path, which only deletes those devices, and leaves kexec
    or a reboot nothing of mlx5_core to shut down."""
    if not os.path.isdir(driverDirectory):
        return
    for address in os.listdir(driverDirectory):
        if not _PCI_ADDRESS.match(address):
            continue
        try:
            _unbind(driverDirectory, address)
        except EnvironmentError:
            traceback.print_exc()


def _clearMsrBits(device, register, bits):
    "True when a bit was set and is now clear."
    fd = os.open(device, os.O_RDWR)
    try:
        os.lseek(fd, register, os.SEEK_SET)
        value = os.read(fd, 8)
        if len(value) < 8:
            return False
        current = struct.unpack("<Q", value)[0]
        if not current & bits:
            return False
        os.lseek(fd, register, os.SEEK_SET)
        os.write(fd, struct.pack("<Q", current & ~bits))
        return True
    finally:
        os.close(fd)


def _cpusThatDetectSplitLocks(cpuinfo):
    with open(cpuinfo) as f:
        return len([line for line in f if line.startswith("flags") and "split_lock_detect" in line.split()])


def _turnSplitLockDetectionOff(msrDevices, cpuinfo):
    """Where the CPU can, from Ice Lake on, kernel 5.11 makes it raise an exception on a split
    lock, and the setting stays on through kexec. A kernel from before the feature takes
    split locks while it starts: 4.18 of alma8 stops there and prints nothing. The setting is
    one bit of a per-core register, which a CPU without the feature refuses to read."""
    turnedOff = 0
    for cpu in os.listdir(msrDevices) if os.path.isdir(msrDevices) else []:
        try:
            if _clearMsrBits(os.path.join(msrDevices, cpu, "msr"), _MSR_TEST_CTRL, _SPLIT_LOCK_DETECT):
                turnedOff += 1
        except EnvironmentError:
            pass
    logging.info("Split lock detection turned off on %d cpus", turnedOff)
    detecting = _cpusThatDetectSplitLocks(cpuinfo)
    if turnedOff < detecting:
        logging.error(
            "Split lock detection stays on on %d of %d cpus: a kernel from before the feature, "
            "like 4.18, can hang after kexec with nothing on its console", detecting - turnedOff, detecting)


def reboot(mlx5DriverDirectory=_MLX5_DRIVER_DIRECTORY):
    "reboot -f shuts the devices down the way kexec does, so it meets the same mlx5 hook."
    _unbindMlx5Devices(mlx5DriverDirectory)
    return sh.run("reboot -f")


def _restartWithoutShutdown():
    """A kexec that failed in the middle of the device shutdown leaves kernel locks held, so
    an orderly reboot can hang on them. This restart skips the shutdown; the disks were
    synced before kexec."""
    with open("/proc/sys/kernel/sysrq", "w") as f:
        f.write("1")
    with open("/proc/sysrq-trigger", "w") as f:
        f.write("b")


class LoadKernel:
    def fromBootPartitionGrubConfig(self, grubConfig, bootPath, rootPartition):
        parser = grubconfparser.GrubConfParser(grubConfig)
        sh.run("kexec --load %s --initrd=%s --append='root=%s %s'" % (
            os.path.join(bootPath, parser.defaultKernelImage()),
            os.path.join(bootPath, parser.defaultInitrd()),
            rootPartition,
            self._filterOutRootArgument(parser.defaultKernelCommandLine())))

    def execute(self, mlx5DriverDirectory=_MLX5_DRIVER_DIRECTORY, msrDevices=_MSR_DEVICES, cpuinfo=_CPUINFO):
        """Returns only when kexec failed. The installed system boots from the disk all the
        same, so the machine is restarted, not left where nothing can reach it."""
        _unbindMlx5Devices(mlx5DriverDirectory)
        _turnSplitLockDetectionOff(msrDevices, cpuinfo)
        try:
            sh.run("kexec -e")
        except Exception:
            traceback.print_exc()
            logging.error("kexec failed, restarting to boot the installed system from the disk")
            _restartWithoutShutdown()

    def _filterOutRootArgument(self, commandLine):
        parts = commandLine.split(' ')
        filtered = [p for p in parts if not p.startswith("root=")]
        result = " ".join(filtered)
        logging.info("Adding the following kernel arguments from the GRUB2 Configuration: '%s'." % (result))
        return result
