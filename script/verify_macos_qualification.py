#!/usr/bin/env python3
"""Authenticate locally notarized bytes, preserving exact native-build identity."""
import argparse
import json
import hashlib
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import tomllib
import zipfile
from core_runtime import digest, gh_json, obj, require

ROOT = Path(__file__).resolve().parents[1]
TEAM = 'VR64M92P2M'


def preflight_zip(path):
    with zipfile.ZipFile(path) as archive:
        names = set()
        links = set()
        total = 0
        for item in archive.infolist():
            parts = PurePosixPath(item.filename.rstrip('/')).parts
            require(parts and not item.filename.startswith('/') and '\\' not in item.filename and
                    all(p not in ('.', '..') for p in parts) and item.filename not in names,
                    'Unsafe or duplicate Mac ZIP entry')
            names.add(item.filename)
            total += item.file_size
            require(total <= 2 * 1024**3, 'Mac ZIP is too large')
            if stat.S_ISLNK(item.external_attr >> 16):
                require(item.file_size <= 4096, 'Oversized ZIP link')
                target = archive.read(item).decode()
                require(not target.startswith('/') and '\\' not in target, 'Unsafe Mac ZIP link')
                stack = list(parts[:-1])
                for part in PurePosixPath(target).parts:
                    if part == '..':
                        require(stack, 'Mac ZIP link escapes extraction root')
                        stack.pop()
                    elif part != '.':
                        stack.append(part)
                links.add('/'.join(parts))
        for name in names:
            parts = PurePosixPath(name.rstrip('/')).parts
            require(not any('/'.join(parts[:i]) in links for i in range(1, len(parts))),
                    'ZIP writes through a symbolic link')


def extract(path, output):
    preflight_zip(path)
    output.mkdir()
    subprocess.run(['ditto', '-x', '-k', str(path), str(output)], check=True)
    for entry in output.rglob('*'):
        if entry.is_symlink():
            require(entry.resolve().is_relative_to(output.resolve()), 'Extracted Mac link escapes root')


