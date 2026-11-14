#!/usr/bin/env python3
"""Build test-only modules and the relay; never deploy or modify live WSLg.

Requires the project's pinned Weston source and the exported running-system
SDK. Export /usr/lib/weston/libexec_weston.so.0 from that same system distro
to OUTPUT/libexec_weston.so.0 first. The noop headless module is exclusively
a protocol fixture, not a substitute for GPU + Wayland application tests.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".work/weston-a7e35fdab455"
SDK = ROOT / ".work/native-weston-20261112/sdk"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--panels", action="store_true",
                        help="exercise candidate panel mapping with a mock RAIL transport")
    args = parser.parse_args()
    target = args.output.resolve()
    source = args.source.resolve()
    target.mkdir(parents=True, exist_ok=True)
    if not (target / "libexec_weston.so.0").is_file():
        parser.error("export the matching system libexec_weston.so.0 first")
    outputs = [target / name for name in (
        "headless-backend.so", "ime-probe-shell.so", "trusted-socket-relay",
        "protocol-text-client")]
    if any(path.exists() for path in outputs):
        parser.error("refusing to overwrite binaries that might be loaded")
    (target / "config.h").write_text(
        '#define _GNU_SOURCE 1\n#define PACKAGE_VERSION "9.0.0"\n')
    commands = []

    def run(command):
        commands.append(command)
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout

    run(["wayland-scanner", "server-header",
         "/usr/share/wayland-protocols/stable/presentation-time/presentation-time.xml",
         str(target / "presentation-time-server-protocol.h")])
    flags = shlex.split(subprocess.check_output(
        ["pkg-config", "--cflags", "wayland-server", "pixman-1", "xkbcommon", "egl"], text=True))
    includes = [target, source, source / "include", source / "libweston",
                source / "rdprail-shell",
                SDK / "include/freerdp2", SDK / "include/winpr2",
                ROOT / ".work/weston-sdk/root/usr/include/libdrm"]
    base = ["cc", "-std=gnu99", "-O2", "-fPIC", "-fvisibility=hidden",
            "-Wall", "-Wextra", "-Werror=implicit-function-declaration",
            "-Werror=incompatible-pointer-types", *["-I"+str(p) for p in includes], *flags]
    links = ["-Wl,--no-undefined", "-Wl,-z,now", "-L"+str(SDK / "lib"),
             "-Wl,-rpath-link,"+str(SDK / "lib"),
             "-l:libweston-9.so.0", "-l:libwayland-server.so.0",
             "-l:libpixman-1.so.0", "-lxkbcommon", "-lm"]
    run([*base, "-shared", str(source / "libweston/backend-headless/headless.c"),
         "-o", str(outputs[0]), *links])
    panel_sources = []
    if args.panels:
        for name, xml in [
            ("input-method-unstable-v1", Path("/usr/share/wayland-protocols/unstable/input-method/input-method-unstable-v1.xml")),
            ("weston-rdprail-shell", source / "protocol/weston-rdprail-shell.xml"),
        ]:
            run(["wayland-scanner", "server-header", str(xml), str(target / (name+"-server-protocol.h"))])
            run(["wayland-scanner", "private-code", str(xml), str(target / (name+"-protocol.c"))])
            panel_sources.append(str(target / (name+"-protocol.c")))
        panel_sources += [str(source / "rdprail-shell/input-panel.c"), "-DWSLG_IME_PANEL_FIXTURE=1"]
    run([*base, "-shared", str(ROOT / "tools/ime/protocol_probe_shell.c"),
         *panel_sources,
         "-o", str(outputs[1]), "-L"+str(target), "-l:libexec_weston.so.0", *links])
    run(["cc", "-std=gnu99", "-O2", "-Wall", "-Wextra", "-Werror",
         str(ROOT / "tools/ime/trusted_socket_relay.c"), "-o", str(outputs[2])])
    text_xml = "/usr/share/wayland-protocols/unstable/text-input/text-input-unstable-v1.xml"
    run(["wayland-scanner", "client-header", text_xml,
         str(target / "text-input-v1-client-protocol.h")])
    run(["wayland-scanner", "private-code", text_xml,
         str(target / "text-input-v1-protocol.c")])
    run(["cc", "-std=gnu99", "-O2", "-Wall", "-Wextra", "-Wno-unused-parameter",
         "-Werror", "-I"+str(target), str(ROOT / "tools/ime/protocol_text_client.c"),
         str(target / "text-input-v1-protocol.c"), "-lwayland-client", "-o", str(outputs[3])])
    artifacts = []
    for path in outputs:
        versions = run(["readelf", "--version-info", str(path)])
        required = sorted(set(re.findall(r"GLIBC_(\d+\.\d+)", versions)))
        if any(tuple(map(int, v.split("."))) > (2, 38) for v in required):
            raise RuntimeError("artifact requires libc newer than the system distro")
        dynamic = run(["readelf", "-d", str(path)])
        if "RPATH" in dynamic or "RUNPATH" in dynamic:
            raise RuntimeError("unexpected runtime library search path")
        artifacts.append({"name": path.name, "size": path.stat().st_size,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                          "glibc": required})
    report = {"artifacts": artifacts, "commands": commands,
              "deployed": False, "gpu_acceptance": False}
    (target / "build.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"artifacts": artifacts, "deployed": False}, indent=2))


if __name__ == "__main__":
    main()
