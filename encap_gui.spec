# -*- mode: python ; coding: utf-8 -*-

import os
import platform
import shutil
import sys

sys.path.insert(0, 'src')

from encap.version import __version__


public_key_path = 'src/encap/update_public_key.txt'
datas = [(public_key_path, 'encap')] if os.path.exists(public_key_path) else []
if os.path.exists('THIRD_PARTY_NOTICES.md'):
    datas.append(('THIRD_PARTY_NOTICES.md', '.'))

lame_binary = os.environ.get('ENCAP_LAME_BINARY', '').strip() or shutil.which('lame')
binaries = [(lame_binary, '.')] if lame_binary and os.path.isfile(lame_binary) else []
windows_icon_path = 'assets/icons/EnCap.ico' if sys.platform == 'win32' else None


a = Analysis(
    ['src/encap/gui.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='EnCap',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=windows_icon_path,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='EnCap',
)

if sys.platform == 'darwin':
    platform_name = os.environ.get('ENCAP_PLATFORM')
    if not platform_name:
        platform_name = 'macos-arm64' if platform.machine().lower() == 'arm64' else 'macos-intel'
    public_key = os.environ.get('ENCAP_UPDATE_PUBLIC_KEY', '').strip()
    info_plist = {
        'CFBundleDisplayName': 'EnCap',
        'CFBundleName': 'EnCap',
        'CFBundleShortVersionString': __version__,
        'CFBundleVersion': __version__,
        'LSMinimumSystemVersion': '13.0.0',
        'NSHighResolutionCapable': True,
        'NSSpeechRecognitionUsageDescription': (
            'EnCap uses speech recognition to transcribe audio files you select. '
            'Apple On-Device mode keeps the audio on this Mac.'
        ),
    }
    if public_key:
        info_plist.update(
            {
                'SUFeedURL': (
                    'https://github.com/tlolabs/encap/releases/latest/download/'
                    f'appcast-{platform_name}.xml'
                ),
                'SUPublicEDKey': public_key,
                'SUEnableAutomaticChecks': True,
                'SUAutomaticallyUpdate': True,
            }
        )
    app = BUNDLE(
        coll,
        name='EnCap.app',
        icon='assets/icons/EnCap.icns',
        bundle_identifier='com.tlolabs.encap',
        info_plist=info_plist,
    )
