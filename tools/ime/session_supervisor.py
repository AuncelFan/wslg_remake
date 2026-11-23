#!/usr/bin/env python3
"""Couple the Ubuntu Fcitx daemon and trusted-FD broker in one user service.

Either child exiting ends this process, so systemd restarts both. This closes
the old trusted Wayland connection before Weston launches a new helper. A
broker restart never attaches a second parser to an existing Wayland stream.
"""
from __future__ import annotations
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import stat
import subprocess
import sys
import time


def log(event):
    print(json.dumps({'event': event}), flush=True)


def notify(address, message):
    if address:
        if address.startswith('@'):
            address = '\0' + address[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
            connection.sendto(message.encode(), address)


def monitor(bus, owner, GLib, Gio, children, health_fd, stopping, notify_address):
    ready = False
    handed_off = False
    deadline = time.monotonic() + 35
    heartbeat_deadline = None
    last_probe = 0
    ping_failures = 0
    while not stopping():
        if any(child.poll() is not None for child in children):
            log('child-exited-restart-required')
            return 1

        readable, _, _ = select.select([health_fd], [], [], .2)
        if readable:
            message = os.read(health_fd, 64)
            if not message:
                log('broker-health-channel-closed')
                return 1
            if b'R' in message:
                handed_off = True
            if handed_off:
                heartbeat_deadline = time.monotonic() + 18

        now = time.monotonic()
        if heartbeat_deadline is not None and now >= heartbeat_deadline:
            log('relay-heartbeat-timeout')
            return 1
        if not ready and now >= deadline:
            log('ime-readiness-timeout')
            return 1
        if not handed_off or now - last_probe < (4 if ready else 1):
            continue
        last_probe = now
        try:
            report, = bus.call_sync(
                owner, '/controller', 'org.fcitx.Fcitx.Controller1',
                'DebugInfo', None, GLib.VariantType.new('(s)'),
                Gio.DBusCallFlags.NO_AUTO_START, 1500, None).unpack()
        except GLib.Error:
            ping_failures += 1
            if ping_failures >= 2:
                log('fcitx-unresponsive')
                return 1
        else:
            # A live D-Bus connection can outlast the trusted Wayland frontend.
            # An empty group can exist before a keyboard seat is configured.
            context = re.search(r'^Group \[wayland:socket:\d+\] has (\d+) InputContext',
                                report, re.MULTILINE)
            if ready and context is None:
                log('fcitx-wayland-connection-lost')
                return 1
            if not ready and (context is None or int(context[1]) == 0):
                continue
            ping_failures = 0
            if not ready:
                ready = True
                log('wayland-input-ready')
                notify(notify_address, 'READY=1\nSTATUS=Fcitx connected to Weston')
            else:
                notify(notify_address, 'WATCHDOG=1')
    log('session-stopping')
    return 0


def name_owner(bus):
    from gi.repository import Gio, GLib
    try:
        return bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
            'org.freedesktop.DBus', 'GetNameOwner',
            GLib.Variant('(s)', ('org.fcitx.Fcitx5',)), GLib.VariantType.new('(s)'),
            Gio.DBusCallFlags.NO_AUTO_START, 2000, None).unpack()[0]
    except GLib.Error as error:
        if 'NameHasNoOwner' in str(error):
            return None
        raise


def main():
    from gi.repository import Gio, GLib
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', required=True, type=Path)
    parser.add_argument('--bus-address', default=os.environ.get('DBUS_SESSION_BUS_ADDRESS'))
    parser.add_argument('--fcitx-arg', action='append', default=[])
    args = parser.parse_args()
    if not args.bus_address:
        parser.error('user session DBus address is required')
    path = args.socket
    if not path.is_absolute() or len(os.fsencode(path)) >= 108:
        parser.error('use a short absolute Unix socket path')
    path.parent.mkdir(mode=0o700, exist_ok=True)
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or \
            stat.S_IMODE(parent.st_mode) != 0o700:
        raise PermissionError('bridge directory is not private')
    lock = os.open(path.parent / 'session.lock', os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    bus = Gio.DBusConnection.new_for_address_sync(args.bus_address,
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT |
        Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
    bus.set_exit_on_close(False)
    if name_owner(bus):
        raise RuntimeError('an existing Fcitx owns this bus; refusing to replace it')
    stopping = False
    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    fcitx = broker = None
    owner = None
    health_read = None
    try:
        env = os.environ.copy()
        notify_address = env.pop('NOTIFY_SOCKET', None)
        env.pop('WATCHDOG_PID', None)
        env.pop('WATCHDOG_USEC', None)
        for key in ('WAYLAND_SOCKET', 'LD_PRELOAD', 'NODE_OPTIONS', 'WAYLAND_DEBUG',
                    'MESA_DEBUG', 'MESA_LOG_FILE', 'LIBGL_DEBUG'):
            env.pop(key, None)
        fcitx_args = args.fcitx_arg or ['--enable=wayland,waylandim',
            '--option=wayland=nodefault', '--verbose=*=3,key_trace=0']
        fcitx = subprocess.Popen(['/usr/bin/fcitx5', '-D', '--keep', *fcitx_args], env=env)
        deadline = time.monotonic()+15
        while not stopping and fcitx.poll() is None and time.monotonic() < deadline:
            owner = name_owner(bus)
            if owner:
                pid = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
                    'org.freedesktop.DBus', 'GetConnectionUnixProcessID',
                    GLib.Variant('(s)', (owner,)), GLib.VariantType.new('(u)'),
                    Gio.DBusCallFlags.NO_AUTO_START, 2000, None).unpack()[0]
                if pid != fcitx.pid:
                    raise RuntimeError('DBus owner is not the supervised Fcitx process')
                break
            time.sleep(.1)
        else:
            if stopping:
                return 0
            raise RuntimeError('Fcitx did not acquire the user bus name')
        health_read, health_write = os.pipe()
        try:
            broker = subprocess.Popen([sys.executable,
                str(Path(__file__).with_name('trusted_socket_broker.py')),
                '--socket', str(path), '--bus-address', args.bus_address,
                '--wait-seconds', '30', '--recover-stale',
                '--health-fd', str(health_write)], env=env, pass_fds=(health_write,))
        finally:
            os.close(health_write)
        log('session-started')
        return monitor(bus, owner, GLib, Gio, (fcitx, broker), health_read,
                       lambda: stopping, notify_address)
    finally:
        if health_read is not None:
            os.close(health_read)
        # Close the relay control connection before removing Fcitx's stream.
        if broker and broker.poll() is None:
            broker.terminate()
            try:
                broker.wait(timeout=2)
            except subprocess.TimeoutExpired:
                broker.kill()
                broker.wait()
        # A unique bus name pins shutdown to our child, never a replacement.
        if fcitx and fcitx.poll() is None:
            if owner:
                try:
                    bus.call_sync(owner, '/controller', 'org.fcitx.Fcitx.Controller1',
                        'Exit', None, None, Gio.DBusCallFlags.NO_AUTO_START, 2000, None)
                except GLib.Error:
                    pass
            try:
                fcitx.wait(timeout=2)
            except subprocess.TimeoutExpired:
                fcitx.terminate()
                try:
                    fcitx.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    fcitx.kill()
                    fcitx.wait()
        bus.close_sync(None)
        os.close(lock)


if __name__ == '__main__':
    raise SystemExit(main())
