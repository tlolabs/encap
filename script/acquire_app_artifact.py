#!/usr/bin/env python3
"""Download same-commit native application artifacts after authenticating API digests."""
import argparse
from pathlib import Path
import os
import re
import subprocess
import tempfile
from core_runtime import digest, extract_zip, gh_json, obj, require

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',required=True,type=int);p.add_argument('--workflow',required=True)
    p.add_argument('--platform',choices=['windows','linux','macos'],required=True)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--allow-partial',action='store_true');a=p.parse_args()
    repo=os.environ['GITHUB_REPOSITORY'];revision=os.environ['GITHUB_SHA']
    require(repo in ('tlolabs/ativ','tlolabs/encap'),'Unexpected application repository')
    expected='.github/workflows/'+('native-release.yml' if repo.endswith('/ativ') else 'build-platforms.yml')
    require(a.workflow==expected,'Unexpected native producer workflow')
    run=gh_json(f'repos/{repo}/actions/runs/{a.run}')
    require(run['repository']['full_name']==repo and run['head_repository']['full_name']==repo and
            run['head_sha']==revision and run['event']=='workflow_dispatch' and run['path']==expected and
            run['status']=='completed' and run['conclusion'] in ('success','failure'),'Untrusted native input origin')
    require(not a.allow_partial or repo=='tlolabs/ativ','Partial publication policy is ATIV-only')
    prefix=('ATIV' if repo.endswith('/ativ') else 'EnCap')+'-'+a.platform+'-'
    labels=['arm64','x86_64'] if a.platform=='macos' and repo.endswith('/ativ') else ['arm64','intel'] if a.platform=='macos' else ['x64','ARM64'] if a.platform=='windows' and repo.endswith('/ativ') else ['x86_64','aarch64'] if a.platform=='linux' and repo.endswith('/ativ') else ['x64','arm64']
    artifacts=gh_json(f'repos/{repo}/actions/runs/{a.run}/artifacts?per_page=100')['artifacts']
    jobs=gh_json(f'repos/{repo}/actions/runs/{a.run}/attempts/{run["run_attempt"]}/jobs?per_page=100')['jobs']
    require(not a.output.exists(),'Fresh native input directory required');a.output.mkdir(parents=True)
    downloaded=0
    for label in labels:
        native=[j for j in jobs if j['name']==('macOS' if a.platform=='macos' else a.platform.title())+' '+label and j['conclusion']=='success']
        if a.allow_partial and not native:continue
        name=prefix+label;items=[v for v in artifacts if v['name']==name and not v['expired']]
        require(len(items)==1,'Missing native input artifact: '+name);artifact=items[0]
        require(artifact['workflow_run']['head_sha']==revision and artifact['workflow_run']['id']==a.run and
                re.fullmatch('sha256:[0-9a-f]{64}',artifact.get('digest','')),'Native input artifact origin mismatch')
        native=[j for j in jobs if j['name']==('macOS' if a.platform=='macos' else a.platform.title())+' '+label and j['conclusion']=='success']
        require(len(native)==1,'Native target job did not pass')
        with tempfile.TemporaryDirectory() as temporary:
            archive=Path(temporary)/'artifact.zip'
            with archive.open('wb') as stream:
                subprocess.run(['gh','api',f'repos/{repo}/actions/artifacts/{artifact["id"]}/zip'],stdout=stream,check=True)
            require(digest(archive)==artifact['digest'].removeprefix('sha256:'),'Native input container digest mismatch')
            extract_zip(archive,a.output/name)
        downloaded+=1
    require(downloaded>0,'No native target qualified for signing')
    print('Same-commit native inputs authenticated before platform signing.')
