#!/usr/bin/env python3
"""Build and stage the shared Qt desktop UI on its target host."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ('win-x64', 'win-arm64', 'linux-x64', 'linux-arm64', 'osx-arm64')


def run(*command, env=None):
    subprocess.run([str(arg) for arg in command], cwd=ROOT, check=True, env=env)


def tool(name, qt_prefix):
    suffix = '.exe' if os.name == 'nt' else ''
    if qt_prefix:
        path = qt_prefix / 'bin' / (name + suffix)
        if path.is_file():
            return path
    found = shutil.which(name)
    if not found and platform.system() == 'Linux':
        candidate = Path('/usr/lib/qt6/bin') / name
        if candidate.is_file():
            found = str(candidate)
    if not found:
        raise FileNotFoundError(f'{name} is required to deploy Qt')
    return Path(found)


def copy_required(source, destination):
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def stage_helpers(output, tools, host, reference):
    names = ['encap-engine', 'ffmpeg', 'ffprobe', 'whisper-cli']
    if not reference:
        names.append('encap-update')
    if host == 'win':
        names.append('encap-portable-update')
    suffix = '.exe' if host == 'win' else ''
    for name in names:
        copy_required(tools / (name + suffix), output / (name + suffix))
    metadata = tools.parent / 'Resources/FFmpeg' if reference else tools / 'ffmpeg-runtime'
    target = output.parent / 'Resources/FFmpeg' if reference else output / 'ffmpeg-runtime'
    if not metadata.is_dir():
        raise FileNotFoundError(metadata)
    shutil.copytree(metadata, target, dirs_exist_ok=True)
    for name in ('THIRD_PARTY_NOTICES.md', 'LICENSE'):
        copy_required(ROOT / name, output / name)
    copy_required(ROOT / 'desktop/vendor/miniaudio.LICENSE', output / 'MINIAUDIO-LICENSE')
    copy_required(ROOT / 'runtime/AVID_CORE_LICENSE.txt', output / 'AVID_CORE_LICENSE.txt')


def record_qt_runtime(destination, output, host, qt_prefix):
    qmake = None
    for name in ('qmake6', 'qmake'):
        try:
            qmake = tool(name, qt_prefix)
            break
        except FileNotFoundError:
            pass
    if qmake is None:
        raise FileNotFoundError('qmake is needed to record the exact packaged Qt version')
    version = subprocess.check_output([str(qmake), '-query', 'QT_VERSION'], text=True).strip()
    if not version.startswith('6.'):
        raise ValueError('Only Qt 6 may be packaged')
    files = []
    for path in destination.rglob('*'):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(destination).as_posix()
        name = path.name.lower()
        if not (name.startswith(('qt6', 'libqt6', 'libq')) or '/plugins/' in relative.lower()
                or '/frameworks/' in relative.lower() or relative.startswith('lib/')
                or (host == 'win' and path.suffix.lower() == '.dll')):
            continue
        files.append({'path': relative, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    if not files:
        raise ValueError('Qt deployment is empty')
    record = {
        'qt_version': version,
        'host': host,
        'modules_linked': ['Core', 'Gui', 'Widgets'],
        'license_selection': 'GPL-3.0-only',
        'source_and_notices': 'docs/qt-licensing.md',
        'files': sorted(files, key=lambda value: value['path']),
    }
    (output / 'qt-runtime.json').write_text(json.dumps(record, indent=2) + '\n')
    copy_required(ROOT / 'docs/qt-licensing.md', output / 'QT_LICENSE_AND_SOURCE.md')


def build(args):
    if args.qt_prefix:
        args.qt_prefix = args.qt_prefix.resolve(strict=True)
    host = {'Darwin': 'osx', 'Windows': 'win', 'Linux': 'linux'}[platform.system()]
    machine = 'arm64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x64'
    if args.rid != f'{host}-{machine}':
        raise ValueError('Build and package on the matching native target host')
    reference = host == 'osx'
    version = tomllib.loads((ROOT / 'Cargo.toml').read_text())['workspace']['package']['version']
    build_dir = ROOT / 'build' / ('qt-' + args.rid)
    configure = ['cmake', '-S', ROOT / 'qt', '-B', build_dir, '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_TESTING=ON',
                 f'-DENCAP_VERSION={version}']
    if args.qt_prefix:
        configure.append(f'-DCMAKE_PREFIX_PATH={args.qt_prefix}')
    if host == 'win':
        configure += ['-A', 'ARM64' if machine == 'arm64' else 'x64']
    tools = args.tools.resolve()
    run(*configure)
    run('cmake', '--build', build_dir, '--config', 'Release', '--parallel')
    suffix = '.exe' if host == 'win' else ''
    test_tools = build_dir / ('Release' if host == 'win' else '')
    copy_required(tools / ('encap-engine' + suffix), test_tools / ('encap-engine' + suffix))
    if host == 'win':
        for name in ('encap-playback', 'encap-media'):
            copy_required(build_dir / 'native/Release' / (name + '.dll'), test_tools / (name + '.dll'))
    environment = os.environ.copy()
    environment['ENCAP_TEST_ENGINE'] = str(tools / ('encap-engine' + suffix))
    if host == 'win' and args.qt_prefix:
        environment['PATH'] = str(test_tools) + os.pathsep + str(args.qt_prefix / 'bin') + os.pathsep + environment['PATH']
        environment['QT_PLUGIN_PATH'] = str(args.qt_prefix / 'plugins')
    run('ctest', '--test-dir', build_dir, '-C', 'Release', '--output-on-failure', env=environment)

    if reference:
        destination = ROOT / 'dist/internal/EnCap-Qt-Reference.app'
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(build_dir / 'EnCap.app', destination, symlinks=True)
        contents = destination / 'Contents'
        executable = contents / 'MacOS/EnCap'
        frameworks = contents / 'Frameworks'
        frameworks.mkdir(exist_ok=True)
        copy_required(build_dir / 'native/libencap-playback.dylib', frameworks / 'libencap-playback.dylib')
        run('install_name_tool', '-change', '@rpath/libencap-playback.dylib',
            '@executable_path/../Frameworks/libencap-playback.dylib', executable)
        deploy = tool('macdeployqt', args.qt_prefix)
        run(deploy, destination, '-no-plugins', '-always-overwrite')
        qtplugins = Path(subprocess.check_output([str(tool('qmake', args.qt_prefix)),
                                                   '-query', 'QT_INSTALL_PLUGINS'], text=True).strip())
        for relative in ('platforms/libqcocoa.dylib', 'styles/libqmacstyle.dylib',
                         'imageformats/libqjpeg.dylib', 'imageformats/libqgif.dylib',
                         'imageformats/libqico.dylib'):
            plugin = contents / 'PlugIns' / relative
            copy_required(qtplugins / relative, plugin)
            run(deploy, destination, '-no-plugins', f'-executable={plugin}', '-always-overwrite')
        stage_helpers(contents / 'MacOS', tools, host, True)
        record_qt_runtime(destination, contents / 'MacOS', host, args.qt_prefix)
        info_path = contents / 'Info.plist'
        info = plistlib.loads(info_path.read_bytes())
        info.update(CFBundleIdentifier='com.tlolabs.encap.qt-reference',
                    CFBundleName='EnCap INTERNAL Qt Reference', CFBundleDisplayName='EnCap INTERNAL Qt Reference',
                    CFBundleVersion=version, CFBundleShortVersionString=version,
                    LSMinimumSystemVersion='13.0', NSHighResolutionCapable=True,
                    EnCapDistribution='internal-reference')
        info_path.write_bytes(plistlib.dumps(info))
        for forbidden in ('encap-update', 'update-config.json', 'Sparkle.framework'):
            if list(destination.rglob(forbidden)):
                raise ValueError(f'Internal reference contains forbidden production component: {forbidden}')
        run('codesign', '--force', '--deep', '--sign', '-', destination)
        archive = ROOT / f'dist/internal/EnCap-{version}-INTERNAL-Qt-Reference-osx-arm64.zip'
        archive.unlink(missing_ok=True)
        run('ditto', '-c', '-k', '--keepParent', destination, archive)
        if args.run:
            run('open', '-n', destination)
        return destination

    destination = ROOT / 'dist/staging/EnCap'
    if destination.exists():
        shutil.rmtree(destination)
    if host == 'win':
        output = destination
        copy_required(build_dir / 'Release/EnCap.exe', output / 'EnCap.exe')
        for name in ('encap-playback', 'encap-media'):
            copy_required(build_dir / 'native/Release' / (name + '.dll'), output / (name + '.dll'))
        run(tool('windeployqt', args.qt_prefix), '--release', '--no-translations', '--no-opengl-sw', output / 'EnCap.exe')
    else:
        output = destination / 'bin'
        copy_required(build_dir / 'EnCap', output / 'EnCap')
        for name in ('encap-playback', 'encap-media'):
            copy_required(build_dir / 'native' / ('lib' + name + '.so'), output / ('lib' + name + '.so'))
        qtpaths = tool('qtpaths6', args.qt_prefix)
        def query(key):
            return Path(subprocess.check_output([qtpaths, '--query', key], text=True).strip())
        qtlib, plugins = query('QT_INSTALL_LIBS'), query('QT_INSTALL_PLUGINS')
        for name in ('Core', 'Gui', 'Widgets', 'DBus', 'XcbQpa', 'WaylandClient'):
            for library in qtlib.glob('libQt6' + name + '.so*'):
                if library.is_file():
                    copy_required(library.resolve(), destination / 'lib' / library.name)
        for category in ('platforms', 'platformthemes', 'imageformats', 'iconengines', 'xcbglintegrations', 'wayland-shell-integration'):
            if (plugins / category).is_dir():
                shutil.copytree(plugins / category, output / 'plugins' / category, symlinks=True)
        (output / 'qt.conf').write_text('[Paths]\nPlugins = plugins\n')
        desktop = destination / 'share/applications/com.tlolabs.encap.desktop'
        copy_required(ROOT / 'desktop/packaging/com.tlolabs.encap.desktop', desktop)
        copy_required(ROOT / 'assets/icons/png/EnCap-256.png',
                      destination / 'share/icons/hicolor/256x256/apps/com.tlolabs.encap.png')
    stage_helpers(output, tools, host, False)
    record_qt_runtime(destination, output, host, args.qt_prefix)
    target = ('windows-' if host == 'win' else 'linux-') + machine + ('' if host == 'win' else '-appimage')
    run(sys.executable, ROOT / 'script/update_config.py', output, target)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rid', choices=TARGETS, required=True)
    parser.add_argument('--tools', type=Path, required=True, help='staged Rust engine, FFmpeg and Whisper binaries')
    parser.add_argument('--qt-prefix', type=Path, help='Qt installation prefix containing bin, lib and plugins')
    parser.add_argument('--run', action='store_true', help='launch the internal macOS Qt reference')
    options = parser.parse_args()
    if options.run and options.rid != 'osx-arm64':
        parser.error('--run requires --rid osx-arm64')
    print(build(options))
