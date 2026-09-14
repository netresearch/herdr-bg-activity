import fcntl
import os
import stat
import tempfile
import unittest
from unittest import mock

import fakes  # noqa: F401 - puts the plugin module on sys.path

from herdr_bg_activity import acquire_lock, lock_path

SOCKET = "/home/user/.config/herdr/herdr.sock"


class LockPathTest(unittest.TestCase):
    def test_uses_runtime_dir_not_herdr_dir(self):
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/1000"}):
            path = lock_path(SOCKET)
        self.assertEqual(os.path.dirname(path), "/run/user/1000")
        self.assertIn(f"-{os.getuid()}-", os.path.basename(path))

    def test_falls_back_to_temp_dir(self):
        env = {k: v for k, v in os.environ.items() if k != "XDG_RUNTIME_DIR"}
        with mock.patch.dict(os.environ, env, clear=True):
            path = lock_path(SOCKET)
        self.assertEqual(os.path.dirname(path), tempfile.gettempdir())

    def test_same_session_same_lock_other_session_other_lock(self):
        self.assertEqual(lock_path(SOCKET), lock_path(SOCKET))
        other = "/home/user/.config/herdr/sessions/work/herdr.sock"
        self.assertNotEqual(lock_path(SOCKET), lock_path(other))


class AcquireLockTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "x.lock")

    def tearDown(self):
        self.dir.cleanup()

    def test_creates_private_file_and_holds_the_lock(self):
        fd = acquire_lock(self.path)
        try:
            self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
            other = os.open(self.path, os.O_WRONLY)
            try:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(other)
        finally:
            os.close(fd)

    def test_tightens_mode_of_existing_file(self):
        with open(self.path, "w"):
            pass
        os.chmod(self.path, 0o644)
        os.close(acquire_lock(self.path))
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_refuses_file_owned_by_another_user(self):
        real_fstat = os.fstat

        def foreign_fstat(fd):
            info = real_fstat(fd)
            fields = list(info)
            fields[stat.ST_UID] = info.st_uid + 1
            return os.stat_result(fields)

        closed = []
        real_close = os.close
        with (
            mock.patch("herdr_bg_activity.os.fstat", side_effect=foreign_fstat),
            mock.patch(
                "herdr_bg_activity.os.close",
                side_effect=lambda fd: (closed.append(fd), real_close(fd)),
            ),
            mock.patch("herdr_bg_activity.fcntl.flock") as flock,
            self.assertRaises(PermissionError),
        ):
            acquire_lock(self.path)
        flock.assert_not_called()
        self.assertEqual(len(closed), 1)

    def test_refuses_planted_symlink(self):
        target = os.path.join(self.dir.name, "victim")
        os.symlink(target, self.path)
        with self.assertRaises(OSError):
            acquire_lock(self.path)
        self.assertFalse(os.path.exists(target))


if __name__ == "__main__":
    unittest.main()
