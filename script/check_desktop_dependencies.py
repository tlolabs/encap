#!/usr/bin/env python3
"""Check the reviewed Qt module inventory and vendored preview source."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def check():
    inventory = json.loads((ROOT / 'qt/dependency-inventory.json').read_text())
    cmake = (ROOT / 'qt/CMakeLists.txt').read_text()
    modules = set(inventory['qt_modules'])
    assert modules == {'Core', 'Gui', 'Widgets'}
    assert 'find_package(Qt6 6.4 REQUIRED COMPONENTS Core Gui Widgets)' in cmake
    linked = set(re.findall(r'Qt6::([A-Za-z0-9_]+)', cmake))
    assert linked == modules, f'Qt linkage differs from reviewed inventory: {linked}'
    assert inventory['qt_license_choice'] == 'GPL-3.0-only'
    for path in inventory['notice_files']:
        assert (ROOT / path).is_file(), f'Missing notice: {path}'
    source = ROOT / 'desktop/vendor/miniaudio.h'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == 'e5cb323cec7932d068a225d7c84f8b895caa7027b6b052fe0085e825c323a730', 'miniaudio source changed'
    print('Qt Core/Gui/Widgets inventory and miniaudio source match the reviewed dependencies.')

if __name__ == '__main__':
    check()
