#!/usr/bin/env python3
"""Acquire/build/stage EnCAP's pinned linked application library; never publish.

An SDK override must pass the same receipt/spec/source checks as a source build.
This helper issues unqualified development candidates, not platform qualification.
The historical executable-runtime checks remain separate for unfinished paths.
"""
import argparse
import ctypes
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent.parent
PIN = ROOT / 'runtime/linked-core.json'
TARGETS = {
    'macos-arm64': 'aarch64-apple-darwin', 'macos-x86_64': 'x86_64-apple-darwin',
    'windows-x86_64': 'x86_64-pc-windows-gnu', 'windows-arm64': 'aarch64-pc-windows-gnullvm',
    'linux-x86_64': 'x86_64-unknown-linux-gnu', 'linux-arm64': 'aarch64-unknown-linux-gnu',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def obj(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique)


def run(command, **kwargs):
    return subprocess.check_output([str(value) for value in command], text=True, **kwargs).strip()


def checked_path(root, relative):
    path = PurePosixPath(relative)
    require(relative and not path.is_absolute() and '\\' not in relative and ':' not in relative
            and all(part not in ('', '.', '..') for part in relative.split('/')), 'Unsafe receipt path')
    result = Path(root) / relative
    require(result.is_file() and not result.is_symlink() and result.resolve().is_relative_to(Path(root).resolve()),
            'Missing, linked or escaping receipt file: ' + relative)
    return result


def source_checkout(cache=None, fetch=False):
    pin = obj(PIN)
    source = Path(cache or Path(tempfile.gettempdir()) / ('encap-linked-core-source-' + pin['revision'])).absolute()
    if not source.exists():
        require(fetch, 'Pinned Core source missing; provision with --fetch or a previously acquired --cache')
        source.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='encap-core-acquire-', dir=source.parent) as temporary:
            checkout = Path(temporary) / 'source'
            subprocess.run(['git', 'init', str(checkout)], check=True, stdout=sys.stderr)
            subprocess.run(['git', '-C', str(checkout), 'remote', 'add', 'origin', pin['repository']], check=True)
            subprocess.run(['git', '-C', str(checkout), 'fetch', '--depth=1', 'origin', pin['revision']], check=True,
                           stdout=sys.stderr)
            subprocess.run(['git', '-C', str(checkout), 'checkout', '--detach', 'FETCH_HEAD'], check=True,
                           stdout=sys.stderr)
            checkout.rename(source)
    require(run(['git', '-C', source, 'remote', 'get-url', 'origin']) == pin['repository'],
            'Core source cache origin differs from the immutable remote pin')
    require(run(['git', '-C', source, 'rev-parse', 'HEAD']) == pin['revision'], 'Core source revision mismatch')
    require(not run(['git', '-C', source, '-c', 'core.fsmonitor=false', 'status', '--porcelain', '--untracked-files=all']),
            'Core source checkout contains changes; use an unchanged pinned cache')
    require(digest(source / 'runtime/linked/spec.json') == pin['spec_sha256'], 'Core linked specification identity mismatch')
    return source


def upstream(source):
    # Only execute modules from the verified immutable remote checkout.
    sys.path.insert(0, str(source / 'scripts/linked'))
    for name in ('binary', 'source', 'runtime'):
        sys.modules.pop(name, None)
    binary = importlib.import_module('binary')
    runtime = importlib.import_module('runtime')
    return binary, runtime


