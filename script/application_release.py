#!/usr/bin/env python3
# SPDX-FileCopyrightText: Thomas Lothian
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage only exact, authenticated application packages whose release gates passed."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib
from core_runtime import REPOSITORY, TARGETS, digest, extract_zip, gh_json, obj, require

ROOT = Path(__file__).resolve().parents[1]
APPLICATION = 'encap'
REPOSITORY = 'tlolabs/'+APPLICATION
PREFIX = 'ATIV' if APPLICATION == 'ativ' else 'EnCap'
REQUIRED = {'native_packaging', 'native_launch', 'media', 'lifecycle', 'signing', 'authenticated_upgrade', 'manual_acceptance'}
PRODUCERS = {'.github/workflows/native-release.yml', '.github/workflows/build-platforms.yml',
             '.github/workflows/sign-windows.yml', '.github/workflows/sign-linux.yml', '.github/workflows/verify-macos.yml'}


def validate(plan, pin, revision):
    version = tomllib.loads((ROOT/'Cargo.toml').read_text())['workspace']['package']['version']
    require(plan['schema'] == 1 and plan['repository'] == REPOSITORY and plan['version'] == version and
            plan['tag'] == 'v'+version and re.fullmatch('[0-9a-f]{40}',plan.get('application_revision') or ''), 'Release application/version identity mismatch')
    require(not pin.get('qualification_only') and re.fullmatch('[0-9a-f]{40}', pin.get('release_revision') or '') and
            re.fullmatch('[0-9a-f]{64}', pin.get('manifest_sha256') or ''), 'Application cannot publish an unpublished Core candidate')
    require(set(plan['targets']) == TARGETS, 'Application matrix must remain recorded in full')
    passed = {target: entry for target, entry in plan['targets'].items() if entry['status'] == 'passed'}
    require(passed and (APPLICATION == 'ativ' or set(passed) == TARGETS), 'No qualified target or incomplete required EnCAP matrix')
    for target, entry in passed.items():
        require(REQUIRED <= entry['checks'].keys() and all(entry['checks'][name]['status'] == 'passed' and
                entry['checks'][name]['evidence'] for name in REQUIRED), 'Incomplete application acceptance: '+target)
        require(entry['core_release_tag'] == pin['release_tag'] and entry['core_manifest_sha256'] == pin['manifest_sha256'] and
                entry['original_binary_sha256'] == pin['targets'][target]['binary_sha256'], 'Application evidence has wrong Core identity')
        package=entry['package']; label={'macos-x86_64':'intel','windows-x86_64':'x64','linux-x86_64':'x64'}.get(target,target.split('-')[1])
        system=target.split('-')[0]; extension='AppImage' if system=='linux' else 'zip'
        names={f'{PREFIX}-{version}-{system}-{label}.{extension}'}
        require(package['filename'] in names and re.fullmatch('[0-9a-f]{64}',package['sha256']) and package['size']>0, 'Wrong release package identity')
        for check in REQUIRED:
            for record in entry['checks'][check]['evidence']:
                path=(ROOT/record['path']).resolve()
                require(path.is_relative_to((ROOT/'docs').resolve()) and digest(path)==record['sha256'], 'Acceptance evidence path/hash mismatch')
                report=obj(path)
                require(report['application_revision']==plan['application_revision'] and report['target']==target and
                        report['package_sha256']==package['sha256'] and report['status']=='passed', 'Acceptance does not apply to final package')
                if check=='manual_acceptance':require(report['reviewer'] and report['accepted_at'], 'Actual reviewer acceptance required')
                if check=='authenticated_upgrade':
                    require(all(report['results'].get(name)=='passed' for name in ('previous_version_upgrade','invalid_signature','tampered_bytes','wrong_target','settings_preserved','user_files_preserved','updated_launch','intended_core_runtime')), 'Real upgrade evidence incomplete')
        require(entry['acquisition']['mode']=='published_release' and entry['acquisition']['manifest_sha256']==pin['manifest_sha256'] and entry['acquisition']['clean_environment'] is True, 'Clean production runtime acquisition evidence missing')
        origin=entry['origin']
        expected_workflow='.github/workflows/sign-windows.yml' if system=='windows' else '.github/workflows/sign-linux.yml' if system=='linux' else '.github/workflows/verify-macos.yml'
        require(origin['workflow']==expected_workflow, 'Production platform signing workflow required')
        require(origin['workflow'] in PRODUCERS and re.fullmatch('[0-9a-f]{64}',origin['artifact_zip_sha256']), 'Untrusted application producer')
    return passed


