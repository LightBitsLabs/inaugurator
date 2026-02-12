import os


def createFSTab(rootPath, root, boot, swap, esp=None):
    filename = os.path.join(rootPath, "etc", "fstab")
    with open(filename, "w") as f:
        if esp is not None:
            f.write(_UEFI_TEMPLATE % dict(root=root, boot=boot, swap=swap, esp=esp))
        else:
            f.write(_TEMPLATE % dict(root=root, boot=boot, swap=swap))


_TEMPLATE = """
LABEL=ROOT /                       ext4    defaults        1 1
LABEL=SWAP swap                    swap    defaults        0 0
LABEL=BOOT /boot                   ext4    defaults        1 2
"""

_UEFI_TEMPLATE = """
LABEL=ROOT /                       ext4    defaults        1 1
LABEL=SWAP swap                    swap    defaults        0 0
LABEL=BOOT /boot                   ext4    defaults        1 2
LABEL=ESP  /boot/efi               vfat    umask=0077      0 2
"""
