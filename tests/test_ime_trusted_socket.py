"""Linux transport checks; do not treat these as desktop IME acceptance."""
import array
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ime_broker", ROOT / "tools/ime/trusted_socket_broker.py")
BROKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BROKER)


@unittest.skipUnless(hasattr(socket, "SCM_RIGHTS"), "requires Linux Unix FD passing")
class DescriptorPacketTest(unittest.TestCase):
    def setUp(self):
        self.sender, self.receiver = socket.socketpair(
            socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.peer, self.wayland = socket.socketpair()
        self.addCleanup(self.sender.close)
        self.addCleanup(self.receiver.close)
        self.addCleanup(self.peer.close)
        self.addCleanup(self.wayland.close)

    def send(self, payload, fds):
        self.sender.sendmsg([payload], [(
            socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds))])

    def count_fds(self):
        return len(os.listdir("/proc/self/fd"))

    def test_one_unix_stream_descriptor_preserves_channel(self):
        self.send(b"WSLGIME1", [self.wayland.fileno()])
        fd = BROKER.receive_wayland_fd(self.receiver)
        with socket.socket(fileno=fd) as transferred:
            self.assertFalse(os.get_inheritable(fd))
            self.peer.sendall(b"protocol bytes")
            self.assertEqual(transferred.recv(32), b"protocol bytes")

    def test_bad_magic_closes_received_descriptor(self):
        before = self.count_fds()
        self.send(b"INVALID!", [self.wayland.fileno()])
        with self.assertRaises(ValueError):
            BROKER.receive_wayland_fd(self.receiver)
        self.assertEqual(self.count_fds(), before)

    def test_multiple_descriptors_are_rejected_without_leak(self):
        before = self.count_fds()
        self.send(b"WSLGIME1", [self.wayland.fileno(), self.peer.fileno()])
        with self.assertRaises(ValueError):
            BROKER.receive_wayland_fd(self.receiver)
        self.assertEqual(self.count_fds(), before)

    def test_truncated_packet_is_rejected_without_leak(self):
        before = self.count_fds()
        self.send(b"WSLGIME1extra", [self.wayland.fileno()])
        with self.assertRaises(ValueError):
            BROKER.receive_wayland_fd(self.receiver)
        self.assertEqual(self.count_fds(), before)

    def test_pipe_descriptor_is_rejected_without_leak(self):
        read_fd, write_fd = os.pipe()
        self.addCleanup(os.close, read_fd)
        self.addCleanup(os.close, write_fd)
        before = self.count_fds()
        self.send(b"WSLGIME1", [read_fd])
        with self.assertRaises(ValueError):
            BROKER.receive_wayland_fd(self.receiver)
        self.assertEqual(self.count_fds(), before)

    def test_inet_socket_is_rejected_without_leak(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as inet:
            before = self.count_fds()
            self.send(b"WSLGIME1", [inet.fileno()])
            with self.assertRaises(ValueError):
                BROKER.receive_wayland_fd(self.receiver)
            self.assertEqual(self.count_fds(), before)


@unittest.skipUnless(os.environ.get("WSLG_IME_RELAY_BIN"), "set the compiled relay path")
class NativeRelayTest(unittest.TestCase):
    def setUp(self):
        self.binary = os.environ["WSLG_IME_RELAY_BIN"]
        self.directory = tempfile.TemporaryDirectory(prefix="ime-relay-test-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "broker.sock"
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.server.bind(str(self.path))
        self.path.chmod(0o600)
        self.server.listen(1)
        self.server.settimeout(3)
        self.addCleanup(self.server.close)
        self.peer, self.wayland = socket.socketpair()
        self.addCleanup(self.peer.close)
        self.addCleanup(self.wayland.close)

    def launch(self):
        env = os.environ.copy()
        env.update(WAYLAND_SOCKET=str(self.wayland.fileno()),
                   WSLG_IME_BRIDGE_SOCKET=str(self.path))
        return subprocess.Popen([self.binary], env=env,
                                pass_fds=[self.wayland.fileno()],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_native_handoff_and_broker_lifetime(self):
        process = self.launch()
        try:
            with self.server.accept()[0] as accepted:
                self.assertEqual(BROKER.peer_uid(accepted), os.getuid())
                fd = BROKER.receive_wayland_fd(accepted)
                accepted.sendall(b"O")
                with socket.socket(fileno=fd) as transferred:
                    self.peer.sendall(b"unmodified Wayland data")
                    self.assertEqual(transferred.recv(64), b"unmodified Wayland data")
                self.assertIsNone(process.poll())
            stdout, stderr = process.communicate(timeout=3)
            self.assertEqual(process.returncode, 0, stderr)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_relay_refuses_nonprivate_directory(self):
        Path(self.directory.name).chmod(0o755)
        process = self.launch()
        stdout, stderr = process.communicate(timeout=3)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn(b"mode 0700", stderr)

    def test_relay_refuses_nonprivate_socket(self):
        self.path.chmod(0o666)
        process = self.launch()
        stdout, stderr = process.communicate(timeout=3)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn(b"mode 0600", stderr)


if __name__ == "__main__":
    unittest.main()
