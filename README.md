The Inaugurator image is built inside a Fedora 28 container
(`docker/build-inaugurator.dockerfile`). Its kernel, kernel modules and firmware
come from a later Fedora release, pinned by `KERNEL_VERSION` in that dockerfile:
Fedora 28's own kernel has no driver for NICs newer than 2019.

To build:

    dockerize make -f Makefile.lb all

The build ends with two checks of what it made: every NIC and storage controller
listed for the lab has a loadable driver in the initrd, and the kernel and the
initrd together fit the PXE loader.

To test, inside the build container (`make docker-shell`):

    make unittest       # unit tests
    make check_image    # builds the image there and runs the same two checks

When the lab gets a NIC model the image has to drive, add its PCI ID to
`LAB_PCI_DEVICES` in `inaugurator/tests/image_check.py`. If `check_image` then
fails, either `Makefile.build` does not copy the driver into the thin image or
the pinned kernel is too old for it.
