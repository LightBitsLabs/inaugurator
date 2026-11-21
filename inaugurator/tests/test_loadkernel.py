import os
import shutil
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
        loadkernel.LoadKernel().execute(mlx5DriverDirectory=self.driverDirectory)

    def test_unbindsEveryMlx5DeviceBeforeKexec(self):
        self._addDriverEntries("0000:8f:00.0", "0000:8f:00.1")
        self._execute()
        self.assertEquals(sorted(self.calls[:2]), ["unbind 0000:8f:00.0", "unbind 0000:8f:00.1"])
        self.assertEquals(self.calls[2:], ["kexec -e"])

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


if __name__ == '__main__':
    unittest.main()
