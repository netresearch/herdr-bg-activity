import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from herdr_bg_activity import MAX_CONNECT_FAILURES, Publisher, run


class ScriptedHerdr:
    """Raises the scripted exceptions for agent.list, one per tick."""

    def __init__(self, errors):
        self.errors = list(errors)
        self.ticks = 0

    def call(self, method, params):
        if method == "agent.list":
            self.ticks += 1
            raise self.errors.pop(0)
        raise AssertionError(f"unexpected call {method}")


class RunTest(unittest.TestCase):
    def run_quietly(self, herdr):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = run(herdr, Publisher(herdr), sleep=lambda _: None)
        return code, stderr.getvalue()

    def test_unexpected_error_does_not_stop_the_poller(self):
        errors = [TypeError("'NoneType' object is not iterable")]
        errors += [OSError("gone")] * MAX_CONNECT_FAILURES
        herdr = ScriptedHerdr(errors)
        code, log = self.run_quietly(herdr)
        self.assertEqual(code, 0)
        self.assertEqual(herdr.ticks, 1 + MAX_CONNECT_FAILURES)
        self.assertIn("tick failed: TypeError", log)

    def test_repeated_error_is_logged_once(self):
        errors = [TypeError("same")] * 3 + [OSError("gone")] * MAX_CONNECT_FAILURES
        _, log = self.run_quietly(ScriptedHerdr(errors))
        self.assertEqual(log.count("tick failed"), 1)

    def test_other_error_breaks_the_connection_failure_streak(self):
        errors = [OSError("gone")] * (MAX_CONNECT_FAILURES - 1)
        errors += [TypeError("answered")]
        errors += [OSError("gone")] * MAX_CONNECT_FAILURES
        herdr = ScriptedHerdr(errors)
        code, _ = self.run_quietly(herdr)
        self.assertEqual(code, 0)
        self.assertEqual(herdr.ticks, 2 * MAX_CONNECT_FAILURES)

    def test_exits_after_consecutive_connection_failures(self):
        herdr = ScriptedHerdr([OSError("gone")] * MAX_CONNECT_FAILURES)
        code, log = self.run_quietly(herdr)
        self.assertEqual(code, 0)
        self.assertIn("herdr unreachable", log)


if __name__ == "__main__":
    unittest.main()
