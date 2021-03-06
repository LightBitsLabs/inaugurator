import os
import logging
from inaugurator import sh


USER_SETTINGS_DIR = "etc/default"
USER_SETTINGS_FILENAME = "grub"


def modifyingGrubConf(userSettingsFileHandler, existingConfiguration, serialDevices, passThroughArgs):
    serialDevices = serialDevices or []
    passThroughArgs = passThroughArgs or ""
    wasGrubCmdlineLinuxParameterWritten = False
    logging.info("Modifying GRUB2 user settings file...")
    for line in existingConfiguration.splitlines():
        line = line.strip()
        if line.startswith("GRUB_CMDLINE_LINUX="):
            wasGrubCmdlineLinuxParameterWritten = True
            maxSplit = 1
            cmdline = line.split("=", maxSplit)[1].strip(" \"")
            argsWithoutConsole = [arg for arg in cmdline.split(" ") if not arg.startswith("console=")]
            configurationWithoutConsole = " ".join(argsWithoutConsole)
            consoleConfiguration = " ".join(["console=%s" % (device,) for device in serialDevices])
            passThroughArgsStringify = " ".join(passThroughArgs.split(","))
            line = "GRUB_CMDLINE_LINUX=\"%(configurationWithoutConsole)s %(consoleConfiguration)s %(passThroughArgs)s\"" % \
                dict(configurationWithoutConsole=configurationWithoutConsole,
                     consoleConfiguration=consoleConfiguration,
                     passThroughArgs=passThroughArgsStringify)
        userSettingsFileHandler.write(line)
        userSettingsFileHandler.write(os.linesep)
    if not wasGrubCmdlineLinuxParameterWritten:
        userSettingsFileHandler.write("# Generated by Inaugurator\n")
        userSettingsFileHandler.write("GRUB_CMDLINE_LINUX=\"%s\"\n" % (consoleConfiguration,))


def getUserSettingFileName(destination):
    destUserSettingsDir = os.path.join(destination, USER_SETTINGS_DIR)
    if os.path.isfile(destUserSettingsDir):
        logging.warning("It seems that there's a file instead of a directory in GRUB2's user settings path "
                        " (%(path)s). Removing it...", dict(path=destUserSettingsDir))
        os.unlink(destUserSettingsDir)
    if not os.path.exists(destUserSettingsDir):
        os.makedirs(destUserSettingsDir)
    return os.path.join(destUserSettingsDir, USER_SETTINGS_FILENAME)


def getExistingConfiguration(destUserSettingsFilename):
    existingConfiguration = ""
    if os.path.isfile(destUserSettingsFilename):
        logging.info("GRUB2's user settings file already exists. Reading it...")
        with open(destUserSettingsFilename, "r") as grubDefaultConfig:
            existingConfiguration = grubDefaultConfig.read()
    elif os.path.exists(destUserSettingsFilename):
        logging.warning("It seems that there is a non-file in GRUB2's user settings path: %(path)s. Will not"
                        "modify GRUB2 settings.", dict(path=destUserSettingsFilename))
    return existingConfiguration


def updateGrubConf(serialDevices, destination, passThroughArgs):
    destUserSettingsFilename = getUserSettingFileName(destination)
    existingConfiguration = getExistingConfiguration(destUserSettingsFilename)
    with open(destUserSettingsFilename, 'wb') as default_grub:
        modifyingGrubConf(default_grub,
                          existingConfiguration,
                          serialDevices,
                          passThroughArgs)


def grub_prefix(destination):
    if sh.has_tool(destination, 'grub2-install'):
        return 'grub2'
    if sh.has_tool(destination, 'grub-install'):
        return 'grub'
    return None


def install(targetDevice, destination):

    prefix = grub_prefix(destination)
    if prefix is None:
        raise Exception("Failed to install grub boot menu grub tools not found")

    chrootScript = '%(prefix)s-install %(targetDevice)s && %(prefix)s-mkconfig > /boot/%(prefix)s/grub.cfg' % dict(
        prefix=prefix, targetDevice=targetDevice)

    sh.run("/usr/sbin/busybox chroot %s sh -c '%s'" % (destination, chrootScript))
