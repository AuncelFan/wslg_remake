"""Check reversible user-session promotion without touching the real desktop."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ime_installer',ROOT/'tools/ime/install_user_session.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class SessionPromotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root/'home'
        self.home.mkdir()
        self.runtime = self.root/'runtime'
        self.runtime.mkdir()
        (self.runtime/'build.json').write_text(json.dumps({'artifacts':[]}))
        self.backup = self.root/'backup'
        self.paths = [self.home/'.zshenv',self.home/'.local/bin/chatgpt',
                      self.home/'.config/systemd/user/wslg-ime.service']
        self.originals = [installer.NEW+'\n','#!/bin/sh\nold-wrapper\n','[Service]\nExecStart=/bin/true\n']
        records=[]
        for path,text in zip(self.paths,self.originals):
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(text)
            path.chmod(0o755 if path.name == 'chatgpt' else 0o644)
            records.append({'path':str(path),'installed_sha256':installer.digest(path)})
        self.previous = self.root/'previous.json'
        self.previous.write_text(json.dumps({'files':records}))
        (self.home/'.zshrc').write_text('export GALLIUM_DRIVER=d3d12\nexport LIBVA_DRIVER_NAME=d3d12\n# keep\n')

    def invoke(self,*arguments):
        with patch.object(installer.Path,'home',return_value=self.home), \
             patch.object(sys,'argv',['install_user_session.py',*map(str,arguments)]), \
             patch.object(installer,'run',return_value='') as run, \
             patch.object(installer.subprocess,'run',return_value=subprocess.CompletedProcess([],0)):
            installer.main()
            return run

    def promote(self):
        return self.invoke('--runtime',self.runtime,'--backup',self.backup,
            '--upgrade-from',self.previous,'--remove-legacy-libva')

    def test_upgrade_and_rollback_restore_exact_files_and_enabled_state(self):
        self.promote()
        wrapper=self.paths[1].read_text()
        self.assertIn('--enable-wayland-ime',wrapper)
        self.assertNotIn('--disable-renderer-backgrounding',wrapper)
        self.assertIn('UnsetEnvironment=WAYLAND_SOCKET WAYLAND_DEBUG',self.paths[2].read_text())
        self.assertEqual((self.home/'.zshrc').read_text(),'export GALLIUM_DRIVER=d3d12\n# keep\n')
        manifest=json.loads((self.backup/'manifest.json').read_text())
        self.assertTrue(manifest['service_enabled_before'])
        self.assertEqual(len(manifest['files']),4)
        run=self.invoke('--rollback',self.backup/'manifest.json')
        for path,text in zip(self.paths,self.originals):
            self.assertEqual(path.read_text(),text)
        self.assertIn('export LIBVA_DRIVER_NAME=d3d12',(self.home/'.zshrc').read_text())
        self.assertIn(unittest.mock.call('systemctl','--user','enable','wslg-ime.service'),run.call_args_list)

    def test_changed_current_file_refuses_before_any_write(self):
        self.paths[1].write_text('user edited\n')
        with self.assertRaises(RuntimeError): self.promote()
        self.assertFalse(self.backup.exists())
        self.assertFalse((self.runtime/'ime').exists())
        self.assertEqual(self.paths[1].read_text(),'user edited\n')

    def test_rollback_refuses_to_overwrite_later_user_edits(self):
        self.promote()
        self.paths[1].write_text('new user edit\n')
        with self.assertRaises(RuntimeError): self.invoke('--rollback',self.backup/'manifest.json')
        self.assertEqual(self.paths[1].read_text(),'new user edit\n')

    def test_missing_upgrade_manifest_entry_refuses(self):
        self.previous.write_text(json.dumps({'files':[]}))
        with self.assertRaises(RuntimeError): self.promote()
        self.assertFalse(self.backup.exists())


if __name__ == '__main__':
    unittest.main()