def validate_sdk(prefix, target_id, profile, source):
    require(target_id in TARGETS, 'Unsupported application target')
    prefix = Path(prefix).absolute()
    metadata = obj(prefix / 'linked-ffmpeg.json')
    spec = obj(source / 'runtime/linked/spec.json')
    target = next(value for value in spec['targets'] if value['id'] == target_id)
    require(profile in spec['profiles'] and target['platform'] in spec['profiles'][profile]['platforms'],
            'Profile does not support the selected platform')
    require(metadata.get('schema') == 1 and metadata.get('kind') == 'avid-linked-ffmpeg'
            and metadata.get('target') == TARGETS[target_id] and metadata.get('target_id') == target_id
            and metadata.get('platform') == target['platform'] and metadata.get('arch') == target['arch']
            and metadata.get('profile') == profile and metadata.get('minimum') == target['minimum']
            and metadata.get('linkage') == 'static'
            and metadata.get('source_revision') == spec['ffmpeg']['revision']
            and metadata.get('ffmpeg_version') == spec['ffmpeg']['version'], 'Linked SDK identity/profile/target mismatch')
    require(metadata.get('source_provenance', {}).get('status') == 'verified'
            and metadata['source_provenance'].get('archive_sha256') == spec['ffmpeg']['sha256'],
            'Linked SDK source authentication missing')
    binary, runtime = upstream(source)
    runtime.verify_sdk_spec(prefix, metadata, spec)
    required_libraries = {'lib/lib' + name + '.a' for name in spec['libraries']}
    libraries = metadata.get('libraries', {})
    require(required_libraries <= set(libraries), 'Required linked native libraries missing')
    for relative, expected in libraries.items():
        path = checked_path(prefix, relative)
        require(digest(path) == expected, 'Linked SDK library hash mismatch: ' + relative)
        binary.validate_file(path, target)
    names = {'ffmpeg', *spec['profiles'][profile]['dependencies']}
    require(set(metadata.get('sources', {})) == names, 'Corresponding source inventory mismatch')
    for name, record in metadata['sources'].items():
        path = checked_path(prefix, 'corresponding-source/' + record['archive'])
        require(digest(path) == record['sha256'], 'Corresponding source hash mismatch: ' + name)
        expected = spec['ffmpeg'] if name == 'ffmpeg' else spec['dependencies'][name]
        require(record['sha256'] == expected.get('sha256', expected.get('archive_sha256')),
                'Corresponding source differs from Core pin: ' + name)
        notices = prefix / 'licenses' / name
        require(notices.is_dir() and any(path.is_file() and not path.is_symlink() for path in notices.iterdir()),
                'Required dependency notices missing: ' + name)
    runtime.verified_runtime_dependencies(prefix, metadata, target)
    expected_encoders = set(spec['encoders'] + spec['profiles'][profile]['encoders'])
    require(expected_encoders <= set(metadata.get('components', {}).get('encoder', [])), 'Profile encoders missing')
    require(metadata.get('components', {}).get('protocol') == ['file'], 'Unexpected media network protocol')
    return {'prefix': str(prefix), 'target': target_id, 'rust_target': TARGETS[target_id], 'profile': profile,
            'minimum': target['minimum'], 'metadata_sha256': digest(prefix / 'linked-ffmpeg.json'),
            'core_revision': obj(PIN)['revision'], 'core_spec_sha256': obj(PIN)['spec_sha256'],
            'sdk_original_spec_sha256': metadata['spec_sha256'], 'selected_recipe_equivalence': 'verified',
            'native_qualification': 'not_run'}


def provision(args):
    source = source_checkout(args.cache, args.fetch)
    prefix = args.prefix
    if prefix is None:
        require(args.work is not None, 'A fresh --work directory is required to build a linked SDK')
        command = [sys.executable, source / 'scripts/linked/build.py', '--target', args.target,
                   '--profile', args.profile, '--work', args.work, '--jobs', str(args.jobs)]
        if args.fetch:
            command.append('--fetch')
        if args.cmake:
            command += ['--cmake', args.cmake]
        for name in ('cc', 'cxx', 'cxx_runtime'):
            value = getattr(args, name, None)
            if value:
                command += ['--' + name.replace('_', '-'), value]
        subprocess.run([str(value) for value in command], check=True, stdout=sys.stderr)
        prefix = args.work / 'prefix'
    return validate_sdk(prefix, args.target, args.profile, source)


