#!/usr/bin/env python3
"""Shared release tooling. Python is used only in build/release CI, never in an app."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import tomllib
from xml.etree import ElementTree as ET
import zipfile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

SPARKLE = 'http://www.andymatuschak.org/xml-namespaces/sparkle'
ET.register_namespace('sparkle', SPARKLE)
ROOT = Path(__file__).resolve().parents[1]
SPECS = {**{f'macos-{a}': ('macos', arch, 'zip', '13.0.0') for a,arch in [('arm64','aarch64'),('intel','x86_64')]},
         **{f'windows-{a}': ('windows', arch, 'zip', '10.0.17763') for a,arch in [('arm64','aarch64'),('x64','x86_64')]},
         **{f'linux-{a}-appimage': ('linux', arch, 'AppImage', '4.18.0') for a,arch in [('arm64','aarch64'),('x64','x86_64')]}}

def stable(version):
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',version):
        raise ValueError('Stable SemVer MAJOR.MINOR.PATCH required')
    if any(int(p)>2**64-1 for p in version.split('.')): raise ValueError('Version component overflow')
    return tuple(map(int,version.split('.')))

def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()

def verify_package(path, target, app, repo, version, public):
    """Read packaged identity without executing the artifact being inspected."""
    expected = dict(application_id=app,repository=repo,version=version,channel='stable',target=target,public_key=base64.b64encode(public).decode())
    if path.suffix == '.zip':
        with zipfile.ZipFile(path) as archive:
            configs = [n for n in archive.namelist() if n=='update-config.json' or n.endswith('.app/Contents/Resources/update-config.json')]
            if len(configs)!=1: raise ValueError('Exactly one packaged update identity required')
            if json.loads(archive.read(configs[0])) != expected: raise ValueError('Packaged version/key/application mismatch')
            if target.startswith('macos-'):
                info=plistlib.loads(archive.read(configs[0].replace('Resources/update-config.json','Info.plist')))
                if any(info.get(k)!=v for k,v in dict(CFBundleIdentifier=app,CFBundleVersion=version,CFBundleShortVersionString=version,SUPublicEDKey=expected['public_key']).items()):
                    raise ValueError('macOS bundle version, identity or update key mismatch')
    else:
        # Type 2 AppImages embed a SquashFS filesystem. Locate its superblock;
        # unsquashfs only reads data and does not execute the AppImage runtime.
        data=path.read_bytes()
        if data[:4]!=b'\x7fELF' or data[8:11]!=b'AI\x02': raise ValueError('Type 2 AppImage required')
        found=[]; start=0
        while True:
            offset=data.find(b'hsqs',start)
            if offset<0: break
            start=offset+4
            if data[offset+28:offset+32]!=b'\x04\x00\x00\x00': continue
            for name in ('usr/lib/ativ/update-config.json','usr/bin/update-config.json'):
                result=subprocess.run(['unsquashfs','-cat','-o',str(offset),str(path),name],capture_output=True)
                if result.returncode==0: found.append(json.loads(result.stdout))
        if found != [expected]: raise ValueError('AppImage packaged version/key/application mismatch')

def build(assets, version, channel, tag, seed, public_key, *, app='com.tlolabs.ativ', repo='tlolabs/ativ', prefix='ATIV', published_at=None):
    stable(version)
    if channel!='stable' or tag!='v'+version: raise ValueError('Only matching stable release tags are permitted')
    key=Ed25519PrivateKey.from_private_bytes(seed)
    if key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)!=public_key: raise ValueError('Update signing keys do not match')
    # CI supplies the immutable tag commit time, making regeneration deterministic.
    published_at=published_at or subprocess.check_output(['git','show','-s','--format=%cI','HEAD'],cwd=ROOT,text=True).strip()
    datetime.fromisoformat(published_at.replace('Z','+00:00'))
    payload=dict(schema=2,application_id=app,repository=repo,version=version,tag=tag,channel='stable',draft=False,prerelease=False,
                 published_at=published_at,release_notes_url=f'https://github.com/{repo}/releases/tag/{tag}',restart_required=True,migration='none',assets={})
    for target,(platform,arch,extension,minimum) in SPECS.items():
        label=target.split('-')[1]; name=f'{prefix}-{version}-{platform}-{label}.{extension}';path=assets/name
        if not path.is_file(): continue
        verify_package(path,target,app,repo,version,public_key)
        size=path.stat().st_size
        if not 0<size<=2*1024**3: raise ValueError('Artifact size outside supported bounds')
        url=f'https://github.com/{repo}/releases/download/{tag}/{name}'
        payload['assets'][target]=dict(url=url,filename=name,size=size,sha256=sha(path),platform=platform,architecture=arch,minimum_os=minimum,
                                      minimum_glibc='2.39.0' if platform=='linux' else None,format=extension)
        if platform=='macos':
            root=ET.Element('rss',version='2.0');feed=ET.SubElement(root,'channel');ET.SubElement(feed,'title').text=f'{prefix} stable'
            item=ET.SubElement(feed,'item');ET.SubElement(item,'title').text=f'{prefix} {version}'
            ET.SubElement(item,f'{{{SPARKLE}}}version').text=version
            ET.SubElement(item,f'{{{SPARKLE}}}shortVersionString').text=version
            ET.SubElement(item,f'{{{SPARKLE}}}minimumSystemVersion').text=minimum
            ET.SubElement(item,'link').text=payload['release_notes_url']
            ET.SubElement(item,'pubDate').text=datetime.fromisoformat(published_at.replace('Z','+00:00')).strftime('%a, %d %b %Y %H:%M:%S %z')
            ET.SubElement(item,'enclosure',{'url':url,'length':str(size),'type':'application/octet-stream',f'{{{SPARKLE}}}edSignature':base64.b64encode(key.sign(path.read_bytes())).decode()})
            ET.ElementTree(root).write(assets/f'appcast-{target}.xml',encoding='utf-8',xml_declaration=True)
    if not payload['assets']: raise ValueError('No release artifacts available')
    def envelope(value):
        raw=json.dumps(value,separators=(',',':'),sort_keys=True).encode()
        return dict(payload=base64.b64encode(raw).decode(),signature=base64.b64encode(key.sign(raw)).decode())
    (assets/'update-manifest.json').write_text(json.dumps(envelope(payload),indent=2)+'\n')
    # Keep deployed ATIV schema-1 readers working through the bridge release.
    if prefix=='ATIV':
        legacy=dict(schema=1,version=version,channel='stable',assets={k:{f:v[f] for f in ('url','filename','size','sha256')} for k,v in payload['assets'].items()})
        (assets/'latest.json').write_text(json.dumps(envelope(legacy),indent=2)+'\n')
    # EnCAP's original object-payload wire format signs serde's field order.
    # Retain ZIP readers; old tar installations need an explicit manual AppImage bridge.
    else:
        old_assets={k:dict(archive='zip',sha256=v['sha256'],size=v['size'],url=v['url']) for k,v in sorted(payload['assets'].items()) if v['format']=='zip'}
        legacy=dict(assets=old_assets,notes='Linux tar installations require the documented manual AppImage bridge.',release_url=payload['release_notes_url'],schema_version=1,version=version)
        raw=json.dumps(legacy,separators=(',',':'),ensure_ascii=False).encode()
        (assets/'latest.json').write_text(json.dumps(dict(payload=legacy,signature=base64.b64encode(key.sign(raw)).decode()),indent=2)+'\n')
    checksums(assets)
    return payload

def checksums(assets):
    (assets/'SHA256SUMS').write_text(''.join(sha(p)+'  '+p.name+'\n' for p in sorted(assets.iterdir()) if p.is_file() and p.name!='SHA256SUMS'))

def verify_assets(assets, public, app, repo, version):
    envelope=json.loads((assets/'update-manifest.json').read_text())
    raw=base64.b64decode(envelope['payload'],validate=True)
    Ed25519PublicKey.from_public_bytes(public).verify(base64.b64decode(envelope['signature'],validate=True),raw)
    payload=json.loads(raw)
    if payload['schema']!=2 or payload['application_id']!=app or payload['repository']!=repo or payload['version']!=version or payload['tag']!='v'+version or payload['channel']!='stable' or payload['draft'] or payload['prerelease']: raise ValueError('Release identity mismatch')
    stable(version)
    for target,asset in payload['assets'].items():
        platform,arch,extension,minimum=SPECS[target]
        name=asset['filename']
        if not re.fullmatch(r'[A-Za-z0-9_.-]+',name) or name in ('.','..'): raise ValueError('Unsafe artifact filename')
        if asset['platform']!=platform or asset['architecture']!=arch or asset['format']!=extension or asset['minimum_os']!=minimum: raise ValueError('Artifact target mismatch')
        if asset['url']!=f'https://github.com/{repo}/releases/download/v{version}/{name}': raise ValueError('Artifact release URL mismatch')
        path=assets/name
        if path.stat().st_size!=asset['size'] or sha(path)!=asset['sha256']: raise ValueError('Manifest/artifact mismatch')
        verify_package(path,target,app,repo,version,public)
        if platform=='macos':
            tree=ET.parse(assets/f'appcast-{target}.xml');enclosure=tree.find('.//enclosure')
            if enclosure.attrib['url']!=asset['url'] or int(enclosure.attrib['length'])!=asset['size'] or tree.find(f'.//{{{SPARKLE}}}version').text!=version: raise ValueError('Appcast identity mismatch')
            Ed25519PublicKey.from_public_bytes(public).verify(base64.b64decode(enclosure.attrib[f'{{{SPARKLE}}}edSignature'],validate=True),path.read_bytes())
    return payload

def main():
    p=argparse.ArgumentParser();p.add_argument('--assets',type=Path,required=True);p.add_argument('--verify',action='store_true');p.add_argument('--version');p.add_argument('--channel',default='stable');p.add_argument('--tag');a=p.parse_args()
    workspace=tomllib.loads((ROOT/'Cargo.toml').read_text())['workspace']['package'];version=workspace['version']
    repo=workspace['repository'].removeprefix('https://github.com/');short=repo.split('/')[1];prefix={'ativ':'ATIV','encap':'EnCap'}[short]
    if a.version and a.version!=version: raise ValueError('Requested version differs from authoritative Cargo version')
    public=base64.b64decode(os.environ[short.upper()+'_UPDATE_PUBLIC_KEY'],validate=True)
    if a.verify: verify_assets(a.assets,public,'com.tlolabs.'+short,repo,version)
    else: build(a.assets,version,a.channel,a.tag or 'v'+version,base64.b64decode(os.environ[short.upper()+'_UPDATE_PRIVATE_KEY'],validate=True),public,app='com.tlolabs.'+short,repo=repo,prefix=prefix)

if __name__=='__main__':main()
