import logging
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from inaugurator import loadkernel


class Test(unittest.TestCase):
    def setUp(self):
        self.driverDirectory = tempfile.mkdtemp()
        self.calls = []
        self.kexecFails = False
        self.originals = (loadkernel.sh.run, loadkernel._unbind, loadkernel._restartWithoutShutdown)
        loadkernel.sh.run = self._run
        loadkernel._unbind = lambda directory, address: self.calls.append("unbind %s" % address)
        loadkernel._restartWithoutShutdown = lambda: self.calls.append("restart")

    def tearDown(self):
        loadkernel.sh.run, loadkernel._unbind, loadkernel._restartWithoutShutdown = self.originals
        shutil.rmtree(self.driverDirectory)

    def _run(self, command):
        self.calls.append(command)
        if self.kexecFails:
            raise subprocess.CalledProcessError(-9, command, "")

    def _addDriverEntries(self, * addresses):
        for name in addresses + ("module",):
            os.symlink("/nonexistent", os.path.join(self.driverDirectory, name))
        for name in ("bind", "unbind", "new_id"):
            open(os.path.join(self.driverDirectory, name), "w").close()

    def _execute(self):
        loadkernel.LoadKernel().execute(
            mlx5DriverDirectory=self.driverDirectory,
            msrDevices=os.path.join(self.driverDirectory, "no-cpu"))

    def test_unbindsEveryMlx5DeviceBeforeKexec(self):
        self._addDriverEntries("0000:8f:00.0", "0000:8f:00.1")
        self._execute()
        self.assertEquals(sorted(self.calls[:2]), ["unbind 0000:8f:00.0", "unbind 0000:8f:00.1"])
        self.assertEquals(self.calls[2:], ["kexec -e"])

    def test_unbindsADeviceInAPciDomainOfMoreThanFourDigits(self):
        self._addDriverEntries("10000:01:00.0")
        self._execute()
        self.assertEquals(self.calls, ["unbind 10000:01:00.0", "kexec -e"])

    def test_kexecsWhenTheDriverIsNotLoaded(self):
        shutil.rmtree(self.driverDirectory)
        self._execute()
        os.makedirs(self.driverDirectory)
        self.assertEquals(self.calls, ["kexec -e"])

    def test_kexecsWhenADeviceCannotBeUnbound(self):
        self._addDriverEntries("0000:8f:00.0", "0000:8f:00.1")

        def unbind(directory, address):
            self.calls.append("unbind %s" % address)
            raise IOError("No such device")
        loadkernel._unbind = unbind
        self._execute()
        self.assertEquals(len(self.calls), 3)
        self.assertEquals(self.calls[2], "kexec -e")

    def test_restartsWhenKexecFails(self):
        self.kexecFails = True
        self._execute()
        self.assertEquals(self.calls, ["kexec -e", "restart"])

    def test_doesNotRestartAfterKexec(self):
        self._execute()
        self.assertEquals(self.calls, ["kexec -e"])

    def test_rebootUnbindsEveryMlx5DeviceFirst(self):
        self._addDriverEntries("0000:8f:00.0", "0000:8f:00.1")
        loadkernel.reboot(mlx5DriverDirectory=self.driverDirectory)
        self.assertEquals(sorted(self.calls[:2]), ["unbind 0000:8f:00.0", "unbind 0000:8f:00.1"])
        self.assertEquals(self.calls[2:], ["reboot -f"])