def application_source():
    names = run(['git', '-C', ROOT, '-c', 'core.fsmonitor=false', 'ls-files', '-co', '--exclude-standard', '-z']).split('\0')
    # Preserve, but do not absorb, the unrelated owner reports/evidence present
    # before this task. All native host inputs and build/packaging recipes are
    # part of the combined application corresponding-source inventory.
    preexisting = ('docs/verification/transcription-avid-core-evidence/',)
    preexisting_files = {'docs/verification/transcription-avid-core.md',
                        'helpers/avid_transcriber/VERIFICATION.md'}
    files = {name: digest(ROOT / name) for name in sorted(set(names))
             if name and name not in preexisting_files and not name.startswith(preexisting)
             and (name in ('Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
                           'README.md', 'CHANGELOG.md', 'Makefile', 'AGENTS.md', '.gitignore')
                  or name.startswith(('crates/', 'include/', 'runtime/', 'vendor/', 'macos/', 'qt/',
                                      'desktop/', 'helpers/', 'script/', '.github/', 'assets/', 'docs/', 'updater/')))
             and (ROOT / name).is_file() and not (ROOT / name).is_symlink()}
    return {'sha256': hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(), 'files': files,
            'head': run(['git', '-C', ROOT, 'rev-parse', 'HEAD'])}


def library_name(target):
    return 'encap_app.dll' if target.startswith('windows') else 'libencap_app.' + ('dylib' if target.startswith('macos') else 'so')


def metadata_directory(library_directory):
    directory = Path(library_directory)
    if directory.name == 'Frameworks' and directory.parent.name == 'Contents':
        # Frameworks is an Apple code location. Source archives, receipts and
        # notices belong in Resources so codesign does not treat them as code.
        return directory.parent / 'Resources/EnCAPLinked'
    return directory / 'EnCAPLinked'


def normalized_code(path):
    from verify_macos_qualification import code_hash
    with tempfile.TemporaryDirectory(prefix='encap-linked-code-') as temporary:
        return code_hash(path, Path(temporary))


