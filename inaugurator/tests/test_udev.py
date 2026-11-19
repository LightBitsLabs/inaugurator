import unittest
from inaugurator import udev


ALIAS_TABLE = {
    'pci': {
        'pci:v000015B3d0000101Fsv*sd*bc*sc*i*': 'mlx5_core',
        'pci:v00008086d0000159Bsv*sd*bc*sc*i*': 'ice',
        'pci:v*d*sv*sd*bc01sc08i02*': 'nvme',
    },
    'usb': {
        'usb:v*p*d*dc*dsc*dp*ic08isc06ip50in*': 'usb_storage',
    },
}


def _device(modalias):
    return {u'MODALIAS': modalias}


class Test(unittest.TestCase):
    def test_findsDriverByVendorAndDevice(self):
        device = _device('pci:v000015B3d0000101Fsv000015B3sd00000001bc02sc00i00')
        self.assertEquals(udev._findDriver(device, ALIAS_TABLE), 'mlx5_core')

    def test_findsDriverByClass(self):
        device = _device('pci:v0000144Dd0000A808sv0000144Dsd0000A801bc01sc08i02')
        self.assertEquals(udev._findDriver(device, ALIAS_TABLE), 'nvme')

    def test_noDriverForUnknownDevice(self):
        device = _device('pci:v000015B3d00001021sv000015B3sd00000001bc02sc00i00')
        self.assertIs(udev._findDriver(device, ALIAS_TABLE), None)

    def test_noDriverForUnknownSubsystem(self):
        self.assertIs(udev._findDriver(_device('acpi:PNP0C0F:'), ALIAS_TABLE), None)

    def test_aliasOfOneSubsystemDoesNotMatchAnother(self):
        device = _device('usb:v000015B3p0000101Fd0000dc00dsc00dp00ic02isc00ip00in00')
        self.assertIs(udev._findDriver(device, ALIAS_TABLE), None)


if __name__ == '__main__':
    unittest.main()