class TestSplitLockDetection(unittest.TestCase):
    TEST_CTRL = 0x33
    SPLIT_LOCK_DETECT = 1 << 29

    def setUp(self):
        self.msrDevices = tempfile.mkdtemp()
        self.cpuinfoDirectory = tempfile.mkdtemp()
        self.cpuinfo = os.path.join(self.cpuinfoDirectory, "cpuinfo")
        self._writeCpuinfo(cpus=0, withTheFlag=False)
        self.calls = []
        self.originalRun = loadkernel.sh.run
        loadkernel.sh.run = self.calls.append
        self.logged = []
        self.handler = logging.Handler()
        self.handler.emit = lambda record: self.logged.append((record.levelname, record.getMessage()))
        logging.getLogger().addHandler(self.handler)
        self.originalLevel = logging.getLogger().level
        logging.getLogger().setLevel(logging.INFO)

    def tearDown(self):
        logging.getLogger().removeHandler(self.handler)
        logging.getLogger().setLevel(self.originalLevel)
        loadkernel.sh.run = self.originalRun
        shutil.rmtree(self.msrDevices)
        shutil.rmtree(self.cpuinfoDirectory)

    def _writeCpuinfo(self, cpus, withTheFlag):
        flags = "fpu vme split_lock_detect md_clear" if withTheFlag else "fpu vme md_clear"
        with open(self.cpuinfo, "w") as f:
            for cpu in xrange(cpus):
                f.write("processor\t: %d\nmodel name\t: A CPU\n" % cpu)
                f.write("flags\t\t: %s\nbugs\t\t: none\n\n" % flags)

    def _addCpu(self, number, testCtrl=None, size=0x200):
        "A file in place of /dev/cpu/<number>/msr: the register number is the offset."
        os.makedirs(os.path.join(self.msrDevices, str(number)))
        with open(os.path.join(self.msrDevices, str(number), "msr"), "wb") as f:
            f.write("\xee" * size)
            if testCtrl is not None:
                f.seek(self.TEST_CTRL)
                f.write(struct.pack("<Q", testCtrl))

    def _testCtrl(self, number):
        with open(os.path.join(self.msrDevices, str(number), "msr"), "rb") as f:
            f.seek(self.TEST_CTRL)
            return struct.unpack("<Q", f.read(8))[0]

    def _execute(self):
        loadkernel.LoadKernel().execute(
            mlx5DriverDirectory=os.path.join(self.msrDevices, "no-driver"), msrDevices=self.msrDevices,
            cpuinfo=self.cpuinfo)

    def test_turnsItOffOnEveryCpuBeforeKexec(self):
        self._addCpu(0, self.SPLIT_LOCK_DETECT)
        self._addCpu(17, self.SPLIT_LOCK_DETECT)
        loadkernel.sh.run = lambda command: self.calls.append(
            (command, self._testCtrl(0), self._testCtrl(17)))
        self._execute()
        self.assertEquals(self.calls, [("kexec -e", 0, 0)])

    def test_keepsTheOtherBitsOfTheRegister(self):
        self._addCpu(0, self.SPLIT_LOCK_DETECT | 0x80000001)
        self._execute()
        self.assertEquals(self._testCtrl(0), 0x80000001)

    def test_doesNotWriteARegisterThatHasItOff(self):
        self._addCpu(0, 0x1)
        os.chmod(os.path.join(self.msrDevices, "0", "msr"), 0o444)
        before = os.stat(os.path.join(self.msrDevices, "0", "msr")).st_mtime
        self._execute()
        self.assertEquals(self._testCtrl(0), 0x1)
        self.assertEquals(os.stat(os.path.join(self.msrDevices, "0", "msr")).st_mtime, before)

    def test_kexecsWhenACpuRefusesToReadTheRegister(self):
        self._addCpu(0, size=0x10)
        os.makedirs(os.path.join(self.msrDevices, "1"))
        os.makedirs(os.path.join(self.msrDevices, "microcode"))
        self._addCpu(2, self.SPLIT_LOCK_DETECT)
        self._execute()
        self.assertEquals(self._testCtrl(2), 0)
        self.assertEquals(self.calls, ["kexec -e"])

    def test_kexecsWhenThereAreNoMsrDevices(self):
        shutil.rmtree(self.msrDevices)
        self._execute()
        os.makedirs(self.msrDevices)
        self.assertEquals(self.calls, ["kexec -e"])

    def test_logsOnHowManyCpusItWasTurnedOff(self):
        self._writeCpuinfo(cpus=3, withTheFlag=True)
        for cpu in xrange(3):
            self._addCpu(cpu, self.SPLIT_LOCK_DETECT)
        self._execute()
        self.assertEquals(self.logged, [("INFO", "Split lock detection turned off on 3 cpus")])

    def test_saysThatTheNextKernelCanHangWhenACpuKeepsItOn(self):
        self._writeCpuinfo(cpus=3, withTheFlag=True)
        self._addCpu(0, self.SPLIT_LOCK_DETECT)
        os.makedirs(os.path.join(self.msrDevices, "1"))
        self._execute()
        self.assertEquals(self.logged[0], ("INFO", "Split lock detection turned off on 1 cpus"))
        self.assertEquals([level for level, message in self.logged[1:]], ["ERROR"])
        self.assertIn("2 of 3 cpus", self.logged[1][1])
        self.assertEquals(self.calls, ["kexec -e"])

    def test_saysSoWhenThereIsNoMsrDeviceAtAll(self):
        self._writeCpuinfo(cpus=2, withTheFlag=True)
        shutil.rmtree(self.msrDevices)
        self._execute()
        os.makedirs(self.msrDevices)
        self.assertEquals([level for level, message in self.logged], ["INFO", "ERROR"])
        self.assertIn("2 of 2 cpus", self.logged[1][1])

    def test_aCpuWithoutTheFeatureIsNotAnError(self):
        self._writeCpuinfo(cpus=2, withTheFlag=False)
        self._addCpu(0, size=0x10)
        self._addCpu(1, size=0x10)
        self._execute()
        self.assertEquals(self.logged, [("INFO", "Split lock detection turned off on 0 cpus")])


if __name__ == '__main__':
    unittest.main()
