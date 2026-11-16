#!/usr/bin/env python3
"""Scope a pinned Fcitx addon to one session, falling back after package updates.

The manifest contains package versions and the SHA-256 of libwaylandim.so.
On mismatch the ordinary system addon is used. This launcher never modifies
the installed daemon, application, compositor or package-owned libraries.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def addon_path(directory: Path) -> str:
    manifest = json.loads((directory / 'manifest.json').read_text())
    packages = manifest['packages']
    if not packages:
        raise ValueError('empty package manifest')
    result = subprocess.run(
        ['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\n', *packages],
        check=True, capture_output=True, text=True)
    installed = dict(line.split('\t', 1) for line in result.stdout.splitlines())
    if installed != packages:
        raise ValueError('installed Fcitx package versions changed')
    library = directory / 'libwaylandim.so'
    if hashlib.sha256(library.read_bytes()).hexdigest() != manifest['sha256']:
        raise ValueError('addon checksum changed')
    system_dir = Path(manifest['system_addon_dir'])
    if not system_dir.is_absolute() or not system_dir.is_dir():
        raise ValueError('system addon directory unavailable')
    return f'{directory}:{system_dir}'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--addon-dir', required=True, type=Path)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == '--':
        command = command[1:]
    if not command:
        parser.error('a session command is required after --')
    env = os.environ.copy()
    env.pop('FCITX_ADDON_DIRS', None)
    try:
        env['FCITX_ADDON_DIRS'] = addon_path(args.addon_dir.resolve(strict=True))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f'wslg-ime: local shortcut addon skipped ({type(error).__name__}); '
              'using system addons. Check the pinned Fcitx build.', file=sys.stderr)
    os.execvpe(command[0], command, env)


if __name__ == '__main__':
    main()
