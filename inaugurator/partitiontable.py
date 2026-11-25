import re
import stat
import traceback
import time
import os
from inaugurator import sh
from inaugurator import udevdb


# Each command here takes seconds on a healthy disk, so one still running after five minutes is
# taken for stuck, and killing it turns a hang into a failure. A slow disk can reach the limit
# too, so a timeout never leads to anything that erases the disk: the handlers below that read
# a failed command as "the layout does not match" let it through, and it does not start the
# rebuild.
_COMMAND_TIMEOUT_SECONDS = 5 * 60
# mkfs.ext4 discards the whole device before it writes, and on a large or a slow device that
# alone can take longer than the limit above.
_MKFS_TIMEOUT_SECONDS = 30 * 60
_SYSFS_BLOCK_DEVICES = "/sys/class/block"


def _run(command, timeout=_COMMAND_TIMEOUT_SECONDS):
    return sh.run(command, timeout=timeout)


def _mkfs(arguments):
    return _run("mkfs.ext4 %s" % arguments, timeout=_MKFS_TIMEOUT_SECONDS)


def _disk(device, sysfs=_SYSFS_BLOCK_DEVICES):
    """The kernel name of the disk that a disk or a partition is on, and the identity the disk
    reports, or None when it reports none. A disk that is reachable through two paths is two
    disks to the kernel, with one identity."""
    node = os.path.realpath(os.path.join(sysfs, os.path.basename(device)))
    if os.path.exists(os.path.join(node, "partition")):
        node = os.path.dirname(node)
    for attribute in ("device/wwid", "wwid"):
        try:
            with open(os.path.join(node, attribute)) as f:
                identity = f.read().strip()
        except EnvironmentError:
            continue
        if identity:
            return os.path.basename(node), identity
    return os.path.basename(node), None


def _isBlockDevice(path):
    try:
        return stat.S_ISBLK(os.stat(path).st_mode)
    except OSError:
        return False


def _lvm(arguments):
    """Any lvm command can scan every block device, and each scan can hit the udev wait
    that udevdb describes, so the devices are marked before every one of them."""
    udevdb.markBlockDevicesInitialized()
    return _run("lvm %s" % arguments)


