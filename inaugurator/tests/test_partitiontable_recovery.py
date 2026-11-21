import unittest
from inaugurator import partitiontable
from inaugurator import sh


class TestCommands(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.failing = ()
        self.timingOut = ()
        self.notBlockDevices = ()
        self.originalRun = partitiontable.sh.run
        self.originalMark = partitiontable.udevdb.markBlockDevicesInitialized
        self.originalIsBlockDevice = partitiontable._isBlockDevice
        partitiontable.sh.run = self._run
        partitiontable.udevdb.markBlockDevicesInitialized = lambda: None
        partitiontable._isBlockDevice = lambda path: path not in self.notBlockDevices
        self.tested = partitiontable.PartitionTable("/dev/sda")

    def tearDown(self):
        partitiontable.sh.run = self.originalRun
        partitiontable.udevdb.markBlockDevicesInitialized = self.originalMark
        partitiontable._isBlockDevice = self.originalIsBlockDevice

    PARTED_PRINT = "BYT;/dev/sda:128000MB:scsi:512:512:gpt:ATA disk:;" \
        "1:1.05MB:3.15MB:2.10MB::primary:bios_grub;" \
        "2:3.15MB:1077MB:1074MB:ext4:primary:boot, esp;" \
        "3:1077MB:128000MB:126923MB::primary:lvm;"

    def _run(self, command, timeout):
        self.assertEquals(timeout, partitiontable._COMMAND_TIMEOUT_SECONDS)
        self.calls.append(command)
        if command.startswith(self.timingOut):
            raise sh.TimeoutExpired("'%s' did not finish" % command)
        if command.startswith(self.failing):
            raise Exception("'%s' failed" % command)
        if command.startswith("parted -s -m"):
            return self.PARTED_PRINT

    def test_everyCommandRunsWithATimeout(self):
        source = open(partitiontable.__file__.replace(".pyc", ".py")).read()
        direct = [line for line in source.splitlines() if 'sh.run(' in line]
        self.assertEquals(direct, ['    return sh.run(command, timeout=_COMMAND_TIMEOUT_SECONDS)'])

    def test_deletePartitionsWipesEveryPartitionBeforeDeletingTheTable(self):
        self.tested._deletePartitions()
        self.assertEquals(self.calls, [
            "lvm vgchange --activate n inaugurator-v2",
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
            "busybox mdev -s",
            "parted -s -m /dev/sda unit MB print",
            "sfdisk --delete /dev/sda",
            "busybox mdev -s"])

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

    def test_aTimeoutOfVgremoveStopsTheCreation(self):
        self.timingOut = ("lvm vgremove",)
        with self.assertRaises(sh.TimeoutExpired):
            self.tested._create()
        self.assertEquals(self.calls[-1], "lvm vgremove -f inaugurator-v2")


class TestPrepare(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.failures = dict(clear=[], verify=[])
        self.tested = partitiontable.PartitionTable("/dev/sda")
        self.tested.clear = lambda: self._called("clear")
        self.tested.verify = lambda: self._called("verify")
        self.tested._deletePartitions = lambda: self._called("deletePartitions")

    def _called(self, name):
        self.calls.append(name)
        if self.failures.get(name):
            raise self.failures[name].pop(0)

    def test_aDiskThatSetsUpIsLeftAlone(self):
        self.tested.prepare()
        self.assertEquals(self.calls, ["verify"])

    def test_clearsFirstWhenAsked(self):
        self.tested.prepare(clearFirst=True)
        self.assertEquals(self.calls, ["clear", "verify"])

    def test_deletesThePartitionsAndSetsUpAgainAfterAFailure(self):
        self.failures["verify"] = [Exception("Created partition table isn't as expected")]
        self.tested.prepare()
        self.assertEquals(self.calls, ["verify", "deletePartitions", "verify"])

    def test_recoversFromACommandThatTimedOut(self):
        self.failures["verify"] = [sh.TimeoutExpired("lvm pvscan")]
        self.tested.prepare()
        self.assertEquals(self.calls, ["verify", "deletePartitions", "verify"])

    def test_recoversFromAFailureToClearTheDisk(self):
        self.failures["clear"] = [Exception("dd failed")]
        self.tested.prepare(clearFirst=True)
        self.assertEquals(self.calls, ["clear", "deletePartitions", "verify"])

    def test_aSecondFailureIsRaised(self):
        self.failures["verify"] = [Exception("first"), ValueError("second")]
        with self.assertRaises(ValueError):
            self.tested.prepare()
        self.assertEquals(self.calls, ["verify", "deletePartitions", "verify"])


if __name__ == '__main__':
    unittest.main()
