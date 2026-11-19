import os
import shutil
import tempfile
import unittest
from inaugurator import partitiontable
from inaugurator import udevdb


class Test(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.sysfsBlock = os.path.join(self.root, "sys", "class", "block")
        self.udevData = os.path.join(self.root, "run", "udev", "data")
        os.makedirs(self.sysfsBlock)

    def tearDown(self):
        shutil.rmtree(self.root)

    def _addBlockDevice(self, name, deviceNumber):
        os.makedirs(os.path.join(self.sysfsBlock, name))
        with open(os.path.join(self.sysfsBlock, name, "dev"), "w") as f:
            f.write(deviceNumber + "\n")

    def _mark(self):
        udevdb.markBlockDevicesInitialized(sysfsBlock=self.sysfsBlock, udevData=self.udevData)

    def test_createsAnEntryPerBlockDevice(self):
        self._addBlockDevice("sda", "8:0")
        self._addBlockDevice("sda3", "8:3")
        self._addBlockDevice("nvme5n1p66", "259:70")
        self._mark()
        self.assertEquals(sorted(os.listdir(self.udevData)), ["b259:70", "b8:0", "b8:3"])

    def test_keepsAnExistingEntry(self):
        self._addBlockDevice("sda", "8:0")
        os.makedirs(self.udevData)
        with open(os.path.join(self.udevData, "b8:0"), "w") as f:
            f.write("E:ID_FS_TYPE=LVM2_member\n")
        self._mark()
        with open(os.path.join(self.udevData, "b8:0")) as f:
            self.assertEquals(f.read(), "E:ID_FS_TYPE=LVM2_member\n")

    def test_coversDevicesThatAppearLater(self):
        self._addBlockDevice("sda", "8:0")
        self._mark()
        self._addBlockDevice("sda1", "8:1")
        self._mark()
        self.assertEquals(sorted(os.listdir(self.udevData)), ["b8:0", "b8:1"])

    def test_noBlockDevices(self):
        self._mark()
        self.assertEquals(os.listdir(self.udevData), [])


class TestScanPhysicalVolume(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.originalRun = partitiontable.sh.run
        self.originalMark = partitiontable.udevdb.markBlockDevicesInitialized
        partitiontable.sh.run = lambda command: self.calls.append(command)
        partitiontable.udevdb.markBlockDevicesInitialized = lambda: self.calls.append("mark")

    def tearDown(self):
        partitiontable.sh.run = self.originalRun
        partitiontable.udevdb.markBlockDevicesInitialized = self.originalMark

    def test_marksBlockDevicesBeforeTheScan(self):
        partitiontable.PartitionTable._scanPhysicalVolume("/dev/sda3")
        self.assertEquals(self.calls, ["mark", "lvm pvscan --cache /dev/sda3"])


if __name__ == '__main__':
    unittest.main()
