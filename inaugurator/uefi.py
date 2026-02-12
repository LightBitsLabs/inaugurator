import os
import logging


_EFI_FIRMWARE_PATH = "/sys/firmware/efi"


def isUEFIBoot():
    """Detect whether the system was booted in UEFI mode.

    UEFI firmware exposes a sysfs directory at /sys/firmware/efi. If this
    directory exists the machine was booted in UEFI mode; otherwise it was
    booted in legacy BIOS mode.
    """
    isUEFI = os.path.isdir(_EFI_FIRMWARE_PATH)
    if isUEFI:
        logging.info("UEFI boot detected (%(path)s exists)", dict(path=_EFI_FIRMWARE_PATH))
    else:
        logging.info("Legacy BIOS boot detected (%(path)s does not exist)", dict(path=_EFI_FIRMWARE_PATH))
    return isUEFI
