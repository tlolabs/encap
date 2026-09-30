#!/usr/bin/env python3
"""Acquire and package checksum-pinned AVID Core runtimes; never compile FFmpeg."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
PIN = json.loads((ROOT / 'runtime/core-runtime.json').read_text())


def digest(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def target_id(target):
    target = target.replace('aarch64', 'arm64')
    if target not in PIN['targets']:
        raise ValueError('Unsupported Core target: ' + target)
    return target


def pair(target):
    return [name + ('.exe' if target.startswith('windows') else '') for name in ['ffmpeg', 'ffprobe']]


def machine(path, target):
    with path.open('rb') as file:
        data = file.read(4096)
    arm = target.endswith('arm64')
    if target.startswith('macos'):
        valid = len(data) >= 8 and data[:4] == b'\xcf\xfa\xed\xfe' and struct.unpack_from('<I', data, 4)[0] == (0x100000c if arm else 0x1000007)
    elif target.startswith('linux'):
        valid = len(data) >= 20 and data[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', data, 18)[0] == (183 if arm else 62)
    else:
        offset = struct.unpack_from('<I', data, 60)[0] if len(data) >= 64 else 0
        valid = offset >= 64 and offset + 6 <= len(data) and data[:2] == b'MZ' and data[offset:offset+4] == b'PE\0\0' and struct.unpack_from('<H', data, offset+4)[0] == (0xaa64 if arm else 0x8664)
    if not valid:
        raise ValueError('Wrong runtime architecture: ' + str(path))


def checked_files(metadata, target):
    path = metadata / 'SHA256SUMS'
    if digest(path) != PIN['targets'][target]['checksums_sha256']:
        raise ValueError('Core checksum manifest differs from pinned artifact')
    files = {}
    for line in path.read_text().splitlines():
        expected, name = line.split('  ', 1)
        if name in files or Path(name).is_absolute() or any(p in ('', '.', '..') for p in name.split('/')) or '\\' in name or len(expected) != 64:
            raise ValueError('Invalid Core checksum path')
        files[name] = expected
    return files


def verify(runtime, target, binary=None, signed=False):
    target = target_id(target)
    binary = binary or runtime
    files = checked_files(runtime, target)
    required = {'spec.json', 'build.json', 'validation.json', 'repeat-build.json', 'source-provenance.json', 'core-tests-passed.txt', 'SOURCE.json', *pair(target)}
    if not required <= files.keys():
        raise ValueError('Incomplete Core runtime')
    for path in runtime.rglob('*'):
        if path.is_symlink():
            raise ValueError('Core runtime contains a symlink')
    for name, expected in files.items():
        if name in pair(target):
            continue
        if digest(runtime / name) != expected:
            raise ValueError('Core metadata checksum mismatch: ' + name)
    info = json.loads((runtime / 'build.json').read_text())
    if info['target'] != target or info['core_revision'] != PIN['revision'] or info['core_worktree_modified']:
        raise ValueError('Core build identity mismatch')
    hashes = {name: files[name] for name in pair(target)}
    if signed:
        signature = json.loads((runtime / 'signed-payload.json').read_text())
        if signature['schema'] != 1 or signature['target'] != target or signature['original_binary_sha256'] != hashes:
            raise ValueError('Signed runtime identity mismatch')
        hashes = signature['signed_binary_sha256']
    for name in pair(target):
        machine(binary / name, target)
        if (binary / name).is_symlink() or digest(binary / name) != hashes[name]:
            raise ValueError('Core executable checksum mismatch: ' + name)
    source = (runtime / 'corresponding-source.tar.gz') if signed else runtime.parent / PIN['targets'][target]['source_archive']
    if digest(source) != PIN['targets'][target]['source_sha256']:
        raise ValueError('Core corresponding source mismatch')
    return info


def provision(target):
    target = target_id(target)
    selected = os.environ.get('ENCAP_FFMPEG_RUNTIME')
    if selected:
        runtime = Path(selected).resolve()
        verify(runtime, target)
        return runtime
    record = PIN['targets'][target]
    artifact_root = ROOT / 'build/core-artifacts' / str(PIN['run_id'])
    artifact = artifact_root / record['artifact']
    archive = artifact / 'packages' / record['archive']
    runtime = ROOT / 'build/core-runtime' / target / record['archive'].removesuffix('.tar.gz')
    if runtime.exists():
        verify(runtime, target)
        return runtime
    if not archive.is_file():
        subprocess.run(['gh', 'run', 'download', str(PIN['run_id']), '--repo', PIN['repository'], '--name', record['artifact'], '--dir', str(artifact)], check=True)
    if digest(archive) != record['sha256']:
        raise ValueError('Core archive checksum mismatch')
    source = artifact / record['source_archive']
    if digest(source) != record['source_sha256']:
        raise ValueError('Core source archive checksum mismatch')
    runtime.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as contents:
        for member in contents.getmembers():
            if not (member.isfile() or member.isdir()) or member.name.split('/')[0] != runtime.name:
                raise ValueError('Unexpected Core archive entry')
        contents.extractall(runtime.parent, filter='data')
    shutil.copy2(source, runtime.parent / source.name)
    verify(runtime, target)
    return runtime


def core_identity():
    pin = tomllib.loads((ROOT / 'Cargo.toml').read_text())['workspace']['dependencies']['avid-core']
    packages = tomllib.loads((ROOT / 'Cargo.lock').read_text())['package']
    core, = [package for package in packages if package['name'] == 'avid-core']
    source = f"git+{pin['git']}?rev={pin['rev']}#{pin['rev']}"
    if core['source'] != source or pin['version'] != '=' + core['version'] or pin['rev'] != PIN['revision']:
        raise ValueError('Core lock differs from the runtime pin')
    return dict(version=core['version'], revision=pin['rev'], source=source)


def engine_identity(binary, target):
    engine = binary / ('encap-engine.exe' if target.startswith('windows') else 'encap-engine')
    identity = json.loads(subprocess.check_output([str(engine.resolve()), 'build-info'], timeout=30))
    if identity['avid_core'] != core_identity():
        raise ValueError('Packaged engine differs from pinned AVID Core')
    return identity


def stage(target, runtime, binary):
    target = target_id(target)
    verify(runtime, target)
    engine = binary / ('encap-engine.exe' if target.startswith('windows') else 'encap-engine')
    subprocess.run([str(engine.resolve()), 'validate-core-runtime', str(runtime.resolve())], check=True, timeout=60)
    binary.mkdir(parents=True, exist_ok=True)
    for item in runtime.iterdir():
        destination = binary / item.name
        if destination.exists():
            raise ValueError('Refusing to overwrite runtime payload: ' + item.name)
        if item.is_dir():
            shutil.copytree(item, destination)
        else:
            shutil.copy2(item, destination)
    shutil.copy2(runtime.parent / PIN['targets'][target]['source_archive'], binary / 'corresponding-source.tar.gz')
    identity = engine_identity(binary, target)
    write_json(binary / 'encap-runtime.json', {'schema': 1, 'owner': 'AVID Core', **identity, 'target': target})


def finish(target, binary, metadata):
    target = target_id(target)
    original = binary if (binary / 'SHA256SUMS').exists() else metadata
    files = checked_files(original, target)
    write_json(original / 'signed-payload.json', {'schema': 1, 'target': target,
               'original_binary_sha256': {name: files[name] for name in pair(target)},
               'signed_binary_sha256': {name: digest(binary / name) for name in pair(target)}})
    if original.resolve() != metadata.resolve():
        metadata.mkdir(parents=True, exist_ok=True)
        names = {Path(name).parts[0] for name in files} - set(pair(target))
        names |= {'SHA256SUMS', 'encap-runtime.json', 'signed-payload.json', 'corresponding-source.tar.gz'}
        for name in sorted(names):
            if (metadata / name).exists():
                raise ValueError('Metadata destination already exists: ' + name)
            shutil.move(str(original / name), metadata / name)


def validate(target, binary, metadata, runtime=None):
    target = target_id(target)
    verify(metadata, target, binary, signed=True)
    provenance = json.loads((metadata / 'encap-runtime.json').read_text())
    identity = engine_identity(binary, target)
    if provenance != {'schema': 1, 'owner': 'AVID Core', **identity, 'target': target}:
        raise ValueError('Packaged Core/application provenance mismatch')
    if runtime:
        verify(runtime, target)
    engine = binary / ('encap-engine.exe' if target.startswith('windows') else 'encap-engine')
    subprocess.run([str(engine.resolve()), 'validate-tools'], env=dict(os.environ, PATH=''), check=True, timeout=60)
    return provenance


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['provision', 'key', 'stage', 'finish', 'validate'])
    parser.add_argument('target')
    parser.add_argument('--runtime', type=Path)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--metadata', type=Path)
    args = parser.parse_args()
    if args.mode == 'provision':
        print(provision(args.target))
    elif args.mode == 'key':
        print(PIN['targets'][target_id(args.target)]['sha256'])
    elif args.binary is None:
        parser.error('--binary is required')
    elif args.mode == 'stage':
        stage(args.target, args.runtime or provision(args.target), args.binary)
    elif args.mode == 'finish':
        finish(args.target, args.binary, args.metadata or args.binary)
    else:
        print(json.dumps(validate(args.target, args.binary, args.metadata or args.binary, args.runtime)))
