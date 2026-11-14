#!/usr/bin/env python3
"""Promote a verified IME candidate into a new self-contained runtime directory.

Never edits loaded modules, user settings, or WSLg configuration. Keeps the
accepted machine code, exports, and GLIBC requirements; relocates only the
copied shell's desktop-library dependency. Reports contain private local paths.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from prepare_production_modules import sha, text_hash, exports, versions, output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    source, destination = args.source.resolve(), args.destination.resolve()
    if not destination.is_relative_to(ROOT/'runtime') or destination == ROOT/'runtime':
        parser.error('destination must be a fresh directory beneath runtime/')
    if destination.exists():
        parser.error('refusing to overwrite an existing runtime')
    original = json.loads((source/'build.json').read_text())
    expected = {item['name']:item['sha256'] for item in original['artifacts']}
    desktop = Path(original['desktop_dependency'])
    expected[desktop.name] = original['desktop_sha256']
    inputs = {name:source/name for name in expected if name != desktop.name}
    inputs[desktop.name] = desktop
    required = {'rdp-backend.so','rdprail-shell.so','trusted-socket-relay','libweston-desktop-9.so.0'}
    if set(inputs) != required:
        raise RuntimeError('unexpected accepted artifact set')
    for name,path in inputs.items():
        if sha(path) != expected[name]:
            raise RuntimeError('accepted input hash changed: '+name)
    needed = output('patchelf','--print-needed',str(inputs['rdprail-shell.so'])).splitlines()
    if str(desktop) not in needed:
        raise RuntimeError('candidate shell does not reference its accepted desktop library')
    destination.mkdir(parents=True)
    artifacts = []
    for name,path in inputs.items():
        target = destination/name
        shutil.copy2(path,target)
        target.chmod(0o755)
        if name == 'rdprail-shell.so':
            subprocess.run(['patchelf','--replace-needed',str(desktop),
                str(destination/desktop.name),str(target)],check=True)
        subprocess.run(['strip','--strip-unneeded','--remove-section=.gnu_debuglink',
            '--remove-section=.gnu_debugdata',str(target)],check=True)
        if re.search(r'\.(?:debug_|zdebug_|gnu_debuglink|gnu_debugdata)',
                     output('readelf','-SW',str(target))):
            raise RuntimeError('debug sections remain: '+name)
        if text_hash(path) != text_hash(target) or exports(path) != exports(target) or \
                versions(path) != versions(target) or sha(path) != expected[name]:
            raise RuntimeError('accepted code/ABI changed: '+name)
        artifacts.append({'name':name,'bytes':target.stat().st_size,'sha256':sha(target),
            'source_sha256':expected[name], 'text_sha256':text_hash(target),
            'machine_code_matches_accepted':True,'dynamic_exports_match':True,
            'glibc_requirements_match':True,'debug_sections':False})
    final_needed = output('patchelf','--print-needed',str(destination/'rdprail-shell.so')).splitlines()
    if str(destination/desktop.name) not in final_needed or str(desktop) in final_needed:
        raise RuntimeError('production desktop dependency was not relocated')
    report = {'created_at':datetime.now().astimezone().isoformat(),
        'classification':'custom optimized stripped production deployment; not an official upstream release',
        'source_candidate':str(source),'recompiled':False,'artifacts':artifacts,
        'desktop_dependency':str(destination/desktop.name),
        'desktop_sha256':sha(destination/desktop.name),
        'existing_minimize_fixes_preserved':True}
    (destination/'build.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'prepared':True,'artifacts':artifacts},indent=2))


if __name__ == '__main__':
    main()
