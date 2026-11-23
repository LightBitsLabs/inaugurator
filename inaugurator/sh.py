import errno
import os
import signal
import subprocess
import sys
import threading


logFilepath = None


class TimeoutExpired(Exception):
    pass


_KILL_GRACE_SECONDS = 10


def _outputWithin(process, timeout):
    """Returns (output, expired). A command still running after timeout seconds is killed, and
    then waited for only briefly: a process stuck inside the kernel cannot die, and a child
    that moved to another session keeps the pipe open, so the read may never end. What the
    command wrote until then is returned: it is the only trace of where it hung."""
    chunks = []
    failure = []
    abandoned = threading.Event()

    def readUntilTheEnd():
        while True:
            try:
                chunk = os.read(process.stdout.fileno(), 65536)
            except OSError as e:
                if e.errno == errno.EINTR:
                    continue
                raise
            if not chunk:
                break
            if abandoned.isSet():
                # a writer that escaped the kill must not grow this list for as long as it lives
                process.stdout.close()
                return
            chunks.append(chunk)
        process.wait()

    def read():
        try:
            readUntilTheEnd()
        except Exception:
            failure.append(sys.exc_info())

    def kill():
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
    reader = threading.Thread(target=read)
    reader.daemon = True
    reader.start()
    reader.join(timeout)
    if not reader.isAlive():
        if failure:
            # without its reader the command has no one to wait for it
            kill()
            raise failure[0][0], failure[0][1], failure[0][2]
        return "".join(chunks), False
    kill()
    reader.join(_KILL_GRACE_SECONDS)
    abandoned.set()
    return "".join(chunks), True


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
