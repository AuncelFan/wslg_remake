"""Real private-socket protocol tests; not GPU/desktop acceptance tests."""
import os
from pathlib import Path
import selectors
import shlex
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SeatGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="wslg-seat-guard-")
        cls.base = Path(cls.temporary.name)
        cls.guard = cls.base / "wait-wayland-seat"
        cls.fixture = cls.base / "seat-fixture"
        for source, target, package in [
            (ROOT / "tools/portal/wait_wayland_seat.c", cls.guard, "wayland-client"),
            (ROOT / "tests/wayland_seat_fixture.c", cls.fixture, "wayland-server"),
        ]:
            flags = shlex.split(subprocess.check_output(["pkg-config", "--cflags", "--libs", package], text=True))
            subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(target), *flags], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_case(self, mode, expected, minimum=0):
        with tempfile.TemporaryDirectory(prefix="runtime-", dir=self.base) as runtime:
            env = os.environ.copy()
            env.update(XDG_RUNTIME_DIR=runtime, WAYLAND_DISPLAY="seat-test")
            env.pop("WAYLAND_SOCKET", None)
            server = subprocess.Popen([str(self.fixture), "seat-test", str(mode)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(server.stdout, selectors.EVENT_READ)
                    self.assertTrue(selector.select(3), "fixture did not become ready")
                self.assertEqual(server.stdout.readline().strip(), "ready")
                started = time.monotonic()
                client = subprocess.run([str(self.guard), "--timeout-ms=900"], env=env, text=True, capture_output=True, timeout=3)
                self.assertEqual(client.returncode, expected, client.stderr)
                self.assertGreaterEqual(time.monotonic() - started, minimum)
                self.assertLess(time.monotonic() - started, 2)
            finally:
                if server.poll() is None:
                    server.terminate()
                _, error = server.communicate(timeout=3)
                self.assertNotIn("guard must not request", error)

    def test_ready_seat(self): self.run_case(0, 0)
    def test_late_seat_waits(self): self.run_case(1, 0, .1)
    def test_late_capabilities_waits(self): self.run_case(2, 0, .1)
    def test_removed_seat_and_replacement(self): self.run_case(3, 0, .25)
    def test_connection_loss_fails_closed(self): self.run_case(4, 1, .1)
    def test_missing_keyboard_times_out(self): self.run_case(5, 75, .7)
    def test_no_seat_times_out(self): self.run_case(6, 75, .7)
    def test_invalid_timeout(self):
        for value in ["0", "-1", "abc", "120001", "", "10x"]:
            with self.subTest(value=value):
                self.assertEqual(subprocess.run([str(self.guard), "--timeout-ms=" + value]).returncode, 64)


if __name__ == "__main__": unittest.main()