def qualification_only_path(path):
    return path.startswith('docs/') or path in ('runtime/application-qualification.json', 'runtime/updater-qualification.json')


def stage(plan, pin, output):
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    passed=validate(plan,pin,revision)
    build_revision=plan['application_revision']
    subprocess.run(['git','merge-base','--is-ancestor',build_revision,revision],cwd=ROOT,check=True)
    changed=subprocess.check_output(['git','diff','--name-only',build_revision,revision],cwd=ROOT,text=True).splitlines()
    require(all(qualification_only_path(p) for p in changed), 'Application inputs changed after qualification; new native evidence required')
    require(not output.exists(), 'Application staging destination must be new')
    output.mkdir(parents=True)
    for target, entry in passed.items():
        require(entry['acquisition']['mode']=='published_release' and entry['acquisition']['manifest_sha256']==pin['manifest_sha256'] and entry['acquisition']['clean_environment'] is True, 'Clean production runtime acquisition evidence missing')
        origin=entry['origin'];run=gh_json(f'repos/{REPOSITORY}/actions/runs/{origin["run_id"]}')
        require(run['repository']['full_name']==REPOSITORY and run['head_repository']['full_name']==REPOSITORY and
                run['head_sha']==build_revision and run['path']==origin['workflow'] and run['event']=='workflow_dispatch' and
                run['status']=='completed' and run['conclusion'] in ('success','failure'), 'Application package run origin mismatch')
        artifacts=gh_json(f'repos/{REPOSITORY}/actions/runs/{origin["run_id"]}/artifacts?per_page=100')['artifacts']
        artifacts=[a for a in artifacts if a['id']==origin['artifact_id'] and not a['expired']]
        require(len(artifacts)==1 and artifacts[0]['digest']=='sha256:'+origin['artifact_zip_sha256'] and
                artifacts[0]['workflow_run']['head_sha']==build_revision, 'Application artifact origin/digest mismatch')
        jobs=gh_json(f'repos/{REPOSITORY}/actions/runs/{origin["run_id"]}/attempts/{run["run_attempt"]}/jobs?per_page=100')['jobs']
        jobs=[j for j in jobs if j['id'] in origin['required_native_job_ids'] and j['conclusion']=='success']
        require(jobs and len(jobs)==len(origin['required_native_job_ids']), 'Required native final-package jobs did not pass')
        system=target.split('-')[0]
        if system in ('windows','linux'):
            require({'sign','Verify signed '+system.title()+' '+target} <= {j['name'] for j in jobs}, 'Exact platform signing/native verification jobs required')
        if system=='macos':
            require({'Verify signed macOS '+target} <= {j['name'] for j in jobs}, 'Exact native notarized ZIP verification job required')
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);archive=root/'artifact.zip'
            with archive.open('wb') as stream:
                subprocess.run(['gh','api',f'repos/{REPOSITORY}/actions/artifacts/{origin["artifact_id"]}/zip'],stdout=stream,check=True)
            require(digest(archive)==origin['artifact_zip_sha256'],'Application artifact container was altered')
            extract_zip(archive,root/'payload')
            package=entry['package'];paths=list((root/'payload').rglob(package['filename']))
            require(len(paths)==1 and digest(paths[0])==package['sha256'] and paths[0].stat().st_size==package['size'],'Final application bytes differ from qualification')
            shutil.copy2(paths[0],output/package['filename'])
            if target.startswith('linux'):
                signatures=list((root/'payload').rglob(package['filename']+'.asc'))
                require(len(signatures)==1 and digest(signatures[0])==entry['signature_sha256'],'Final AppImage signature missing/altered')
                shutil.copy2(signatures[0],output/signatures[0].name)
    (output/'application-qualification.json').write_text(json.dumps(plan,indent=2)+'\n')
    print('Qualified exact application packages staged; publication still requires signed tag, update metadata and provenance.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    stage(obj(ROOT/'runtime/application-qualification.json'),obj(ROOT/'runtime/core-runtime.json'),a.output)
