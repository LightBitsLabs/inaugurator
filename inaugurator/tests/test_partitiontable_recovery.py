import os
import re
import shutil
import tempfile
import unittest
from inaugurator import partitiontable
from inaugurator import sh


class TestCommands(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.outputs = {}
        self.failing = ()
        self.failingOnce = []
        self.timingOut = ()
        self.notBlockDevices = ()
        self.disks = {}
        self.originalRun = partitiontable.sh.run
        self.originalMark = partitiontable.udevdb.markBlockDevicesInitialized
        self.originalIsBlockDevice = partitiontable._isBlockDevice
        self.originalDisk = partitiontable._disk
        partitiontable.sh.run = self._run
        partitiontable.udevdb.markBlockDevicesInitialized = lambda: None
        partitiontable._isBlockDevice = lambda path: path not in self.notBlockDevices
        partitiontable._disk = lambda device: self.disks.get(
            device, (re.sub(r"^(sd[a-z]+)\d+$", r"\1", os.path.basename(device)), None))
        self.tested = partitiontable.PartitionTable("/dev/sda")

    def tearDown(self):
        partitiontable.sh.run = self.originalRun
        partitiontable.udevdb.markBlockDevicesInitialized = self.originalMark
        partitiontable._isBlockDevice = self.originalIsBlockDevice
        partitiontable._disk = self.originalDisk

    PARTED_PRINT = "BYT;/dev/sda:128000MB:scsi:512:512:gpt:ATA disk:;" \
        "1:1.05MB:3.15MB:2.10MB::primary:bios_grub;" \
        "2:3.15MB:1077MB:1074MB:ext4:primary:boot, esp;" \
        "3:1077MB:128000MB:126923MB::primary:lvm;"
    PVSCAN = "  PV /dev/sda3   VG inaugurator-v2   lvm2 [123.00 GiB / 20.00 GiB free]\n" \
        "  Total: 1 [123.00 GiB] / in use: 1 [123.00 GiB] / in no VG: 0 [0   ]\n"
    PVSCAN_WITH_THE_NAME_ON_ANOTHER_DISK = \
        "  PV /dev/sdb3   VG inaugurator-v2   lvm2 [200.00 GiB / 20.00 GiB free]\n" \
        "  PV /dev/sda3   VG inaugurator-v2   lvm2 [123.00 GiB / 20.00 GiB free]\n" \
        "  Total: 2 [323.00 GiB] / in use: 2 [323.00 GiB] / in no VG: 0 [0   ]\n"
    PVSCAN_WITH_A_COPY_OF_THE_LABEL = \
        "  WARNING: Not using lvmetad because duplicate PVs were found.\n" \
        "  WARNING: Use multipath or vgimportclone to resolve duplicate PVs?\n" \
        "  WARNING: After duplicates are resolved, run \"pvscan --cache\" to enable lvmetad.\n" \
        "  WARNING: PV PJc2ac-oZ72-iJ6N-k27N-YjaX-OHsM-ul1fqw on /dev/sdb was already found on " \
        "/dev/sda3.\n" \
        "  WARNING: PV PJc2ac-oZ72-iJ6N-k27N-YjaX-OHsM-ul1fqw prefers device /dev/sda3 because device " \
        "size is correct.\n" + PVSCAN
    PVSCAN_WITH_A_COPY_BETWEEN_OTHER_DISKS = \
        "  WARNING: PV aaaaaa-oZ72-iJ6N-k27N-YjaX-OHsM-ul1fqw on /dev/sdc was already found on " \
        "/dev/sdd.\n" + PVSCAN
    PVSCAN_WITHOUT_VOLUMES = "  No matching physical volumes found\n"
    IDENTITY = "naa.5000c500a1b2c3d4"

    def _run(self, command, timeout):
        expected = partitiontable._MKFS_TIMEOUT_SECONDS if command.startswith("mkfs.ext4 ") else \
            partitiontable._COMMAND_TIMEOUT_SECONDS
        self.assertEquals(timeout, expected)
        self.calls.append(command)
        if command.startswith(self.timingOut):
            raise sh.TimeoutExpired("'%s' did not finish" % command)
        if command.startswith(self.failing):
            raise Exception("'%s' failed" % command)
        for prefix in self.failingOnce:
            if command.startswith(prefix):
                self.failingOnce.remove(prefix)
                raise Exception("'%s' failed" % command)
        if command in self.outputs:
            output = self.outputs[command]
            if isinstance(output, list):
                return output.pop(0) if len(output) > 1 else output[0]
            return output
        if command.startswith("parted -s -m"):
            return self.PARTED_PRINT

    def _commands(self, * prefixes):
        return [command for command in self.calls if command.startswith(prefixes)]

    def test_everyCommandRunsWithATimeout(self):
        source = open(partitiontable.__file__.replace(".pyc", ".py")).read()
        direct = [line for line in source.splitlines() if 'sh.run(' in line]
        self.assertEquals(direct, ['    return sh.run(command, timeout=timeout)'])

    def test_deletePartitionsWipesEveryPartitionBeforeDeletingTheTable(self):
        self.tested._deletePartitions()
        self.assertEquals(self.calls, [
            "lvm vgchange --activate n inaugurator-v2",
            "busybox rm -fr /dev/inaugurator-v2",
            "busybox mdev -s",
            "parted -s -m /dev/sda unit MB print",
            "busybox dd if=/dev/zero of=/dev/sda1 bs=1M count=1",
            "busybox dd if=/dev/zero of=/dev/sda2 bs=1M count=1",
            "busybox dd if=/dev/zero of=/dev/sda3 bs=1M count=1",
            "sfdisk --delete /dev/sda",
            "busybox mdev -s"])

    def test_deletePartitionsGoesOnWhenTheDiskHasNoVolumeGroupOrPartitionTable(self):
        self.failing = ("lvm vgchange", "parted", "sfdisk")
        self.tested._deletePartitions()
        self.assertEquals(self.calls, [
            "lvm vgchange --activate n inaugurator-v2",
            "busybox rm -fr /dev/inaugurator-v2",
            "busybox mdev -s",
            "parted -s -m /dev/sda unit MB print",
            "sfdisk --delete /dev/sda",
            "busybox mdev -s"])

    def test_deletePartitionsStopsAtACommandThatTimesOut(self):
        self.timingOut = ("lvm vgchange",)
        with self.assertRaises(sh.TimeoutExpired):
            self.tested._deletePartitions()
        self.assertEquals(self.calls, ["lvm vgchange --activate n inaugurator-v2"])

    def test_wipesOnlyPartitionsThatHaveADeviceNode(self):
        self.notBlockDevices = ("/dev/sda2",)
        self.tested._wipePartitionHeaders()
        self.assertEquals(self.calls, [
            "busybox mdev -s",
            "parted -s -m /dev/sda unit MB print",
            "busybox dd if=/dev/zero of=/dev/sda1 bs=1M count=1",
            "busybox dd if=/dev/zero of=/dev/sda3 bs=1M count=1"])

    def test_aTimeoutWhileReadingThePartitionTableIsNotAMismatch(self):
        self.timingOut = ("parted -s -m",)
        with self.assertRaises(sh.TimeoutExpired):
            self.tested._findMismatchInPartitionTable()

    def test_aTimeoutWhileReadingTheVolumesIsNotAMismatch(self):
        self.timingOut = ("lvm pvscan",)
        with self.assertRaises(sh.TimeoutExpired):
            self.tested._findMismatchInLVM()

    def test_aTimeoutWhileReadingTheLogicalVolumesIsNotAMismatch(self):
        self.tested.parseLVMPhysicalVolume = lambda partition: dict(
            name=self.tested.VOLUME_GROUP, sizeMB=126000)
        self.timingOut = ("lvm lvdisplay",)
        with self.assertRaises(sh.TimeoutExpired):
            self.tested._findMismatchInLVM()

    def test_aTimeoutOfVgremoveStopsTheCreation(self):
        self.timingOut = ("lvm vgremove",)
        with self.assertRaises(sh.TimeoutExpired):
            self.tested._create()
        self.assertEquals(self.calls[-1], "lvm vgremove -f inaugurator-v2")

    def test_mkfsGetsALongerLimitThanTheOtherCommands(self):
        self.assertGreater(partitiontable._MKFS_TIMEOUT_SECONDS, partitiontable._COMMAND_TIMEOUT_SECONDS)
        self.timingOut = ("lvm vgremove",)
        with self.assertRaises(sh.TimeoutExpired):
            self.tested._create()
        self.assertEquals(self._commands("mkfs"), ["mkfs.ext4 /dev/sda2 -L BOOT"])

    def test_aValidDiskIsKeptWhenTheOtherDisksCannotBeInspected(self):
        self.tested._findMismatch = lambda: None
        self.outputs = {"lvm pvscan": self.PVSCAN}
        self.failing = ("blkid",)
        with self.assertRaisesRegexp(Exception, "blkid"):
            self.tested.prepare()
        self.assertEquals(self.calls, [
            "lvm pvscan",
            "lvm pvscan --cache /dev/sda3",
            "lvm vgchange --activate y inaugurator-v2",
            "lvm vgscan --mknodes",
            "busybox find /dev/inaugurator",
            "lvm pvscan",
            "blkid"])

    def test_wipesABootLabelOnAnotherDiskAfterFindingAValidLayout(self):
        self.tested._findMismatch = lambda: None
        self.outputs = {
            "lvm pvscan": self.PVSCAN,
            "blkid": '/dev/sda2: LABEL="BOOT" TYPE="ext4"\n/dev/sdb2: LABEL="BOOT" TYPE="ext4"\n'}
        self.tested.prepare()
        self.assertEquals(self.calls[-2:], ["blkid", "busybox dd if=/dev/zero of=/dev/sdb2 bs=1M count=1"])

    def test_inspectsTheOtherDisksAfterCreatingTheLayout(self):
        mismatches = ["Partition count is not 3", None]
        self.tested._findMismatch = lambda: mismatches.pop(0)
        self.tested._create = lambda: self.calls.append("create")
        self.outputs = {"lvm pvscan": self.PVSCAN, "blkid": ""}
        self.tested.prepare()
        self.assertEquals(self.calls, ["lvm pvscan", "create", "lvm pvscan", "blkid"])

    def test_aDiskThatRefusesToBeClearedIsNotAccepted(self):
        self.tested._findMismatch = lambda: None
        self.outputs = {"lvm pvscan": self.PVSCAN, "blkid": ""}
        self.failing = ("busybox dd", "sfdisk")
        with self.assertRaisesRegexp(Exception, "busybox dd if=/dev/zero of=/dev/sda bs=1M count=512"):
            self.tested.prepare(clearFirst=True)
        self.assertNotIn("lvm vgchange --activate y inaugurator-v2", self.calls)
        self.assertNotIn("blkid", self.calls)

    def test_aValidDiskIsKeptWhenAnotherDiskCarriesTheSameVolumeGroupName(self):
        self.tested._findMismatch = lambda: None
        self.outputs = {"lvm pvscan": [self.PVSCAN_WITH_THE_NAME_ON_ANOTHER_DISK, self.PVSCAN], "blkid": ""}
        self.tested.prepare()
        self.assertEquals(self.calls, [
            "lvm pvscan",
            "busybox dd if=/dev/zero of=/dev/sdb3 bs=1M count=1",
            "busybox dd if=/dev/zero of=/dev/sdb bs=1M count=1",
            "lvm pvscan --cache",
            "lvm pvscan --cache /dev/sda3",
            "lvm vgchange --activate y inaugurator-v2",
            "lvm vgscan --mknodes",
            "busybox find /dev/inaugurator",
            "lvm pvscan",
            "blkid"])

    def test_aValidDiskIsKeptWhenAnotherDiskCarriesACopyOfItsLabel(self):
        self.tested._findMismatch = lambda: None
        self.outputs = {"lvm pvscan": [self.PVSCAN_WITH_A_COPY_OF_THE_LABEL, self.PVSCAN], "blkid": ""}
        self.tested.prepare()
        self.assertEquals(self._commands("busybox dd", "sfdisk", "mkfs"), [
            "busybox dd if=/dev/zero of=/dev/sdb bs=1M count=1"])
        self.assertEquals(self.calls[:3], [
            "lvm pvscan", "busybox dd if=/dev/zero of=/dev/sdb bs=1M count=1", "lvm pvscan --cache"])

    def test_theCopiesAreWipedBeforeTheLayoutIsJudged(self):
        judged = []
        self.tested._findMismatch = lambda: judged.append(list(self.calls))
        self.outputs = {"lvm pvscan": [self.PVSCAN_WITH_THE_NAME_ON_ANOTHER_DISK, self.PVSCAN], "blkid": ""}
        self.tested.prepare()
        self.assertEquals(judged[0][-1], "lvm pvscan --cache")

    def test_theDiskIsRebuiltWhenItFailsWithNoCopyOnAnotherDisk(self):
        self.tested._findMismatch = lambda: None
        self.tested._create = lambda: self.calls.append("create")
        self.failingOnce = ["lvm vgchange --activate y"]
        self.outputs = {"lvm pvscan": self.PVSCAN, "blkid": ""}
        self.tested.prepare()
        self.assertEquals(self._commands("sfdisk"), ["sfdisk --delete /dev/sda"])

    def test_aDiskThatHoldsTheInstallationSourceIsNotRebuilt(self):
        self.tested._findMismatch = lambda: None
        self.failing = ("lvm vgchange --activate y",)
        self.outputs = {"lvm pvscan": self.PVSCAN, "blkid": ""}
        with self.assertRaisesRegexp(Exception, "lvm vgchange --activate y"):
            self.tested.prepare(rebuildOnFailure=False)
        self.assertEquals(self._commands("busybox dd", "sfdisk", "mkfs", "lvm vgchange --activate n"), [])

    def test_aTimeoutDoesNotStartTheRebuild(self):
        self.tested._findMismatch = lambda: None
        self.timingOut = ("lvm vgchange --activate y",)
        self.outputs = {"lvm pvscan": self.PVSCAN}
        with self.assertRaises(sh.TimeoutExpired):
            self.tested.prepare()
        self.assertEquals(self.calls, [
            "lvm pvscan", "lvm pvscan --cache /dev/sda3", "lvm vgchange --activate y inaugurator-v2"])

    def test_wipingTheCopiesReportsWhetherThereWereAny(self):
        self.outputs = {"lvm pvscan": self.PVSCAN}
        self.assertFalse(self.tested._wipeOtherPartitionsWithSameVolumeGroup())
        self.assertEquals(self.calls, ["lvm pvscan"])

    def test_aCopyBetweenTwoOtherDisksIsLeftAlone(self):
        self.outputs = {"lvm pvscan": self.PVSCAN_WITH_A_COPY_BETWEEN_OTHER_DISKS}
        self.assertFalse(self.tested._wipeOtherPartitionsWithSameVolumeGroup())
        self.assertEquals(self.calls, ["lvm pvscan"])

    def test_aMissingVolumeGroupFailsOnlyWhereOneIsExpected(self):
        self.outputs = {"lvm pvscan": self.PVSCAN_WITHOUT_VOLUMES}
        self.assertFalse(self.tested._wipeOtherPartitionsWithSameVolumeGroup(volumeGroupExpected=False))
        with self.assertRaisesRegexp(Exception, "No volume group was found"):
            self.tested._wipeOtherPartitionsWithSameVolumeGroup()

    def test_anotherPathToTheTargetDiskIsNotWipedAsACopy(self):
        self.disks = {"/dev/sda": ("sda", self.IDENTITY), "/dev/sdb3": ("sdb", self.IDENTITY)}
        self.outputs = {"lvm pvscan": self.PVSCAN_WITH_THE_NAME_ON_ANOTHER_DISK}
        with self.assertRaisesRegexp(Exception, "another path"):
            self.tested._wipeOtherPartitionsWithSameVolumeGroup()
        self.assertEquals(self.calls, ["lvm pvscan"])

    def test_aBootLabelOnAnotherPathToTheTargetDiskIsNotWiped(self):
        self.disks = {"/dev/sda": ("sda", self.IDENTITY), "/dev/sdb2": ("sdb", self.IDENTITY)}
        self.outputs = {
            "blkid": '/dev/sda2: LABEL="BOOT" TYPE="ext4"\n/dev/sdb2: LABEL="BOOT" TYPE="ext4"\n'}
        with self.assertRaisesRegexp(Exception, "another path"):
            self.tested._wipeOtherPartitionsWithBootLabel()
        self.assertEquals(self.calls, ["blkid"])

    def test_aCopyOnAnotherPartitionOfTheTargetDiskIsWiped(self):
        self.disks = {"/dev/sda": ("sda", self.IDENTITY), "/dev/sda5": ("sda", self.IDENTITY)}
        self.outputs = {
            "lvm pvscan": self.PVSCAN + "  PV /dev/sda5   VG inaugurator-v2   lvm2 [1.00 GiB / 0 free]\n"}
        self.assertTrue(self.tested._wipeOtherPartitionsWithSameVolumeGroup())
        self.assertEquals(self._commands("busybox dd"), [
            "busybox dd if=/dev/zero of=/dev/sda5 bs=1M count=1"])

    def test_twoDisksWithoutAnIdentityAreNotTakenForOneDisk(self):
        self.outputs = {"lvm pvscan": self.PVSCAN_WITH_THE_NAME_ON_ANOTHER_DISK}
        self.assertTrue(self.tested._wipeOtherPartitionsWithSameVolumeGroup())
        self.assertEquals(self._commands("busybox dd"), [
            "busybox dd if=/dev/zero of=/dev/sdb3 bs=1M count=1",
            "busybox dd if=/dev/zero of=/dev/sdb bs=1M count=1"])


class TestDisk(unittest.TestCase):
    def setUp(self):
        self.sysfs = tempfile.mkdtemp()
        self._addDisk("pci0000:00/ata1/host0/sda", "device/wwid", "t10.ATA     A DISK       SERIAL1 \n")
        self._addPartition("pci0000:00/ata1/host0/sda", "sda3")
        self._addDisk("pci0000:64/nvme/nvme0/nvme0n1", "wwid", "eui.36344630528019990025384500000001\n")
        self._addPartition("pci0000:64/nvme/nvme0/nvme0n1", "nvme0n1p3")
        self._addDisk("virtual/block/loop0", None, None)

    def tearDown(self):
        shutil.rmtree(self.sysfs)

    def _addDisk(self, path, identityAttribute, identity):
        directory = os.path.join(self.sysfs, "devices", path)
        os.makedirs(directory)
        if identityAttribute is not None:
            if os.path.dirname(identityAttribute):
                os.makedirs(os.path.join(directory, os.path.dirname(identityAttribute)))
            with open(os.path.join(directory, identityAttribute), "w") as f:
                f.write(identity)
        os.symlink(directory, os.path.join(self.sysfs, os.path.basename(path)))

    def _addPartition(self, diskPath, name):
        directory = os.path.join(self.sysfs, "devices", diskPath, name)
        os.makedirs(directory)
        open(os.path.join(directory, "partition"), "w").close()
        os.symlink(directory, os.path.join(self.sysfs, name))

    def _disk(self, device):
        return partitiontable._disk(device, sysfs=self.sysfs)

    def test_aDiskIsItsOwnDisk(self):
        self.assertEquals(self._disk("/dev/sda"), ("sda", "t10.ATA     A DISK       SERIAL1"))

    def test_aPartitionIsOnTheDiskThatHoldsIt(self):
        self.assertEquals(self._disk("/dev/sda3"), ("sda", "t10.ATA     A DISK       SERIAL1"))

    def test_theDigitsInTheNameOfAnNvmeDiskAreNotAPartitionNumber(self):
        self.assertEquals(self._disk("/dev/nvme0n1"), ("nvme0n1", "eui.36344630528019990025384500000001"))
        self.assertEquals(self._disk("/dev/nvme0n1p3"), ("nvme0n1", "eui.36344630528019990025384500000001"))

    def test_aDiskThatReportsNoIdentityHasNone(self):
        self.assertEquals(self._disk("/dev/loop0"), ("loop0", None))

    def test_aDeviceTheKernelDoesNotListIsItsOwnDiskWithoutAnIdentity(self):
        self.assertEquals(self._disk("/dev/mapper/some-volume"), ("some-volume", None))


class TestPrepare(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.failures = dict()
        self.tested = partitiontable.PartitionTable("/dev/sda")
        self.tested.clear = lambda: self._called("clear")
        self.tested._setUpLayout = lambda: self._called("setUpLayout")
        self.tested._wipeCopiesOnOtherDevices = lambda: self._called("wipeCopiesOnOtherDevices")
        self.tested._deletePartitions = lambda: self._called("deletePartitions")
        self.tested._wipeOtherPartitionsWithSameVolumeGroup = self._wipeVolumeGroupCopies

    def _called(self, name):
        self.calls.append(name)
        if self.failures.get(name):
            raise self.failures[name].pop(0)

    def _wipeVolumeGroupCopies(self, volumeGroupExpected):
        self.assertFalse(volumeGroupExpected)
        self._called("wipeVolumeGroupCopies")

    def test_aDiskThatSetsUpIsLeftAlone(self):
        self.tested.prepare()
        self.assertEquals(self.calls, ["wipeVolumeGroupCopies", "setUpLayout", "wipeCopiesOnOtherDevices"])

    def test_clearsFirstWhenAsked(self):
        self.tested.prepare(clearFirst=True)
        self.assertEquals(self.calls, [
            "wipeVolumeGroupCopies", "clear", "setUpLayout", "wipeCopiesOnOtherDevices"])

    def test_rebuildsADiskThatFailsToSetUp(self):
        self.failures["setUpLayout"] = [Exception("Created partition table isn't as expected")]
        self.tested.prepare()
        self.assertEquals(self.calls, [
            "wipeVolumeGroupCopies", "setUpLayout", "deletePartitions", "setUpLayout",
            "wipeCopiesOnOtherDevices"])

    def test_aFailureToWipeTheCopiesIsRaisedAndTheDiskIsKept(self):
        self.failures["wipeVolumeGroupCopies"] = [ValueError("dd failed on the other disk")]
        with self.assertRaises(ValueError):
            self.tested.prepare()
        self.assertEquals(self.calls, ["wipeVolumeGroupCopies"])

    def test_aTimeoutIsRaisedAndTheDiskIsKept(self):
        self.failures["setUpLayout"] = [sh.TimeoutExpired("lvm pvscan")]
        with self.assertRaises(sh.TimeoutExpired):
            self.tested.prepare()
        self.assertEquals(self.calls, ["wipeVolumeGroupCopies", "setUpLayout"])

    def test_aTimeoutOfTheClearIsRaised(self):
        self.failures["clear"] = [sh.TimeoutExpired("busybox dd")]
        with self.assertRaises(sh.TimeoutExpired):
            self.tested.prepare(clearFirst=True)
        self.assertEquals(self.calls, ["wipeVolumeGroupCopies", "clear"])

    def test_aTimeoutOfTheRebuildIsRaised(self):
        self.failures["setUpLayout"] = [Exception("first")]
        self.failures["deletePartitions"] = [sh.TimeoutExpired("lvm vgchange")]
        with self.assertRaises(sh.TimeoutExpired):
            self.tested.prepare()
        self.assertEquals(self.calls, ["wipeVolumeGroupCopies", "setUpLayout", "deletePartitions"])

    def test_aDiskThatHoldsTheInstallationSourceIsNotRebuilt(self):
        self.failures["setUpLayout"] = [ValueError("first")]
        with self.assertRaises(ValueError):
            self.tested.prepare(rebuildOnFailure=False)
        self.assertEquals(self.calls, ["wipeVolumeGroupCopies", "setUpLayout"])

    def test_aDiskThatHoldsTheInstallationSourceIsNotRebuiltAfterAFailedClearEither(self):
        self.failures["clear"] = [ValueError("dd failed")]
        with self.assertRaises(ValueError):
            self.tested.prepare(clearFirst=True, rebuildOnFailure=False)
        self.assertEquals(self.calls, ["wipeVolumeGroupCopies", "clear"])

    def test_rebuildsAfterAFailureToClearTheDisk(self):
        self.failures["clear"] = [Exception("dd failed")]
        self.tested.prepare(clearFirst=True)
        self.assertEquals(self.calls, [
            "wipeVolumeGroupCopies", "clear", "deletePartitions", "clear", "setUpLayout",
            "wipeCopiesOnOtherDevices"])

    def test_clearsAgainBeforeTheSecondSetUpWhenAskedToClear(self):
        self.failures["setUpLayout"] = [Exception("first")]
        self.tested.prepare(clearFirst=True)
        self.assertEquals(self.calls, [
            "wipeVolumeGroupCopies", "clear", "setUpLayout", "deletePartitions", "clear", "setUpLayout",
            "wipeCopiesOnOtherDevices"])

    def test_aDiskThatCannotBeClearedIsNotSetUp(self):
        self.failures["clear"] = [Exception("first"), ValueError("second")]
        with self.assertRaises(ValueError):
            self.tested.prepare(clearFirst=True)
        self.assertEquals(self.calls, ["wipeVolumeGroupCopies", "clear", "deletePartitions", "clear"])

    def test_aFailureOfTheRebuiltDiskIsRaised(self):
        self.failures["setUpLayout"] = [Exception("first"), ValueError("second")]
        with self.assertRaises(ValueError):
            self.tested.prepare()
        self.assertEquals(self.calls, [
            "wipeVolumeGroupCopies", "setUpLayout", "deletePartitions", "setUpLayout"])

    def test_aFailureToWipeCopiesOnOtherDevicesDoesNotRebuildTheDisk(self):
        self.failures["wipeCopiesOnOtherDevices"] = [ValueError("blkid failed")]
        with self.assertRaises(ValueError):
            self.tested.prepare()
        self.assertEquals(self.calls, ["wipeVolumeGroupCopies", "setUpLayout", "wipeCopiesOnOtherDevices"])

    def test_verifySetsUpTheLayoutAndThenWipesTheCopiesOnOtherDevices(self):
        self.tested.verify()
        self.assertEquals(self.calls, ["setUpLayout", "wipeCopiesOnOtherDevices"])


if __name__ == '__main__':
    unittest.main()
