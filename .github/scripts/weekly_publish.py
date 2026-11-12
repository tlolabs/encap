#!/usr/bin/env python3
"""Append verified weekly downloads to an existing release; never alter feeds/tags."""
import argparse, hashlib, json, re, subprocess
from pathlib import Path
from urllib.parse import quote

def api(path):
    return json.loads(subprocess.check_output(['gh','api',path],text=True))

def publish(repo,tag,sha,target,folder):
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+',tag) or not re.fullmatch('[a-f0-9]{40}',sha): raise ValueError('Invalid tag/SHA')
    if target not in ('linux-x64','linux-arm64','windows-x64','windows-arm64'): raise ValueError('Invalid target')
    base=f'repos/{repo}'; ref=api(base+'/git/ref/tags/'+quote(tag,safe=''))['object']
    for _ in range(16):
        if ref['type']=='commit': break
        if ref['type']!='tag': raise ValueError('Invalid tag object')
        ref=api(base+'/git/tags/'+ref['sha'])['object']
    if ref['type']!='commit' or ref['sha']!=sha: raise ValueError('Remote tag moved')
    release=api(base+'/releases/tags/'+tag)
    if release['draft'] or release['tag_name']!=tag: raise ValueError('Existing published release required')
    proof=json.loads((folder/'verification.json').read_text())
    name=f'EnCap-{tag[1:]}-{target}'+('.zip' if target.startswith('windows') else '.AppImage')
    package=folder/name
    if package.is_symlink() or not package.is_file(): raise ValueError('Missing regular package')
    digest=hashlib.sha256(package.read_bytes()).hexdigest()
    if any(proof.get(k)!=v for k,v in dict(tag=tag,sha=sha,target=target,package=name,sha256=digest,status='passed').items()): raise ValueError('Package evidence mismatch')
    checksum=folder/(name+'.sha256')
    if checksum.read_text()!=digest+'  '+name+'\n': raise ValueError('Checksum mismatch')
    evidence=folder/(name+'.verification.json'); evidence.write_bytes((folder/'verification.json').read_bytes())
    assets={a['name']:a for a in release['assets']}
    for path in (package,checksum,evidence):
        expected='sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
        if path.name in assets:
            if assets[path.name].get('digest')!=expected or assets[path.name]['size']!=path.stat().st_size: raise ValueError('Existing asset differs; never overwrite')
            continue
        subprocess.run(['gh','release','upload',tag,str(path),'--repo',repo],check=True)
        uploaded=api(base+'/releases/tags/'+tag)['assets']
        if not any(a['name']==path.name and a.get('digest')==expected and a['size']==path.stat().st_size for a in uploaded): raise ValueError('Uploaded asset verification failed')
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--repo',required=True); p.add_argument('--tag',required=True); p.add_argument('--sha',required=True); p.add_argument('--target',required=True); p.add_argument('--folder',type=Path,required=True); a=p.parse_args(); publish(a.repo,a.tag,a.sha,a.target,a.folder)
