"""Checks a built initrd directory: the drivers the lab's hardware needs are in it, and
each can be loaded from it. Run after the build:

    python -m inaugurator.tests.image_check build/inaugurator.thin.initrd.dir
"""
import glob
import os
import subprocess
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
    (0x1077, 0x8070, 'qede'),       # FastLinQ QL41000
]
NVME_MODALIAS = 'pci:v0000144Dd0000A808sv0000144Dsd0000A801bc01sc08i02'
# Every storage and network driver that a lab machine binds. One that the kernel has built
# in passes as it is; if a later kernel makes it a module, the check fails until the build
# copies it.
LAB_DRIVERS = [
    'ahci', 'ata_piix', 'sd_mod', 'usb_storage', 'megaraid_sas', 'nvme',
    'mlx5_core', 'igb', 'i40e', 'ixgbe', 'ice', 'tg3', 'e1000e', 'bnx2x', 'bnxt_en', 'qede',
]

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
    """module name -> paths, relative to the modules directory, of the module and all it needs.
    Read from the builder's module tree: the image's own modules.dep is generated from the
    modules that were copied, so it cannot name one that is missing."""
    result = dict()
    with open(os.path.join('/lib/modules', os.path.basename(_modulesDir()), 'modules.dep')) as f:
        for line in f:
            path, needs = line.strip().split(':')
            name = os.path.basename(path).split('.')[0].replace('-', '_')
            result[name] = [path] + needs.split()
    return result


def _builtInDrivers():
    with open(os.path.join(_modulesDir(), 'modules.builtin')) as f:
        return set(os.path.basename(line).split('.')[0].replace('-', '_') for line in f)


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

    def test_labDriversAreBuiltInOrLoadable(self):
        builtIn = _builtInDrivers()
        for driver in LAB_DRIVERS:
            if driver not in builtIn:
                self._assertLoadable(driver)

    def test_firmwareNamedByTheModulesIsInTheImage(self):
        "A driver that does not find its firmware loads and then fails to bring its device up."
        for driver, paths in self.dependencies.items():
            module = os.path.join(_modulesDir(), paths[0])
            if not os.path.exists(module):
                continue
            for name in subprocess.check_output(['modinfo', '-F', 'firmware', module]).split():
                found = glob.glob(os.path.join(imageDir, 'lib', 'firmware', name + '*'))
                self.assertTrue(found, "%s names firmware %s" % (driver, name))


if __name__ == '__main__':
    imageDir = sys.argv.pop(1)
    unittest.main()