def bundle_sources(args):
    require(not args.output.exists(), 'Fresh corresponding-source output required')
    lock_hash = digest(ROOT / 'Cargo.lock')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='encap-cargo-sources-') as temporary:
        tree = Path(temporary)
        command = ['cargo', 'vendor', '--manifest-path', ROOT / 'Cargo.toml', '--locked', '--versioned-dirs']
        if not args.fetch:
            command.append('--offline')
        command.append(tree / 'vendor')
        configuration = run(command)
        require(digest(ROOT / 'Cargo.lock') == lock_hash, 'Cargo.lock changed during source bundling')
        (tree / 'vendor-config.toml').write_text(configuration.replace(str(tree / 'vendor'), 'vendor') + '\n')
        shutil.copy2(ROOT / 'Cargo.lock', tree / 'Cargo.lock')
        shutil.copy2(ROOT / 'Cargo.toml', tree / 'Cargo.toml')
        files = {}
        for path in sorted(tree.rglob('*')):
            require(not path.is_symlink(), 'Corresponding Cargo source contains a symlink')
            if path.is_file():
                files[path.relative_to(tree).as_posix()] = digest(path)
        require(any(name.endswith('/.cargo-checksum.json') for name in files), 'Cargo source checksums missing')
        manifest = {'schema': 1, 'kind': 'encap-cargo-corresponding-source', 'cargo_lock_sha256': lock_hash,
                    'files': files, 'scope': 'All Cargo.lock target dependencies, including pinned Git Core and licenses'}
        (tree / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
        with tarfile.open(args.output, 'w:gz') as archive:
            for path in sorted(tree.rglob('*')):
                if path.is_file():
                    archive.add(path, arcname=path.relative_to(tree).as_posix(), recursive=False)
    return {'source_bundle': str(args.output), 'sha256': digest(args.output), 'cargo_lock_sha256': lock_hash,
            'file_count': len(files), 'status': 'verified'}


def verify_source_bundle(path):
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        require(len(names) == len(set(names)) and sum(member.size for member in members) <= 4 * 1024**3,
                'Duplicate or oversized Cargo source bundle')
        for member in members:
            require(member.isfile() and not member.name.startswith('/') and '\\' not in member.name
                    and ':' not in member.name and all(part not in ('', '.', '..') for part in member.name.split('/')),
                    'Unsafe Cargo source bundle entry')
        manifest_member = archive.getmember('manifest.json')
        require(manifest_member.size <= 32 * 1024**2, 'Oversized Cargo source manifest')
        manifest = json.loads(archive.extractfile(manifest_member).read())
        require(manifest.get('schema') == 1 and manifest.get('kind') == 'encap-cargo-corresponding-source'
                and manifest.get('cargo_lock_sha256') == digest(ROOT / 'Cargo.lock'),
                'Cargo source bundle differs from application lockfile')
        require(set(names) == set(manifest['files']) | {'manifest.json'}, 'Cargo source inventory mismatch')
        for member in members:
            if member.name != 'manifest.json':
                require(hashlib.file_digest(archive.extractfile(member), 'sha256').hexdigest() == manifest['files'][member.name],
                        'Cargo source bundle file hash mismatch: ' + member.name)
        import tomllib
        lock_bytes = archive.extractfile('Cargo.lock').read()
        require(hashlib.sha256(lock_bytes).hexdigest() == digest(ROOT / 'Cargo.lock'), 'Bundled Cargo.lock changed')
        packages = [package for package in tomllib.loads(lock_bytes.decode())['package'] if 'source' in package]
        expected_directories = {'vendor/' + package['name'] + '-' + package['version'] for package in packages}
        checksum_files = {name.rsplit('/', 1)[0] for name in names if name.endswith('/.cargo-checksum.json')}
        require(checksum_files == expected_directories, 'Incomplete or unexpected Cargo dependency inventory')
        for package in packages:
            directory = 'vendor/' + package['name'] + '-' + package['version']
            checksum = json.loads(archive.extractfile(directory + '/.cargo-checksum.json').read())
            require(checksum.get('package') == package.get('checksum'), 'Cargo registry package checksum differs from lockfile')
            actual_files = {name.removeprefix(directory + '/'): sha for name, sha in manifest['files'].items()
                            if name.startswith(directory + '/') and name != directory + '/.cargo-checksum.json'}
            require(actual_files == checksum.get('files'), 'Vendored dependency differs from Cargo checksums: ' + directory)
    return {'sha256': digest(path), 'cargo_lock_sha256': manifest['cargo_lock_sha256'],
            'file_count': len(manifest['files']), 'status': 'verified'}


def binary_identity(path, target_id, source):
    spec = obj(source / 'runtime/linked/spec.json')
    target = next(value for value in spec['targets'] if value['id'] == target_id)
    binary, _ = upstream(source)
    identity = binary.validate_file(path, target)
    if target_id.startswith('macos'):
        data = Path(path).read_bytes()
        offset, count = 32, struct.unpack_from('<I', data, 16)[0]
        minima = []
        for _ in range(count):
            command, size = struct.unpack_from('<II', data, offset)
            require(size >= 8 and offset + size <= len(data), 'Malformed Mach-O load command')
            if command in (0x32, 0x24):
                value = struct.unpack_from('<I', data, offset + (12 if command == 0x32 else 8))[0]
                minima.append((value >> 16, (value >> 8) & 255, value & 255))
            offset += size
        require(minima and max(minima) <= (13, 0, 0), 'Linked application library exceeds macOS 13 deployment baseline')
        identity['minimum'] = '.'.join(map(str, max(minima)))
    return identity


def build(args):
    source = source_checkout(args.cache)
    sdk = validate_sdk(args.prefix, args.target, args.profile, source)
    require(os.environ.get('AVID_FFMPEG_DEV') != '1', 'Development SDK bypass cannot establish linked build provenance')
    before = application_source()
    target_dir = args.target_dir.absolute()
    env = dict(os.environ, AVID_FFMPEG_PREFIX=sdk['prefix'], AVID_FFMPEG_STATIC='1', CARGO_TARGET_DIR=str(target_dir))
    if args.target.startswith('macos'):
        env['MACOSX_DEPLOYMENT_TARGET'] = '13.0'
        flag = '-Clink-arg=-Wl,-install_name,@rpath/libencap_app.dylib'
    elif args.target.startswith('linux'):
        flag = '-Clink-arg=-Wl,-soname,libencap_app.so'
    else:
        flag = None
    if flag:
        existing = env.get('CARGO_ENCODED_RUSTFLAGS')
        if existing is None:
            import shlex
            existing = '\x1f'.join(shlex.split(env.get('RUSTFLAGS', '')))
        env['CARGO_ENCODED_RUSTFLAGS'] = existing + ('\x1f' if existing else '') + flag
    subprocess.run(['cargo', 'build', '--manifest-path', str(ROOT / 'Cargo.toml'), '--locked', '--release',
                    '--target', TARGETS[args.target], '-p', 'encap-app'], env=env, check=True, stdout=sys.stderr)
    require(application_source() == before, 'Application source changed during linked build; no receipt issued')
    library = target_dir / TARGETS[args.target] / 'release' / library_name(args.target)
    binary = binary_identity(library, args.target, source)
    features = run(['cargo', 'tree', '--locked', '--offline', '--manifest-path', ROOT / 'Cargo.toml',
                    '--target', TARGETS[args.target], '-p', 'encap-app', '-e', 'features'], env=env)
    require('legacy-subprocess' not in features, 'Production linked build includes legacy-subprocess')
    rust_runtime = importlib.import_module('rust_runtime')
    runtime_record = rust_runtime.inspect_rust_runtime(TARGETS[args.target])
    receipt = {'schema': 1, 'kind': 'encap-linked-application-build', 'source': before, 'sdk': sdk,
               'core': obj(PIN), 'features': features, 'rustc': run(['rustc', '-vV']),
               'rust_runtime': runtime_record,
               'library': {'name': library.name, 'path': str(library), 'sha256': digest(library), 'identity': binary},
               'validation': {'native_qualification': 'not_run', 'distribution': 'unqualified',
                              'audio_export': 'unfinished compatibility subprocess',
                              'qt_pcm_playback': 'unfinished compatibility subprocess'}}
    if args.target.startswith('macos'):
        receipt['library']['code_sha256'] = normalized_code(library)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2) + '\n')
    return {'library': str(library), 'receipt': str(args.receipt), 'sha256': digest(library), 'sdk': sdk}


