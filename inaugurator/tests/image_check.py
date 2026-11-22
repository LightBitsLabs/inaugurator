"""Checks a built initrd directory: the drivers the lab's hardware needs are in it, and
each can be loaded from it. Run after the build:

    python -m inaugurator.tests.image_check build/inaugurator.thin.initrd.dir
"""
import os
import sys
import unittest
from inaugurator import udev

# (vendor, device, driver): PCI IDs read off lab machines.
LAB_PCI_DEVICES = [
    (0x15b3, 0x101d, 'mlx5_core'),  # ConnectX-6 Dx
    (0x15b3, 0x101f, 'mlx5_core'),  # ConnectX-6 Lx
    (0x8086, 0x1592, 'ice'),        # E810-C QSFP
    (0x8086, 0x159b, 'ice'),        # E810-XXV SFP
    (0x8086, 0x15ff, 'i40e'),       # X710 10GBASE-T
    (0x8086, 0x1521, 'igb'),        # I350
]
NVME_MODALIAS = 'pci:v0000144Dd0000A808sv0000144Dsd0000A801bc01sc08i02'

imageDir = None


def _modulesDir():
    versions = os.listdir(os.path.join(imageDir, 'lib', 'modules'))
    assert len(versions) == 1, "expected one kernel in the image, found %s" % versions
    return os.path.join(imageDir, 'lib', 'modules', versions[0])


def _aliasTable():
    table = dict()
    with open(os.path.join(_modulesDir(), 'modules.alias')) as f:
        for line in f:
            if line.startswith('#'):
                continue
            alias, driver = line.strip().split(' ', 1)[1].rsplit(' ', 1)
            if ':' in alias:
                table.setdefault(alias.split(':')[0], dict())[alias] = driver
    return table


def _dependencies():
    "module name -> paths, relative to the modules directory, of the module and all it needs"
    result = dict()
    with open(os.path.join(_modulesDir(), 'modules.dep')) as f:
        for line in f:
            path, needs = line.strip().split(':')
            name = os.path.basename(path).split('.')[0].replace('-', '_')
            result[name] = [path] + needs.split()
    return result


def _pciModalias(vendor, device):
    return 'pci:v%08Xd%08Xsv00000000sd00000000bc02sc00i00' % (vendor, device)


class Test(unittest.TestCase):
    def setUp(self):
        self.aliases = _aliasTable()
        self.dependencies = _dependencies()

    def _driver(self, modalias):
        return udev._findDriver({u'MODALIAS': modalias}, self.aliases)

    def _assertLoadable(self, driver):
        self.assertIn(driver, self.dependencies)
        for path in self.dependencies[driver]:
            present = os.path.exists(os.path.join(_modulesDir(), path))
            self.assertTrue(present, "%s needs %s" % (driver, path))

    def test_labPciDevicesHaveLoadableDrivers(self):
        for vendor, device, expected in LAB_PCI_DEVICES:
            driver = self._driver(_pciModalias(vendor, device))
            self.assertEquals(driver, expected, "%04x:%04x resolves to %s" % (vendor, device, driver))
            self._assertLoadable(driver)

    def test_nvmeHasLoadableDriver(self):
        self.assertEquals(self._driver(NVME_MODALIAS), 'nvme')
        self._assertLoadable('nvme')

    def test_everyModuleInTheImageHasItsDependencies(self):
        for driver, paths in self.dependencies.items():
            if os.path.exists(os.path.join(_modulesDir(), paths[0])):
                self._assertLoadable(driver)

    def test_iceHasItsDdpPackage(self):
        package = os.path.join(imageDir, 'lib', 'firmware', 'intel', 'ice', 'ddp', 'ice.pkg')
        self.assertTrue(os.path.exists(package))


if __name__ == '__main__':
    imageDir = sys.argv.pop(1)
    unittest.main()
