import errno
import os
import subprocess
import time
import unittest
from inaugurator import sh

# other test modules replace sh.run with a fake and leave it there
run = sh.run


class Test(unittest.TestCase):
    def test_returnsTheOutputOfACommandThatFinishesInTime(self):
        self.assertEquals(run("echo hello", timeout=10), "hello\n")

    def test_runsToCompletionWithoutATimeout(self):
        self.assertEquals(run("sleep 0.2; echo done"), "done\n")

    def test_killsACommandThatOutlivesItsTimeout(self):
        before = time.time()
        with self.assertRaises(sh.TimeoutExpired):
            run("sleep 30", timeout=0.3)
        self.assertLess(time.time() - before, 5)

    def test_killsTheChildrenOfTheShellToo(self):
        before = time.time()
        with self.assertRaises(sh.TimeoutExpired):
            run("sleep 30 & sleep 30", timeout=0.3)
        self.assertLess(time.time() - before, 5)

    def test_doesNotWaitForAChildThatEscapedTheKillAndKeepsThePipeOpen(self):
        grace, sh._KILL_GRACE_SECONDS = sh._KILL_GRACE_SECONDS, 0.5
        try:
            before = time.time()
            with self.assertRaises(sh.TimeoutExpired):
                run("setsid sleep 8 & sleep 8", timeout=0.3)
            self.assertLess(time.time() - before, 4)
        finally:
            sh._KILL_GRACE_SECONDS = grace

    def test_keepsTheOutputOfACommandItHadToAbandon(self):
        grace, sh._KILL_GRACE_SECONDS = sh._KILL_GRACE_SECONDS, 0.5
        try:
            process = subprocess.Popen(
                "echo before; setsid sleep 8 & sleep 8", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                shell=True, preexec_fn=os.setsid)
            self.assertEquals(sh._outputWithin(process, 0.3), ("before\n", True))
        finally:
            sh._KILL_GRACE_SECONDS = grace

    def test_stopsReadingACommandItHadToAbandon(self):
        grace, sh._KILL_GRACE_SECONDS = sh._KILL_GRACE_SECONDS, 0.5
        try:
            process = subprocess.Popen(
                "setsid sh -c 'for i in $(seq 80); do echo tick || exit; sleep 0.1; done' & sleep 8",
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True, preexec_fn=os.setsid)
            self.assertTrue(sh._outputWithin(process, 0.3)[1])
            deadline = time.time() + 3
            while not process.stdout.closed and time.time() < deadline:
                time.sleep(0.05)
            self.assertTrue(process.stdout.closed)
        finally:
            sh._KILL_GRACE_SECONDS = grace

    def test_readsOnWhenASignalInterruptsTheRead(self):
        process = subprocess.Popen("echo hello", stdout=subprocess.PIPE, shell=True)
        realRead, interruptions = os.read, [errno.EINTR]

        def read(fd, size):
            if interruptions:
                raise OSError(interruptions.pop(), "Interrupted system call")
            return realRead(fd, size)
        os.read = read
        try:
            self.assertEquals(sh._outputWithin(process, 10), ("hello\n", False))
        finally:
            os.read = realRead

    def test_aReaderThatFailsRaisesItsOwnErrorAndKillsTheCommand(self):
        process = subprocess.Popen(
            "echo hello; sleep 30", stdout=subprocess.PIPE, shell=True, preexec_fn=os.setsid)
        realRead = os.read

        def read(fd, size):
            raise OSError(errno.EIO, "Input/output error")
        os.read = read
        try:
            with self.assertRaises(OSError) as raised:
                sh._outputWithin(process, 10)
        finally:
            os.read = realRead
        self.assertEquals(raised.exception.errno, errno.EIO)
        self.assertEquals(process.wait(), -9)

    def test_aFailingCommandRaisesCalledProcessError(self):
        with self.assertRaises(subprocess.CalledProcessError):
            run("exit 3", timeout=10)


if __name__ == '__main__':
    unittest.main()