def stage(args):
    source = source_checkout(args.cache)
    sdk = validate_sdk(args.prefix, args.target, args.profile, source)
    receipt = obj(args.receipt)
    require(receipt.get('kind') == 'encap-linked-application-build' and receipt.get('schema') == 1
            and receipt.get('core') == obj(PIN) and receipt.get('sdk') == sdk,
            'Linked application receipt/source/SDK mismatch')
    require(receipt.get('source') == application_source(), 'Application source differs from linked build receipt')
    require(args.library.name == library_name(args.target)
            and receipt['library']['sha256'] == digest(args.library), 'Linked library differs from build receipt')
    identity = binary_identity(args.library, args.target, source)
    require(identity == receipt['library']['identity'], 'Linked binary identity differs from build receipt')
    source_bundle = verify_source_bundle(args.source_bundle) if args.source_bundle else None
    require(not args.destination.exists() or not (args.destination / args.library.name).exists(),
            'Refusing to overwrite an existing linked library')
    # A host on another target cannot execute ABI qualification. Inspection still
    # rejects contamination; native final-package smoke remains separately required.
    import platform
    native = ((args.target.startswith('macos') and sys.platform == 'darwin')
              or (args.target.startswith('linux') and sys.platform.startswith('linux'))
              or (args.target.startswith('windows') and sys.platform == 'win32'))
    arch = 'arm64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x86_64'
    if native and args.target.endswith(arch):
        api = ctypes.CDLL(str(args.library.absolute()))
        require(api.encap_app_abi_version() == 1 and api.encap_app_schema_version() == 1, 'Application ABI/schema mismatch')
    dependencies = identity.get('dependencies', [])
    # The linked media SDK is static. Reject unresolved custom loader dependencies
    # rather than copying arbitrary system/developer libraries into the package.
    if args.target.startswith('macos'):
        require(all(name.startswith(('/System/Library/', '/usr/lib/')) for name in dependencies),
                'Unprovided custom linked-library dependency')
    elif args.target.startswith('linux'):
        allowed = {'libc.so.6', 'libm.so.6', 'libpthread.so.0', 'libdl.so.2', 'librt.so.1',
                   'libgcc_s.so.1', 'libstdc++.so.6', 'ld-linux-x86-64.so.2', 'ld-linux-aarch64.so.1'}
        require(set(dependencies) <= allowed, 'Unprovided linked ELF dependency')
    else:
        # PE inspection by the upstream parser covers architecture, not imports.
        text = run(['llvm-readobj', '--coff-imports', args.library])
        import re
        imports = {name.lower() for name in re.findall(r'^\s+Name: (\S+)\s*$', text, re.M)}
        allowed = {'kernel32.dll', 'ntdll.dll', 'user32.dll', 'advapi32.dll', 'bcrypt.dll', 'ws2_32.dll',
                   'ole32.dll', 'shell32.dll', 'userenv.dll', 'secur32.dll', 'normaliz.dll', 'msvcrt.dll',
                   'ucrtbase.dll', 'crypt32.dll', 'iphlpapi.dll', 'ncrypt.dll', 'oleaut32.dll'}
        require(all(name in allowed or name.startswith(('api-ms-win-', 'ext-ms-win-')) for name in imports),
                'Unprovided Windows runtime DLL; provide a supported static runtime build or extend explicit packaging')
        identity['imports'] = sorted(imports)
    args.destination.mkdir(parents=True, exist_ok=True)
    metadata_dir = metadata_directory(args.destination)
    require(not metadata_dir.exists(), 'Fresh linked metadata destination required')
    metadata_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.encap-linked-stage-', dir=args.destination) as temporary:
        staging = Path(temporary)
        payload = staging / 'EnCAPLinked'
        payload.mkdir()
        shutil.copy2(args.receipt, payload / 'build-receipt.json')
        shutil.copy2(PIN, payload / 'core-source.json')
        shutil.copy2(args.prefix / 'linked-ffmpeg.json', payload / 'linked-ffmpeg.json')
        shutil.copy2(source / 'runtime/linked/spec.json', payload / 'linked-spec.json')
        (payload / 'validator').mkdir()
        shutil.copy2(source / 'scripts/linked/binary.py', payload / 'validator/binary.py')
        shutil.copytree(args.prefix / 'licenses', payload / 'licenses')
        shutil.copytree(args.prefix / 'corresponding-source', payload / 'corresponding-source')
        rust_runtime = importlib.import_module('rust_runtime')
        rust_runtime.copy_rust_runtime(receipt['rust_runtime'], payload / 'licenses/rust-runtime')
        with (payload / 'corresponding-source/avid-core.tar').open('wb') as output:
            subprocess.run(['git', '-C', str(source), 'archive', obj(PIN)['revision']], stdout=output, check=True)
        with tarfile.open(payload / 'corresponding-source/encap-source.tar.gz', 'w:gz') as output:
            for name in receipt['source']['files']:
                output.add(ROOT / name, arcname=name, recursive=False)
        if source_bundle:
            shutil.copy2(args.source_bundle, payload / 'corresponding-source/cargo-dependencies.tar.gz')
            require(digest(payload / 'corresponding-source/cargo-dependencies.tar.gz') == source_bundle['sha256'],
                    'Cargo source bundle changed during staging')
            (payload / 'cargo-source-bundle.json').write_text(json.dumps(source_bundle, indent=2) + '\n')
        (payload / 'qualification.json').write_text(json.dumps({
            'status': 'development-unqualified', 'native_final_package': 'not_run',
            'corresponding_cargo_dependency_sources': 'verified' if source_bundle else 'required before distribution',
            'limitations': obj(PIN)['unsupported'], 'binary_identity': identity}, indent=2) + '\n')
        files = {path.relative_to(payload).as_posix(): digest(path) for path in sorted(payload.rglob('*')) if path.is_file()}
        (payload / 'SHA256.json').write_text(json.dumps(files, sort_keys=True, indent=2) + '\n')
        shutil.copy2(args.library, staging / args.library.name)
        require(digest(staging / args.library.name) == receipt['library']['sha256'], 'Staged linked binary changed')
        require(application_source() == receipt['source'], 'Application source changed while staging')
        payload.rename(metadata_dir)
        (staging / args.library.name).rename(args.destination / args.library.name)
    return {'library': str(args.destination / args.library.name), 'metadata': str(metadata_dir),
            'sha256': receipt['library']['sha256'], 'qualification': 'development-unqualified'}


