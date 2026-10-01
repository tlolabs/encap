#!/usr/bin/env python3
# SPDX-FileCopyrightText: Thomas Lothian
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared fail-closed Core acquisition. Candidate access is qualification-only.

Requires Python 3.11+ and authenticated GitHub CLI. Never executes downloaded code.
Hosts vendor this exact file and pin its SHA-256 from an immutable Core commit.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import tarfile
import tempfile
import zipfile

REPOSITORY = 'tlolabs/avid-core'
TARGETS = {'macos-arm64', 'macos-x86_64', 'windows-arm64', 'windows-x86_64', 'linux-arm64', 'linux-x86_64'}


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def obj(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique)


def gh_json(path):
    return json.loads(subprocess.check_output(['gh', 'api', path]))


def safe_name(name):
    require(isinstance(name, str) and name and not name.startswith('/') and '\\' not in name and ':' not in name
            and all(part not in ('', '.', '..') for part in name.split('/')), 'Unsafe archive/manifest path')
    return PurePosixPath(name)


def pair(target):
    require(target in TARGETS, 'Unsupported target')
    return [name + ('.exe' if target.startswith('windows') else '') for name in ('ffmpeg', 'ffprobe')]


def machine(path, target):
    with Path(path).open('rb') as stream:
        data = stream.read(4096)
    arm = target.endswith('arm64')
    if target.startswith('macos'):
        valid = len(data) >= 8 and data[:4] == b'\xcf\xfa\xed\xfe' and struct.unpack_from('<I', data, 4)[0] == (0x100000c if arm else 0x1000007)
    elif target.startswith('linux'):
        valid = len(data) >= 20 and data[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', data, 18)[0] == (183 if arm else 62)
    else:
        offset = struct.unpack_from('<I', data, 60)[0] if len(data) >= 64 else 0
        valid = len(data) >= 64 and data[:2] == b'MZ' and offset >= 64 and offset + 6 <= len(data) and data[offset:offset+4] == b'PE\0\0' and struct.unpack_from('<H', data, offset+4)[0] == (0xaa64 if arm else 0x8664)
    require(valid, 'Wrong executable architecture')


def extract_zip(archive, destination):
    with zipfile.ZipFile(archive) as source:
        seen = set()
        require(sum(i.file_size for i in source.infolist()) < 1024**3, 'Oversized artifact')
        for item in source.infolist():
            name = item.filename.rstrip('/')
            safe_name(name)
            require(name not in seen and not stat.S_ISLNK(item.external_attr >> 16), 'Duplicate or linked archive entry')
            seen.add(name)
            path = destination / name
            if item.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with source.open(item) as src, path.open('xb') as dst:
                    shutil.copyfileobj(src, dst)


def extract_runtime(archive, destination, root_name):
    with tarfile.open(archive) as source:
        members = source.getmembers()
        require(sum(m.size for m in members) < 1024**3, 'Oversized runtime')
        seen = set()
        for member in members:
            path = safe_name(member.name)
            require(path.parts[0] == root_name and member.name not in seen and
                    (member.isfile() or member.isdir()), 'Unexpected root, duplicate or nonregular runtime entry')
            seen.add(member.name)
        for member in members:
            path = destination / member.name
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as src, path.open('xb') as dst:
                    shutil.copyfileobj(src, dst)
                path.chmod(0o755 if member.mode & 0o111 else 0o644)


def check_origin(plan, run, artifacts, jobs):
    require(plan['repository'] == REPOSITORY and set(plan['targets']) == TARGETS, 'Repository or complete matrix mismatch')
    require(run['id'] == plan['build_run'] and run['run_attempt'] == plan['build_attempt'] and
            run['head_sha'] == plan['build_revision'] and run['head_branch'] == plan['build_branch'] and
            run['event'] == 'workflow_dispatch' and run['path'] == plan['build_workflow'] and
            run['repository']['full_name'] == REPOSITORY and run['head_repository']['full_name'] == REPOSITORY and
            run['status'] == 'completed' and run['conclusion'] == 'success', 'Untrusted or unsuccessful build origin')
    require(re.fullmatch('[0-9a-f]{40}', plan['build_revision']) is not None, 'Full source revision required')
    for target, record in plan['targets'].items():
        selected = [a for a in artifacts if a['id'] == record['artifact_id']]
        require(len(selected) == 1, 'Missing artifact identity')
        artifact = selected[0]
        require(not artifact['expired'] and artifact['name'] == record['artifact'] and
                artifact['digest'] == 'sha256:' + record['artifact_zip_sha256'] and
                artifact['workflow_run']['id'] == plan['build_run'] and
                artifact['workflow_run']['head_sha'] == plan['build_revision'], 'Artifact origin/digest mismatch')
        matching = [j for j in jobs if j['id'] == record['native_job_id']]
        require(len(matching) == 1, 'Missing native job')
        job = matching[0]
        required = {'Build and validate native Windows runtime' if target.startswith('windows') else 'Build and validate native Unix runtime',
                    'Upload validated Core runtime candidate and corresponding source'}
        require(job['name'] == 'build (' + target + ')' and job['conclusion'] == 'success' and
                job['labels'] == record['runner_labels'] and
                required <= {s['name'] for s in job['steps'] if s['conclusion'] == 'success'}, 'Required native steps did not pass')


def candidate(plan, target, destination, qualification=False):
    require(qualification, 'CI candidates may only be acquired for explicit unpublished qualification')
    repo = plan['repository']
    require(repo == REPOSITORY, 'Unexpected source repository')
    run = gh_json(f'repos/{repo}/actions/runs/{plan["build_run"]}')
    artifacts = gh_json(f'repos/{repo}/actions/runs/{plan["build_run"]}/artifacts?per_page=100')['artifacts']
    jobs = gh_json(f'repos/{repo}/actions/runs/{plan["build_run"]}/jobs?per_page=100')['jobs']
    check_origin(plan, run, artifacts, jobs)
    record = plan['targets'][target]
    destination = Path(destination)
    require(not destination.exists(), 'Fresh acquisition destination required')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        tmp = Path(tmp)
        archive_zip = tmp / 'artifact.zip'
        with archive_zip.open('wb') as stream:
            subprocess.run(['gh', 'api', f'repos/{repo}/actions/artifacts/{record["artifact_id"]}/zip'], stdout=stream, check=True)
        require(digest(archive_zip) == record['artifact_zip_sha256'], 'Authenticated artifact digest mismatch')
        payload = tmp / 'payload'
        extract_zip(archive_zip, payload)
        archive = payload / 'packages' / record['archive']
        source = payload / record['source_archive']
        require(digest(archive) == record['sha256'] and digest(source) == record['source_sha256'], 'Pinned candidate archive/source mismatch')
        destination.mkdir()
        shutil.copy2(archive, destination / record['archive'])
        shutil.copy2(source, destination / record['source_archive'])
        (destination / 'origin.json').write_text(json.dumps({'run': run, 'artifact': next(a for a in artifacts if a['id'] == record['artifact_id']),
                                                          'job': next(j for j in jobs if j['id'] == record['native_job_id'])}, indent=2) + '\n')
    return install(plan, target, destination)


def checked_files(runtime, record):
    require(digest(runtime / 'SHA256SUMS') == record['checksums_sha256'], 'Checksum manifest identity mismatch')
    files = {}
    for line in (runtime / 'SHA256SUMS').read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
        require(match is not None, 'Invalid checksum entry')
        safe_name(match[2])
        require(match[2] not in files, 'Duplicate checksum entry')
        files[match[2]] = match[1]
    return files


def verify_directory(plan, target, runtime, binary=None, signed=None):
    runtime = Path(runtime)
    record = plan['targets'][target]
    files = checked_files(runtime, record)
    required = {'build.json', 'spec.json', 'source-provenance.json', 'validation.json', 'repeat-build.json', 'SOURCE.json', 'core-tests-passed.txt', *pair(target)}
    require(required <= files.keys(), 'Incomplete Core runtime')
    require(not any(p.is_symlink() for p in runtime.rglob('*')), 'Runtime links prohibited')
    for name, expected in files.items():
        if name not in pair(target):
            require(digest(runtime / name) == expected, 'Altered Core metadata: ' + name)
    build, spec, validation, repeat = (obj(runtime / name) for name in ('build.json', 'spec.json', 'validation.json', 'repeat-build.json'))
    require(build['target'] == target and build['core_revision'] == plan['build_revision'] and build['core_worktree_modified'] is False
            and build['source_revision'] == spec['source']['revision'] and build['version'] == spec['source']['version']
            and build['recipe'] == spec['recipe'] and build['spec_sha256'] == digest(runtime / 'spec.json'), 'Core source/build mismatch')
    require(validation['target'] == target and validation['binary_sha256'] == {n: files[n] for n in pair(target)} and
            repeat['status'] == 'passed' and repeat['target'] == target and repeat['core_revision'] == plan['build_revision'] and
            repeat['binary_sha256'] == {n: {'first': files[n], 'second': files[n]} for n in pair(target)}, 'Native/repeat evidence mismatch')
    if 'binary_sha256' in record:
        require(record['binary_sha256'] == validation['binary_sha256'], 'Release executable identity mismatch')
    binary = Path(binary) if binary else runtime
    hashes = {n: files[n] for n in pair(target)}
    if signed is not None:
        require(signed['target'] == target and signed['original_binary_sha256'] == hashes and
                set(signed['signed_binary_sha256']) == set(pair(target)), 'Invalid signed derivative mapping')
        hashes = signed['signed_binary_sha256']
    for name in pair(target):
        require(not (binary / name).is_symlink() and digest(binary / name) == hashes[name], 'Executable hash mismatch: ' + name)
        machine(binary / name, target)
    return build


def install(plan, target, destination):
    record = plan['targets'][target]
    destination = Path(destination)
    archive, source = destination / record['archive'], destination / record['source_archive']
    require(digest(archive) == record['sha256'] and digest(source) == record['source_sha256'], 'Archive integrity mismatch')
    runtime = destination / record['archive'].removesuffix('.tar.gz')
    require(not runtime.exists(), 'Fresh runtime installation required')
    extract_runtime(archive, destination, runtime.name)
    verify_directory(plan, target, runtime)
    require(obj(runtime / 'SOURCE.json')['sha256'] == digest(source), 'Source manifest mismatch')
    return runtime


def authenticate_manifest(pin, manifest_path):
    require(digest(manifest_path) == pin['manifest_sha256'], 'Manifest does not match pinned authenticated identity')
    subprocess.run(['gh', 'attestation', 'verify', str(manifest_path), '--repo', REPOSITORY,
                    '--signer-workflow', REPOSITORY + '/.github/workflows/runtime-release.yml',
                    '--source-digest', pin['release_revision'], '--source-ref', 'refs/tags/' + pin['release_tag'],
                    '--deny-self-hosted-runners'], check=True, stdout=subprocess.DEVNULL)
    manifest = obj(manifest_path)
    require(manifest['repository'] == REPOSITORY and manifest['release_tag'] == pin['release_tag'] and
            manifest['build_revision'] == pin['build_revision'] and manifest['build_run'] == pin['build_run'] and
            manifest['promotion_revision'] == pin['release_revision'] and set(manifest['targets']) == TARGETS,
            'Release manifest source/matrix mismatch')
    for target in TARGETS:
        for field in ('archive', 'sha256', 'source_archive', 'source_sha256', 'checksums_sha256'):
            require(manifest['targets'][target][field] == pin['targets'][target][field], 'Release differs from qualified runtime: '+target)
    return manifest


def verify_receipt(pin, target, runtime, qualification=False):
    runtime = Path(runtime)
    record = pin['targets'][target]
    root = runtime.parent
    require(digest(root / record['archive']) == record['sha256'] and
            digest(root / record['source_archive']) == record['source_sha256'], 'Cached original assets differ from pin')
    if qualification:
        origin = obj(root / 'origin.json')
        run = gh_json(f'repos/{REPOSITORY}/actions/runs/{pin["build_run"]}')
        artifacts = gh_json(f'repos/{REPOSITORY}/actions/runs/{pin["build_run"]}/artifacts?per_page=100')['artifacts']
        jobs = gh_json(f'repos/{REPOSITORY}/actions/runs/{pin["build_run"]}/jobs?per_page=100')['jobs']
        check_origin(pin, run, artifacts, jobs)
        require(origin['run']['id'] == run['id'] and origin['run']['head_sha'] == run['head_sha'] and
                origin['artifact']['id'] == record['artifact_id'] and
                origin['artifact']['digest'] == 'sha256:'+record['artifact_zip_sha256'] and
                origin['job']['id'] == record['native_job_id'], 'Cached candidate origin differs from pin')
    else:
        receipt = obj(root / 'release-verification.json')
        require(receipt['repository'] == REPOSITORY and receipt['target'] == target and
                receipt['release_tag'] == pin['release_tag'] and receipt['release_revision'] == pin['release_revision'] and
                receipt['manifest_sha256'] == pin['manifest_sha256'] and receipt['archive_sha256'] == record['sha256'],
                'Cached release receipt differs from trusted pin')
        authenticate_manifest(pin, root / 'manifest.json')
    verify_directory(pin, target, runtime)
    return runtime


def release(pin, target, destination):
    require(pin['repository'] == REPOSITORY and re.fullmatch(r'ffmpeg-[0-9]+\.[0-9]+\.[0-9]+-r[0-9]+\.[0-9]+', pin['release_tag']) is not None,
            'Exact versioned Core release pin required')
    require(re.fullmatch('[0-9a-f]{40}', pin['release_revision']) is not None and
            re.fullmatch('[0-9a-f]{64}', pin['manifest_sha256']) is not None, 'Authenticated release identity not configured')
    destination = Path(destination)
    require(not destination.exists(), 'Fresh acquisition destination required')
    status = gh_json(f'repos/{REPOSITORY}/releases/tags/{pin["release_tag"]}')
    require(not status['draft'] and not status['prerelease'], 'Production cannot use an unpublished/prerelease runtime')
    destination.mkdir(parents=True)
    subprocess.run(['gh', 'release', 'download', pin['release_tag'], '--repo', REPOSITORY, '--pattern', 'manifest.json', '--dir', str(destination)], check=True)
    manifest_path = destination / 'manifest.json'
    manifest = authenticate_manifest(pin, manifest_path)
    record = manifest['targets'][target]
    for name in (record['archive'], record['source_archive']):
        require(safe_name(name).name == name, 'Release asset must be a basename')
        subprocess.run(['gh', 'release', 'download', pin['release_tag'], '--repo', REPOSITORY, '--pattern', name, '--dir', str(destination)], check=True)
    runtime = install(manifest, target, destination)
    (destination / 'release-verification.json').write_text(json.dumps({'repository': REPOSITORY, 'release_tag': pin['release_tag'],
        'release_revision': pin['release_revision'], 'manifest_sha256': digest(manifest_path), 'target': target,
        'archive_sha256': digest(destination / record['archive']), 'signer_workflow': '.github/workflows/runtime-release.yml'}, indent=2) + '\n')
    return runtime


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['release', 'candidate'])
    parser.add_argument('--pin', required=True, type=Path)
    parser.add_argument('--target', required=True, choices=sorted(TARGETS))
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--qualification', action='store_true')
    args = parser.parse_args()
    pin = obj(args.pin)
    if args.mode == 'release':
        require(not args.qualification, 'Qualification flag cannot change release trust')
        runtime = release(pin, args.target, args.destination)
    else:
        runtime = candidate(pin, args.target, args.destination, args.qualification)
    print(runtime.resolve())
