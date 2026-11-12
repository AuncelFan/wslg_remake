#!/usr/bin/env python3
"""Prepare the pinned Weston candidate under this project's .work directory.

Downloads/extracts source and applies the local patch. Never builds, installs,
opens a display, changes WSL settings, or overwrites an existing directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a7e35fdab455dce5774b43b8aff682f748307e31"
ARCHIVE_SHA256 = "c70b47d0c5cb9150af36d4cceb412e619971fdb404d2432461cac3c7aa65078f"
URL = f"https://codeload.github.com/microsoft/weston-mirror/tar.gz/{COMMIT}"
PATCH = ROOT / "patches/weston/0001-rdp-resume-deferred-repaint-on-ack.patch"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--direct", action="store_true", help="Ignore proxy variables for this download only")
    args = parser.parse_args()
    destination = args.destination.resolve()
    work = (ROOT / ".work").resolve()
    if not destination.is_relative_to(work) or destination == work:
        parser.error("destination must be a new directory below this project's .work/")
    if destination.exists():
        parser.error("destination already exists; refusing to overwrite")
    if not PATCH.is_file():
        parser.error(f"missing patch: {PATCH}")
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    archive = cache / f"weston-{COMMIT}.tar.gz"
    if not archive.exists():
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if args.direct else urllib.request.build_opener()
        with tempfile.NamedTemporaryFile(dir=cache, suffix=".part", delete=False) as output:
            temporary = Path(output.name)
            try:
                with opener.open(URL, timeout=120) as response:
                    shutil.copyfileobj(response, output)
                output.flush()
                if digest(temporary) != ARCHIVE_SHA256:
                    raise ValueError("download SHA256 mismatch; refusing source")
                temporary.replace(archive)
            finally:
                temporary.unlink(missing_ok=True)
    if digest(archive) != ARCHIVE_SHA256:
        raise ValueError("cached source SHA256 mismatch; refusing source")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="weston-prepare-", dir=destination.parent) as directory:
        stage = Path(directory)
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(stage, filter="data")
        source = stage / f"weston-mirror-{COMMIT}"
        # This extracted source is not a Git checkout. Do not let Git discover
        # the enclosing public repository and silently skip out-of-prefix paths.
        git_env = dict(os.environ)
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
            git_env.pop(key, None)
        git_env["GIT_CEILING_DIRECTORIES"] = str(stage.resolve())
        for check in [True, False]:
            command = ["git", "-C", str(source), "-c", "core.autocrlf=false", "apply"]
            if check:
                command.append("--check")
            subprocess.run([*command, str(PATCH)], check=True, env=git_env)
        files = ["libweston/backend-rdp/rdp.c", "libweston/backend-rdp/rdp.h",
                 "libweston/backend-rdp/rdprail.c"]
        manifest = {
            "base_commit": COMMIT, "source_url": URL,
            "source_archive_sha256": ARCHIVE_SHA256,
            "patch": str(PATCH.relative_to(ROOT)), "patch_sha256": digest(PATCH),
            "modified_files": {name: digest(source / name) for name in files},
            "stage": "source candidate only; not built or installed",
            "system_modified": False,
        }
        (source / "wslg-repaint-candidate.json").write_text(json.dumps(manifest, indent=2) + "\n")
        source.rename(destination)
    print(destination)
    print("Pinned source and patch verified. No system components changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
