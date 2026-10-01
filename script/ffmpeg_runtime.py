#!/usr/bin/env python3
"""Acquire and package checksum-pinned AVID Core runtimes; never compile FFmpeg."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
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


def checked_files(metadata, target):
    from core_runtime import checked_files as core_checked_files
    return core_checked_files(metadata, PIN['targets'][target])


def verify(runtime, target, binary=None, signed=False):
    from core_runtime import verify_directory
    target = target_id(target)
    derivative = json.loads((runtime / 'signed-payload.json').read_text()) if signed else None
    info = verify_directory(PIN, target, runtime, binary=binary, signed=derivative)
    source = runtime / 'corresponding-source.tar.gz' if signed else runtime.parent / PIN['targets'][target]['source_archive']
    if digest(source) != PIN['targets'][target]['source_sha256']:
        raise ValueError('Core corresponding source mismatch')
    return info


def provision(target):
    from core_runtime import release, require, verify_receipt
    target = target_id(target)
    verifier = json.loads((ROOT / 'runtime/core-acquirer.json').read_text())
    require(digest(ROOT / 'script/core_runtime.py') == verifier['sha256'],
            'Shared Core verifier differs from its pin')
    require(PIN.get('acquisition') == 'release' and not PIN.get('qualification_only'),
            'EnCAP requires a published AVID Core runtime')
    selected = os.environ.get('ENCAP_FFMPEG_RUNTIME')
    if selected:
        runtime = Path(selected).resolve()
        return verify_receipt(PIN, target, runtime)
    destination = ROOT / 'build/core-acquisition' / PIN['release_tag'] / target
    if destination.exists():
        runtime = destination / PIN['targets'][target]['archive'].removesuffix('.tar.gz')
        return verify_receipt(PIN, target, runtime)
    return release(PIN, target, destination)


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
               'signed_binary_sha256': {name: digest(binary / name) for name in pair(target)},
               'transformation': 'platform code signing or identity-preserving staging',
               'signing_identity': os.environ.get('APPLE_SIGN_IDENTITY') or os.environ.get('ENCAP_SIGN_IDENTITY') or os.environ.get('AZURE_SIGNING_ACCOUNT') or 'unconfigured',
               'original_runtime_archive_sha256': PIN['targets'][target]['sha256']})
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
