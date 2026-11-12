#!/usr/bin/env python3
"""Copy accepted modules to a new runtime directory and strip debug symbols.

Does not replace installed/loaded files, edit configuration, or restart WSL.
Verifies .text, dynamic exports, and GLIBC requirements before accepting copies.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = {
    "rdp-backend": ROOT / ".work/native-weston-20261112/patched/rdp-backend.so",
    "desktop": ROOT / ".work/native-desktop-20261112/acked/libweston-desktop-9.so.0",
    "shell": ROOT / ".work/native-desktop-20261112/acked/rdprail-shell.so",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def output(*args):
    return subprocess.check_output(args, text=True)


def text_hash(path):
    with tempfile.TemporaryDirectory(prefix="weston-text-") as temp:
        section = Path(temp) / "text.bin"
        subprocess.run(["objcopy", "--dump-section", ".text=" + str(section), str(path),
                        str(Path(temp) / "copy.elf")], check=True)
        return sha(section)


def exports(path):
    return sorted(line.split()[-1] for line in output("nm", "-D", "--defined-only", str(path)).splitlines() if line.strip())


def versions(path):
    return sorted(set(re.findall(r"GLIBC_(\d+(?:\.\d+)+)", output("readelf", "-V", str(path)))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    dest = args.destination.resolve()
    if not dest.is_relative_to(ROOT / "runtime") or dest == ROOT / "runtime":
        parser.error("Use a new directory beneath this project's runtime/.")
    if dest.exists() or args.report.exists():
        parser.error("Refusing existing runtime output/report.")
    builds = {name: json.loads((ROOT / path).read_text()) for name, path in {
        "rdp": "evidence/native-wslg-20261112/build.json",
        "desktop": "evidence/desktop-state-20261112/build.json"}.items()}
    expected = {"rdp-backend": builds["rdp"]["variants"]["patched"]["module_sha256"],
                "desktop": builds["desktop"]["variants"]["acked"]["library_sha256"],
                "shell": builds["desktop"]["variants"]["acked"]["shell_sha256"]}
    for name, path in SOURCE.items():
        if sha(path) != expected[name]:
            raise RuntimeError("Accepted source module changed: " + name)
    dest.mkdir(parents=True)
    targets = {name: dest / source.name for name, source in SOURCE.items()}
    report = {"at": datetime.now().astimezone().isoformat(),
              "classification": "local optimized stripped production deployment; not an official upstream release",
              "recompiled": False, "modules": {}}
    for name, source in SOURCE.items():
        target = targets[name]
        shutil.copyfile(source, target)
        if name == "shell":
            subprocess.run(["patchelf", "--replace-needed", str(SOURCE["desktop"]), str(targets["desktop"]), str(target)], check=True)
        subprocess.run(["strip", "--strip-unneeded", "--remove-section=.gnu_debuglink",
                        "--remove-section=.gnu_debugdata", str(target)], check=True)
        sections = output("readelf", "-SW", str(target))
        if re.search(r"\.(?:debug_|zdebug_|gnu_debuglink|gnu_debugdata)", sections):
            raise RuntimeError("Debug data remains: " + name)
        checks = ((text_hash(source) == text_hash(target), "machine code changed"),
                  (exports(source) == exports(target), "public exports changed"),
                  (versions(source) == versions(target), "GLIBC requirements changed"),
                  (sha(source) == expected[name], "accepted source was modified"))
        for passed, message in checks:
            if not passed:
                raise RuntimeError(name + ": " + message)
        report["modules"][name] = {
            "source": str(source), "source_sha256": sha(source),
            "path": str(target), "sha256": sha(target), "bytes": target.stat().st_size,
            "text_sha256": text_hash(target), "text_matches_accepted": True,
            "dynamic_exports_match": True, "glibc_versions_match": True,
            "debug_sections": False, "dynamic": output("readelf", "-d", str(target)),
            "required_glibc": versions(target)}
    manifest = {"label": "production-wslg-1.0.79-weston-a7e35fd",
                "custom": {n: str(p.relative_to(ROOT)) for n, p in targets.items()},
                "expected_sha256": {n: sha(p) for n, p in targets.items()},
                "expected_log_levels": {"WESTON_RDP_DEBUG_LEVEL": "2",
                                        "WESTON_RDPRAIL_SHELL_DEBUG_LEVEL": "2",
                                        "WESTON_RDP_DEBUG_CLIPBOARD_LEVEL": "0"}}
    (dest / "deployment.json").write_text(json.dumps(manifest, indent=2) + "\n")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({n: {k:v for k,v in item.items() if k in ("bytes", "sha256", "debug_sections", "text_matches_accepted")} for n,item in report["modules"].items()}, indent=2))


if __name__ == "__main__":
    main()
