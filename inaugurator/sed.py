
import re
import time
import logging
import tempfile
import requests
from inaugurator import sh
from subprocess import CalledProcessError, Popen


class Sed:
    def __init__(self, nvme_list, selftest_url):
        self.nvme_list = nvme_list
        self.selftest_url = selftest_url
        self.seds = self.get_all_sed_devices()

    def get_all_sed_devices(self):
        """
        command: `sedutil-cli --scan`
        output:
            Scanning for Opal compliant disks
            /dev/nvme0  2      INTEL SSDPE2KX080T8O                     VDV10184
            /dev/nvme1  2      SAMSUNG MZWLJ1T9HBJR-00007               EPK9CB5Q
            /dev/nvme2  2      SAMSUNG MZWLJ1T9HBJR-00007               EPK9CB5Q
            /dev/nvme3  2      SAMSUNG MZWLJ1T9HBJR-00007               EPK9CB5Q
            /dev/nvme4  2      SAMSUNG MZWLJ1T9HBJR-00007               EPK9CB5Q

        command: `sedutil-cli --query /dev/nvme0`
        output:
            /dev/nvme0 NVMe INTEL SSDPE2KX080T8O                     VDV10184 PHLJ128000PC8P0HGN
            TPer function (0x0001)
                ACKNAK = N, ASYNC = N. BufferManagement = N, comIDManagement  = N, Streaming = Y, SYNC = Y
            Locking function (0x0002)
                Locked = N, LockingEnabled = N, LockingSupported = Y, MBRDone = N, MBREnabled = N, MBRAbsent = N, MediaEncrypt = Y
            Geometry function (0x0003)
                Align = Y, Alignment Granularity = 8 (4096), Logical Block size = 512, Lowest Aligned LBA = 0
            SingleUser function (0x0201)
                ALL = N, ANY = N, Policy = Y, Locking Objects = 9
            DataStore function (0x0202)
                Max Tables = 10, Max Size Tables = 10485760, Table size alignment = 4096
            OPAL 2.0 function (0x0203)
                Base comID = 0x0800, Initial PIN = 0x00, Reverted PIN = 0x00, comIDs = 1
                Locking Admins = 4, Locking Users = 9, Range Crossing = Y
            Block SID Authentication function (0x0402)
                SID Blocked State = N, SID Value State = N, Hardware Reset = N

            TPer Properties:
              MaxComPacketSize = 19968  MaxResponseComPacketSize = 19968
              MaxPacketSize = 19948  MaxIndTokenSize = 19912  MaxPackets = 1
              MaxSubpackets = 1  MaxMethods = 1  MaxSessions = 1
              MaxAuthentications = 2  MaxTransactionLimit = 1  DefSessionTimeout = 300000
              MaxSessionTimeout = 0  MinSessionTimeout = 5000  DefTransTimeout = 2000
              MaxTransTimeout = 10000  MinTransTimeout = 500  MaxComIDTime = 1000

            Host Properties:
              MaxComPacketSize = 2048  MaxPacketSize = 2028
              MaxIndTokenSize = 1992  MaxPackets = 1  MaxSubpackets = 1
              MaxMethods = 1
            """
        seds = {}
        try:
            r = sh.run("sedutil-cli --scan")
            devices = re.findall("(/dev/nvme\d+)\s+", r)
            if not devices:
                return {}
            for dev in devices:
                try:
                    r = sh.run("sedutil-cli --query {}".format(dev))
                    dev_info = re.findall("(/dev/nvme\d+.+|$)", r)[0].strip().split(" ")
                    if not dev_info:
                        continue
                    is_nvme = dev_info[1].lower() == "nvme"
                    if is_nvme:
                        isn = dev_info[-1]
                        seds[isn] = {"device": dev}
                except Exception as e:
                    logging.error(e)
            return seds
        except (CalledProcessError, Exception), e:
            logging.error(e)
            return {}

    def get_sed(self, isn):
        return self.seds.get(isn, None)

    def reset_seds(self):
        cmds = self._construct_cmds()
        procs = self._get_all_procs(cmds)
        for p in procs:
            while p.poll() is None:
                time.sleep(0.1)
            device = self._get_device_path_from_isn(p.isn)
            if p.returncode != 0:
                err = self._find_error_msg_in_file(p.ferr.name)
                err_msg = "device {} failed to reset. reason: {}".format(device, err)
                logging.error(err_msg)
                self.seds[p.isn]["error"] = err_msg
            else:
                logging.info("%s reset successfully", device)
            p.ferr.close()

    def _get_device_path_from_isn(self, isn):
        devices = self.nvme_list.get("Devices", None)
        if not devices:
            return "Unknown"
        for nvme in devices:
            if nvme["SerialNumber"] == isn:
                return nvme["DevicePath"]
        return "Unknown"

    def _find_error_msg_in_file(self, fname):
        with open(fname, "rb") as f:
            output = f.read().strip().split("\n")
            return "; ".join(output)

    def _get_all_procs(self, cmds):
        procs = []
        for cmd, isn in cmds:
            try:
                ferr = tempfile.NamedTemporaryFile()
                logging.debug("Executing command %s", cmd)
                p = Popen(cmd, shell=True, stderr=ferr)
                p.ferr, p.isn = ferr, isn
                procs.append(p)
            except (CalledProcessError, Exception), e:
                dev = self._get_device_path_from_isn(isn)
                err_msg = "device {} failed to reset. reason: {}".format(dev, e)
                logging.error(err_msg)
                self.seds[isn]["error"] = err_msg
        return procs

    def _construct_cmds(self):
        cmds = []
        cmd = "sedutil-cli --PSIDrevert {} {}"
        for isn, data in self.seds.items():
            psid = self._get_psid_from_isn(isn)
            device = data["device"]
            if not psid:
                nvme_dev = self._get_device_path_from_isn(isn)
                err_msg = "psid is not available for dev {} with isn: {}".format(nvme_dev, isn)
                logging.error(err_msg)
                data["error"] = err_msg
            else:
                cmds.append((cmd.format(psid, device), isn))
        return cmds

    def _get_psid_from_isn(self, isn):
        try:
            full_url = "http://{}/sed/{}/psid".format(self.selftest_url, isn)
            r = requests.get(full_url)
            if not r.ok:
                raise Exception("No psid found for isn {}".format(isn))
            return r.json()
        except Exception as e:
            logging.error(e)

