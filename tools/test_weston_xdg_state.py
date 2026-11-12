#!/usr/bin/env python3
"""Compile the actual pinned and candidate comparator bodies and replay states.

This is a state-machine regression, not GUI or GPU acceptance. No live process
is accessed. Sources are extracted rather than maintaining a second comparator.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = "weston_desktop_xdg_toplevel_state_compare"


def extract(path, name):
    text = path.read_text()
    start = text.index("static bool\n" + FUNCTION + "(")
    end = text.index("\nstatic void", start)
    return text[start:end].replace(FUNCTION, name, 1)


HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <wayland-util.h>
struct weston_size { int width, height; };
struct weston_surface { int width, height; };
struct weston_desktop_xdg_toplevel_state { bool maximized, fullscreen, resizing, activated; };
struct weston_desktop_xdg_surface_configure { struct wl_list link; unsigned serial; };
struct weston_desktop_xdg_toplevel_configure {
 struct weston_desktop_xdg_surface_configure base;
 struct weston_desktop_xdg_toplevel_state state;
 struct weston_size size;
};
struct weston_desktop_xdg_toplevel {
 struct { bool configured; struct wl_list configure_list; struct weston_surface *surface; } base;
 struct { struct weston_desktop_xdg_toplevel_state state; struct weston_size size; } pending, next, current;
};
'''
CHECKS = r'''
static unsigned checks;
static void check(bool value) { assert(value); ++checks; }
static void init(struct weston_desktop_xdg_toplevel *t, struct weston_surface *s) {
 memset(t,0,sizeof(*t)); s->width=1920; s->height=1032;
 t->base.surface=s; t->base.configured=true; wl_list_init(&t->base.configure_list);
}
int main(void) {
 struct weston_desktop_xdg_toplevel t;
 struct weston_surface s;
 init(&t,&s);
 /* Captured: bufferless deactivation ACK/commit left current=true. */
 t.current.state.activated=true; t.next.state.activated=false; t.pending.state.activated=true;
 check(baseline(&t)); check(!candidate(&t));
 /* ACK received; new buffer/commit not received yet: do not duplicate. */
 t.next.state.activated=true; t.current.state.activated=false;
 check(!baseline(&t)); check(candidate(&t));
 /* For every state flag, compare against last ACK, not old committed value. */
 for (int flag=0; flag<4; flag++) {
  init(&t,&s);
  bool *cur[] = {&t.current.state.maximized,&t.current.state.fullscreen,&t.current.state.resizing,&t.current.state.activated};
  bool *ack[] = {&t.next.state.maximized,&t.next.state.fullscreen,&t.next.state.resizing,&t.next.state.activated};
  bool *pending[] = {&t.pending.state.maximized,&t.pending.state.fullscreen,&t.pending.state.resizing,&t.pending.state.activated};
  *cur[flag]=true; *pending[flag]=true;
  check(baseline(&t)); check(!candidate(&t));
  *ack[flag]=true; *cur[flag]=false;
  check(!baseline(&t)); check(candidate(&t));
 }
 /* Initial configure must always be sent. */
 init(&t,&s); t.base.configured=false;
 check(!baseline(&t)); check(!candidate(&t));
 /* Latest unacknowledged configure wins, even with multiple queue entries. */
 init(&t,&s);
 struct weston_desktop_xdg_toplevel_configure a={0},b={0};
 a.state.activated=true; b.state.activated=false;
 wl_list_insert(&t.base.configure_list,&a.base.link);
 wl_list_insert(&a.base.link,&b.base.link);
 t.next.state.activated=true; t.pending.state.activated=false;
 check(baseline(&t)); check(candidate(&t));
 t.pending.state.activated=true;
 check(!baseline(&t)); check(!candidate(&t));
 wl_list_remove(&a.base.link); wl_list_remove(&b.base.link);
 /* Keep existing geometry comparison and zero-size semantics. */
 init(&t,&s); t.pending.size=s.width==1920 ? (struct weston_size){1920,1032} : (struct weston_size){0};
 check(candidate(&t)); t.pending.size.width=1919; check(!candidate(&t));
 t.pending.size.width=0; check(!candidate(&t));
 t.pending.size.height=0; check(candidate(&t));
 /* Repeated restore/deactivate and independent windows. */
 struct weston_desktop_xdg_toplevel other; struct weston_surface os;
 init(&other,&os);
 for(int i=0;i<100;i++) {
  t.next.state.activated=(i%2); t.current.state.activated=!(i%2);
  t.pending.state.activated=!(i%2);
  check(!candidate(&t)); check(candidate(&other));
  t.next.state=t.pending.state; check(candidate(&t));
 }
 printf("{\"assertions_passed\":%u,\"captured_failure_reproduced\":true,\"gui_acceptance\":false}\n", checks);
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=ROOT / ".work/native-desktop-20261112/acked/source/libweston-desktop/xdg-shell.c")
    args = parser.parse_args()
    baseline = ROOT / ".work/weston-a7e35fdab455/libweston-desktop/xdg-shell.c"
    evidence = ROOT / "evidence/desktop-state-20261112"
    work = ROOT / ".work/native-desktop-20261112"
    src = work / "comparator-regression.c"
    src.write_text(HARNESS + extract(baseline, "baseline") + extract(args.candidate, "candidate") + CHECKS)
    exe = work / "comparator-regression"
    subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", str(src), "-lwayland-server", "-o", str(exe)], check=True)
    result = json.loads(subprocess.check_output([str(exe)], text=True))
    result["source_sha256"] = {"baseline": hashlib.sha256(baseline.read_bytes()).hexdigest(), "candidate": hashlib.sha256(args.candidate.read_bytes()).hexdigest()}
    (evidence / "comparator-regression.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
