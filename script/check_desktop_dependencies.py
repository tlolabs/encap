#!/usr/bin/env python3
"""Reject unaudited package/version/hash changes and missing distribution notices."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def check():
    licenses = ROOT / 'desktop/licenses'
    inventory = {(i['package'].lower(), i['version']): i for i in json.loads((licenses / 'inventory.json').read_text())}
    seen = set()
    for project in ('EnCap.Application', 'EnCap.Desktop', 'EnCap.Tests'):
        lock = json.loads((ROOT / 'desktop' / project / 'packages.lock.json').read_text())
        for dependencies in lock['dependencies'].values():
            for name, value in dependencies.items():
                if value['type'].lower() == 'project':
                    continue
                key = (name.lower(), value['resolved'])
                item = inventory[key]
                assert item['nuget_content_hash'] == value['contentHash'], f'Hash changed: {key}'
                for notice in item['notice_files']:
                    assert (licenses / notice).is_file(), f'Missing notice: {notice}'
                seen.add(key)
    assert seen == set(inventory), 'Remove obsolete dependency inventory entries'
    source = ROOT / 'desktop/vendor/miniaudio.h'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == '7852e150a86caa935605b37518526d1e4460a94466b2ca8f320d942ee3e4b433', 'miniaudio source changed'
    print(f'{len(seen)} locked NuGet packages and miniaudio match the reviewed inventory.')

if __name__ == '__main__':
    check()
