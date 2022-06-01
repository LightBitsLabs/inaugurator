
import re
import json
import time
import logging
import tempfile
import requests
from inaugurator import sh
from subprocess import CalledProcessError, Popen



def get_all_sed_devices():
    try:
        r = sh.run("lb-sed scan --plugin go")
        devices = json.loads(r)
        return {d["Device"]: {"isn": d["Identity"]["SerialNumber"]} for d in devices if
                d["Identity"]["Protocol"].lower() == "nvme"}
    except (CalledProcessError, Exception), e:
        logging.error(e)
        return {}


def reset_seds(seds, selftest_url):
    cmds = construct_cmds(seds, selftest_url)
    procs = get_all_procs(cmds, seds)

    for p in procs:
        while p.poll() is None:
            time.sleep(0.1)
        if p.returncode != 0:
            err = find_error_msg_in_file(p.ferr.name)
            err_msg = "device {} failed to reset. reason: {}".format(p.dev, err)
            logging.error(err_msg)
            seds[p.dev]["error"] = err_msg
        else:
            logging.info("%s reset successfully", p.dev)
        p.ferr.close()

def find_error_msg_in_file(fname):
    with open(fname, "rb") as f:
        output = f.read()
        err = re.findall("Error:.+?(?=\\n)|$", output)[0]
        return err

def get_all_procs(cmds, seds):
    procs = []
    for cmd, dev in cmds:
        try:
            ferr = tempfile.NamedTemporaryFile()
            logging.debug("Executing command %s", cmd)
            p = Popen(cmd, shell=True, stderr=ferr)
            p.dev, p.ferr = dev, ferr
            procs.append(p)
        except (CalledProcessError, Exception), e:
            err_msg = "device {} failed to reset. reason: {}".format(dev, e)
            logging.error(err_msg)
            seds[dev]["error"] = err_msg
    return procs


def construct_cmds(seds, selftest_url):
    cmds = []
    cmd = "lb-sed reset --authority=PSID --passphrase {} --plugin go {}"
    for dev, data in seds.items():
        psid = get_psid_from_isn(data["isn"], selftest_url)
        if not psid:
            err_msg = "psid is not available for dev {} with isn: {}".format(dev, data["isn"])
            logging.error(err_msg)
            data["error"] = err_msg
        else:
            cmds.append((cmd.format(psid, dev), dev))

    return cmds


def get_psid_from_isn(isn, selftest_url):
    try:
        full_url = "http://{}/sed/{}/psid".format(selftest_url, isn)
        r = requests.get(full_url)
        if not r.ok:
            raise Exception("No psid found for isn {}".format(isn))
        return r.json()
    except Exception as e:
        logging.error(e)
