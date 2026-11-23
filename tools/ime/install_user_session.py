#!/usr/bin/env python3
"""Stage or roll back the local Ubuntu IME user service and launch settings.

Does not restart WSL, install compositor modules, change Fcitx data, or start
the new service in an existing session. Backups contain local user paths and
must stay private. The Windows-side WSLg configuration is managed separately.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
OLD = '''if ! pgrep -x "fcitx5" > /dev/null; then
    fcitx5 -d --disable=wayland,waylandim > /dev/null 2>&1
fi'''
NEW = '''# WSLg IME service owns Fcitx and its compositor-authorized connection.
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user start --no-block wslg-ime.service >/dev/null 2>&1
fi'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--rollback', type=Path)
    parser.add_argument('--upgrade-from', type=Path,
                        help='private manifest of the currently installed session')
    parser.add_argument('--remove-legacy-libva', action='store_true',
                        help='remove the exact legacy d3d12 VA-API export from .zshrc')
    args = parser.parse_args()
    if args.rollback:
        manifest = json.loads(args.rollback.read_text())
        for item in manifest['files']:
            path = Path(item['path'])
            if not path.exists() or digest(path) != item['installed_sha256']:
                raise RuntimeError('installed file changed after deployment: '+str(path))
        subprocess.run(['systemctl','--user','disable','--now','wslg-ime.service'],
                       check=False, capture_output=True)
        for item in reversed(manifest['files']):
            path = Path(item['path'])
            if item['original']:
                shutil.copyfile(item['original'], path)
                path.chmod(item['mode'])
            else:
                path.unlink()
        run('systemctl','--user','daemon-reload')
        if manifest.get('service_enabled_before', False):
            run('systemctl','--user','enable','wslg-ime.service')
        print(json.dumps({'restored': True, 'restart_wsl_required': True}))
        return
    if not args.runtime or not args.backup:
        parser.error('--runtime and --backup are required to stage a candidate')
    runtime, backup = args.runtime.resolve(), args.backup.resolve()
    if not (runtime/'build.json').is_file():
        parser.error('build manifest missing')
    build = json.loads((runtime/'build.json').read_text())
    for item in build['artifacts']:
        if digest(runtime/item['name']) != item['sha256']:
            raise RuntimeError('build artifact changed: '+item['name'])
    zshenv = Path.home()/'.zshenv'
    wrapper = Path.home()/'.local/bin/chatgpt'
    unit = Path.home()/'.config/systemd/user/wslg-ime.service'
    if args.upgrade_from:
        previous = json.loads(args.upgrade_from.read_text())
        required = {str(zshenv), str(wrapper), str(unit)}
        recorded = {item['path']: item for item in previous['files']}
        if not required.issubset(recorded):
            raise RuntimeError('upgrade manifest does not cover the current session')
        for name in required:
            path = Path(name)
            if path.is_symlink() or not path.is_file() or digest(path) != recorded[name]['installed_sha256']:
                raise RuntimeError('installed session changed after deployment: '+name)
    elif unit.exists() or unit.is_symlink():
        raise FileExistsError('user service already exists; inspect it before replacing')
    if zshenv.is_symlink() or wrapper.is_symlink():
        raise RuntimeError('launch settings are symlinks; inspect before editing')
    original = zshenv.read_text()
    expected_block = NEW if args.upgrade_from else OLD
    if original.count(expected_block) != 1:
        raise RuntimeError('expected existing Fcitx startup block exactly once')
    zshrc = Path.home()/'.zshrc'
    legacy_libva = 'export LIBVA_DRIVER_NAME=d3d12'
    zshrc_updated = None
    if args.remove_legacy_libva:
        if zshrc.is_symlink():
            raise RuntimeError('.zshrc is a symlink; inspect before editing')
        current_zshrc = zshrc.read_text()
        lines = current_zshrc.splitlines(keepends=True)
        matches = [line for line in lines if line.strip() == legacy_libva]
        if len(matches) > 1:
            raise RuntimeError('multiple legacy VA-API settings; inspect before editing')
        if matches:
            zshrc_updated = ''.join(line for line in lines if line.strip() != legacy_libva)
    if backup.exists():
        raise FileExistsError('use a fresh private backup directory')
    backup.mkdir(parents=True, mode=0o700)
    service_enabled_before = subprocess.run(['systemctl','--user','is-enabled','--quiet',
        'wslg-ime.service'],capture_output=True).returncode == 0
    snapshot = runtime/'ime'
    snapshot.mkdir(exist_ok=False)
    for name in ('session_supervisor.py','trusted_socket_broker.py'):
        shutil.copyfile(HERE/name, snapshot/name)
    def systemd_quote(value):
        return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
    service = '''[Unit]
Description=WSLg trusted native Wayland Fcitx session
After=dbus.socket
StartLimitIntervalSec=0

[Service]
Type=notify
NotifyAccess=main
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=%t/bus
Environment=XDG_RUNTIME_DIR=%t
Environment=DISPLAY=:0
Environment=WAYLAND_DISPLAY=wayland-0
Environment=LANG=zh_CN.UTF-8
Environment=GALLIUM_DRIVER=d3d12
UnsetEnvironment=WAYLAND_SOCKET WAYLAND_DEBUG LD_PRELOAD NODE_OPTIONS MESA_DEBUG MESA_LOG_FILE LIBGL_DEBUG
ExecStart=/usr/bin/python3 '''+systemd_quote(snapshot/'session_supervisor.py')+''' --socket /mnt/wslg/runtime-dir/wslg-ime-v1/bridge.sock
Restart=on-failure
RestartSec=5s
TimeoutStartSec=55s
WatchdogSec=25s
KillMode=mixed
TimeoutStopSec=12
UMask=0077
SyslogIdentifier=wslg-ime

[Install]
WantedBy=default.target
'''
    (snapshot/'wslg-ime.service').write_text(service)
    run('systemd-analyze','--user','verify',str(snapshot/'wslg-ime.service'))
    changes = [(zshenv, original.replace(expected_block,NEW)),
               (wrapper, (HERE/'chatgpt_wayland_wrapper.sh').read_text()), (unit,service)]
    if zshrc_updated is not None:
        changes.append((zshrc,zshrc_updated))
    records = []
    for index,(path,text) in enumerate(changes):
        path.parent.mkdir(parents=True,exist_ok=True)
        existed = path.exists()
        mode = path.stat().st_mode & 0o777 if existed else 0o644
        saved = backup/str(index)
        if existed:
            shutil.copyfile(path,saved)
        path.write_text(text)
        path.chmod(mode)
        records.append({'path':str(path),'original':str(saved) if existed else None,
                        'mode':mode,'installed_sha256':digest(path)})
        # Save after each write so an interrupted staging remains reversible.
        (backup/'manifest.json').write_text(json.dumps({'files':records,
            'runtime':str(runtime), 'service_enabled_before':service_enabled_before},indent=2)+'\n')
    run('systemctl','--user','daemon-reload')
    run('systemctl','--user','enable','wslg-ime.service')
    print(json.dumps({'staged':True,'started':False,
                       'rollback_manifest':str(backup/'manifest.json')},indent=2))


if __name__ == '__main__':
    main()
