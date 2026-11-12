#!/usr/bin/env python3
"""Compile selected real Weston functions in a non-GUI transport test boundary.

No Weston, RDP client, display, GPU, system packages or live apps are started.
Baseline stalls are expected observations, not passing compositor behavior.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    "gfxredir-window-late-ack", "rdpgfx-global-late-ack",
    "gfxredir-global-late-ack", "still-throttled", "ack-suspension",
    "frame-id-wrap", "ack-burst-coalesced", "ack-before-next-repaint",
    "destroy-wait-progress", "teardown-free-only",
    "output-removed-before-dispatch", "multi-output-retry",
    "unknown-window-ack", "no-repaint-feedback-loop", "sleep-retains-retry",
    "actual-destroy-wait-rdpgfx", "actual-destroy-wait-gfxredir",
    "multiple-windows-one-output",
]
STALL_CASES = {
    "gfxredir-window-late-ack", "rdpgfx-global-late-ack", "gfxredir-global-late-ack",
    "still-throttled", "ack-suspension", "frame-id-wrap", "multi-output-retry",
    "unknown-window-ack", "sleep-retains-retry", "multiple-windows-one-output",
}


def function(text: str, name: str) -> str:
    """Extract complete top-level function, whose closing brace is at column 0."""
    match = re.search(r"(?m)^(?:static )?(?:void|int|UINT)\n" + re.escape(name) + r"\(", text)
    if not match:
        raise ValueError(f"Missing source function: {name}")
    end = text.index("\n}\n", match.end()) + 3
    return text[match.start():end]


def struct(text: str, name: str) -> str:
    start = text.index(f"struct {name} {{\n")
    end = text.index("\n};", start) + 3
    return text[start:end] + "\n"


def generate(source: Path, candidate: bool) -> tuple[str, list[dict]]:
    backend = source / "libweston/backend-rdp"
    rail = (backend / "rdprail.c").read_text()
    util = (backend / "rdputil.c").read_text()
    header = (backend / "rdp.h").read_text()
    snippets = [
        ("rdputil.c", util, "rdp_dispatch_task_to_display_loop"),
        ("rdputil.c", util, "rdp_dispatch_task"),
        ("rdputil.c", util, "rdp_destroy_dispatch_task_event_source"),
    ]
    if candidate:
        snippets.extend(("rdprail.c", rail, name) for name in [
            "rdp_rail_resume_repaint", "rdp_rail_queue_repaint"])
    snippets.extend(("rdprail.c", rail, name) for name in [
        "rail_grfx_client_frame_acknowledge", "gfxredir_client_present_buffer_ack",
        "rdp_rail_update_window_iter", "rdp_rail_output_repaint"])
    code = []
    manifest = []
    for filename, text, name in snippets:
        snippet = function(text, name)
        code.append(f'\n/* Extracted verbatim from {filename}: {name} */\n{snippet}')
        manifest.append({"file": filename, "function": name,
                         "sha256": hashlib.sha256(snippet.encode()).hexdigest()})
    types = struct(header, "rdp_loop_task") + struct(header, "rdp_output")
    types += struct(rail, "update_window_iter_data")
    harness = (ROOT / "tests/weston_repaint_harness.c").read_text()
    harness = harness.replace("/* SOURCE_TYPES: actual rdp_loop_task / rdp_output / iterator definitions. */", types)
    harness = harness.replace("/* SOURCE_FUNCTIONS: actual queue, ACK, output and task teardown functions. */", "\n".join(code))
    destroy = function(rail, "rdp_rail_destroy_window")
    start = destroy.index("int waitRetry = 0;")
    end = destroy.index("\n\t\t\t}\n", start)
    wait = destroy[start:end]
    harness = harness.replace("/* SOURCE_DESTROY_WAIT: verbatim wait block from destroy-window. */", wait)
    manifest.append({"file": "rdprail.c", "function": "rdp_rail_destroy_window (wait block)",
                     "sha256": hashlib.sha256(wait.encode()).hexdigest()})
    return harness, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=ROOT / ".work/weston-a7e35fdab455")
    parser.add_argument("--candidate", type=Path, default=ROOT / ".work/weston-ack-repaint")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/weston-repaint-tests.json")
    parser.add_argument("--sanitize", action="store_true", help="Use AddressSanitizer and UndefinedBehaviorSanitizer")
    args = parser.parse_args()
    result = {"scope": "selected actual source functions with stubbed compositor/transport; no GUI or GPU validation",
              "sanitized": args.sanitize, "cases_per_variant": len(CASES), "variants": {}}
    flags = shlex.split(subprocess.check_output(
        ["pkg-config", "--cflags", "--libs", "wayland-server", "pixman-1"], text=True))
    with tempfile.TemporaryDirectory(prefix="weston-test-", dir=ROOT / ".work") as directory:
        work = Path(directory)
        for variant, source in [("baseline", args.baseline), ("candidate", args.candidate)]:
            candidate = variant == "candidate"
            text, manifest = generate(source, candidate)
            cfile = work / f"{variant}.c"
            executable = work / variant
            cfile.write_text(text)
            command = ["cc", "-std=gnu99", "-g", "-O1", "-Wall", "-Wextra", "-Werror",
                       "-Wno-unused-function", "-Wno-unused-parameter",
                       f"-DCANDIDATE={int(candidate)}", str(cfile),
                       "-o", str(executable), "-pthread", *flags]
            if args.sanitize:
                command[1:1] = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
            subprocess.run(command, check=True)
            runs = []
            for case in CASES:
                proc = subprocess.run([str(executable), case], text=True, capture_output=True, timeout=15)
                runs.append({"case": case, "returncode": proc.returncode,
                             "expectation": ("retained update automatically retried on ACK" if candidate else
                                             "expected baseline defect: retained update remains unsent")
                             if case in STALL_CASES else "progress/lifetime/flow-control invariant",
                             "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()})
                if proc.returncode:
                    print(proc.stderr)
                    raise RuntimeError(f"{variant} failed: {case}")
            source_hashes = {name: hashlib.sha256((source / "libweston/backend-rdp" / name).read_bytes()).hexdigest()
                             for name in ["rdp.h", "rdp.c", "rdprail.c", "rdputil.c"]}
            result["variants"][variant] = {"source": str(source.resolve()), "source_sha256": source_hashes,
                                           "functions": manifest, "runs": runs}
            print(f"{variant}: {len(runs)}/{len(CASES)} expected source behaviors verified")
    result["all_passed"] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
