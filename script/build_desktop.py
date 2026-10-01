#!/usr/bin/env python3
"""Build the one shared desktop UI; macOS output is always internal and unsigned."""
import argparse
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
RIDS = ('win-x64', 'win-arm64', 'linux-x64', 'linux-arm64', 'osx-arm64')


def run(*command, cwd=ROOT):
    subprocess.run([str(v) for v in command], cwd=cwd, check=True)


def build(args):
    rid = args.rid
    host = {'Darwin': 'osx', 'Windows': 'win', 'Linux': 'linux'}[platform.system()]
    machine = 'arm64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x64'
    if rid != f'{host}-{machine}':
        raise ValueError('Build native adapters on the matching host; cross-publish alone is not a package.')
    run(sys.executable, ROOT / "script/check_desktop_dependencies.py")
    version = tomllib.loads((ROOT / 'Cargo.toml').read_text())['workspace']['package']['version']
    reference = rid == 'osx-arm64'
    output = ROOT / ('dist/internal/EnCap-Avalonia-Reference.app/Contents/MacOS' if reference else 'dist/staging/EnCap' + ('/bin' if host == 'linux' else ''))
    if reference and subprocess.run(['pgrep', '-f', '^' + str(output / 'EnCap') + '( |$)'], capture_output=True).returncode == 0:
        raise ValueError('Close the running reference application before replacing its bundle.')
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    if host == 'win':
        run(sys.executable, ROOT / 'script/update_config.py', '--props', ROOT / 'build/version.props')
    run(args.dotnet, 'publish', 'EnCap.Desktop/EnCap.Desktop.csproj', '-c', 'Release', '-r', rid,
        '--self-contained', 'true', '--disable-build-servers', '-p:RestoreLockedMode=true', f'-p:Version={version}', '-o', output, cwd=ROOT / 'desktop')
    native_build = ROOT / 'build' / ('desktop-native-' + rid)
    configure = ['cmake', '-S', ROOT / 'desktop/native', '-B', native_build, '-DCMAKE_BUILD_TYPE=Release']
    if host == 'win':
        configure += ['-A', 'ARM64' if machine == 'arm64' else 'x64']
    run(*configure)
    run('cmake', '--build', native_build, '--config', 'Release')
    suffix = '.dll' if host == 'win' else '.dylib' if reference else '.so'
    for library in native_build.rglob('*' + suffix):
        if 'encap-' in library.name:
            shutil.copy2(library, output / library.name)
    tools = args.tools.resolve()
    required = ['encap-engine', 'ffmpeg', 'ffprobe', 'whisper-cli']
    if not reference:
        required += ['encap-update']
    if host == 'win':
        required += ['encap-portable-update']
    for name in required:
        filename = name + ('.exe' if host == 'win' else '')
        shutil.copy2(tools / filename, output / filename)
    metadata = tools.parent / 'Resources/FFmpeg' if reference else tools / 'ffmpeg-runtime'
    target_metadata = output.parent / 'Resources/FFmpeg' if reference else output / 'ffmpeg-runtime'
    shutil.copytree(metadata, target_metadata, dirs_exist_ok=True)
    for name in ('THIRD_PARTY_NOTICES.md', 'LICENSE'):
        shutil.copy2(ROOT / name, output / name)
    shutil.copy2(ROOT / 'desktop/vendor/miniaudio.LICENSE', output / 'MINIAUDIO-LICENSE')
    shutil.copy2(ROOT / 'runtime/AVID_CORE_LICENSE.txt', output / 'AVID_CORE_LICENSE.txt')
    shutil.copytree(ROOT / 'desktop/licenses', output / 'licenses', dirs_exist_ok=True)
    if reference:
        # Deliberately no update helper, update-config, Sparkle, or production bundle identifier.
        for name in ('apple-transcriber', 'apple-aac-info', 'whisperkit-transcriber'):
            if (tools / name).exists():
                shutil.copy2(tools / name, output / name)
        contents = output.parent
        info = dict(CFBundleIdentifier='com.tlolabs.encap.avalonia-reference',
                    CFBundleExecutable='EnCap', CFBundleName='EnCap INTERNAL Avalonia Reference',
                    CFBundleDisplayName='EnCap INTERNAL Avalonia Reference', CFBundlePackageType='APPL',
                    CFBundleVersion=version, CFBundleShortVersionString=version,
                    LSMinimumSystemVersion='13.0', NSHighResolutionCapable=True,
                    NSPrincipalClass='NSApplication', EnCapDistribution='internal-reference')
        (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
        (contents / 'PkgInfo').write_text('APPL????')
        # Ad-hoc signing is local integrity only, with no Developer ID/notarization credentials.
        run('codesign', '--force', '--deep', '--sign', '-', contents.parent)
        archive = ROOT / f'dist/internal/EnCap-{version}-INTERNAL-Avalonia-Reference-osx-arm64.zip'
        run('ditto', '-c', '-k', '--keepParent', contents.parent, archive)
    else:
        target = ('windows-' if host == 'win' else 'linux-') + machine + ('' if host == 'win' else '-appimage')
        run(sys.executable, ROOT / 'script/update_config.py', output, target)
    print(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rid', choices=RIDS, required=True)
    parser.add_argument('--tools', type=Path, required=True, help='Verified staged Rust engine, FFmpeg runtime and Whisper helpers')
    parser.add_argument('--dotnet', default='dotnet')
    parser.add_argument('--run', action='store_true', help='Launch the internal macOS reference app after building')
    args = parser.parse_args()
    destination = build(args)
    if args.run:
        if args.rid != 'osx-arm64':
            parser.error('--run is for the internal macOS reference app')
        run('open', '-n', destination.parent.parent)
