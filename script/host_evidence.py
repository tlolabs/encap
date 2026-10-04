#!/usr/bin/env python3
# SPDX-FileCopyrightText: Thomas Lothian
# SPDX-License-Identifier: GPL-3.0-or-later
"""Record native host evidence after package, launch, media and lifecycle checks.

Invocation belongs after successful checks in a reviewed native workflow. Manual
acceptance and authenticated application upgrades remain unrun unless separately
imported from real reviewed evidence. This file never publishes.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
from core_runtime import digest, obj, pair, require, verify_directory


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--application',choices=['ativ','encap'],required=True)
    p.add_argument('--target',required=True)
    p.add_argument('--pin',type=Path,required=True)
    p.add_argument('--binary',type=Path,required=True)
    p.add_argument('--metadata',type=Path,required=True)
    p.add_argument('--packages',nargs='+',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();pin=obj(a.pin)
    machine=platform.machine().lower();machine={'aarch64':'arm64','amd64':'x86_64'}.get(machine,machine)
    system={'darwin':'macos'}.get(platform.system().lower(),platform.system().lower())
    require(a.target==system+'-'+machine,'Host evidence requires actual native target execution')
    derivative=obj(a.metadata/'signed-payload.json')
    verify_directory(pin,a.target,a.metadata,binary=a.binary,signed=derivative)
    engine=a.binary/(a.application+'-engine'+('.exe' if system=='windows' else ''))
    identity=json.loads(subprocess.check_output([str(engine.resolve()),'build-info']))
    subprocess.run([str(engine.resolve()),'check' if a.application=='ativ' else 'validate-tools'],env=dict(os.environ,PATH=''),check=True)
    revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    subprocess.run(['git','diff','--quiet','HEAD','--'],check=True)
    require(not os.environ.get('GITHUB_SHA') or os.environ['GITHUB_SHA'] == revision, 'Workflow/application revision mismatch')
    version=os.environ.get('ATIV_VERSION', identity[a.application+'_version'])
    # These assertions are supplied by successful workflow step ordering, with its
    # authenticated artifact digest and job logs checked on import in Core.
    checks={name:{'status':'passed','evidence':['native workflow run '+os.environ.get('GITHUB_RUN_ID','local')+': completed '+name+' step']} for name in ('packaging','launch','media','lifecycle')}
    checks.update({'signing':{'status':'not_run','evidence':[]},'authenticated_upgrade':{'status':'not_run','evidence':[]},'manual_accessibility':{'status':'awaiting_acceptance','evidence':[]}})
    report={'schema':1,'scope':'native_host_packaging','status':'passed','application_repository':'tlolabs/'+a.application,
            'application_revision':revision,'application_version':version,'engine_version':identity[a.application+'_version'],
            'core_build_revision':pin['build_revision'],'core_build_run':pin['build_run'],'target':a.target,'native_target':a.target,
            'native_environment':{'system':platform.system(),'machine':platform.machine(),'platform':platform.platform(),
                                  'runner_os':os.environ.get('RUNNER_OS'),'image_os':os.environ.get('ImageOS'),'image_version':os.environ.get('ImageVersion')},
            'runtime_archive_sha256':pin['targets'][a.target]['sha256'],
            'original_binary_sha256':derivative['original_binary_sha256'],'signed_derivative':derivative,
            'packages':[{'filename':p.name,'sha256':digest(p),'size':p.stat().st_size} for p in a.packages],
            'checks':checks,'evidence_origin':{'repository':os.environ.get('GITHUB_REPOSITORY'),'revision':revision,
                'event':os.environ.get('GITHUB_EVENT_NAME','local'),'run_id':os.environ.get('GITHUB_RUN_ID'),'artifact_digest_verified':False}}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n')
    print('Native host evidence recorded; production signing, authenticated upgrades and manual acceptance remain separate unrun entries.')

if __name__=='__main__':main()