def verify_stage(args):
    directory = args.directory.absolute()
    metadata = metadata_directory(directory)
    require(not metadata.is_symlink(), 'Linked metadata directory is a symbolic link')
    expected = obj(metadata / 'SHA256.json')
    actual = {path.relative_to(metadata).as_posix() for path in metadata.rglob('*') if not path.is_dir()}
    require(actual == set(expected) | {'SHA256.json'}, 'Linked metadata inventory differs from checksum manifest')
    require(not any(path.is_symlink() for path in metadata.rglob('*')), 'Linked metadata contains symbolic links')
    for relative, sha in expected.items():
        require(digest(checked_path(metadata, relative)) == sha, 'Linked metadata hash mismatch: ' + relative)
    receipt = obj(metadata / 'build-receipt.json')
    require(receipt.get('kind') == 'encap-linked-application-build' and receipt.get('schema') == 1
            and receipt.get('core') == obj(PIN) and obj(metadata / 'core-source.json') == obj(PIN),
            'Linked packaged source identity mismatch')
    require(digest(metadata / 'linked-spec.json') == obj(PIN)['spec_sha256'], 'Packaged Core specification mismatch')
    require(digest(metadata / 'linked-ffmpeg.json') == receipt['sdk']['metadata_sha256'], 'Packaged SDK receipt changed')
    source_files = receipt.get('source', {}).get('files', {})
    require(hashlib.sha256(json.dumps(source_files, sort_keys=True).encode()).hexdigest() == receipt['source']['sha256'],
            'Packaged application source hash is inconsistent')
    target_id = receipt['sdk']['target']
    require(target_id in TARGETS and receipt['sdk']['rust_target'] == TARGETS[target_id], 'Unsupported packaged target')
    library = checked_path(directory, library_name(target_id))
    # The exact immutable Core validator accompanies the package, so extraction
    # verification needs no source cache, network access or adjacent repository.
    validator_name = 'scripts/linked/binary.py'
    with tarfile.open(metadata / 'corresponding-source/avid-core.tar') as archive:
        members = [member for member in archive.getmembers() if member.name == validator_name]
        require(len(members) == 1 and members[0].isfile(), 'Pinned source validator missing')
        original = archive.extractfile(members[0]).read()
    require(hashlib.sha256(original).hexdigest() == obj(PIN)['binary_validator_sha256']
            and digest(metadata / 'validator/binary.py') == obj(PIN)['binary_validator_sha256'],
            'Packaged validator differs from corresponding Core source')
    import types
    binary = types.ModuleType('encap_packaged_binary')
    # Hash-verified code only. Loading through SourceFileLoader would write
    # __pycache__ inside the sealed package and break its next integrity check.
    exec(compile(original, str(metadata / 'validator/binary.py'), 'exec'), binary.__dict__)
    target = next(value for value in obj(metadata / 'linked-spec.json')['targets'] if value['id'] == target_id)
    identity = binary.validate_file(library, target)
    for field in ('arch', 'format', 'dependencies', 'search_paths', 'install_name'):
        require(identity.get(field) == receipt['library']['identity'].get(field), 'Packaged native loader identity changed')
    signed_path = metadata / 'signed-library.json'
    signed = obj(signed_path) if signed_path.exists() else None
    if target_id.startswith('macos'):
        require(normalized_code(library) == receipt['library'].get('code_sha256'),
                'Signed linked library code differs from its fixed-source build')
        if args.bind_signature:
            subprocess.run(['codesign', '--verify', '--strict', str(library)], check=True)
            signed = {'schema': 1, 'sha256': digest(library), 'code_sha256': receipt['library']['code_sha256']}
            signed_path.write_text(json.dumps(signed, indent=2) + '\n')
            expected['signed-library.json'] = digest(signed_path)
            (metadata / 'SHA256.json').write_text(json.dumps(expected, sort_keys=True, indent=2) + '\n')
        require(digest(library) == (signed['sha256'] if signed else receipt['library']['sha256']),
                'Signed linked library raw hash differs; bind only after code-identity verification')
        if signed:
            require(signed.get('schema') == 1 and signed.get('code_sha256') == receipt['library']['code_sha256'],
                    'Linked signature binding identity mismatch')
    else:
        require(not args.bind_signature, 'Signature binding is only supported for macOS Mach-O')
        require(digest(library) == receipt['library']['sha256'], 'Packaged linked library hash changed')
    qualification = obj(metadata / 'qualification.json')
    if args.require_qualified:
        require(qualification.get('status') == 'qualified'
                and qualification.get('native_final_package') == 'passed'
                and qualification.get('corresponding_cargo_dependency_sources') == 'verified'
                and not qualification.get('limitations'),
                'Linked migration is unqualified: Audio/playback prerequisites, corresponding sources and native final-package evidence remain required')
    return {'status': 'verified', 'target': target_id, 'sha256': digest(library),
            'qualification': qualification.get('status'), 'signed_hash_bound': signed is not None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    bundle = commands.add_parser('bundle-sources')
    bundle.add_argument('--output', type=Path, required=True)
    bundle.add_argument('--fetch', action='store_true')
    verify = commands.add_parser('verify-stage')
    verify.add_argument('--directory', type=Path, required=True)
    verify.add_argument('--bind-signature', action='store_true')
    verify.add_argument('--require-qualified', action='store_true')
    for name in ('provision', 'validate-sdk', 'build', 'stage'):
        command = commands.add_parser(name)
        command.add_argument('--target', required=True, choices=sorted(TARGETS))
        command.add_argument('--profile', required=True, choices=['apple-lgpl', 'apple-gpl', 'gpl-software'])
        command.add_argument('--cache', type=Path)
        command.add_argument('--prefix', type=Path, required=name != 'provision')
        if name == 'provision':
            command.add_argument('--fetch', action='store_true')
            command.add_argument('--work', type=Path)
            command.add_argument('--jobs', type=int, default=min(os.cpu_count() or 2, 8))
            command.add_argument('--cmake', type=Path)
            command.add_argument('--cc')
            command.add_argument('--cxx')
            command.add_argument('--cxx-runtime', choices=['c++', 'stdc++'])
        if name == 'build':
            command.add_argument('--target-dir', type=Path, required=True)
            command.add_argument('--receipt', type=Path, required=True)
        if name == 'stage':
            command.add_argument('--library', type=Path, required=True)
            command.add_argument('--receipt', type=Path, required=True)
            command.add_argument('--destination', type=Path, required=True)
            command.add_argument('--source-bundle', type=Path)
    args = parser.parse_args()
    if args.command == 'bundle-sources':
        result = bundle_sources(args)
    elif args.command == 'verify-stage':
        result = verify_stage(args)
    elif args.command == 'validate-sdk':
        result = validate_sdk(args.prefix, args.target, args.profile, source_checkout(args.cache))
    else:
        result = {'provision': provision, 'build': build, 'stage': stage}[args.command](args)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
