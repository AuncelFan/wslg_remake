#!/usr/bin/env python3
"""Link isolated Weston RDP modules in Ubuntu against the running WSLg SDK.

The SDK is exported read-only from the current system distro. This tool never
installs anything or changes WSL configuration. Check both outputs with the
system distro's `ldd -r` before using WESTON_MODULE_MAP.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FILES = ["hash.c", "rdp.c", "rdpdisp.c", "rdpclip.c", "rdprail.c", "rdputil.c"]
CONFIG = """#define _GNU_SOURCE 1
#define _ALL_SOURCE 1
#define MAJOR_IN_SYSMACROS 1
#define HAVE_MKOSTEMP 1
#define HAVE_POSIX_FALLOCATE 1
#define HAVE_MEMFD_CREATE 1
#define HAVE_STRCHRNUL 1
#define HAVE_INITGROUPS 1
#define HAVE_FREERDP_GFXREDIR_H 1
#define HAVE_FREERDP_RDPAPPLIST_H 1
#define HAVE_OPENSSL 1
#define BUILD_RDP_COMPOSITOR 1
#define PACKAGE_VERSION "9.0.0"
"""


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=ROOT / ".work/native-weston-20261112")
    parser.add_argument("--baseline", type=Path, default=ROOT / ".work/weston-a7e35fdab455")
    parser.add_argument("--candidate", type=Path, default=ROOT / ".work/weston-reproduced")
    parser.add_argument("--evidence", type=Path, default=ROOT / "evidence/native-wslg-20261112")
    args = parser.parse_args()
    work, evidence = args.work.resolve(), args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    sdk = work / "sdk"
    includes = sdk / "include"
    version = (includes / "freerdp2/freerdp/version.h").read_text()
    if '"c4030980b"' not in version:
        parser.error("exported FreeRDP headers do not match the current pinned WSLg")
    flags = shlex.split(subprocess.check_output(
        ["pkg-config", "--cflags", "wayland-server", "pixman-1", "xkbcommon"], text=True))
    report = {"built_at": datetime.now().astimezone().isoformat(),
              "scope": "complete dynamically linked RDP backend modules; exact system-distro FreeRDP/WinPR headers and runtime libraries; Ubuntu compiler/libc headers",
              "sdk_archive_sha256": digest(work / "system-sdk.tar"),
              "original_installed_backend_sha256": digest(work / "original-installed-rdp-backend.so"),
              "compiler": subprocess.check_output(["cc", "--version"], text=True).splitlines()[0],
              "config": CONFIG, "variants": {}}

    def execute(name, command):
        proc = subprocess.run(command, text=True, capture_output=True, timeout=120)
        (evidence / f"{name}.stdout.log").write_text(proc.stdout)
        (evidence / f"{name}.stderr.log").write_text(proc.stderr)
        if proc.returncode:
            print(proc.stderr[-7000:])
            raise RuntimeError(f"{name} failed ({proc.returncode})")
        return proc.stdout

    for variant, source in [("baseline", args.baseline.resolve()), ("patched", args.candidate.resolve())]:
        target = work / variant
        target.mkdir(exist_ok=True)
        (target / "config.h").write_text(CONFIG)
        inc = [target, source, source / "include", source / "libweston",
               includes, includes / "freerdp2", includes / "winpr2",
               work / "openssl-sdk/usr/include", work / "openssl-sdk/usr/include/x86_64-linux-gnu",
               ROOT / ".work/weston-sdk/root/usr/include/libdrm"]
        objects, commands = [], []
        for name in FILES:
            obj = target / f"{name}.o"
            command = ["cc", "-std=gnu99", "-g", "-O2", "-fPIC", "-fvisibility=hidden",
                       "-Werror=implicit-function-declaration", "-Werror=incompatible-pointer-types",
                       *[f"-I{path}" for path in inc], *flags, "-c",
                       str(source / "libweston/backend-rdp" / name), "-o", str(obj)]
            execute(f"{variant}-{name}", command)
            objects.append(str(obj))
            commands.append(command)
            print(f"{variant}/{name}: compiled", flush=True)
        module = target / "rdp-backend.so"
        libs = sdk / "lib"
        link = ["cc", "-shared", "-Wl,--no-undefined", "-Wl,-z,now", "-Wl,--build-id=sha1",
                "-o", str(module), *objects, f"-L{libs}", f"-Wl,-rpath-link,{libs}",
                *[f"-l:{name}" for name in ("libweston-9.so.0", "libwayland-server.so.0", "libpixman-1.so.0",
                  "libxkbcommon.so.0", "libfreerdp2.so.2", "libfreerdp-server2.so.2", "libwinpr2.so.2", "libcrypto.so.3")],
                "-lm", "-pthread", "-ldl"]
        execute(f"{variant}-link", link)
        versions = execute(f"{variant}-versions", ["readelf", "--version-info", str(module)])
        required = sorted(set(re.findall(r"GLIBC_(\d+\.\d+)", versions)),
                          key=lambda value: tuple(map(int, value.split("."))))
        if any(tuple(map(int, value.split("."))) > (2, 38) for value in required):
            raise RuntimeError(f"module requires newer libc than system distro: {required}")
        dynamic = execute(f"{variant}-dynamic", ["readelf", "-d", str(module)])
        if "RUNPATH" in dynamic or "RPATH" in dynamic:
            raise RuntimeError("module unexpectedly contains a build-time library search path")
        exports = execute(f"{variant}-exports", ["nm", "-D", "--defined-only", str(module)])
        if "weston_backend_init" not in exports:
            raise RuntimeError("missing backend entry point")
        report["variants"][variant] = {"source": str(source), "module": str(module),
            "module_sha256": digest(module), "source_sha256": {
                name: digest(source / "libweston/backend-rdp" / name) for name in FILES + ["rdp.h"]},
            "required_glibc_versions": required, "compile_commands": commands, "link_command": link,
            "system_loader_preflight_required": True}
        print(f"{variant}: linked {module} ({module.stat().st_size} bytes)", flush=True)
    report["all_linked"] = True
    (evidence / "build.json").write_text(json.dumps(report, indent=2) + "\n")
    print(evidence / "build.json")


if __name__ == "__main__":
    main()
