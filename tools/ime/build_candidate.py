#!/usr/bin/env python3
"""Build a fresh, ABI-checked WSLg IME candidate; never deploy it.

Uses the pinned source with all three project patches applied, the exported
running-system SDK, and the already accepted production desktop library.
Requires an additional system-shell-sdk.tar exported read-only from WSLg.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from build_native_rdp_backend import CONFIG, FILES


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--extra-sdk', type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if (output / 'build.json').exists() or any((output / n).exists() for n in (
            'rdp-backend.so', 'rdprail-shell.so', 'libweston-desktop-9.so.0')):
        parser.error('refusing to overwrite final binaries; use a fresh output')
    output.mkdir(parents=True, exist_ok=True)
    build = output / '.build'
    build.mkdir(exist_ok=True)
    sdk = ROOT / '.work/native-weston-20261112/sdk'
    if '"c4030980b"' not in (sdk/'include/freerdp2/freerdp/version.h').read_text():
        parser.error('FreeRDP SDK does not match the pinned WSLg build')
    extra = args.extra_sdk.resolve()
    with tarfile.open(extra / 'system-shell-sdk.tar') as archive:
        archive.extractall(extra / 'root', filter='data')
    library = extra / 'root/usr/lib'
    # Keep this override local to the candidate. No loader environment changes.
    desktop = ROOT / 'runtime/wslg-1.0.79-weston-a7e35fd-production/libweston-desktop-9.so.0'
    if not desktop.is_file():
        parser.error('accepted production desktop library not found')
    config = CONFIG + '''#define HAVE_GLIB 1
#define HAVE_WINPR 1
#define HAVE_LIBRSVG2 1
#define HAVE_JPEG 1
#define HAVE_WEBP 1
#define DATADIR "/usr/share"
#define BINDIR "/usr/bin"
#define LIBEXECDIR "/usr/libexec"
#define PACKAGE_NAME "weston"
#define PACKAGE_STRING "weston 9.0.0"
#define PACKAGE_URL "https://wayland.freedesktop.org"
'''
    (build / 'config.h').write_text(config)
    commands = []

    def run(command, name=None):
        commands.append(command)
        proc = subprocess.run(command, text=True, capture_output=True, timeout=180)
        if name:
            (build / (name + '.log')).write_text(proc.stdout + proc.stderr)
        if proc.returncode:
            raise RuntimeError(shlex.join(command) + '\n' + proc.stdout + proc.stderr)
        return proc.stdout

    protocols = [
        ('weston-rdprail-shell', source / 'protocol/weston-rdprail-shell.xml'),
        ('input-method-unstable-v1', Path('/usr/share/wayland-protocols/unstable/input-method/input-method-unstable-v1.xml')),
    ]
    for name, xml in protocols:
        for mode, suffix in [('server-header', 'server-protocol.h'), ('private-code', 'protocol.c')]:
            run(['wayland-scanner', mode, str(xml), str(build / f'{name}-{suffix}')])
    flags = shlex.split(run(['pkg-config', '--cflags', 'wayland-server',
        'wayland-client', 'pixman-1', 'xkbcommon', 'librsvg-2.0', 'glib-2.0',
        'cairo', 'libpng', 'libjpeg', 'libwebp']))
    includes = [build, source, source / 'include', source / 'libweston',
                source / 'libweston-desktop', sdk / 'include',
                sdk / 'include/freerdp2', sdk / 'include/winpr2',
                ROOT / '.work/native-weston-20261112/openssl-sdk/usr/include',
                ROOT / '.work/native-weston-20261112/openssl-sdk/usr/include/x86_64-linux-gnu',
                ROOT / '.work/weston-sdk/root/usr/include/libdrm']
    cc = ['cc', '-std=gnu99', '-O2', '-g', '-fPIC', '-fvisibility=hidden',
          '-Werror=implicit-function-declaration', '-Werror=incompatible-pointer-types',
          '-Wno-deprecated-declarations', *['-I'+str(p) for p in includes], *flags]
    all_headers = list((source / 'rdprail-shell').glob('*.h')) + [
        source / 'include/libweston/backend-rdp.h',
        source / 'libweston/backend-rdp/rdp.h', build / 'config.h']
    header_hash = ''.join(sha(p) for p in all_headers)

    def objects(paths):
        result = []
        for path in paths:
            obj = build / (path.parent.name + '-' + path.stem + '.o')
            command = [*cc, '-c', str(path), '-o', str(obj)]
            identity = hashlib.sha256((sha(path) + header_hash + repr(command)).encode()).hexdigest()
            stamp = obj.with_suffix('.sha')
            if not obj.exists() or not stamp.exists() or stamp.read_text() != identity:
                run(command, obj.stem)
                stamp.write_text(identity)
            result.append(str(obj))
            print('compiled', path.name, flush=True)
        return result

    libflags = [f'-L{sdk / "lib"}', f'-L{library / "weston"}', f'-L{library}',
                f'-Wl,-rpath-link,{sdk / "lib"}', f'-Wl,-rpath-link,{library}',
                '-Wl,-rpath-link,/usr/lib/x86_64-linux-gnu']
    base_libs = ['libweston-9.so.0', 'libwayland-server.so.0', 'libpixman-1.so.0',
                 'libxkbcommon.so.0', 'libfreerdp2.so.2',
                 'libfreerdp-server2.so.2', 'libwinpr2.so.2', 'libcrypto.so.3']
    # SDK search comes first, but the extra libs are unique names.
    def link(name, objs, libs):
        target = build / name
        run(['cc', '-shared', '-Wl,--no-undefined', '-Wl,-z,now',
             '-Wl,--build-id=sha1', '-Wl,-soname,'+name, '-o', str(target),
             *objs, *libflags, *['-l:'+n for n in libs], '-lm', '-pthread', '-ldl'], name+'-link')
        return target

    backend = link('rdp-backend.so', objects([
        source / 'libweston/backend-rdp' / f for f in FILES]), base_libs)
    shell_files = [source / 'rdprail-shell' / f for f in (
        'shell.c', 'input-panel.c', 'app-list.c', 'img-load.c')]
    shell_files += [source / 'shared' / f for f in (
        'config-parser.c', 'option-parser.c', 'file-util.c', 'os-compatibility.c',
        'image-loader.c', 'cairo-util.c', 'frame.c')]
    shell_files += [build / (n+'-protocol.c') for n, _ in protocols]
    shell_libs = base_libs + ['libexec_weston.so.0', 'libwayland-client.so.0',
        'librsvg-2.so.2', 'libglib-2.0.so.0', 'libgobject-2.0.so.0',
        'libcairo.so.2', 'libpng16.so.16', 'libjpeg.so.62', 'libwebp.so.7']
    # Absolute DT_NEEDED prevents silently loading the stock, unfixed desktop library.
    shell_obj = objects(shell_files)
    shell = build / 'rdprail-shell.so'
    run(['cc', '-shared', '-Wl,--no-undefined', '-Wl,-z,now', '-Wl,--build-id=sha1',
         '-Wl,-soname,rdprail-shell.so', '-o', str(shell), *shell_obj, str(desktop),
         *libflags, *['-l:'+n for n in shell_libs], '-lm', '-pthread', '-ldl'], 'shell-link')
    run(['patchelf', '--replace-needed', 'libweston-desktop-9.so.0', str(desktop), str(shell)])
    if str(desktop) not in run(['readelf', '-d', str(shell)]):
        raise RuntimeError('shell did not retain the accepted desktop dependency')
    relay = build / 'trusted-socket-relay'
    run(['cc', '-std=gnu99', '-O2', '-g', '-Wall', '-Wextra', '-Werror',
         str(ROOT / 'tools/ime/trusted_socket_relay.c'), '-o', str(relay)], 'relay')
    report = {'built_at': datetime.now().astimezone().isoformat(),
              'source': str(source), 'artifacts': [], 'deployed': False,
              'existing_minimize_fixes_preserved': True, 'commands': commands,
              'config': config}
    for path in (backend, shell, relay):
        versions = run(['readelf', '--version-info', str(path)])
        glibc = sorted(set(re.findall(r'GLIBC_(\d+\.\d+)', versions)))
        if any(tuple(map(int, v.split('.'))) > (2, 38) for v in glibc):
            raise RuntimeError('unsupported libc: '+repr(glibc))
        dynamic = run(['readelf', '-d', str(path)])
        if 'RPATH' in dynamic or 'RUNPATH' in dynamic:
            raise RuntimeError('unexpected library search path')
        run(['objcopy', '--only-keep-debug', str(path), str(build / (path.name+'.debug'))])
        release = output / (path.name+'.new')
        shutil.copyfile(path, release)
        release.chmod(path.stat().st_mode & 0o777)
        run(['strip', '--strip-unneeded', str(release)])
        sections = run(['readelf', '-S', str(release)])
        if '.debug_' in sections:
            raise RuntimeError('debug sections remain in release candidate')
        release.rename(output / path.name)
        report['artifacts'].append({'name': path.name, 'sha256': sha(output / path.name),
            'bytes': (output / path.name).stat().st_size, 'glibc': glibc,
            'optimized': True, 'debug_sections': False})
    shutil.copyfile(desktop, output / desktop.name)
    # Shell already references the accepted immutable desktop library above.
    report['desktop_dependency'] = str(desktop)
    report['desktop_sha256'] = sha(desktop)
    (output / 'build.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report['artifacts'], indent=2))


if __name__ == '__main__':
    main()
