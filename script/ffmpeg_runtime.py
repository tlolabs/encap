#!/usr/bin/env python3
"""ENCAP-owned source runtime provisioning, packaging and verification; no Core runtime assets."""
import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tomllib
from ffmpeg_build import ROOT, SPEC, SPEC_PATH, build, digest, recipe_digest, target_id, write_json


def pair(target):
    return [name + ('.exe' if target.startswith('windows') else '') for name in ['ffmpeg', 'ffprobe']]


def machine(path, target):
    data = path.read_bytes()[:4096]
    arm = target.endswith('arm64')
    if target.startswith('macos'):
        valid = data[:4] == b'\xcf\xfa\xed\xfe' and struct.unpack_from('<I', data, 4)[0] == (0x100000c if arm else 0x1000007)
    elif target.startswith('linux'):
        valid = data[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', data, 18)[0] == (183 if arm else 62)
    else:
        offset = struct.unpack_from('<I', data, 60)[0] if len(data) >= 64 else 0
        valid = data[:2] == b'MZ' and data[offset:offset+4] == b'PE\0\0' and struct.unpack_from('<H', data, offset+4)[0] == (0xaa64 if arm else 0x8664)
    if not valid:
        raise ValueError('Wrong runtime architecture: ' + str(path))


def checked_files(metadata):
    files = json.loads((metadata / 'payload.json').read_text())
    for name in files:
        if Path(name).is_absolute() or '..' in Path(name).parts or '\\' in name:
            raise ValueError('Invalid runtime manifest path')
    return files


def verify(runtime, target, binary=None, signed=False):
    binary = binary or runtime
    if (runtime / 'dependency.json').read_bytes() != SPEC_PATH.read_bytes():
        raise ValueError('Runtime dependency pin differs from ENCAP')
    info = json.loads((runtime / 'build.json').read_text())
    if info['owner'] != 'EnCAP' or info['target'] != target or info['recipe_sha256'] != recipe_digest():
        raise ValueError('Runtime recipe/owner/target mismatch')
    files = checked_files(runtime)
    required = {'dependency.json', 'build.json', 'config.log', 'config.h', *pair(target)}
    if not required <= files.keys():
        raise ValueError('Incomplete source runtime manifest')
    for name, expected in files.items():
        if name in pair(target):
            continue
        if digest(runtime / name) != expected:
            raise ValueError('Runtime metadata/source checksum mismatch: ' + name)
    for record in [SPEC['source'], *SPEC['external_libraries'].values()]:
        if digest(runtime / 'sources' / record['url'].split('/')[-1]) != record['sha256']:
            raise ValueError('Packaged corresponding source mismatch')
    hashes = info['binary_sha256']
    if any(files[name] != hashes[name] for name in pair(target)):
        raise ValueError('Original runtime hashes disagree')
    if signed:
        signature = json.loads((runtime / 'signed-payload.json').read_text())
        if signature['target'] != target or signature['original_binary_sha256'] != hashes:
            raise ValueError('Signed runtime identity mismatch')
        hashes = signature['signed_binary_sha256']
    for name in pair(target):
        machine(binary / name, target)
        if digest(binary / name) != hashes[name]:
            raise ValueError('Runtime executable checksum mismatch: ' + name)
    return info


def provision(target):
    target = target_id(target)
    # CI can provide only an ENCAP-verified source payload. This is not an arbitrary tool override.
    selected = os.environ.get('ENCAP_FFMPEG_RUNTIME')
    if selected:
        runtime = Path(selected)
        verify(runtime, target)
        return runtime.resolve()
    return build(target)


def core_identity():
    manifest = tomllib.loads((ROOT / 'Cargo.toml').read_text())
    pin = manifest['workspace']['dependencies']['avid-core']
    packages = tomllib.loads((ROOT / 'Cargo.lock').read_text())['package']
    core, = [package for package in packages if package['name'] == 'avid-core']
    source = f"git+{pin['git']}?rev={pin['rev']}#{pin['rev']}"
    if core['source'] != source or pin['version'] != '=' + core['version']:
        raise ValueError('Core lock differs from the approved pin')
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
    binary.mkdir(parents=True, exist_ok=True)
    for item in runtime.iterdir():
        destination = binary / item.name
        if destination.exists():
            raise ValueError('Refusing to overwrite runtime payload: ' + item.name)
        if item.is_dir():
            shutil.copytree(item, destination)
        else:
            shutil.copy2(item, destination)
    version = os.environ.get('ENCAP_VERSION') or tomllib.loads((ROOT / 'Cargo.toml').read_text())['workspace']['package']['version']
    write_json(binary / 'encap-runtime.json', {'schema': 1, 'owner': 'EnCAP', 'encap_version': version,
               'avid_core': engine_identity(binary, target)['avid_core'],
               'ffmpeg_version': SPEC['source']['version'], 'target': target, 'architecture': target.split('-', 1)[1],
               'recipe_sha256': recipe_digest()})


def finish(target, binary, metadata):
    target = target_id(target)
    info = json.loads((binary / 'build.json').read_text())
    # stage() verifies original hashes before platform signing; signing may alter executable bytes.
    write_json(binary / 'signed-payload.json', {'schema': 1, 'target': target,
               'original_binary_sha256': info['binary_sha256'],
               'signed_binary_sha256': {name: digest(binary / name) for name in pair(target)}})
    if binary.resolve() != metadata.resolve():
        metadata.mkdir(parents=True, exist_ok=True)
        names = {Path(name).parts[0] for name in checked_files(binary)} - set(pair(target))
        names |= {'payload.json', 'encap-runtime.json', 'signed-payload.json'}
        for name in sorted(names):
            if (metadata / name).exists():
                raise ValueError('Metadata destination already exists: ' + name)
            shutil.move(str(binary / name), metadata / name)


def validate(target, binary, metadata, runtime=None):
    target = target_id(target)
    verify(metadata, target, binary, signed=True)
    provenance = json.loads((metadata / 'encap-runtime.json').read_text())
    if provenance['owner'] != 'EnCAP' or provenance['ffmpeg_version'] != SPEC['source']['version'] or provenance['target'] != target or provenance['architecture'] != target.split('-', 1)[1] or provenance['recipe_sha256'] != recipe_digest():
        raise ValueError('Packaged ENCAP runtime provenance mismatch')
    identity = engine_identity(binary, target)
    if provenance['avid_core'] != identity['avid_core'] or provenance['encap_version'] != identity['encap_version']:
        raise ValueError('Packaged Core/application provenance mismatch')
    if runtime:
        verify(runtime, target)
        for name in checked_files(runtime):
            if name not in pair(target) and (metadata / name).read_bytes() != (runtime / name).read_bytes():
                raise ValueError('Packaged metadata differs from source build')
    engine = binary / ('encap-engine.exe' if target.startswith('windows') else 'encap-engine')
    subprocess.run([str(engine.resolve()), 'validate-tools'], env=dict(os.environ, PATH=''), check=True, timeout=60)
    return provenance


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['provision', 'stage', 'finish', 'validate'])
    parser.add_argument('target')
    parser.add_argument('--runtime', type=Path)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--metadata', type=Path)
    args = parser.parse_args()
    if args.mode == 'provision':
        print(provision(args.target))
    elif args.binary is None:
        parser.error('--binary is required')
    elif args.mode == 'stage':
        stage(args.target, args.runtime or provision(args.target), args.binary)
    elif args.mode == 'finish':
        finish(args.target, args.binary, args.metadata or args.binary)
    else:
        print(json.dumps(validate(args.target, args.binary, args.metadata or args.binary, args.runtime)))
