import os
import signal
import subprocess
import threading


logFilepath = None


class TimeoutExpired(Exception):
    pass


_KILL_GRACE_SECONDS = 10


def _outputWithin(process, timeout):
    """Returns (output, expired). A command still running after timeout seconds is killed, and
    then waited for only briefly: a process stuck inside the kernel cannot die, and a child
    that moved to another session keeps the pipe open, so the read may never end."""
    collected = []
    reader = threading.Thread(target=lambda: collected.append(process.communicate()[0]))
    reader.daemon = True
    reader.start()
    reader.join(timeout)
    if not reader.isAlive():
        return collected[0], False
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    reader.join(_KILL_GRACE_SECONDS)
    return (collected[0] if collected else ""), True


def run(* args, ** kwargs):
    """timeout, in seconds, kills a command that is still running by then and raises TimeoutExpired."""
    timeout = kwargs.pop("timeout", None)
    commandRepr = " ".join(args)
    message = "\n\nExecuting Command: %s\n\n" % (commandRepr,)
    if logFilepath is None:
        print message
    expired = False
    if timeout is not None:
        # The command runs under a shell; only a process group of its own lets the kill reach
        # the shell's children.
        kwargs["preexec_fn"] = os.setsid
    cmdPipe = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True, shell=True, ** kwargs)
    if timeout is None:
        output, _ = cmdPipe.communicate()
    else:
        output, expired = _outputWithin(cmdPipe, timeout)
    if logFilepath is not None:
        try:
            with open(logFilepath, "a+") as f:
                f.write(message)
                if output is not None:
                    f.write(output)
                    f.flush()
        except Exception as ex:
            print "Cannot write to log file: %s" % ex.args
    if expired:
        print "Command '%s' did not finish in %d seconds and was killed\n%s" % (args, timeout, output)
        raise TimeoutExpired("Command '%s' did not finish in %d seconds" % (commandRepr, timeout))
    if cmdPipe.returncode != 0:
        ex = subprocess.CalledProcessError(cmdPipe.returncode, commandRepr, output)
        print "Command '%s' failed: %d\n%s" % (args, cmdPipe.returncode, output)
        raise ex
    return output


def has_tool(rootPath, tool):
    try:
        run("/usr/sbin/busybox chroot %s sh -c 'which %s'" % (rootPath, tool))
        return True
    except:
        return False
