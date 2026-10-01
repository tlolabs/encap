#!/usr/bin/env python3
"""Gate native upgrade evidence, then probe staged or actual published releases.

Never creates a passing installation report. A native harness/operator must supply
actual older-to-newer installation results tied to the exact final package hash.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import tomllib
from tlo_update_release import stable
ROOT=Path(__file__).resolve().parents[1]
CASES=('previous_version_upgrade','invalid_signature','tampered_bytes','wrong_target','wrong_application',
       'settings_preserved','user_files_preserved','updated_launch','interrupted_installation','native_signatures')

def require(condition,message):
    if not condition: raise ValueError(message)

def qualify(assets, published=False, gate_only=False):
    import base64
    envelope=json.loads((assets/'update-manifest.json').read_text())
    manifest=json.loads(base64.b64decode(envelope['payload'],validate=True))
    # The workflow must run tlo_update_release --verify first; the Rust probe also
    # authenticates the bytes independently against each trusted old config.
    ledger=json.loads((ROOT/'runtime/updater-qualification.json').read_text())
    require(ledger['schema']==1,'Unsupported qualification ledger')
    results=[]
    for target,asset in manifest['assets'].items():
        entry=ledger['targets'].get(target,{})
        require(entry.get('status')=='passed', 'Native authenticated installation is not qualified: '+target)
        report_path=(ROOT/entry['report']).resolve()
        require(report_path.is_relative_to((ROOT/'docs/updates').resolve()),'Evidence outside docs/updates')
        raw=report_path.read_bytes();require(hashlib.sha256(raw).hexdigest()==entry['report_sha256'],'Evidence digest mismatch')
        report=json.loads(raw)
        require(report['status']=='passed' and report['target']==target and report['package_sha256']==asset['sha256'] and report['version']==manifest['version'], 'Evidence applies to different package')
        require(report.get('host') and report.get('tested_at') and report.get('reviewer'),'Native test host/time/reviewer missing')
        require(all(report['results'].get(case)=='passed' for case in CASES),'Unperformed native upgrade/failure tests')
        config=report['previous_config']
        require(config['target']==target and config['application_id']==manifest['application_id'] and config['repository']==manifest['repository'] and config['channel']=='stable','Wrong previous application configuration')
        require(stable(config['version'])<stable(manifest['version']),'Older installed application required')
        require(len(report.get('previous_package_sha256',''))==64,'Previous authenticated package identity missing')
        if gate_only: continue
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'old-config.json';path.write_text(json.dumps(config))
            output=subprocess.check_output(['cargo','run','--locked','-p','tlo-updater','--bin','tlo-qualify','--',str(path),'--published' if published else str(assets.resolve())],cwd=ROOT,text=True)
            results.append(json.loads(output))
    require(manifest['assets'],'No update targets')
    return results

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--assets',required=True,type=Path);parser.add_argument('--published',action='store_true');parser.add_argument('--gate-only',action='store_true');args=parser.parse_args()
    print(json.dumps(qualify(args.assets,args.published,args.gate_only),indent=2))
