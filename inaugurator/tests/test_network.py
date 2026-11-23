import subprocess
import unittest
from inaugurator import network


class TestNetworkInterfaceStat(unittest.TestCase):
    def setUp(self):
        self.attrs = dict(
            address="b4:96:91:00:00:01", mtu="1500", operstate="up", speed="25000", carrier="1")
        self.unreadable = set()
        self.originalRun = network.sh.run
        network.sh.run = self.runShell

    def tearDown(self):
        network.sh.run = self.originalRun

    def runShell(self, command):
        attr = command.split("/")[-1]
        if attr in self.unreadable:
            raise subprocess.CalledProcessError(1, command, "cat: read error: Invalid argument")
        return self.attrs[attr] + "\n"

    def test_reportsAnInterfaceThatIsUp(self):
        self.assertEquals(network.NetworkInterface("eth7").stat(), self.attrs)

    def test_interfaceThatCouldNotBeBroughtUp(self):
        self.attrs["operstate"] = "down"
        self.unreadable = set(["speed", "carrier"])
        stat = network.NetworkInterface("eth8").stat()
        self.assertEquals(stat["speed"], "-1")
        self.assertEquals(stat["carrier"], "0")
        self.assertEquals(stat["operstate"], "down")
        self.assertEquals(stat["address"], "b4:96:91:00:00:01")

    def test_unreadableAddressStillFails(self):
        self.unreadable = set(["address"])
        self.assertRaises(subprocess.CalledProcessError, network.NetworkInterface("eth8").stat)


if __name__ == '__main__':
    unittest.main()
