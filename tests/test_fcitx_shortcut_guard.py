"""Verify that an outdated or modified addon cannot be selected silently."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'tools/ime/fcitx-waylandim/guarded_session.py'
SPEC = importlib.util.spec_from_file_location('fcitx_shortcut_guard', SOURCE)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class ShortcutGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        (self.directory / 'libwaylandim.so').write_bytes(b'test module')
        self.manifest = {
            'packages': {'fcitx5': '5.1.7-1build3'},
            'sha256': hashlib.sha256(b'test module').hexdigest(),
            'system_addon_dir': str(self.directory),
        }
        self.write_manifest()

    def write_manifest(self):
        (self.directory / 'manifest.json').write_text(json.dumps(self.manifest))

    def query(self, version='5.1.7-1build3'):
        return patch.object(guard.subprocess, 'run', return_value=
            subprocess.CompletedProcess([], 0, f'fcitx5\t{version}\n', ''))

    def test_matching_build_selected(self):
        with self.query():
            self.assertEqual(guard.addon_path(self.directory),
                             f'{self.directory}:{self.directory}')

    def test_changed_package_rejected(self):
        with self.query('5.1.13-1'):
            with self.assertRaisesRegex(ValueError, 'versions changed'):
                guard.addon_path(self.directory)

    def test_modified_module_rejected(self):
        (self.directory / 'libwaylandim.so').write_bytes(b'changed')
        with self.query():
            with self.assertRaisesRegex(ValueError, 'checksum changed'):
                guard.addon_path(self.directory)

    def test_empty_package_manifest_rejected(self):
        self.manifest['packages'] = {}
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'empty package manifest'):
            guard.addon_path(self.directory)


if __name__ == '__main__':
    unittest.main()
