#!/usr/bin/env python3
"""Sign/verify feeds using the pinned upstream Sparkle tool, never custom XML crypto."""
import argparse, base64, hashlib, os, re, subprocess, tarfile, tempfile, urllib.request
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from tlo_update_release import checksums
ROOT=Path(__file__).resolve().parents[1]

def tool_archive():
    # The application and publisher share one Sparkle version/digest pin.
    source=(ROOT/'script/build_and_run.sh').read_text()
    version=re.search(r'^SPARKLE_VERSION="([^"]+)"',source,re.M)[1]
    expected=re.search(r'^SPARKLE_SHA256="([0-9a-f]{64})"',source,re.M)[1]
    archive=ROOT/'.sparkle'/f'Sparkle-{version}.tar.xz'
    if not archive.exists():
        archive.parent.mkdir(parents=True,exist_ok=True)
        with urllib.request.urlopen(f'https://github.com/sparkle-project/Sparkle/releases/download/{version}/Sparkle-{version}.tar.xz',timeout=60) as response:
            data=response.read(128*1024*1024+1)
        if len(data)>128*1024*1024 or hashlib.sha256(data).hexdigest()!=expected: raise ValueError('Sparkle tool archive checksum mismatch')
        archive.write_bytes(data)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=expected: raise ValueError('Sparkle tool archive checksum mismatch')
    return archive

def sign_feeds(assets, seed_text, public_text, verify=False):
    seed=base64.b64decode(seed_text,validate=True)
    key=Ed25519PrivateKey.from_private_bytes(seed)
    if key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)!=base64.b64decode(public_text,validate=True): raise ValueError('Configured update keys disagree')
    feeds=sorted(assets.glob('appcast-macos-*.xml'))
    if not feeds: raise ValueError('No macOS appcasts to authenticate')
    with tempfile.TemporaryDirectory(prefix='encap-sparkle-sign-') as directory:
        # Extract only the authenticated upstream executable, not an arbitrary archive tree.
        with tarfile.open(tool_archive()) as archive:
            member=archive.getmember('./bin/sign_update')
            if not member.isfile(): raise ValueError('Pinned Sparkle signer is not a regular file')
            stream=archive.extractfile(member)
            if stream is None: raise ValueError('Pinned Sparkle signer missing')
            tool=Path(directory)/'sign_update';tool.write_bytes(stream.read());tool.chmod(0o755)
        for feed in feeds:
            command=[str(tool),'--ed-key-file','-']
            if verify: command.append('--verify')
            command.append(str(feed.resolve()))
            result=subprocess.run(command,input=seed_text+'\n',text=True,capture_output=True)
            if result.returncode: raise RuntimeError('Upstream Sparkle feed verification/signing failed for '+feed.name)
    if not verify: checksums(assets)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--assets',type=Path,required=True);p.add_argument('--verify',action='store_true');a=p.parse_args()
    sign_feeds(a.assets,os.environ['ENCAP_UPDATE_PRIVATE_KEY'].strip(),os.environ['ENCAP_UPDATE_PUBLIC_KEY'].strip(),a.verify)
