#!/usr/bin/env python3
"""Install a user-local, one-shot Wayland input prerequisite for GTK portal.

Does not modify GTK/ChatGPT/Weston packages, restart WSL, or add a daemon.
Deployment receipts contain local paths and must remain private. Restart the
GTK portal separately after preserving any open chooser's diagnostic state.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
UNIT = "xdg-desktop-portal-gtk.service"
DROPIN_NAME = "60-wslg-seat-ready.conf"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs)


def quote_systemd(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def rollback(receipt_path):
    receipt = json.loads(receipt_path.read_text())
    # Refuse rollback if files have changed since this installation.
    for item in receipt["files"]:
        path = Path(item["path"])
        if path.is_symlink() or not path.is_file() or digest(path) != item["sha256"]:
            raise RuntimeError("installed file changed; inspect before rollback: " + str(path))
    for item in reversed(receipt["files"]):
        if item["created"]:
            Path(item["path"]).unlink()
    run("systemctl", "--user", "daemon-reload")
    print(json.dumps({"rolled_back": True, "restart_backend_required": True}))


def install(receipt_path):
    if os.geteuid() == 0:
        raise RuntimeError("run as the desktop user, not root")
    if receipt_path.exists() or receipt_path.is_symlink():
        raise FileExistsError("use a fresh private receipt path")
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    dropin = config_home / "systemd/user" / (UNIT + ".d") / DROPIN_NAME
    if dropin.exists() or dropin.is_symlink():
        raise FileExistsError("portal drop-in already exists; inspect it before replacing")
    # Confirm that a real existing backend unit is available before staging.
    unit_before = run("systemctl", "--user", "cat", UNIT).stdout
    source = HERE / "wait_wayland_seat.c"
    source_hash = digest(source)
    runtime = Path.home() / ".local/lib/wslg-portal" / source_hash[:16]
    binary = runtime / "wait-wayland-seat"
    manager_environment = dict(
        line.split("=", 1)
        for line in run("systemctl", "--user", "show-environment").stdout.splitlines()
        if "=" in line
    )
    # Match the service's user-manager environment, not a shell's overrides.
    manager_environment.pop("WAYLAND_SOCKET", None)
    flags = shlex.split(run("pkg-config", "--cflags", "--libs", "wayland-client").stdout)
    with tempfile.TemporaryDirectory(prefix="wslg-portal-build-") as temporary:
        compiled = Path(temporary) / binary.name
        run("cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            str(source), "-o", str(compiled), *flags)
        run("strip", "--strip-unneeded", str(compiled))
        # A live preflight refuses to deploy against an unusable display.
        preflight = run(str(compiled), "--timeout-ms=20000", env=manager_environment, timeout=23)
        if binary.exists() or binary.is_symlink():
            if binary.is_symlink() or not binary.is_file() or digest(binary) != digest(compiled):
                raise FileExistsError("content-addressed runtime differs: " + str(binary))
            binary_created = False
        else:
            runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(compiled, binary)
            binary.chmod(0o755)
            binary_created = True
    # Keep this below the usual 25-second D-Bus activation timeout. The guard
    # waits for protocol events, with no fixed delay when the seat is ready.
    configuration = (
        "# Managed by wslg_remake tools/portal/install_seat_guard.py\n"
        "# Wait only at startup; do not run a background watcher.\n"
        "[Service]\n"
        "Environment=GDK_BACKEND=wayland\n"
        "UnsetEnvironment=WAYLAND_SOCKET\n"
        "ExecStartPre=" + quote_systemd(binary) + " --timeout-ms=20000\n"
        "TimeoutStartSec=25s\n"
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    receipt = {
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "unit": UNIT,
        "source_sha256": source_hash,
        "build": ["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "strip --strip-unneeded"],
        "preflight": preflight.stderr.strip(),
        "unit_before": unit_before,
        "files": [
            {"path": str(binary), "sha256": digest(binary), "created": binary_created},
            {"path": str(dropin), "sha256": hashlib.sha256(configuration.encode()).hexdigest(), "created": True},
        ],
        "restart_backend_required": True,
    }
    # Write the receipt first so even a failed reload has a rollback record.
    with receipt_path.open("x") as stream:
        os.chmod(receipt_path, 0o600)
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    try:
        dropin.parent.mkdir(parents=True, exist_ok=True)
        with dropin.open("x") as stream:
            stream.write(configuration)
        run("systemctl", "--user", "daemon-reload")
        run("systemd-analyze", "--user", "verify", UNIT)
    except Exception:
        # Undo only the exact drop-in just written. Preserve the receipt and
        # runtime for inspection rather than retrying an uncertain mutation.
        if dropin.is_file() and digest(dropin) == receipt["files"][1]["sha256"]:
            dropin.unlink()
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        raise
    print(json.dumps({"installed": True, "receipt": str(receipt_path),
                      "dropin": str(dropin), "binary": str(binary),
                      "binary_bytes": binary.stat().st_size,
                      "restart_backend_required": True}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--install", action="store_true")
    mode.add_argument("--rollback", type=Path, metavar="RECEIPT")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.rollback:
        rollback(args.rollback)
    else:
        if not args.receipt:
            parser.error("--install requires --receipt (private deployment record)")
        install(args.receipt)


if __name__ == "__main__":
    main()