def code_hash(path, temporary):
    copy = temporary / 'unsigned-code'
    shutil.copy2(path, copy)
    subprocess.run(['codesign', '--remove-signature', str(copy)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    data = bytearray(copy.read_bytes())
    # codesign removal retains the LINKEDIT virtual reservation of its old
    # signature. Compare all remaining bytes, normalizing only that reservation.
    bases = [0]
    if data[:4] == b'\xca\xfe\xba\xbe':
        count, = struct.unpack_from('>I', data, 4)
        require(0 < count <= 32, 'Invalid fat Mach-O architecture count')
        bases = [struct.unpack_from('>I', data, 8+i*20+8)[0] for i in range(count)]
    for base in bases:
        require(data[base:base+4] == b'\xcf\xfa\xed\xfe', 'Expected 64-bit Mach-O code')
        count, command_bytes = struct.unpack_from('<II', data, base+16)
        offset = base+32
        require(count <= 10000 and offset+command_bytes <= len(data), 'Invalid Mach-O load commands')
        for _ in range(count):
            command, size = struct.unpack_from('<II', data, offset)
            require(size >= 8 and offset+size <= base+32+command_bytes, 'Invalid Mach-O command length')
            if command == 0x19 and data[offset+8:offset+24].rstrip(b'\0') == b'__LINKEDIT':
                require(size >= 72, 'Invalid LINKEDIT command')
                struct.pack_into('<Q', data, offset+32, 0)
            offset += size
        require(offset == base+32+command_bytes, 'Invalid Mach-O command collection')
    result = hashlib.sha256(data).hexdigest()
    copy.unlink()
    return result


def magic(path):
    with path.open('rb') as stream:
        return stream.read(4)


def compare_signed_build(original, final):
    def entries(app):
        return {str(p.relative_to(app)):p for p in app.rglob('*')
                if (p.is_symlink() or not p.is_dir()) and '_CodeSignature' not in p.parts}
    before, after = entries(original), entries(final)
    require(before.keys() == after.keys(), 'Signing added or removed application payload files')
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        for name, old in before.items():
            new = after[name]
            if old.is_symlink() or new.is_symlink():
                require(old.is_symlink() and new.is_symlink() and os.readlink(old) == os.readlink(new),
                        'Signing changed application links')
            elif magic(old) in (b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'):
                require(code_hash(old, temporary) == code_hash(new, temporary), 'Signed executable code changed: '+name)
                subprocess.run(['codesign', '--verify', '--strict', '-R', '=anchor apple generic and certificate leaf[subject.OU] = "'+TEAM+'"', str(new)], check=True)
            elif old.name == 'signed-payload.json':
                a, b = obj(old), obj(new)
                for key in ('schema', 'target', 'original_binary_sha256', 'original_runtime_archive_sha256'):
                    require(a[key] == b[key], 'Original Core identity changed during signing')
            else:
                require(digest(old) == digest(new), 'Signing changed application resource: '+name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application', choices=['ativ', 'encap'], required=True)
    parser.add_argument('--target', choices=['macos-arm64', 'macos-x86_64'], required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--original-zip', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    repo, revision = os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_SHA']
    require(repo == 'tlolabs/'+args.application and os.environ['GITHUB_EVENT_NAME'] == 'workflow_dispatch', 'Maintainer dispatch required')
    version = tomllib.loads((ROOT/'Cargo.toml').read_text())['workspace']['package']['version']
    require(args.tag == 'qualification-'+version+'-'+revision[:12] and re.fullmatch('[0-9a-f]{64}', args.sha256), 'Exact draft qualification identity required')
    release = gh_json(f'repos/{repo}/releases/tags/{args.tag}')
    require(release['draft'] is True and release['target_commitish'] == revision, 'Qualification draft has wrong build revision')
    prefix, appname = ('ATIV', 'ATIV.app') if args.application == 'ativ' else ('EnCap', 'EnCap.app')
    label = 'arm64' if args.target.endswith('arm64') else 'intel'
    filename = f'{prefix}-{version}-macos-{label}.zip'
    assets = [a for a in release['assets'] if a['name'] == filename]
    require(len(assets) == 1 and assets[0].get('digest') == 'sha256:'+args.sha256, 'Signed input asset digest mismatch')
    require(not args.output.exists(), 'Fresh final-package output required')
    args.output.mkdir(parents=True)
    archive = args.output/filename
    with archive.open('wb') as stream:
        subprocess.run(['gh', 'api', '-H', 'Accept: application/octet-stream', f'repos/{repo}/releases/assets/{assets[0]["id"]}'], stdout=stream, check=True)
    require(digest(archive) == args.sha256, 'Signed input bytes changed')
    extract(args.original_zip.resolve(), args.output/'original')
    extract(archive.resolve(), args.output/'extracted')
    original, app = args.output/'original'/appname, args.output/'extracted'/appname
    compare_signed_build(original, app)
    info = plistlib.loads((app/'Contents/Info.plist').read_bytes())
    require(info['CFBundleShortVersionString'] == version, 'Signed app version mismatch')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', '-R', '=anchor apple generic and certificate leaf[subject.OU] = "'+TEAM+'"', str(app)], check=True)
    subprocess.run(['xcrun', 'stapler', 'validate', str(app)], check=True)
    subprocess.run(['spctl', '--assess', '--type', 'execute', '--verbose=2', str(app)], check=True)
    print(json.dumps({'application_revision':revision,'target':args.target,'package_sha256':args.sha256,'status':'passed',
                      'scope':'Developer ID, notarization, stapled final archive and unchanged qualified executable code',
                      'team_id':TEAM,'qualification_draft_id':release['id'],'qualification_asset_id':assets[0]['id']}))

if __name__ == '__main__':main()
