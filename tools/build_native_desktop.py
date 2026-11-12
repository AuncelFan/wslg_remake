#!/usr/bin/env python3
"""Build isolated pinned libweston-desktop A/B libraries; never install them.

Each copied shell differs from the installed shell only in its DT_NEEDED
reference to the project-local desktop library. No global loader path is used.
Run system-distro ldd -r and inspect actual Weston maps before GUI testing.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".work/weston-a7e35fdab455"
WORK = ROOT / ".work/native-desktop-20261112"
SDK = ROOT / ".work/native-weston-20261112/sdk"
EVIDENCE = ROOT / "evidence/desktop-state-20261112"
PATCH = ROOT / "patches/weston/0002-xdg-shell-compare-last-acked-state.patch"
FILES = ["libweston-desktop.c", "client.c", "seat.c", "surface.c", "xwayland.c",
         "wl-shell.c", "xdg-shell.c", "xdg-shell-v6.c"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(name, command):
    proc = subprocess.run(command, capture_output=True, text=True, timeout=120)
    (EVIDENCE / f"{name}.log").write_text(proc.stdout + proc.stderr)
    if proc.returncode:
        raise RuntimeError(f"{name}: {proc.stderr[-5000:]}")
    return proc.stdout


def main():
    global EVIDENCE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, default=WORK,
                        help='Fresh output directory; existing libraries are never overwritten.')
    parser.add_argument('--evidence', type=Path, default=EVIDENCE)
    args = parser.parse_args()
    work = args.work.resolve()
    EVIDENCE = args.evidence.resolve()
    for variant in ('baseline', 'acked'):
        for name in ('libweston-desktop-9.so.0', 'rdprail-shell.so'):
            if (work / variant / name).exists():
                parser.error('Refusing to overwrite a library that may be loaded. Use a fresh --work and --evidence directory.')
    if (EVIDENCE / 'build.json').exists():
        parser.error('Refusing to replace saved build evidence. Use a fresh --evidence directory.')
    if digest(SOURCE / 'libweston-desktop/xdg-shell.c') != '899c4d0241bacc66d0aab77ed61d3891a8d575e0e1efd1b44c5e1bccaeceaed5':
        parser.error('Pinned baseline xdg-shell source changed; inspect before building.')
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    flags = shlex.split(subprocess.check_output(
        ["pkg-config", "--cflags", "wayland-server", "pixman-1", "xkbcommon"], text=True))
    report = {"built_at": datetime.now().astimezone().isoformat(),
              "pinned_commit": "a7e35fdab455dce5774b43b8aff682f748307e31",
              "patch_sha256": digest(PATCH), "variants": {},
              "installed_files_modified": False, "app_modified": False}
    for variant in ("baseline", "acked"):
        target = work / variant
        target.mkdir(parents=True, exist_ok=True)
        src = target / "source/libweston-desktop"
        src.mkdir(parents=True, exist_ok=True)
        for f in FILES:
            shutil.copyfile(SOURCE / "libweston-desktop" / f, src / f)
        if variant == "acked":
            run("apply-patch", ["patch", "--batch", "--fuzz=0", "-p1", "-d",
                                str(target / "source"), "-i", str(PATCH)])
        (target / "config.h").write_text(
            "#define _GNU_SOURCE 1\n#define PACKAGE_VERSION \"9.0.0\"\n")
        for name, xml in [
            ("xdg-shell", "/usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml"),
            ("xdg-shell-unstable-v6", "/usr/share/wayland-protocols/unstable/xdg-shell/xdg-shell-unstable-v6.xml"),
        ]:
            for mode, suffix in [("server-header", "server-protocol.h"), ("private-code", "protocol.c")]:
                run(f"{variant}-{name}-{mode}", ["wayland-scanner", mode, xml, str(target / f"{name}-{suffix}")])
        inc = [target, SOURCE, SOURCE / "include", SOURCE / "libweston",
               SOURCE / "libweston-desktop", SDK / "include/libweston-9"]
        objects, commands = [], []
        sources = [src / f for f in FILES] + [target / f"{n}-protocol.c" for n in ("xdg-shell", "xdg-shell-unstable-v6")]
        for path in sources:
            obj = target / (path.stem + ".o")
            command = ["cc", "-std=gnu99", "-O2", "-g", "-fPIC", "-fvisibility=hidden",
                       "-Werror=implicit-function-declaration", "-Werror=incompatible-pointer-types",
                       *[f"-I{p}" for p in inc], *flags, "-c", str(path), "-o", str(obj)]
            run(f"{variant}-{path.stem}", command)
            commands.append(command)
            objects.append(str(obj))
        lib = target / "libweston-desktop-9.so.0"
        link = ["cc", "-shared", "-Wl,--no-undefined", "-Wl,-z,now",
                "-Wl,-soname,libweston-desktop-9.so.0", "-o", str(lib), *objects,
                f"-L{SDK / 'lib'}", f"-Wl,-rpath-link,{SDK / 'lib'}",
                "-l:libweston-9.so.0", "-l:libwayland-server.so.0", "-l:libpixman-1.so.0", "-lm"]
        run(f"{variant}-link", link)
        versions = run(f"{variant}-versions", ["readelf", "--version-info", str(lib)])
        required = sorted(set(re.findall(r"GLIBC_(\d+\.\d+)", versions)))
        if any(tuple(map(int, v.split('.'))) > (2, 38) for v in required):
            raise RuntimeError(f"Unsupported GLIBC requirement: {required}")
        dynamic = run(f"{variant}-dynamic", ["readelf", "-d", str(lib)])
        if "RPATH" in dynamic or "RUNPATH" in dynamic:
            raise RuntimeError("Unexpected loader search path")
        shell = target / "rdprail-shell.so"
        shutil.copyfile(WORK / "original/rdprail-shell.so", shell)
        run(f"{variant}-shell-dependency", ["patchelf", "--replace-needed",
            "libweston-desktop-9.so.0", str(lib), str(shell)])
        report["variants"][variant] = {
            "library": str(lib), "library_sha256": digest(lib),
            "shell": str(shell), "shell_sha256": digest(shell),
            "xdg_source_sha256": digest(src / "xdg-shell.c"),
            "compile_commands": commands, "link_command": link,
            "required_glibc": required}
        print(f"{variant}: built {lib}", flush=True)
    original = run("original-exports", ["nm", "-D", "--defined-only", str(WORK / "original/libweston-desktop-9.so.0")])
    exported = lambda text: {l.split()[-1] for l in text.splitlines() if l.strip()}
    for variant in report["variants"]:
        new = run(f"{variant}-exports", ["nm", "-D", "--defined-only", report["variants"][variant]["library"]])
        if exported(original) != exported(new):
            raise RuntimeError("Public exported symbols changed")
    (EVIDENCE / "build.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Both public export sets match the installed library.")


if __name__ == "__main__":
    main()