class PartitionTable:
    _DEFAULT_SIZES_GB = dict(
        smallSwap=1,
        bigSwap=8,
        smallOsmosisCache=5,
        bigOsmosisCache=30,
        minimumRoot=7,
        createRoot=10)
    VOLUME_GROUP = "inaugurator-v2"
    LAYOUT_SCHEMES = dict(GPT=dict(partitions=dict(bios_boot=dict(sizeMB=2, set_flags="bios_grub", flags="bios_grub"),
                                                   boot=dict(sizeMB=1024, fs="ext4", flags="boot, esp", set_flags="boot"),
                                                   lvm=dict(set_flags="lvm", flags="lvm", sizeMB="fillUp")),
                                   order=("bios_boot", "boot", "lvm")),
                          MBR=dict(partitions=dict(boot=dict(sizeMB=1024, fs="ext4", set_flags="boot", flags="boot"),
                                                   lvm=dict(set_flags="lvm", flags="lvm", sizeMB="fillUp")),
                                   order=("boot", "lvm")))

    def __init__(self, device, sizesGB=dict(), layoutScheme="GPT", hypervisor=False):
        self._sizesGB = dict(self._DEFAULT_SIZES_GB)
        self._sizesGB.update(sizesGB)
        self._hypervisor = hypervisor
        if hypervisor:
            self._set_hyperviosr()
        self._device = device
        self._cachedDiskSize = None
        self._created = False
        if layoutScheme not in self.LAYOUT_SCHEMES:
            print "Invalid layout scheme. Possible values: '%s'" % "', '".join(self.LAYOUT_SCHEMES.keys())
            raise ValueError(layoutScheme)
        self._layoutScheme = layoutScheme
        self._physicalPartitions = self.LAYOUT_SCHEMES[layoutScheme]["partitions"]
        self._physicalPartitionsOrder = self.LAYOUT_SCHEMES[layoutScheme]["order"]

    def _set_hyperviosr(self):
        PartitionTable.VOLUME_GROUP = "hypervisor"
        self._sizesGB['smallSwap'] = 1
        self._sizesGB['bigSwap'] = 1
        self._sizesGB['smallOsmosisCache'] = 1
        self._sizesGB['bigOsmosisCache'] = 1

    def created(self):
        return self._created

    def clear(self, device=None, count=512):
        if device is None:
            device = self._device
        _run("busybox dd if=/dev/zero of=%(device)s bs=1M count=%(count)s" %
             dict(device=device, count=count))

    def prepare(self, clearFirst=False, rebuildOnFailure=True):
        """Leaves the disk with a verified layout. A layout that fails to set up is rebuilt
        from nothing, once. The rebuild costs the disk its contents, so it starts only when
        the disk itself is at fault. The copies of its volume group are wiped from the other
        disks before the disk is looked at: lvm does not activate a volume group that it
        finds twice, which would pass for a fault of this disk. A timeout is raised as it is,
        because a slow disk reaches it too. rebuildOnFailure is False for a disk that holds
        what is about to be installed."""
        self._wipeOtherPartitionsWithSameVolumeGroup(volumeGroupExpected=False)
        try:
            if clearFirst:
                self.clear()
            self._setUpLayout()
        except sh.TimeoutExpired:
            raise
        except Exception:
            if not rebuildOnFailure:
                raise
            traceback.print_exc()
            self._rebuild(clearFirst)
        self._wipeCopiesOnOtherDevices()

    def _rebuild(self, clearFirst):
        print "Disk setup failed, deleting the partitions of %s and setting it up again" % self._device
        self._deletePartitions()
        if clearFirst:
            # _deletePartitions is best effort: without a clear that succeeded, the layout
            # the caller asked to erase could survive and be accepted as it is
            self.clear()
        self._setUpLayout()

    def _deletePartitions(self):
        """Empties the partition table, so that the next setup rebuilds the whole layout.
        Each step is best effort: a disk that failed half way through its setup can lack the
        volume group, the partitions or the partition table itself. A timeout ends it: the
        next step would wait as long on the same disk."""
        for step in (self._deactivateVolumeGroup, self._removeVolumeGroupLinks, self._wipePartitionHeaders,
                     self._deletePartitionTable):
            try:
                step()
            except sh.TimeoutExpired:
                raise
            except Exception:
                traceback.print_exc()
                print "%s failed" % step.__name__
        _run("busybox mdev -s")

    def _deactivateVolumeGroup(self):
        # active volumes keep the lvm partition busy, and a busy partition cannot be deleted
        _lvm("vgchange --activate n %s" % self.VOLUME_GROUP)

    def _removeVolumeGroupLinks(self):
        # with no udev the links of the deactivated volumes stay, and vgcreate refuses a
        # name that has a directory in /dev
        _run("busybox rm -fr /dev/%s" % self.VOLUME_GROUP)

    def _wipePartitionHeaders(self):
        # a partition created again at the same offset would bring the old LVM label or filesystem back
        _run("busybox mdev -s")
        for partition in self.parsePartitionTable():
            # dd creates a regular file where the node is missing, and mdev then keeps that
            # file in place of the node: the next mkfs would format a file in memory
            if _isBlockDevice(partition["device"]):
                self.clear(device=partition["device"], count=1)

    def _deletePartitionTable(self):
        _run("sfdisk --delete %s" % self._device)

    def _create(self):
        self.clear()
        script = self._getPartitionCommand()
        print "creating new partition table of layout '%s': \n%s\n" % (self._layoutScheme, script)
        _run(script)
        self._setFlags()
        _run("busybox mdev -s")
        _mkfs("%s -L BOOT" % self._getPartitionPath("boot"))
        try:
            _lvm("vgremove -f %s" % (self.VOLUME_GROUP, ))
        except sh.TimeoutExpired:
            raise
        except:
            traceback.print_exc()
            print "'lvm vgremove' failed"
        lvmPartitionPath = self._getPartitionPath("lvm")
        _lvm("pvcreate -y -ff %s" % (lvmPartitionPath,))
        _lvm("vgcreate -y %s %s" % (self.VOLUME_GROUP, lvmPartitionPath))
        if self._diskSizeMB() / 1024 >= self._sizesGB['createRoot'] + self._sizesGB['bigSwap'] + \
                self._sizesGB["bigOsmosisCache"]:
            swapSizeGB = 8
        else:
            swapSizeGB = 1
        _lvm("lvcreate --zero n --name swap --size %dG %s" % (swapSizeGB, self.VOLUME_GROUP))
        if self._diskSizeMB() / 1024 > self._sizesGB['createRoot'] + swapSizeGB + \
                self._sizesGB["bigOsmosisCache"]:
            osmosisCacheSizeGB = self._sizesGB["bigOsmosisCache"]
        else:
            osmosisCacheSizeGB = self._sizesGB["smallOsmosisCache"]
        _lvm("lvcreate --zero n --name osmosis-cache --size %dG %s" %
             (osmosisCacheSizeGB, self.VOLUME_GROUP))

        rootSize = "--extents 80%FREE"
        if self._hypervisor:
            rootSize = "--extents 100%FREE"

        _lvm("lvcreate --zero n --name root %s %s" % (rootSize, self.VOLUME_GROUP))
        _lvm("vgscan --mknodes")
        self._waitForFileToShowUp("/dev/%s/swap" % self.VOLUME_GROUP)
        _run("mkswap /dev/%s/swap -L SWAP" % self.VOLUME_GROUP)
        self._waitForFileToShowUp("/dev/%s/root" % self.VOLUME_GROUP)
        _mkfs("/dev/%s/root -L ROOT" % self.VOLUME_GROUP)
        self._waitForFileToShowUp("/dev/%s/osmosis-cache" % self.VOLUME_GROUP)
        _mkfs("/dev/%s/osmosis-cache" % self.VOLUME_GROUP)
        self._created = True

    def _getPartitionCommand(self):
        if self._layoutScheme == "MBR":
            bootSize = self._physicalPartitions["boot"]["sizeMB"]
            script = "echo -ne '8,%s,83\\n,,8e\\n' | sfdisk --unit M %s --in-order --force" % (
                bootSize, self._device)
        elif self._layoutScheme == "GPT":
            biosBootStart = 1
            biosBootEnd = biosBootStart + self._physicalPartitions["bios_boot"]["sizeMB"]
            bootStart = biosBootEnd
            bootEnd = bootStart + self._physicalPartitions["boot"]["sizeMB"]
            script = "parted -s %(device)s -- " \
                     "mklabel gpt mkpart primary ext4 %(biosBootStart)sMiB %(biosBootEnd)sMiB " \
                     "mkpart primary ext4 %(bootStart)sMiB %(bootEnd)sMiB " \
                     "mkpart primary ext4 %(lvmStart)sMiB -1" % \
                dict(device=self._device,
                     biosBootStart=biosBootStart,
                     biosBootEnd=biosBootEnd,
                     bootStart=bootStart,
                     bootEnd=bootEnd,
                     lvmStart=bootEnd)
        return script

    def _setFlags(self):
        for partitionIdx, partition in enumerate(self._physicalPartitionsOrder):
            partitionNr = partitionIdx + 1
            flag = self._physicalPartitions[partition]["set_flags"]
            print "Setting flag '%s' for partition #%d..." % (flag, partitionNr)
            _run("parted -s %s set %d %s on" % (self._device, partitionNr, flag))

    def parsePartitionTable(self):
        cmd = "parted -s -m %(device)s unit MB print" % dict(device=self._device)
        output = _run(cmd)
        print "Output of parted: %(output)s" % dict(output=output)
        lines = [line.strip() for line in output.split(";")]
        lines = [line for line in lines if line]
        partitionsLines = lines[2:]
        partitions = [dict(zip(("nr", "start", "end", "size", "fs", "name", "flags"),
                      partitionLine.split(":"))) for partitionLine in partitionsLines]
        return [dict(device="%(device)s%(nr)s" % dict(device=self._device, nr=partition["nr"]),
                     sizeMB=float(partition["size"].rstrip("MB")),
                     fs=partition["fs"],
                     flags=partition["flags"])
                for partition in partitions]

    @classmethod
    def _fieldsOfLastTableRow(self, output):
        return re.split(r"\s+", output.strip().split("\n")[-1].strip())

    @classmethod
    def parseLVMPhysicalVolume(cls, partition):
        _lvm("pvscan --cache %s" % partition)
        fields = cls._fieldsOfLastTableRow(_lvm("pvdisplay --units m --columns %s" % partition))
        assert fields[0] == partition, "Invalid columns output from pvdisplay: %s" % fields
        assert fields[4].endswith("m")
        return dict(name=fields[1], sizeMB=int(re.match(r"\d+", fields[4]).group(0)))

    @classmethod
    def parseLVMLogicalVolume(cls, label):
        fields = cls._fieldsOfLastTableRow(_lvm("lvdisplay --units m --columns /dev/%s/%s" % (
            cls.VOLUME_GROUP, label)))
        assert fields[0] == label, "Invalid columns output from lvdisplay: %s" % fields
        assert fields[3].endswith("m")
        return dict(volumeGroup=fields[1], sizeMB=int(re.match(r"\d+", fields[3]).group(0)))

    def _diskSizeMB(self):
        if self._cachedDiskSize is None:
            with open(os.path.join("/sys/block/", self._device.split("/dev/")[1], "size"), "r") as f:
                contents = f.read()
            contents = contents.strip()
            nrBlocks = int(contents)
            BLOCK_SIZE = 512
            NR_BYTES_IN_MB = 1024 ** 2
            sizeMB = nrBlocks * BLOCK_SIZE / NR_BYTES_IN_MB
            self._cachedDiskSize = sizeMB
        return self._cachedDiskSize

    def _findMismatchInPartitionTable(self):
        try:
            parsed = self.parsePartitionTable()
        except sh.TimeoutExpired:
            raise
        except:
            print "Unable to parse partition table"
            traceback.print_exc()
            return "Unable to parse partition table"
        if len(parsed) != len(self._physicalPartitions):
            return "Partition count is not %(nrPartitions)s" % \
                dict(nrPartitions=len(self._physicalPartitions))
        for partitionPurpose, actualPartition in zip(self._physicalPartitionsOrder, parsed):
            expectedPartition = self._physicalPartitions[partitionPurpose]
            for attrName in ("fs", "flags"):
                if attrName not in expectedPartition:
                    continue
                actual = actualPartition[attrName]
                expected = expectedPartition[attrName]
                if expected != actual:
                    return "Expected attribute %(attrName)s of %(partitionPurpose)s partition to be " \
                           "'%(expected)s', not '%(actual)s'" % \
                           dict(attrName=attrName,
                                partitionPurpose=partitionPurpose,
                                expected=expected,
                                actual=actual)

            expectedSize = expectedPartition["sizeMB"]
            if expectedPartition["sizeMB"] == "fillUp":
                sizeOfOthers = self._combinedSizeOfAllOtherPartitions(partitionPurpose)
                expectedSize = self._diskSizeMB() - sizeOfOthers
            if not self._approximatelyEquals(expectedSize, actualPartition["sizeMB"]):
                return "Expected partition %(partitionPurpose)s to be approximately %(expectedSize)sMB" % \
                    dict(partitionPurpose=partitionPurpose, expectedSize=expectedSize)
        return None

    def _combinedSizeOfAllOtherPartitions(self, partitionPurpose):
        return sum([attrs["sizeMB"] for purpose, attrs in
                    self._physicalPartitions.iteritems() if purpose != partitionPurpose])

    def _findMismatchInLVM(self):
        lvmPartitionPath = self._getPartitionPath("lvm")
        try:
            physical = self.parseLVMPhysicalVolume(lvmPartitionPath)
        except sh.TimeoutExpired:
            raise
        except:
            print "Unable to parse physical volume"
            traceback.print_exc()
            return "Unable to parse physical volume"
        if physical['name'] != self.VOLUME_GROUP:
            return "Physical volume name is '%s', and not '%s'" % (physical['name'], self.VOLUME_GROUP)
        if physical['sizeMB'] * 1.1 < self._combinedSizeOfAllOtherPartitions("lvm"):
            return "Physical volume does not fill up most of the disk: %s < %s" % (
                physical['sizeMB'], self._diskSizeMB())

        try:
            swap = self.parseLVMLogicalVolume("swap")
            root = self.parseLVMLogicalVolume("root")
            osmosis = self.parseLVMLogicalVolume("osmosis-cache")
        except sh.TimeoutExpired:
            raise
        except:
            print "Unable to parse logical volume/s"
            traceback.print_exc()
            return "Unable to parse physical volume/s"
        if root['sizeMB'] <= self._sizesGB['minimumRoot'] * 1024 * 0.9:
            return "Root partition is too small"
        if self._diskSizeMB() / 1024 >= self._sizesGB['createRoot'] + self._sizesGB['bigSwap'] + \
                self._sizesGB["bigOsmosisCache"]:
            minimumSwapSizeGB = self._sizesGB['bigSwap']
        else:
            minimumSwapSizeGB = self._sizesGB['smallSwap']
        if swap['sizeMB'] <= minimumSwapSizeGB * 1024 * 0.9:
            return "Swap partition is too small"
        if self._diskSizeMB() / 1024 >= self._sizesGB['createRoot'] + minimumSwapSizeGB + \
                self._sizesGB["bigOsmosisCache"]:
            minimumOsmosisCacheSizeGB = self._sizesGB['bigOsmosisCache']
        else:
            minimumOsmosisCacheSizeGB = self._sizesGB['smallOsmosisCache']
        if osmosis['sizeMB'] <= minimumOsmosisCacheSizeGB * 1024 * 0.9:
            return "Osmosis cache partition is too small (%(sizeMB)sG)" % dict(sizeMB=osmosis["sizeMB"])

        return None

    def _findMismatch(self):
        mismatch = self._findMismatchInPartitionTable()
        if mismatch is not None:
            return mismatch
        return self._findMismatchInLVM()

    def _approximatelyEquals(self, first, second):
        return first > second * 0.9 and first < second * 1.1

    _DUPLICATE_PHYSICAL_VOLUME = re.compile(r"PV \S+ on (\S+) was already found on (\S+?)\.?$")

    def _copiesOfThePhysicalVolume(self, pvscanOutput):
        """lvm lists a physical volume that it finds on two devices once, under the device it
        prefers, and names the two in a warning."""
        target = self._getPartitionPath("lvm")
        copies = set()
        for line in pvscanOutput.splitlines():
            found = self._DUPLICATE_PHYSICAL_VOLUME.search(line.strip())
            if found is not None and target in found.groups():
                copies.update(found.groups())
        copies.discard(target)
        return copies

    def _parseVGs(self, pvscanOutput=None):
        if pvscanOutput is None:
            pvscanOutput = _lvm("pvscan")
        print "`pvscan` output:\n %(pvscanOutput)s" % dict(pvscanOutput=pvscanOutput)
        vgs = dict()
        if "No matching physical volumes found" in pvscanOutput:
            return vgs
        pvscanOutput = [line.strip() for line in pvscanOutput.splitlines()]
        pvscanOutput = [line for line in pvscanOutput if not line.startswith("Total:")]
        for line in pvscanOutput:
            parts = line.split(" ")
            parts = [part for part in parts if part]
            if len(parts) > 4 and parts[0] == "PV" and parts[2] == "VG":
                device = parts[1]
                name = parts[3]
                assert device not in vgs
                vgs[device] = name
        return vgs

    def _refuseAnotherPathToTheTarget(self, device):
        """A copy on a disk with the identity of the target, under another kernel name, is the
        target itself seen through a second path, and wiping it would wipe the target."""
        targetName, targetIdentity = _disk(self._device)
        name, identity = _disk(device)
        if name != targetName and identity is not None and identity == targetIdentity:
            raise Exception(
                "%s is another path to the target disk %s (both report '%s'): it is not wiped, "
                "and a disk with two paths cannot be set up here" % (device, self._device, identity))

    def _wipeOtherPartitionsWithSameVolumeGroup(self, volumeGroupExpected=True):
        "Returns True when it wiped a copy."
        print "Validating that volume group %(vg)s is bound only to one device..." % \
              dict(vg=self.VOLUME_GROUP)
        pvscanOutput = _lvm("pvscan")
        vgs = self._parseVGs(pvscanOutput)
        if not vgs and volumeGroupExpected:
            raise Exception("No volume group was found after configuration of LVM.")
        targetPhysicalVolumeForVolumeGroup = self._getPartitionPath("lvm")
        copies = self._copiesOfThePhysicalVolume(pvscanOutput)
        copies.update(
            physicalVolume for physicalVolume, volumeGroup in vgs.iteritems()
            if physicalVolume != targetPhysicalVolumeForVolumeGroup and volumeGroup == self.VOLUME_GROUP)
        for physicalVolume in sorted(copies):
            self._refuseAnotherPathToTheTarget(physicalVolume)
            print "Wiping '%(physicalVolume)s' since it contains another copy of the volume group..." \
                  % dict(physicalVolume=physicalVolume)
            self.clear(device=physicalVolume, count=1)
            physicalDevice = "/dev/%s" % _disk(physicalVolume)[0]
            if physicalDevice == physicalVolume:
                continue
            if physicalDevice == self._device:
                print "Skipping wipe of the physical device that contained the volume group since" \
                      " it's the target divice."
                continue
            print "Wiping the physical device '%(physicalDevice)s' which contained the volume " \
                  "group..." % dict(physicalDevice=physicalDevice)
            self.clear(device=physicalDevice, count=1)
        if copies:
            # lvm stops using its cache daemon when it finds a physical volume twice, until the
            # next full scan
            _lvm("pvscan --cache")
        return bool(copies)

    def _getDevicesLabeledAsBoot(self):
        output = _run("blkid")
        print "blkid output:\n"
        print output
        for line in output.splitlines():
            line = line.strip()
            parts = line.split(":", 1)
            if len(parts) != 2:
                continue
            device, data = parts
            if " LABEL=\"BOOT\"" in data:
                device = device.strip()
                yield device

    def _wipeOtherPartitionsWithBootLabel(self):
        print "Validating that device %(device)s is the only one with BOOT label..." % \
              dict(device=self._getPartitionPath("boot"))
        for device in self._getDevicesLabeledAsBoot():
            if device != self._getPartitionPath("boot") and device != self._device:
                self._refuseAnotherPathToTheTarget(device)
                print "Wiping '%(device)s' since it is labeled as BOOT (probably leftovers from previous " \
                      "inaugurations)..." % (dict(device=device))
                self.clear(device=device, count=1)

    def verify(self):
        self._setUpLayout()
        self._wipeCopiesOnOtherDevices()

    def _wipeCopiesOnOtherDevices(self):
        self._wipeOtherPartitionsWithSameVolumeGroup()
        self._wipeOtherPartitionsWithBootLabel()

    def _setUpLayout(self):
        if not self._findMismatch():
            print "Partition table already set up"
            lvmPartitionPath = self._getPartitionPath("lvm")
            _lvm("pvscan --cache %s" % lvmPartitionPath)
            _lvm("vgchange --activate y %s" % self.VOLUME_GROUP)
            _lvm("vgscan --mknodes")
            print "/dev/inaugurator:"
            try:
                print _run("busybox find /dev/inaugurator")
            except Exception as e:
                print "Unable: %s" % e
            return
        self._create()
        for retry in xrange(5):
            mismatch = self._findMismatch()
            if mismatch is None:
                return
            else:
                print "Partition table not correct even after %d retries: '%s'" % (
                    retry, mismatch)
                time.sleep(0.2)
        print "Found Partition Table:", self.parsePartitionTable()
        try:
            print "Found LVM physical:", self.parseLVMPhysicalVolume()
        except:
            print "Can't get physical LVM"
        try:
            print "Found LVM logical:", self.parseLVMLogicalVolume()
        except:
            print "Can't get logical LVM"
        print "Mismatch:", self._findMismatch()
        raise Exception("Created partition table isn't as expected")

    def _waitForFileToShowUp(self, path):
        before = time.time()
        while not os.path.exists(path):
            if time.time() - before > 2:
                raise Exception("Timeout waiting for '%s' to show up" % path)
            time.sleep(0.02)

    def _getPartitionPath(self, partitionPurpose):
        partitionIdx = self._physicalPartitionsOrder.index(partitionPurpose)
        partitionNr = partitionIdx + 1
        return "%(device)s%(partitionNr)s" % dict(device=self._device, partitionNr=partitionNr)

    def getBootPartitionPath(self):
        return self._getPartitionPath("boot")
