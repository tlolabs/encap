#!/usr/bin/env python3
"""Write packaged update identity using Cargo.toml as the sole version source."""
import argparse, base64, json, os, plistlib, re, tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def version():
    value=tomllib.loads((ROOT/'Cargo.toml').read_text())['workspace']['package']['version']
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',value): raise ValueError('Stable SemVer required')
    return value

def configure(stage,target):
    value=version()
    if target not in ('macos-arm64','macos-intel','windows-x64','windows-arm64','linux-x64-appimage','linux-arm64-appimage'): raise ValueError('Unknown target')
    public=os.environ.get('ENCAP_UPDATE_PUBLIC_KEY','')
    if public=='development-build-no-update-key' and os.environ.get('ENCAP_RELEASE')!='1': public=''
    if public and len(base64.b64decode(public,validate=True))!=32: raise ValueError('Invalid update key')
    if os.environ.get('ENCAP_RELEASE')=='1' and not public: raise ValueError('Production packages require the deployed update public key')
    if target.startswith('macos-'):
        info = plistlib.loads((stage.parent / 'Info.plist').read_bytes())
        if info.get('CFBundleIdentifier') != 'com.tlolabs.encap' or info.get('EnCapDistribution') == 'internal-reference':
            raise ValueError('Only the native production macOS bundle may receive production update identity')
    stage.mkdir(parents=True,exist_ok=True)
    identity=dict(application_id='com.tlolabs.encap',repository='tlolabs/encap',version=value,channel='stable',target=target,public_key=public)
    (stage/'update-config.json').write_text(json.dumps(identity,indent=2)+'\n')
    if target.startswith('macos-'):
        path=stage.parent/'Info.plist';info=plistlib.loads(path.read_bytes())
        info.update(CFBundleIdentifier=identity['application_id'],CFBundleVersion=value,CFBundleShortVersionString=value)
        path.write_bytes(plistlib.dumps(info))
    return value

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--version',action='store_true');p.add_argument('--props',type=Path);p.add_argument('stage',type=Path,nargs='?');p.add_argument('target',nargs='?');a=p.parse_args()
    if a.version: print(version())
    elif a.props:
        a.props.parent.mkdir(parents=True,exist_ok=True)
        a.props.with_name('encap.app.manifest').write_text((ROOT/'desktop/packaging/app.manifest').read_text().replace('@ENCAP_VERSION@',version()+'.0'))
        a.props.write_text(f'<Project><PropertyGroup><Version>{version()}</Version><AssemblyVersion>{version()}.0</AssemblyVersion><FileVersion>{version()}.0</FileVersion></PropertyGroup></Project>\n')
    elif a.stage and a.target: configure(a.stage,a.target)
    else: p.error('Specify --version, --props or stage and target')
