import argparse
import sys
import types
import unittest
import inaugurator


def _ceremony():
    "The ceremony imports the osmosis python package, which the unit tests do not install."
    if "inaugurator.osmosiscleanup" not in sys.modules:
        try:
            from inaugurator import osmosiscleanup
        except ImportError:
            stub = types.ModuleType("inaugurator.osmosiscleanup")
            inaugurator.osmosiscleanup = sys.modules["inaugurator.osmosiscleanup"] = stub
    from inaugurator import ceremony
    return ceremony


class Test(unittest.TestCase):
    def setUp(self):
        self.ceremony = _ceremony()
        self.prepared = []
        self.originals = (self.ceremony.partitiontable.PartitionTable, self.ceremony.lvmetad.Lvmetad)
        test = self

        class PartitionTable:
            def __init__(self, device, layoutScheme, hypervisor):
                pass

            def prepare(self, ** kwargs):
                test.prepared.append(kwargs)

            def getBootPartitionPath(self):
                return "/dev/sda2"
        self.ceremony.partitiontable.PartitionTable = PartitionTable
        self.ceremony.lvmetad.Lvmetad = lambda: None

    def tearDown(self):
        self.ceremony.partitiontable.PartitionTable, self.ceremony.lvmetad.Lvmetad = self.originals

    def _createPartitionTable(self, source, clearDisk=False):
        class Bare(self.ceremony.Ceremony):
            def __init__(self):
                pass
        tested = Bare()
        tested._args = argparse.Namespace(
            inauguratorSource=source, inauguratorClearDisk=clearDisk, inauguratorPartitionLayout="GPT",
            hypervisor=False)
        tested._targetDevice = "/dev/sda"
        tested._createPartitionTable()

    def test_aDiskThatGetsItsLabelFromElsewhereMayBeRebuilt(self):
        for source in ("network", "DOK", "CDROM"):
            self._createPartitionTable(source)
        self.assertEquals(self.prepared, [dict(clearFirst=False, rebuildOnFailure=True)] * 3)

    def test_aDiskThatHoldsTheLabelToInstallIsNotRebuilt(self):
        self._createPartitionTable("local")
        self.assertEquals(self.prepared, [dict(clearFirst=False, rebuildOnFailure=False)])

    def test_passesARequestToClearTheDisk(self):
        self._createPartitionTable("network", clearDisk=True)
        self.assertEquals(self.prepared, [dict(clearFirst=True, rebuildOnFailure=True)])


if __name__ == '__main__':
    unittest.main()
