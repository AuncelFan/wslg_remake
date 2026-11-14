#!/usr/bin/env python3
"""Experimental single-handoff broker; run inside the Fcitx user's distro.

This does not start/reconfigure Fcitx, edit Weston, or auto-activate a DBus
service. The intended daemon enables wayland/waylandim with
--option=wayland=nodefault. Use isolated XDG directories AND a private bus
for experiments. A successful handoff is not Chinese-input acceptance.
"""
from __future__ import annotations

import argparse
import array
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import stat
import struct


def peer_uid(connection: socket.socket) -> int:
    return struct.unpack("3i", connection.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))[1]


def receive_wayland_fd(connection: socket.socket) -> int:
    """Reject malformed/multi-FD packets and close every received descriptor."""
    descriptors = array.array("i")
    try:
        data, controls, flags, _ = connection.recvmsg(
            8, socket.CMSG_SPACE(16 * descriptors.itemsize), socket.MSG_CMSG_CLOEXEC)
        for level, kind, content in controls:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                usable = len(content) - len(content) % descriptors.itemsize
                descriptors.frombytes(content[:usable])
        if data != b"WSLGIME1" or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
            raise ValueError("invalid or truncated descriptor packet")
        if len(descriptors) != 1:
            raise ValueError("exactly one descriptor is required")
        if not stat.S_ISSOCK(os.fstat(descriptors[0]).st_mode):
            raise ValueError("Wayland descriptor must be a socket")
        with socket.socket(fileno=os.dup(descriptors[0])) as probe:
            if probe.family != socket.AF_UNIX or probe.type != socket.SOCK_STREAM:
                raise ValueError("Wayland descriptor must be an AF_UNIX stream socket")
        result = descriptors.pop()
        return result
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def forward_to_fcitx(connection, fd: int) -> tuple[str, object]:
    from gi.repository import Gio, GLib
    owner = connection.call_sync(
        "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
        "GetNameOwner", GLib.Variant("(s)", ("org.fcitx.Fcitx5",)),
        GLib.VariantType.new("(s)"), Gio.DBusCallFlags.NO_AUTO_START, 3000, None,
    ).unpack()[0]
    unix_fds = Gio.UnixFDList.new()
    index = unix_fds.append(fd)
    connection.call_with_unix_fd_list_sync(
        owner, "/controller", "org.fcitx.Fcitx.Controller1",
        "OpenWaylandConnectionSocket", GLib.Variant("(h)", (index,)),
        GLib.VariantType.new("()"), Gio.DBusCallFlags.NO_AUTO_START,
        8000, unix_fds, None,
    )
    return owner, connection


def serve(path: Path, bus_address: str, wait_seconds: float,
          recover_stale: bool = False) -> None:
    from gi.repository import Gio, GLib
    if not path.is_absolute() or len(os.fsencode(path)) >= 108:
        raise ValueError("use a short absolute Unix socket path")
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or \
            stat.S_IMODE(parent.st_mode) != 0o700:
        raise ValueError("socket directory must be owned by this uid with mode 0700")
    lock_fd = os.open(str(path)+'.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    lock_stat = os.fstat(lock_fd)
    if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_uid != os.getuid() or \
            stat.S_IMODE(lock_stat.st_mode) != 0o600:
        os.close(lock_fd)
        raise PermissionError('broker lock must be a private regular file')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path.exists() or path.is_symlink():
            previous = path.lstat()
            if not recover_stale or not stat.S_ISSOCK(previous.st_mode) or \
                    previous.st_uid != os.getuid() or stat.S_IMODE(previous.st_mode) != 0o600:
                raise FileExistsError('refusing to replace an unverified socket path')
            path.unlink()
    except BaseException:
        os.close(lock_fd)
        raise
    bus = Gio.DBusConnection.new_for_address_sync(
        bus_address,
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT |
        Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
    bus.set_exit_on_close(False)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    bound_inode = None
    try:
        listener.bind(str(path))
        bound_inode = path.lstat().st_ino
        path.chmod(0o600)
        listener.listen(1)
        listener.settimeout(wait_seconds)
        print(json.dumps({"event": "listening", "uid": os.getuid()}), flush=True)
        with listener.accept()[0] as client:
            if peer_uid(client) != os.getuid():
                raise PermissionError("helper uid does not match broker uid")
            client.settimeout(10)
            fd = receive_wayland_fd(client)
            try:
                owner, _ = forward_to_fcitx(bus, fd)
            finally:
                os.close(fd)
            client.sendall(b"O")
            client.setblocking(False)
            print(json.dumps({"event": "fcitx-handoff-confirmed"}), flush=True)
            loop = GLib.MainLoop()

            def owner_changed(_bus, _sender, _path, _interface, _signal, params):
                _name, old, new = params.unpack()
                if old == owner and new != owner:
                    loop.quit()

            def relay_changed(_fd, _condition):
                loop.quit()
                return False

            subscription = bus.signal_subscribe(
                "org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
                "/org/freedesktop/DBus", "org.fcitx.Fcitx5",
                Gio.DBusSignalFlags.NONE, owner_changed)
            watch = GLib.io_add_watch(
                client.fileno(), GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                relay_changed)
            def stop_loop():
                loop.quit()
                return True
            signals = [GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, stop_loop)
                       for sig in (signal.SIGINT, signal.SIGTERM)]
            # Cover a daemon exit between handoff and subscription.
            current = bus.call_sync(
                "org.freedesktop.DBus", "/org/freedesktop/DBus",
                "org.freedesktop.DBus", "GetNameOwner",
                GLib.Variant("(s)", ("org.fcitx.Fcitx5",)),
                GLib.VariantType.new("(s)"), Gio.DBusCallFlags.NO_AUTO_START,
                3000, None).unpack()[0]
            if current == owner:
                loop.run()
            bus.signal_unsubscribe(subscription)
            # io_add_watch is removed by GLib after its callback returns False.
            context = GLib.MainContext.default()
            if context.find_source_by_id(watch):
                GLib.source_remove(watch)
            for source in signals:
                GLib.source_remove(source)
    finally:
        listener.close()
        if bound_inode is not None:
            try:
                if path.lstat().st_ino == bound_inode:
                    path.unlink()
            except FileNotFoundError:
                pass
        bus.close_sync(None)
        os.close(lock_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True, type=Path)
    parser.add_argument("--bus-address", default=os.environ.get("DBUS_SESSION_BUS_ADDRESS"))
    parser.add_argument("--wait-seconds", type=float, default=30)
    parser.add_argument("--recover-stale", action="store_true",
                        help="recover this private service socket under an exclusive lock")
    args = parser.parse_args()
    if not args.bus_address:
        parser.error("a user session DBus address is required")
    if not 0 < args.wait_seconds <= 3600:
        parser.error("wait-seconds must be between 0 and 3600")
    serve(args.socket, args.bus_address, args.wait_seconds, args.recover_stale)


if __name__ == "__main__":
    main()
