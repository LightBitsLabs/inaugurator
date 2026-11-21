import os
import re
import logging
import traceback
from inaugurator import grubconfparser
from inaugurator import sh

_MLX5_DRIVER_DIRECTORY = "/sys/bus/pci/drivers/mlx5_core"
_PCI_ADDRESS = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]$")


def _unbind(driverDirectory, address):
    with open(os.path.join(driverDirectory, "unbind"), "w") as f:
        f.write(address)


def _unbindMlx5Devices(driverDirectory):
    """In kernel 5.11 the shutdown hook of mlx5_core reads the driver of each of its auxiliary
    devices without checking that there is one, and no RDMA driver is loaded here. An adapter
    whose firmware has no fast teardown takes that path, and kexec dies in a kernel oops.
    Unbinding takes the remove path, which only deletes those devices, and leaves kexec
    nothing of mlx5_core to shut down."""
    if not os.path.isdir(driverDirectory):
        return
    for address in os.listdir(driverDirectory):
        if not _PCI_ADDRESS.match(address):
            continue
        try:
            _unbind(driverDirectory, address)
        except EnvironmentError:
            traceback.print_exc()


class LoadKernel:
    def fromBootPartitionGrubConfig(self, grubConfig, bootPath, rootPartition):
        parser = grubconfparser.GrubConfParser(grubConfig)
        sh.run("kexec --load %s --initrd=%s --append='root=%s %s'" % (
            os.path.join(bootPath, parser.defaultKernelImage()),
            os.path.join(bootPath, parser.defaultInitrd()),
            rootPartition,
            self._filterOutRootArgument(parser.defaultKernelCommandLine())))

    def execute(self, mlx5DriverDirectory=_MLX5_DRIVER_DIRECTORY):
        _unbindMlx5Devices(mlx5DriverDirectory)
        sh.run("kexec -e")

    def _filterOutRootArgument(self, commandLine):
        parts = commandLine.split(' ')
        filtered = [p for p in parts if not p.startswith("root=")]
        result = " ".join(filtered)
        logging.info("Adding the following kernel arguments from the GRUB2 Configuration: '%s'." % (result))
        return result
