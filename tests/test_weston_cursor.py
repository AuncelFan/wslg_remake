"""Compile the patched cursor path itself, rather than a Python reimplementation.

Set WESTON_CURSOR_SOURCE to a pinned Weston tree with patches 1 through 4 applied.
The live GPU + Wayland probe is a separate integration check.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CursorTest(unittest.TestCase):
    def test_actual_cursor_update(self):
        source = Path(os.environ.get(
            'WESTON_CURSOR_SOURCE', ROOT / '.work/weston-pointer-20261116'))
        path = source / 'libweston/backend-rdp/rdprail.c'
        if not path.is_file():
            self.skipTest('set WESTON_CURSOR_SOURCE to the patched pinned source')
        text = path.read_text()
        start = text.index('static uint32_t\nrdp_rail_cursor_hotspot(')
        end = text.index('\nstatic char *\nrdp_showstate_to_string', start)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'cursor-under-test.h').write_text(text[start:end])
            binary = tmp / 'cursor-test'
            subprocess.run(['cc', '-std=gnu99', '-O2', '-Wall', '-Wextra',
                            '-Werror', '-I' + str(tmp),
                            str(ROOT / 'tests/weston_cursor_harness.c'),
                            '-o', str(binary)], check=True)
            result = subprocess.run([str(binary)], text=True,
                                    capture_output=True, check=True)
            self.assertIn('PASS: 8 cursor geometry/update scenarios', result.stdout)


if __name__ == '__main__':
    unittest.main()
