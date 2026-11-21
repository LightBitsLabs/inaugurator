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

    def test_aFailingCommandRaisesCalledProcessError(self):
        with self.assertRaises(subprocess.CalledProcessError):
            run("exit 3", timeout=10)


if __name__ == '__main__':
    unittest.main()
